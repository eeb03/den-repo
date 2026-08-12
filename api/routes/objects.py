"""
SubsurfaceObject and association API.

Exposes the association evidence and the objects resolved from it, keeping the
two separable: a client can inspect why two observations were linked, and
re-cut the objects at a different score threshold, without recomputing
anything.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database.objects_store import (
    load_associations, load_objects, replace_objects, upsert_associations,
)
from schemas.associations import AssociationRecord, AssociationSet
from schemas.objects import ObservationRef, SubsurfaceObject, build_object
from utils.logger import get_logger
from auth.dependencies import require_dataset_access, require_owned_dataset

logger = get_logger(__name__)
router = APIRouter()


class AssociationWriteRequest(BaseModel):
    associations: list[AssociationRecord] = Field(..., min_length=1)


class ResolveRequest(BaseModel):
    #: Objects are a resolution of the association graph at ONE threshold.
    #: Changing it re-cuts the graph; the evidence is untouched.
    min_score: float = Field(1.0, ge=0.0, le=1.0)
    attested_by: dict[str, list[str]] = Field(default_factory=dict)


@router.get("/vocabulary")
def vocabulary():
    return {
        "object_statuses": [
            {"value": "hypothesised",
             "meaning": "observations associated; nothing corroborates them",
             "is_real_thing": False},
            {"value": "corroborated",
             "meaning": ("members from at least two INDEPENDENT acquisitions; a "
                         "detector agreeing with itself on one line does not qualify"),
             "is_real_thing": False},
            {"value": "attested",
             "meaning": ("an attested ground-truth label refers to it; only this may "
                         "be spoken of as a real thing"),
             "is_real_thing": True},
        ],
        "association_methods": ["adjacent_trace", "adjacent_profile",
                                "cross_survey", "manual"],
        "rules": [
            "an association is a hypothesis carrying its evidence, never a finding",
            "every criterion is caller-supplied and stored on the record",
            "score is the fraction of criteria satisfied, NOT a probability",
            "an object's position is derived from its members, never invented",
            "cross_survey association is UNVALIDATED: no held dataset has repeat "
            "coverage of the same ground with timestamps",
        ],
    }


@router.get("/{dataset_id}/associations")
def list_associations(dataset_id: str,
                      method: Optional[str] = Query(None),
                      min_score: float = Query(0.0, ge=0.0, le=1.0),
                      independent_only: bool = Query(False),
    _dataset=Depends(require_dataset_access)):
    s = load_associations(dataset_id)
    out = [a for a in s.associations if a.score >= min_score]
    if method:
        out = [a for a in out if a.method.value == method]
    if independent_only:
        out = [a for a in out if a.is_independent_evidence]
    return {
        "dataset_id": dataset_id,
        "count": len(out),
        "associations": [a.model_dump(mode="json") for a in out],
        "independent_count": sum(1 for a in out if a.is_independent_evidence),
        "note": ("associations within one acquisition are not independent evidence, "
                 "however close the traces"),
    }


@router.post("/{dataset_id}/associations")
def write_associations(dataset_id: str, body: AssociationWriteRequest,
    _dataset=Depends(require_owned_dataset)):
    try:
        out = upsert_associations(dataset_id, body.associations)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"dataset_id": dataset_id, "written": len(body.associations),
            "total_after_write": len(out.associations)}


@router.get("/{dataset_id}")
def list_objects(dataset_id: str, status: Optional[str] = Query(None),
    _dataset=Depends(require_dataset_access)):
    objs = load_objects(dataset_id)
    if status:
        objs = [o for o in objs if o.status.value == status]
    return {
        "dataset_id": dataset_id, "count": len(objs),
        "objects": [o.model_dump(mode="json") for o in objs],
        "by_status": {s: sum(1 for o in objs if o.status.value == s)
                      for s in ("hypothesised", "corroborated", "attested")},
        "placed": sum(1 for o in objs if o.is_placed),
        "note": ("objects that are not placed have no coordinate on Earth and must "
                 "not be drawn at a default one"),
    }


@router.post("/{dataset_id}/resolve")
def resolve_objects(dataset_id: str, body: ResolveRequest,
    _dataset=Depends(require_owned_dataset)):
    """
    Re-cuts the association graph into objects at a given score threshold.

    Replaces the object set wholesale, because objects are a resolution: merging
    two resolutions computed at different thresholds would produce a set no
    single threshold could have produced. The associations are untouched.
    """
    s = load_associations(dataset_id)
    if not s.associations:
        raise HTTPException(404, f"dataset {dataset_id!r} has no associations to resolve")
    by_obs: dict[str, ObservationRef] = {}
    assoc_by_obs: dict[str, list[str]] = {}
    for a in s.associations:
        for ref in (a.observation_a, a.observation_b):
            by_obs.setdefault(ref.observation_id, ref)
            assoc_by_obs.setdefault(ref.observation_id, []).append(a.id)

    objects: list[SubsurfaceObject] = []
    for group in s.connected_components(min_score=body.min_score):
        members = [by_obs[i] for i in group if i in by_obs]
        if not members:
            continue
        attested = sorted({t for i in group for t in body.attested_by.get(i, [])})
        assoc_ids = sorted({aid for i in group for aid in assoc_by_obs.get(i, [])})
        objects.append(build_object(dataset_id, members,
                                    association_ids=assoc_ids,
                                    attested_by=attested or None))
    replace_objects(dataset_id, objects)
    logger.info(f"objects: resolved {len(objects)} object(s) at min_score="
                f"{body.min_score} for {dataset_id}")
    return {
        "dataset_id": dataset_id, "min_score": body.min_score,
        "objects_created": len(objects),
        "by_status": {s_: sum(1 for o in objects if o.status.value == s_)
                      for s_ in ("hypothesised", "corroborated", "attested")},
        "objects": [o.model_dump(mode="json") for o in objects],
        "note": ("objects are a resolution at one threshold; the association evidence "
                 "is unchanged and can be re-cut"),
    }
