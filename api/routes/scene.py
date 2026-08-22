"""
Reconstructed-scene API.

A thin surface over `api.scene`, mirroring `api/routes/candidates.py`'s own
shape: this layer adds no semantics of its own. Whether a scene may be
shown, and what it may contain, is decided entirely by
`schemas.views._scene_3d`/`fusion.vertical_reference.assess` (via
`api.scene.build_scene`) and the existing candidate pipeline. A dataset
that hasn't cleared those gates gets `resolved: false` here, same as it
already gets `resolved: false` from `/api/views/resolve`.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.scene import build_scene
from auth.dependencies import dataset_or_404, get_current_user, require_dataset_access
from database.models import User
from database.session import get_db

router = APIRouter()


@router.get("/{dataset_id}")
def get_scene(
    dataset_id: str,
    surface_dataset_id: Optional[str] = Query(
        None,
        description=(
            "A separate dataset holding the surface (DEM/LiDAR) frame, when the "
            "surface was not ingested into this dataset itself -- the same "
            "cross-dataset relationship /api/fusion/* already reads via "
            "load_frames_for."),
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _dataset=Depends(require_dataset_access),
):
    """The reconstructed-scene payload for one dataset, or why it is unresolved."""
    # `require_dataset_access` only checks the path's own dataset_id.
    # surface_dataset_id is a second dataset named by the caller, from a
    # query parameter no dependency sees -- it gets the same visibility
    # check here that fusion.py already applies to every dataset id it is
    # handed, so this route cannot become a way to read another user's
    # private surface data by naming their dataset id.
    if surface_dataset_id:
        dataset_or_404(db, user, surface_dataset_id)
    return build_scene(db, dataset_id, surface_dataset_id=surface_dataset_id).model_dump(mode="json")
