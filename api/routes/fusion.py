from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, visible_dataset_ids
from database.models import User
from database.session import get_db
from database.models import Dataset, FusionSample as FusionSampleModel, gen_uuid
from database.frames_store import load_frames_for
from database.records_store import load_all_records
from fusion.sensor_fusion import fuse_datasets, multimodal_only, non_fusable_partitions

router = APIRouter()

# A fusion sample stays listed once ANY of its member datasets is visible to
# the caller (slice 27) -- dropping the sample would misreport that a sample
# involving something the caller CAN see does not exist. But the other
# member IDs in that sample can name a dataset the caller cannot open: a real
# UUID for another user's private data, discoverable only because it shares
# a fusion sample with something the caller owns. This placeholder replaces
# each invisible ID in place -- the array's length and each visible id's
# position are unchanged, so the reported dataset count stays honest while
# no foreign identity leaks.
REDACTED_DATASET_ID = "dataset-not-visible"


@router.post("/run")
def run_fusion(
    dataset_ids: Optional[list[str]] = Query(None, description="Restrict fusion to these dataset IDs; omit for all"),
    radius_m: Optional[float] = None,
    multimodal_only_flag: bool = True,
    persist: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Run spatial sensor fusion across ingested datasets and return (optionally
    persist) the resulting multimodal training samples.

    VISIBILITY, THE SAME RULE AS THE GET (slice 27). Omitting `dataset_ids`
    used to glob and fuse every `*.jsonl` on disk -- every user's records,
    not this caller's. It now resolves to this caller's visible set (their
    own datasets, plus unowned/system data) instead. Naming a dataset the
    caller cannot see is refused whole, as a 404 -- the same wording
    `dataset_or_404` already uses elsewhere -- rather than silently fusing
    only the visible ids from a mixed list, which would let a caller learn
    which of several ids exist by seeing which ones got fused.
    """
    visible = visible_dataset_ids(db, user)

    if dataset_ids is None:
        # Omit means "what I can see", not "every file that has ever been
        # ingested by anyone".
        resolved_ids = sorted(visible)
    else:
        invisible = [d for d in dataset_ids if d not in visible]
        if invisible:
            raise HTTPException(status_code=404, detail="Dataset not found")
        resolved_ids = dataset_ids

    # load_all_records(ids) reads `ids or glob(*.jsonl)` -- an empty list is
    # falsy, so passing [] straight through would glob every file on disk,
    # the exact leak this endpoint exists to close. A resolved set of
    # nothing must load nothing, never fall through to "everything".
    records = load_all_records(resolved_ids) if resolved_ids else []
    # Frames carry the declared CRS, so a projected survey can be reprojected
    # into the geographic frame and fused with it. Without them, projected
    # records stay excluded -- which is the honest outcome, not a failure.
    frames = load_frames_for(r.dataset_id for r in records)
    samples = fuse_datasets(records, radius_m=radius_m, frames=frames)
    # Records fusion could not place. Reported rather than silently absent:
    # an odometry or un-georeferenced dataset simply has no spatial
    # relationship to a geographic one until someone supplies a tie.
    excluded = non_fusable_partitions(records, frames=frames)
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
                    n_reprojected=s.n_reprojected,
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
                "n_reprojected": s.n_reprojected,
                "record_counts": {k: len(v) for k, v in s.records_by_sensor.items()},
            }
            for s in samples
        ],
    }


@router.get("/samples")
def list_fusion_samples(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Same visibility rule as the dataset list: a sample is returned iff at
    # least one of its member datasets is visible to this caller (their own,
    # or unowned/system). A sample that DOES include a visible dataset must
    # not disappear -- that would misreport it as not existing. Within an
    # included sample, any OTHER member id the caller cannot open is replaced
    # with REDACTED_DATASET_ID rather than shown verbatim or dropped: showing
    # it would leak another user's dataset id, dropping it would misreport
    # how many datasets went into the sample.
    visible = visible_dataset_ids(db, user)
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
            "dataset_ids": [
                d if d in visible else REDACTED_DATASET_ID
                for d in (s.dataset_ids or [])
            ],
            "has_ground_truth": s.has_ground_truth,
            "radius_m": s.radius_m,
            "n_reprojected": s.n_reprojected,
        }
        for s in samples
        if visible.intersection(s.dataset_ids or [])
    ]
