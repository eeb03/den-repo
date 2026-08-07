"""
Synchronized-view API.

Resolves one selection into every view, answering per view instead of
pretending all views can show everything. A client renders what resolves and
displays the reason for what does not.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database.frames_store import load_frames, synthesize_frames_from_records
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
def resolve_selection(body: ResolveSelectionRequest):
    """Resolves a selection across all views."""
    sel = body.selection
    frame = None
    vertical = None
    if sel.frame_id:
        records = load_records(sel.dataset_id)
        frames = load_frames(sel.dataset_id) or (
            synthesize_frames_from_records(records) if records else [])
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
                  cross_frame_slice=body.cross_frame_slice)
    return {
        **out.model_dump(mode="json"),
        "resolvable_views": out.resolvable_views,
        "unresolvable_views": [v.view.value for v in out.views if not v.resolved],
    }
