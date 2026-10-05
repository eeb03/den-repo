"""
Response-region API (Interpretation V1). Dataset-scoped like every volume
route, so the dataset's visibility rule decides who may read regions;
generating needs ownership. Reviews are append-only and need only access:
a review is the reviewer's own operator evidence.

    POST /api/volumes/{dataset_id}/{volume_id}/regions/preview
    POST /api/volumes/{dataset_id}/{volume_id}/regions                    (confirm: true)
    GET  /api/volumes/{dataset_id}/{volume_id}/regions
    GET  /api/volumes/{dataset_id}/{volume_id}/regions/{set_id}
    GET  /api/volumes/{dataset_id}/{volume_id}/regions/{set_id}/slice_labels
    GET  /api/volumes/{dataset_id}/{volume_id}/regions/{set_id}/export
    GET  /api/volumes/{dataset_id}/{volume_id}/regions/{set_id}/{region_id}
    POST /api/volumes/{dataset_id}/{volume_id}/regions/{set_id}/{region_id}/reviews
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import api.regions as svc
from auth.dependencies import get_current_user, require_dataset_access, require_owned_dataset
from database.models import User
from database.volumes_store import load_volume
from schemas.region import RegionConfig

router = APIRouter()


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except svc.NotFound as exc:
        raise HTTPException(status_code=404, detail=f"{exc} not found")
    except svc.RegionError as exc:
        raise HTTPException(status_code=409, detail="refused: " + "; ".join(exc.reasons))


@router.post("/{dataset_id}/{volume_id}/regions/preview")
def preview(dataset_id: str, volume_id: str, config: RegionConfig = Body(default_factory=RegionConfig),
            _ds=Depends(require_dataset_access)):
    return _guard(svc.preview, dataset_id, volume_id, config)


@router.post("/{dataset_id}/{volume_id}/regions")
def create(dataset_id: str, volume_id: str, body: dict = Body(...), user: User = Depends(get_current_user),
           _ds=Depends(require_owned_dataset)):
    if body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="generating regions needs explicit confirmation: "
                                                    "send \"confirm\": true after reviewing the preview")
    try:
        config = RegionConfig.model_validate(body.get("config") or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    rs = _guard(svc.create, dataset_id, volume_id, config, user.email)
    return svc.set_payload(rs)


@router.get("/{dataset_id}/{volume_id}/regions")
def list_sets(dataset_id: str, volume_id: str, _ds=Depends(require_dataset_access)):
    from database.regions_store import list_region_sets
    return {"volume_id": volume_id, "region_sets": [
        {"id": rs.id, "created_at": rs.created_at.isoformat(), "count": len(rs.regions), "migrated": rs.migrated,
         "z_unit": rs.z_unit, "algorithm": f"{rs.algorithm} {rs.algorithm_version}", "staleness": svc.staleness(rs)}
        for rs in list_region_sets(dataset_id, volume_id)]}


@router.get("/{dataset_id}/{volume_id}/regions/{set_id}")
def get_set(dataset_id: str, volume_id: str, set_id: str, _ds=Depends(require_dataset_access)):
    return svc.set_payload(_guard(svc.get_set, dataset_id, volume_id, set_id))


@router.get("/{dataset_id}/{volume_id}/regions/{set_id}/slice_labels")
def slice_labels(dataset_id: str, volume_id: str, set_id: str, orientation: str = Query(...),
                 index: int = Query(...), _ds=Depends(require_dataset_access)):
    rs = _guard(svc.get_set, dataset_id, volume_id, set_id)
    product = load_volume(dataset_id, volume_id)
    if product is None:
        raise HTTPException(status_code=404, detail="volume not found")
    return _guard(svc.slice_labels, rs, product, orientation, index)


@router.get("/{dataset_id}/{volume_id}/regions/{set_id}/export")
def export(dataset_id: str, volume_id: str, set_id: str, _ds=Depends(require_dataset_access)):
    rs = _guard(svc.get_set, dataset_id, volume_id, set_id)
    return svc.export_manifest(rs, load_volume(dataset_id, volume_id))


@router.get("/{dataset_id}/{volume_id}/regions/{set_id}/{region_id}")
def get_region(dataset_id: str, volume_id: str, set_id: str, region_id: str,
               _ds=Depends(require_dataset_access)):
    rs = _guard(svc.get_set, dataset_id, volume_id, set_id)
    return _guard(svc.region_payload, rs, region_id)


@router.post("/{dataset_id}/{volume_id}/regions/{set_id}/{region_id}/reviews")
def add_review(dataset_id: str, volume_id: str, set_id: str, region_id: str, body: dict = Body(...),
               user: User = Depends(get_current_user), _ds=Depends(require_dataset_access)):
    rs = _guard(svc.get_set, dataset_id, volume_id, set_id)
    r = _guard(svc.review, rs, region_id, str(body.get("status", "")), user.email, body.get("notes"))
    return {"review": r.model_dump(mode="json"), "region": svc.region_payload(rs, region_id)}
