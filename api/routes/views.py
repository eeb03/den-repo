"""
Synchronized-view API.

Resolves one selection into every view, answering per view instead of
pretending all views can show everything. A client renders what resolves and
displays the reason for what does not.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from auth import dependencies as access
from auth.dependencies import get_current_user
from database.frames_store import load_frames, synthesize_frames_from_records
from database.models import User
from database.session import get_db
from database.records_store import load_records
from schemas.views import Selection, ViewKind, resolve
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class ResolveSelectionRequest(BaseModel):
    selection: Selection
    #: When supplied, the depth-slice answer is sharpened against the frame's
    #: own vertical axis, and the 3D answer against the vertical relationship.
    surface_frame_id: Optional[str] = None
    cross_frame_slice: bool = False


@router.get("/vocabulary")
def vocabulary():
    return {
        "views": [
            {"value": ViewKind.MAP.value, "requires": "a geographic position"},
            {"value": ViewKind.RADARGRAM.value,
             "requires": "a frame and a trace index"},
            {"value": ViewKind.DEPTH_SLICE.value,
             "requires": ("a depth axis (a caller-supplied velocity); a slice across "
                          "frames additionally needs a shared vertical reference")},
            {"value": ViewKind.SCENE_3D.value,
             "requires": "an absolute elevation (X, Y and Z in one frame)"},
            {"value": ViewKind.METADATA.value, "requires": "identifiers only"},
        ],
        "selection_kinds": ["candidate", "object", "label", "trace", "frame"],
        "rules": [
            "a view that cannot locate a selection returns resolved=false with the "
            "reason and what is missing -- never a default coordinate",
            "scene_3d is unresolvable for every dataset currently held: absolute "
            "elevation needs a vertical registration that does not exist",
        ],
    }


@router.post("/resolve")
def resolve_selection(
    body: ResolveSelectionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resolves a selection across all views."""
    sel = body.selection
    # The dataset id arrives in the BODY here rather than the path, so the route
    # dependency cannot see it -- authorisation has to happen in the handler or
    # this becomes the one way round the whole scheme.
    access.dataset_or_404(db, user, sel.dataset_id)

    # Frames are needed for the recorded-modality composition regardless of
    # whether this selection names a frame -- an off-GPR object/label
    # selection must get the same "does not apply" radargram answer a
    # frame/trace selection would, not "names no frame". Records are only
    # loaded when there is no stored frame file to fall back on.
    from schemas.dataset_report import frame_modalities

    frames = load_frames(sel.dataset_id)
    if not frames:
        records = load_records(sel.dataset_id)
        frames = synthesize_frames_from_records(records) if records else []
    recorded_modalities = frame_modalities(frames)

    frame = None
    vertical = None
    if sel.frame_id:
        frame = next((f for f in frames if f.frame_id == sel.frame_id), None)
        if body.surface_frame_id and frame is not None:
            surface = next((f for f in frames if f.frame_id == body.surface_frame_id),
                           None)
            if surface is None:
                raise HTTPException(404, f"no frame {body.surface_frame_id!r}")
            from fusion import vertical_reference as vr
            rel = vr.assess(frame, surface)
            vertical = {"kind": rel.kind.value,
                        "absolute_elevation_available": rel.absolute_elevation_available,
                        "missing": rel.missing}
    out = resolve(sel, frame=frame, vertical=vertical,
                  cross_frame_slice=body.cross_frame_slice,
                  recorded_modalities=recorded_modalities)
    return {
        **out.model_dump(mode="json"),
        "resolvable_views": out.resolvable_views,
        "unresolvable_views": [v.view.value for v in out.views if not v.resolved],
    }
