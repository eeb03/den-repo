"""
Volume API. Every route is dataset-scoped, so the existing dataset visibility
rule (`require_dataset_access`) decides who may read a volume; creating or
deleting one mutates the dataset's products and needs ownership
(`require_owned_dataset`).

    POST   /api/volumes/{dataset_id}/preview               what a build would do, or why not
    POST   /api/volumes/{dataset_id}                       build (requires "confirm": true)
    GET    /api/volumes/{dataset_id}                       list, each with its staleness
    GET    /api/volumes/{dataset_id}/{volume_id}           metadata + staleness
    GET    /api/volumes/{dataset_id}/{volume_id}/slice     one orthogonal slice
    GET    /api/volumes/{dataset_id}/{volume_id}/voxel     one voxel's provenance
    GET    /api/volumes/{dataset_id}/{volume_id}/render3d  bounded DISPLAY-ONLY texture
    GET    /api/volumes/{dataset_id}/{volume_id}/ground_truth   BAM overlay (separate layer)
    DELETE /api/volumes/{dataset_id}/{volume_id}
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import api.volumes as svc
from auth.dependencies import get_current_user, require_dataset_access, require_owned_dataset
from database.models import User
from database.volumes_store import delete_volume
from reconstruction.volume import VolumeRefused
from schemas.volume import VolumeConfig

router = APIRouter()


def _volume(dataset_id: str, volume_id: str):
    try:
        return svc.get(dataset_id, volume_id)
    except svc.VolumeNotFound:
        raise HTTPException(status_code=404, detail="Volume not found")


@router.post("/{dataset_id}/preview")
def preview(dataset_id: str, config: VolumeConfig = Body(default_factory=VolumeConfig),
            _ds=Depends(require_dataset_access)):
    return svc.do_preview(dataset_id, config)


@router.post("/{dataset_id}")
def create(dataset_id: str, body: dict = Body(...), user: User = Depends(get_current_user),
           _ds=Depends(require_owned_dataset)):
    if body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail=(
            "creating a volume needs explicit confirmation: send \"confirm\": true after "
            "reviewing the preview"))
    try:
        config = VolumeConfig.model_validate(body.get("config") or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        return svc.create(dataset_id, config, created_by=user.email)
    except VolumeRefused as exc:
        raise HTTPException(status_code=409, detail="refused: " + "; ".join(exc.reasons))


@router.get("/{dataset_id}")
def list_volumes(dataset_id: str, _ds=Depends(require_dataset_access)):
    return {"dataset_id": dataset_id, "volumes": svc.listing(dataset_id)}


@router.get("/{dataset_id}/{volume_id}")
def get_volume(dataset_id: str, volume_id: str, _ds=Depends(require_dataset_access)):
    return svc.product_payload(_volume(dataset_id, volume_id))


@router.get("/{dataset_id}/{volume_id}/slice")
def get_slice(dataset_id: str, volume_id: str, orientation: str = Query(...), index: int = Query(...),
              field: str = Query("radar_response"), thickness: int = Query(1),
              _ds=Depends(require_dataset_access)):
    try:
        return svc.slice_(_volume(dataset_id, volume_id), orientation, index, field, thickness)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{dataset_id}/{volume_id}/voxel")
def get_voxel(dataset_id: str, volume_id: str, i: int, j: int, k: int,
              _ds=Depends(require_dataset_access)):
    try:
        return svc.voxel(_volume(dataset_id, volume_id), i, j, k)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{dataset_id}/{volume_id}/render3d")
def get_render3d(dataset_id: str, volume_id: str, field: str = Query("response_envelope"),
                 max_dim: int = Query(160), _ds=Depends(require_dataset_access)):
    try:
        return svc.render3d(_volume(dataset_id, volume_id), field, max_dim)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{dataset_id}/{volume_id}/ground_truth")
def get_ground_truth(dataset_id: str, volume_id: str, ds=Depends(require_dataset_access)):
    return svc.ground_truth(_volume(dataset_id, volume_id), getattr(ds, "extra_metadata", None) or {})


@router.delete("/{dataset_id}/{volume_id}")
def remove(dataset_id: str, volume_id: str, _ds=Depends(require_owned_dataset)):
    _volume(dataset_id, volume_id)
    delete_volume(dataset_id, volume_id)
    return {"deleted": volume_id}
