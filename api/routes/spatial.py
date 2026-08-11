"""
The spatial reference API.

ONE DOMAIN, THREE OPERATIONS. Inspect the spatial state, declare something,
read the history. The alternative -- a `PUT /crs`, a `PUT /vertical-datum`, a
`POST /geo-tie` and three more -- would spread one concept across six endpoints
that each need their own authorisation, their own audit row and their own way of
saying "that cannot be applied to this dataset". The declaration KIND is data,
not a URL.

AUTHORISATION IS THE EXISTING MECHANISM, unchanged. Reading uses
`require_dataset_access`; declaring uses `require_owned_dataset`, so published
reference corpora can be inspected by everyone and re-referenced by nobody. A
non-owner gets 404, never 403, so an id cannot be probed for existence.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import spatial as service
from auth.dependencies import get_current_user, require_dataset_access, require_owned_dataset
from database.frames_store import load_frames, synthesize_frames_from_records
from database.models import Dataset, User
from database.records_store import load_records
from database.session import get_db
from schemas.spatial_reference import (
    DIMENSION_STATES,
    DeclarationKind,
    SpatialDimension,
    assess_spatial_reference,
)
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class DeclarationRequest(BaseModel):
    kind: DeclarationKind
    value: dict[str, Any] = Field(default_factory=dict)
    #: WHO asserted this -- a surveyor, a document, an operator. Required, and
    #: distinct from the signed-in account, which is recorded separately: the
    #: person typing may be relaying somebody else's measurement.
    supplied_by: str = Field(..., min_length=1, max_length=300)
    frame_id: Optional[str] = Field(default=None, max_length=300)
    note: Optional[str] = Field(default=None, max_length=2000)


@router.get("/vocabulary")
def vocabulary():
    """
    The spatial contract, stated by the platform rather than duplicated in a
    client. The UI renders these labels; it does not invent them.
    """
    return {
        "dimensions": [
            {"value": d.value, "states": list(DIMENSION_STATES[d])}
            for d in SpatialDimension
        ],
        "declaration_kinds": [
            {"value": DeclarationKind.CRS.value,
             "declares": "the horizontal reference the coordinates are expressed in",
             "requires": ["code", "kind"]},
            {"value": DeclarationKind.VERTICAL_DATUM.value,
             "declares": "what the vertical coordinates are measured from",
             "requires": ["code"]},
            {"value": DeclarationKind.ANTENNA_OFFSET.value,
             "declares": "the offset between the sensor and the ground surface",
             "requires": ["offset_m"]},
            {"value": DeclarationKind.DEPTH_CONVERSION.value,
             "declares": "a propagation velocity, turning measured time into derived depth",
             "requires": ["velocity_m_per_ns"]},
            {"value": DeclarationKind.GEO_TIE.value,
             "declares": "control points tying an along-track axis to real coordinates",
             "requires": ["control_points"]},
            {"value": DeclarationKind.SURFACE_REFERENCE.value,
             "declares": "another dataset asserted to be this survey's surface model",
             "requires": ["surface_dataset_id"]},
        ],
        "rules": [
            "a declaration is a CLAIM, recorded with its author; it is never a measurement",
            "declaring a CRS is always supplied_by_caller -- a user cannot assert that the "
            "source declared something",
            "a velocity produces DERIVED depth, never measured depth",
            "a GeoTie writes registered_position and never overwrites the acquisition's own "
            "position",
            "linking a surface model does not make it usable; assess_surface decides that",
        ],
    }


def _surface_frames(db, dataset_id: str, declarations):
    """
    The frames of whatever dataset has been declared this survey's surface.

    Only an ACTIVE `surface_reference` declaration counts. A DEM sitting in the
    corpus is not this survey's surface because it happens to exist, and
    guessing by geographic overlap would be exactly the silent attachment the
    workflow exists to prevent.
    """
    linked = [d for d in declarations if d.kind == DeclarationKind.SURFACE_REFERENCE.value]
    if not linked:
        return []
    surface_id = (linked[0].value or {}).get("surface_dataset_id")
    if not surface_id:
        return []
    frames = load_frames(surface_id)
    if not frames:
        records = load_records(surface_id)
        frames = synthesize_frames_from_records(records) if records else []
    return frames


def _assess(db, dataset_id: str):
    records = load_records(dataset_id)
    frames = load_frames(dataset_id) or (
        synthesize_frames_from_records(records) if records else [])
    declarations = service.active_declarations(db, dataset_id)
    return assess_spatial_reference(
        dataset_id, frames, records,
        surface_frames=_surface_frames(db, dataset_id, declarations),
        declarations=[d.to_dict() for d in declarations],
        stale_products=service.stale_products(db, dataset_id, declarations),
    )


@router.get("/{dataset_id}")
def get_spatial_reference(dataset_id: str, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    """
    What spatial relationship this dataset has to the physical world.

    Seven dimensions, each with its own state, its reason, what is missing and
    which declaration would resolve it. An unresolved dimension is a correct
    answer, not a gap.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return _assess(db, dataset_id).model_dump(mode="json")


@router.get("/{dataset_id}/declarations")
def list_declarations(dataset_id: str, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    """
    Every claim ever made about this dataset's spatial reference, superseded
    ones included. That history is the point: "what did we think the datum was,
    and who said so" must stay answerable after somebody corrects it.
    """
    rows = service.all_declarations(db, dataset_id)
    return {"dataset_id": dataset_id, "count": len(rows),
            "declarations": [r.to_dict() for r in rows]}


@router.post("/{dataset_id}/declarations", status_code=201)
def declare(dataset_id: str, body: DeclarationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _dataset=Depends(require_owned_dataset)):
    """
    Assert something about how this dataset relates to the physical world.

    ORDER: validate, apply, then record. A declaration that cannot be applied to
    what is actually stored -- a velocity for a dataset with no time axis, a tie
    for a dataset with no odometry -- is refused BEFORE anything is written, so
    the log never contains a claim that had no effect.

    The response returns the re-assessed spatial reference, so the caller sees
    the consequence of the declaration rather than having to ask again and
    correlate. That is what makes inspect → resolve → recalculate one motion.
    """
    try:
        value = service.validate_declaration(body.kind, body.value)
    except service.DeclarationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        applied = service.apply_declaration(
            dataset_id, body.kind, value, body.supplied_by, frame_id=body.frame_id)
    except service.DeclarationError as exc:
        # 409: the declaration is well-formed but contradicts what is stored.
        raise HTTPException(status_code=409, detail=str(exc))

    row = service.record_declaration(
        db, dataset_id, body.kind, value, body.supplied_by,
        user_id=user.id, frame_id=body.frame_id, note=body.note)

    return {
        "declaration": row.to_dict(),
        "applied": applied,
        "spatial_reference": _assess(db, dataset_id).model_dump(mode="json"),
    }
