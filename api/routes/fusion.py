from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.session import get_db
from database.models import Dataset, FusionSample as FusionSampleModel, gen_uuid
from database.records_store import load_all_records
from fusion.sensor_fusion import fuse_datasets, multimodal_only, non_fusable_partitions

router = APIRouter()


@router.post("/run")
def run_fusion(
    dataset_ids: Optional[list[str]] = Query(None, description="Restrict fusion to these dataset IDs; omit for all"),
    radius_m: Optional[float] = None,
    multimodal_only_flag: bool = True,
    persist: bool = True,
    db: Session = Depends(get_db),
):
    """
    Run spatial sensor fusion across ingested datasets and return (optionally
    persist) the resulting multimodal training samples.
    """
    records = load_all_records(dataset_ids)
    samples = fuse_datasets(records, radius_m=radius_m)
    # Records fusion could not place. Reported rather than silently absent:
    # an odometry or un-georeferenced dataset simply has no spatial
    # relationship to a geographic one until someone supplies a tie.
    excluded = non_fusable_partitions(records)
    if multimodal_only_flag:
        samples = multimodal_only(samples)

    if persist:
        for s in samples:
            db.add(
                FusionSampleModel(
                    id=gen_uuid(),
                    spatial_ref_kind=s.spatial_ref_kind,
                    center_lat=s.center_lat,
                    center_lon=s.center_lon,
                    center_x=s.center_x,
                    center_y=s.center_y,
                    radius_m=s.radius_m,
                    dataset_ids=s.dataset_ids,
                    sensor_types=s.sensor_types,
                    has_ground_truth=s.has_ground_truth,
                )
            )
        db.commit()

    return {
        "input_record_count": len(records),
        "fusion_sample_count": len(samples),
        "excluded_from_fusion": [
            {
                "position_kind": p.kind,
                "record_count": len(p.records),
                "dataset_ids": p.dataset_ids,
                "sensor_types": p.sensor_types,
                "reason": p.reason,
            }
            for p in excluded
        ],
        "samples": [
            {
                "spatial_ref_kind": s.spatial_ref_kind,
                "center_lat": s.center_lat,
                "center_lon": s.center_lon,
                "center_x": s.center_x,
                "center_y": s.center_y,
                "radius_m": s.radius_m,
                "sensor_types": s.sensor_types,
                "dataset_ids": s.dataset_ids,
                "has_ground_truth": s.has_ground_truth,
                "record_counts": {k: len(v) for k, v in s.records_by_sensor.items()},
            }
            for s in samples
        ],
    }


@router.get("/samples")
def list_fusion_samples(db: Session = Depends(get_db)):
    samples = db.query(FusionSampleModel).all()
    return [
        {
            "id": s.id,
            "spatial_ref_kind": s.spatial_ref_kind,
            "center_lat": s.center_lat,
            "center_lon": s.center_lon,
            "center_x": s.center_x,
            "center_y": s.center_y,
            "sensor_types": s.sensor_types,
            "dataset_ids": s.dataset_ids,
            "has_ground_truth": s.has_ground_truth,
        }
        for s in samples
    ]
