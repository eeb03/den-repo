import math
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.session import get_db
from database.models import Dataset, User, gen_uuid
from schemas.subterra_record import SensorType
from converters.registry import get_converter
from converters.base import MissingDependencyError
from validators.dataset_validator import validate_dataset
from preprocessing.pipeline import run_pipeline
from preprocessing.time_zero import apply_time_zero_for_dataset
from database.records_store import save_records, load_records
from database.frames_store import load_frames, save_frames, synthesize_frames_from_records
from schemas.spatial import Assumption, AxisKind, has_geographic_coordinates
from ingestion.downloader import download_file, DownloadError
from converters.registry import supported_extensions
from preprocessing.dem_alignment import align_records_with_dem
from configs.settings import settings
from api import dataset_lifecycle as lifecycle
from jobs import storage
from utils.logger import get_logger
from auth.dependencies import (
    get_current_user,
    require_dataset_access,
    require_owned_dataset,
    visible_datasets,
)

logger = get_logger(__name__)

router = APIRouter()


def _geographic_centre(records) -> tuple[Optional[float], Optional[float]]:
    """
    Mean position of the records that HAVE one, or (None, None).

    Averaging over records without coordinates used to drag the centre
    toward null island; a dataset with no geographic position now reports
    no centre at all, which is the truth.
    """
    positioned = [r for r in records if has_geographic_coordinates(r)]
    if not positioned:
        return None, None
    return (sum(r.latitude for r in positioned) / len(positioned),
            sum(r.longitude for r in positioned) / len(positioned))


#: What a modality gets when the caller names no preprocessing mode.
#:
#: GPR resolves to the FULL chain -- `gpr_trace_processing` then
#: `gpr_local_anomaly` -- because that is the composition both benchmarks and the
#: corpus characterisation measure, and the one the regression baseline pins.
#: `gpr_local_anomaly` alone produces a materially different and previously
#: unbenchmarked candidate population (Stage 18 measured 39 cells over |z|>3
#: against 164 on the same real line). This is a claim about which processing the
#: published numbers describe -- NOT a claim that the resulting signal is
#: cleaner, better or more accurate, which nothing here has established.
#:
#: Every other modality keeps "trace". Nothing about their behaviour changes.
DEFAULT_PREPROCESSING_MODE_BY_MODALITY: dict[SensorType, str] = {
    SensorType.GPR: "gpr_full",
}
FALLBACK_PREPROCESSING_MODE = "trace"


def default_preprocessing_mode(sensor_type: SensorType) -> str:
    """The mode used when a caller names none. Never overrides an explicit choice."""
    return DEFAULT_PREPROCESSING_MODE_BY_MODALITY.get(
        sensor_type, FALLBACK_PREPROCESSING_MODE)


def _run_ingest_pipeline(
    raw_path: Path,
    sensor_type: SensorType,
    name: str,
    db: Session,
    source: Optional[str] = None,
    license: Optional[str] = None,
    source_url: Optional[str] = None,
    apply_preprocessing: bool = True,
    preprocessing_mode: Optional[str] = None,
    converter_kwargs: Optional[dict] = None,
    on_stage: Optional[Callable[[str], None]] = None,
    owner_id: Optional[str] = None,
) -> dict:
    """
    The core pipeline shared by every ingest entrypoint (direct upload,
    URL download, source-connector download, local file): convert ->
    validate -> (preprocess) -> persist records -> register metadata.

    preprocessing_mode=None (unspecified) resolves per modality via
    `default_preprocessing_mode`: GPR gets the benchmark-aligned "gpr_full"
    chain, everything else keeps "trace". Passing a mode explicitly always
    wins, including passing "trace" for a GPR dataset.

    preprocessing_mode="trace" treats each record's signal as a multi-sample
    waveform. Use "spatial_grid" for single-value-per-point raster data (GPR
    depth slices, magnetometer/gravity surveys) so smoothing/normalization
    happens across real spatial neighbors instead of being a no-op on a
    length-1 array.

    converter_kwargs passes format-specific options through to the
    converter (e.g. {"stride": 1} for GeoTIFFConverter on a small DEM tile
    where the default stride=10 would sample almost nothing).

    `owner_id`, when given, is the account the resulting dataset belongs to. It
    is passed by the IMPORT WORKER from the job record -- never read from a
    request body -- so a client cannot name the owner of what it uploads.
    Defaulting to None keeps every existing caller producing system/public
    datasets, which is what a script-run ingest genuinely is.

    `on_stage`, when given, is called with the name of each step as it begins
    -- "converting", "validating", "preprocessing", "persisting",
    "registering". It exists so a background import can report WHICH step it is
    in without this function having to know anything about jobs, and so the
    interface never has to invent a completion percentage the pipeline cannot
    actually measure. It defaults to None, so every existing caller is
    unchanged.
    """
    def _stage(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    _stage("converting")
    try:
        converter = get_converter(raw_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    dataset_id = gen_uuid()

    try:
        result = converter.load(raw_path, dataset_id=dataset_id, sensor_type=sensor_type, **(converter_kwargs or {}))
        records, frames = result.records, result.frames
    except MissingDependencyError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Conversion failed: {e}")

    _stage("validating")
    report = validate_dataset(records, dataset_id=dataset_id, source_file=raw_path)

    # Resolved AFTER the sensor type is known, and only when the caller named
    # nothing: an explicit mode always wins, including an explicit "trace" on a
    # GPR dataset.
    resolved_mode = (preprocessing_mode if preprocessing_mode is not None
                     else default_preprocessing_mode(sensor_type))

    if apply_preprocessing:
        _stage("preprocessing")
        records = run_pipeline(records, mode=resolved_mode)

    _stage("persisting")
    save_records(dataset_id, records)
    # Converters not yet migrated to load() return no frames; reconstruct one
    # from the records so every dataset has frame coverage from ingest onward.
    save_frames(dataset_id, frames or synthesize_frames_from_records(records))

    _stage("registering")
    center_lat, center_lon = _geographic_centre(records)
    has_gt = any(r.ground_truth.value != "none" for r in records)

    dataset = Dataset(
        id=dataset_id,
        name=name,
        source=source,
        source_url=source_url,
        license=license,
        sensor_type=sensor_type.value,
        original_format=converter.format_name,
        checksum=report.checksum,
        quality_score=report.quality_score,
        record_count=report.record_count,
        raw_path=str(raw_path),
        has_ground_truth=has_gt,
        center_lat=center_lat,
        center_lon=center_lon,
        owner_id=owner_id,
        # THE MODE IS RECORDED, and only when it was actually applied.
        #
        # Ingest previously stored nothing about how records were processed, so
        # a dataset's processing was unknowable after the fact. It is written
        # here under the SAME key `/reprocess` already uses, so one field answers
        # "what produced these records" wherever they came from.
        #
        # Datasets ingested before this stage carry no such key, and absence
        # must read as UNRECORDED -- never as `gpr_full`. Nothing infers a mode
        # for them, and nothing reprocesses them.
        extra_metadata={
            "validation_issues": report.issues,
            **({"last_preprocessing_mode": resolved_mode,
                "preprocessing_mode_source": (
                    "explicit" if preprocessing_mode is not None else "modality_default")}
               if apply_preprocessing else {}),
        },
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    return {
        "dataset_id": dataset.id,
        "record_count": report.record_count,
        "quality_score": report.quality_score,
        "issues": report.issues,
        "preprocessing_applied": apply_preprocessing,
        "preprocessing_mode": resolved_mode if apply_preprocessing else None,
    }


@router.post("/ingest")
async def ingest_dataset(
    file: UploadFile = File(...),
    sensor_type: SensorType = Form(...),
    name: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    license: Optional[str] = Form(None),
    apply_preprocessing: bool = Form(True),
    preprocessing_mode: Optional[str] = Form(None, description="omit to use the modality default ('gpr_full' for GPR, 'trace' otherwise); 'trace' for multi-sample waveforms, 'spatial_grid' for single-value raster/depth-slice data"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Full ingest pipeline from a direct file upload: save -> convert ->
    validate -> (preprocess) -> register. This is the PRD's "Data
    Conversion Engine" + "Dataset Validator" + "Metadata Database" wired
    together.
    """
    # SECURITY. This previously wrote to `settings.raw_dir / file.filename`
    # with the client's filename unmodified, so a name like
    # `../../../etc/evil.csv` escaped the raw directory and a repeated name
    # silently overwrote an earlier upload.
    #
    # The fix REUSES the storage helper the async import path already uses
    # rather than adding a second sanitiser that could drift from it: the
    # filename is reduced to one safe component, the bytes land in a directory
    # named for a server-generated id (so a collision is unrepresentable), and
    # a partial write is never renamed into place. The original filename is
    # kept only as the dataset's display name, never as a path.
    try:
        raw_path, _, _, _ = storage.save_upload(gen_uuid(), file.filename, file.file)
    except storage.EmptyUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except storage.UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc))

    return _run_ingest_pipeline(
        raw_path, sensor_type, name or file.filename, db,
        source=source, license=license, apply_preprocessing=apply_preprocessing,
        preprocessing_mode=preprocessing_mode,
        owner_id=user.id,
    )


class IngestFromURLRequest(BaseModel):
    url: str
    sensor_type: SensorType
    name: Optional[str] = None
    source: Optional[str] = None
    license: Optional[str] = None
    expected_sha256: Optional[str] = None
    apply_preprocessing: bool = True
    preprocessing_mode: Optional[str] = None


@router.post("/ingest_from_url")
def ingest_from_url(req: IngestFromURLRequest, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    """
    Same pipeline as /ingest, but for a dataset that lives at a URL —
    e.g. a download_url returned by /api/sources/{source}/search. Downloads
    with resume/retry/checksum via the same downloader used by the source
    connectors, then runs it through convert -> validate -> register.
    """
    filename = req.name or req.url.split("/")[-1].split("?")[0] or "download.bin"
    try:
        downloaded_path = download_file(req.url, dest_filename=filename, expected_sha256=req.expected_sha256)
    except DownloadError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Converters dispatch by file extension; downloaded filenames from some
    # sources (e.g. Zenodo's /content URLs) don't always carry one, so copy
    # into raw_dir preserving whatever extension we do have.
    raw_path = settings.raw_dir / downloaded_path.name
    if downloaded_path != raw_path:
        shutil.copy(downloaded_path, raw_path)

    return _run_ingest_pipeline(
        raw_path, req.sensor_type, req.name or filename, db,
        source=req.source, license=req.license, source_url=req.url,
        apply_preprocessing=req.apply_preprocessing,
        preprocessing_mode=req.preprocessing_mode,
    )


@router.post("/{dataset_id}/reprocess")
def reprocess_dataset(
    dataset_id: str,
    preprocessing_mode: str = "spatial_grid",
    smoothing_window: int = 3,
    normalize: bool = True,
    inner_window: int = 5,
    outer_window: int = 15,
    min_ring_count: int = 20,
    trace_inner_window: int = 2,
    trace_outer_window: int = 6,
    depth_inner_window: int = 5,
    depth_outer_window: int = 15,
    min_trace_ring_count: int = 4,
    min_depth_ring_count: int = 10,
    dewow_window: int = 15,
    gain_type: str = "linear",
    gain_power: float = 1.0,
    background_removal_enabled: bool = True,
    dewow_enabled: bool = True,
    gain_enabled: bool = True,
    db: Session = Depends(get_db),
    _dataset=Depends(require_owned_dataset),
):
    """
    Re-run preprocessing on an already-ingested dataset's stored records.

    preprocessing_mode options:
    - "spatial_grid": smooth + (optionally) z-score normalize across the
      whole dataset. Set normalize=false for raw-unit smoothed output.
    - "local_anomaly": compute each point's deviation from its own local
      background (ring between inner_window and outer_window) instead of
      the whole dataset's statistics — surfaces spatially small real
      anomalies that a global z-score would dilute into noise. Bins by
      (lat, lon) — meant for area-covering depth-slice surveys.
    - "gpr_local_anomaly": the same local-anomaly ring statistic, indexed
      by (trace_index, depth) instead of (lat, lon) — for real multi-
      sample SEG-Y trace data, where a single survey line's points would
      otherwise bin into a mostly-empty lat/lon grid. Uses its OWN
      trace_inner_window/trace_outer_window/min_trace_ring_count and
      depth_inner_window/depth_outer_window/min_depth_ring_count instead
      of inner_window/outer_window/min_ring_count — trace and depth
      spacing are not comparable in scale (e.g. ~0.246 m/trace vs.
      ~0.0146 m/sample on the real C1T_7,5_0001 line), so a single
      isotropic window can't meaningfully flag low-confidence cells on
      both axes (see preprocessing/spatial_grid.py::preprocess_trace_local_anomaly).
      See /trace_grid to inspect the result as a radargram-style 2D image.
    - "gpr_trace_processing": classic dewow / background removal / gain,
      for multi-sample trace data (SEG-Y sourced). Reconstructs full
      traces from per-sample records via trace_index/depth when needed.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Uncached: run_pipeline reprocesses these records and they are saved back,
    # so this path must not be handed the shared cached objects.
    records = load_records(dataset_id, use_cache=False)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    records = run_pipeline(
        records, mode=preprocessing_mode, smoothing_window=smoothing_window, normalize=normalize,
        inner_window=inner_window, outer_window=outer_window, min_ring_count=min_ring_count,
        trace_inner_window=trace_inner_window, trace_outer_window=trace_outer_window,
        depth_inner_window=depth_inner_window, depth_outer_window=depth_outer_window,
        min_trace_ring_count=min_trace_ring_count, min_depth_ring_count=min_depth_ring_count,
        dewow_window=dewow_window, gain_type=gain_type, gain_power=gain_power,
        background_removal_enabled=background_removal_enabled, dewow_enabled=dewow_enabled, gain_enabled=gain_enabled,
    )
    save_records(dataset_id, records)

    report = validate_dataset(records, dataset_id=dataset_id)
    dataset.quality_score = report.quality_score
    dataset.extra_metadata = {
        **(dataset.extra_metadata or {}),
        "validation_issues": report.issues,
        "last_preprocessing_mode": preprocessing_mode,
        "last_normalize": normalize,
    }
    db.commit()

    return {
        "dataset_id": dataset_id,
        "record_count": len(records),
        "quality_score": report.quality_score,
        "preprocessing_mode": preprocessing_mode,
    }


@router.post("/{dataset_id}/apply_time_zero")
def apply_time_zero(
    dataset_id: str,
    velocity_m_per_ns: Optional[float] = None,
    db: Session = Depends(get_db),
    _dataset=Depends(require_owned_dataset),
):
    """
    Resolve and apply a time-zero correction to this dataset's stored
    records, PER FRAME (per acquisition line/file) -- the method hierarchy
    from `preprocessing.time_zero.resolve_time_zero_for_frame`: Method A
    (SEG-Y `DelayRecordingTime`) -> an existing operator
    `DeclarationKind.TIME_ZERO` declaration -> Method C
    (`direct_wave_consensus_time_zero`, the one algorithmic method).

    THE FIRST LIVE CALLER. Until this endpoint existed, the time-zero
    framework was fully implemented and tested but never invoked by any
    real path. A `DeclarationKind.TIME_ZERO` declaration itself remains
    non-retroactive (see `api/spatial.py`'s own TIME_ZERO branch, which
    only records the claim) -- calling THIS endpoint is the explicit,
    separate step that actually writes a correction onto records,
    mirroring how `/reprocess` above is the explicit step for
    dewow/background/gain rather than something ingest reruns silently.

    NEVER GUESSES. A frame with no metadata field, no declaration, and
    whose traces don't produce a defensible cross-trace consensus is
    reported `unavailable`/`inconclusive` for that frame -- its records'
    `corrected_time_ns` stays unset and `depth` is left exactly as it was.
    `original_time_ns` is always preserved, for every frame, regardless of
    outcome.

    `velocity_m_per_ns`, if supplied, overrides the velocity used to
    recompute depth for every frame this call resolves a correction for
    (recorded with source `"supplied_by_caller"`). Without it, each
    frame's OWN already-recorded ingest velocity is reused -- this
    endpoint never estimates a new velocity, only reapplies the existing
    one to the now-corrected time axis.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Uncached: this call mutates records and saves them back.
    records = load_records(dataset_id, use_cache=False)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    frames = load_frames(dataset_id) or synthesize_frames_from_records(records)
    eligible = [f for f in frames
                if f.vertical_axis.kind in (AxisKind.TWO_WAY_TIME_NS,
                                            AxisKind.TWO_WAY_TIME_MS,
                                            AxisKind.TWO_WAY_TIME_S)]
    if not eligible:
        raise HTTPException(
            status_code=409,
            detail="no frame carries a measured time axis, so there is no time-zero to correct")

    velocity_overrides = (
        {f.frame_id: velocity_m_per_ns for f in eligible}
        if velocity_m_per_ns is not None else None)
    records, results = apply_time_zero_for_dataset(records, frames, velocity_overrides=velocity_overrides)
    save_records(dataset_id, records)

    report = validate_dataset(records, dataset_id=dataset_id)
    dataset.quality_score = report.quality_score
    dataset.extra_metadata = {
        **(dataset.extra_metadata or {}),
        "validation_issues": report.issues,
    }
    db.commit()

    return {
        "dataset_id": dataset_id,
        "record_count": len(records),
        "quality_score": report.quality_score,
        "frames": {
            frame_id: result.model_dump(mode="json") for frame_id, result in results.items()
        },
        "resolved_frame_count": sum(1 for r in results.values() if r.resolved),
        "frame_count": len(results),
    }


@router.post("/{dataset_id}/align_dem")
def align_dataset_with_dem(dataset_id: str, dem_filename: str, db: Session = Depends(get_db),
    _dataset=Depends(require_owned_dataset)):
    """
    Look up ground-surface elevation from a DEM GeoTIFF (e.g. one fetched via
    /api/sources/opentopography/dem, saved under datasets/downloads/) at each
    of this dataset's (lat, lon) points via bilinear interpolation. Sets
    record.elevation and, where depth is known, stores the resulting
    absolute elevation (surface - depth) in metadata. `dem_filename` is
    resolved relative to datasets/downloads/.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Uncached: DEM alignment rewrites these records and saves them back.
    records = load_records(dataset_id, use_cache=False)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    dem_path = Path(dem_filename)
    if not dem_path.is_absolute():
        dem_path = settings.downloads_dir / dem_filename

    try:
        records = align_records_with_dem(records, dem_path)
    except MissingDependencyError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DEM alignment failed: {e}")

    save_records(dataset_id, records)

    n_aligned = sum(1 for r in records if r.elevation is not None)
    dataset.extra_metadata = {
        **(dataset.extra_metadata or {}),
        "dem_aligned": True,
        "dem_source": str(dem_path.name),
        "dem_aligned_record_count": n_aligned,
    }
    db.commit()

    return {
        "dataset_id": dataset_id,
        "total_records": len(records),
        "records_aligned": n_aligned,
        "dem_source": dem_path.name,
    }


class IngestLocalFileRequest(BaseModel):
    path: str  # relative to datasets/ (e.g. "downloads/COP30_....tif") or absolute inside the container
    sensor_type: SensorType
    name: Optional[str] = None
    source: Optional[str] = None
    license: Optional[str] = None
    apply_preprocessing: bool = True
    preprocessing_mode: Optional[str] = None
    geotiff_stride: Optional[int] = None


@router.post("/ingest_local_file")
def ingest_local_file(req: IngestLocalFileRequest, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    """
    Ingest a file that's already on disk in the container — e.g. a DEM
    tile saved by /api/sources/opentopography/dem — without re-uploading
    it through multipart. `path` is resolved relative to datasets/ unless
    given as absolute.
    """
    src_path = Path(req.path)
    if not src_path.is_absolute():
        src_path = settings.data_root / req.path
    if not src_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {src_path}")

    raw_path = settings.raw_dir / src_path.name
    if src_path != raw_path:
        shutil.copy(src_path, raw_path)

    converter_kwargs = {}
    if req.geotiff_stride is not None:
        converter_kwargs["stride"] = req.geotiff_stride

    return _run_ingest_pipeline(
        raw_path, req.sensor_type, req.name or src_path.name, db,
        source=req.source, license=req.license, apply_preprocessing=req.apply_preprocessing,
        preprocessing_mode=req.preprocessing_mode, converter_kwargs=converter_kwargs,
    )


def _run_depth_slice_pipeline(
    raw_path: Path,
    dataset_id: str,
    depth: float,
    db: Session,
    apply_preprocessing: bool = True,
    preprocessing_mode: str = "trace",
) -> dict:
    """
    Shared logic for adding ONE depth slice to an EXISTING dataset — unlike
    _run_ingest_pipeline, this appends to a dataset_id's stored records
    rather than creating a new dataset. This is what turns a set of
    single-depth Zenodo/source files into one genuine multi-depth survey
    that the depth-slice tabs, /grid?depth=, and fusion machinery already
    know how to use.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    try:
        converter = get_converter(raw_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sensor_type = SensorType(dataset.sensor_type)
    try:
        new_records = converter.convert(raw_path, dataset_id=dataset_id, sensor_type=sensor_type)
    except MissingDependencyError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Conversion failed: {e}")

    if not new_records:
        raise HTTPException(status_code=422, detail="File produced zero records after conversion.")

    # The requested depth wins over whatever the source file's own depth
    # column says (if any) -- exported per-depth-slice files often have no
    # reliable depth field of their own, so the caller telling us "this
    # file is the 1.0-1.5m slice" is the authoritative source of truth.
    for r in new_records:
        r.depth = depth

    if apply_preprocessing:
        new_records = run_pipeline(new_records, mode=preprocessing_mode)

    # Uncached: these records are concatenated with the new slice and saved back.
    existing_records = load_records(dataset_id, use_cache=False)
    existing_depths = {round(r.depth, 4) for r in existing_records if r.depth is not None}
    if round(depth, 4) in existing_depths:
        raise HTTPException(
            status_code=409,
            detail=f"Dataset already has a depth slice at {depth}m. Delete it first or use a different depth value.",
        )

    combined = existing_records + new_records
    save_records(dataset_id, combined)

    report = validate_dataset(combined, dataset_id=dataset_id)
    dataset.record_count = len(combined)
    dataset.quality_score = report.quality_score
    db.commit()

    from preprocessing.spatial_grid import list_available_depths
    return {
        "dataset_id": dataset_id,
        "depth_added": depth,
        "records_added": len(new_records),
        "total_records": len(combined),
        "depths": list_available_depths(combined),
    }


class IngestDepthSliceLocalRequest(BaseModel):
    path: str
    depth: float
    apply_preprocessing: bool = True
    preprocessing_mode: str = "trace"


@router.post("/{dataset_id}/ingest_depth_slice")
def ingest_depth_slice(dataset_id: str, req: IngestDepthSliceLocalRequest, db: Session = Depends(get_db),
    _dataset=Depends(require_owned_dataset)):
    """Add one depth slice (from a file already on disk) to an existing multi-depth dataset."""
    src_path = Path(req.path)
    if not src_path.is_absolute():
        src_path = settings.data_root / req.path
    if not src_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {src_path}")

    raw_path = settings.raw_dir / f"{dataset_id}_depth{req.depth}_{src_path.name}"
    if src_path != raw_path:
        shutil.copy(src_path, raw_path)

    return _run_depth_slice_pipeline(
        raw_path, dataset_id, req.depth, db,
        apply_preprocessing=req.apply_preprocessing, preprocessing_mode=req.preprocessing_mode,
    )


class IngestDepthSliceURLRequest(BaseModel):
    url: str
    depth: float
    expected_sha256: Optional[str] = None
    apply_preprocessing: bool = True
    preprocessing_mode: str = "trace"


@router.post("/{dataset_id}/ingest_depth_slice_from_url")
def ingest_depth_slice_from_url(dataset_id: str, req: IngestDepthSliceURLRequest, db: Session = Depends(get_db),
    _dataset=Depends(require_owned_dataset)):
    """Add one depth slice (downloaded from a URL) to an existing multi-depth dataset."""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    filename = req.url.split("/")[-1].split("?")[0] or "download.bin"
    try:
        downloaded_path = download_file(req.url, dest_filename=f"{dataset_id}_depth{req.depth}_{filename}", expected_sha256=req.expected_sha256)
    except DownloadError as e:
        raise HTTPException(status_code=502, detail=str(e))

    raw_path = settings.raw_dir / downloaded_path.name
    if downloaded_path != raw_path:
        shutil.copy(downloaded_path, raw_path)

    return _run_depth_slice_pipeline(
        raw_path, dataset_id, req.depth, db,
        apply_preprocessing=req.apply_preprocessing, preprocessing_mode=req.preprocessing_mode,
    )


class IngestZipFromURLRequest(BaseModel):
    url: str
    sensor_type: SensorType
    name: Optional[str] = None
    source: Optional[str] = None
    license: Optional[str] = None
    expected_sha256: Optional[str] = None
    apply_preprocessing: bool = True
    preprocessing_mode: Optional[str] = None
    max_files: int = 20  # safety cap -- large archives can contain hundreds of files
    # EXPLICIT, dataset-scoped CRS declaration for source formats that carry
    # coordinates without declaring what they are (SEG-Y SourceX/SourceY).
    # Never inferred, never defaulted: omitting it leaves projected header
    # coordinates preserved-but-unconvertible, which is the honest state.
    crs: Optional[str] = None


@router.post("/ingest_zip_from_url")
def ingest_zip_from_url(req: IngestZipFromURLRequest, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    """
    Downloads a .zip archive, extracts it, finds every file inside (incl.
    subdirectories) whose extension has a registered converter, converts
    each one, and combines all resulting records into ONE dataset. This is
    the missing piece for datasets distributed as a zip of multiple
    survey-line files (e.g. Site_1.zip containing several .sgy lines) --
    plain /ingest_from_url can't handle an archive since converters
    dispatch by file extension and .zip has none.

    Files inside the archive with no matching converter (e.g. a
    proprietary format, readme, preview image) are silently skipped; if
    NONE of the archive's files are supported, this returns a 422 saying
    so explicitly rather than pretending to have ingested something.
    """
    from ingestion.source_resolver import resolve

    filename = req.name or req.url.split("/")[-1].split("?")[0] or "download.zip"
    try:
        downloaded_path = download_file(req.url, dest_filename=filename, expected_sha256=req.expected_sha256)
    except DownloadError as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        scan = resolve(downloaded_path)
        supported_files = [s.primary for s in scan.sources]
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not extract zip archive: {e}")

    if not supported_files:
        recognized = scan.unsupported_summary()
        if recognized:
            detail = (
                f"No READABLE files found inside {filename}, but it does contain "
                f"{sum(recognized.values())} file(s) in recognised formats the platform "
                f"cannot yet read: {recognized}. An adapter for these does not exist yet. "
                f"Readable formats: {sorted(supported_extensions())}."
            )
        else:
            detail = (
                f"No supported files found inside {filename}. SDP currently converts: "
                f"{sorted(supported_extensions())}."
            )
        raise HTTPException(status_code=422, detail=detail)
    if len(supported_files) > req.max_files:
        raise HTTPException(
            status_code=422,
            detail=f"Archive contains {len(supported_files)} supported files, exceeding max_files={req.max_files}. Raise max_files if this is intentional.",
        )

    dataset_id = gen_uuid()
    all_records = []
    all_frames = []
    per_file_errors = []
    georeferenced_count = 0

    from ingestion.kmz_georeference import (build_georeference_lookup,
                                            georeference_records_by_trace, records_needing_kmz_fallback)
    # Sidecars come from source resolution, which attaches a .kmz to every
    # SEG-Y it could belong to. This replaces a hardcoded two-attempt
    # directory search that only ever ran on this one endpoint.
    kmz_files = scan.acquisition_sidecars
    kmz_lookup = build_georeference_lookup(kmz_files) if kmz_files else {}
    if kmz_lookup:
        logger.info(f"ingest_zip_from_url: found {len(kmz_files)} KMZ file(s) with {len(kmz_lookup)} named path(s) for georeferencing")

    for file_path in supported_files:
        try:
            converter = get_converter(file_path)
            converter_kwargs = {"crs": req.crs} if req.crs else {}
            result = converter.load(file_path, dataset_id=dataset_id,
                                    sensor_type=req.sensor_type, **converter_kwargs)
            records = result.records
            file_frames = result.frames or synthesize_frames_from_records(records)

            # SEG-Y header positions are AUTHORITATIVE where usable: they
            # were measured to be a real per-trace acquisition track
            # matching the KMZ to ~1 m (see ingestion/kmz_georeference.py).
            # KMZ is the FALLBACK, applied only when the headers cannot
            # supply a geographic position -- it never overwrites one.
            #
            # WHEN THE FALLBACK DOES RUN IT REPLACES `record.position`. It sets
            # latitude/longitude AND a GeographicPosition, because a KMZ track
            # is a real geographic position and `position` is the platform's
            # single source of spatial truth (georeference_records_by_trace).
            # A projected header position, which is what this branch means by
            # "no geographic view", is therefore superseded -- not kept. The
            # header numbers survive in metadata["segy_x"]/["segy_y"], written
            # by SEGYConverter, so nothing the file reported is lost.
            stem = file_path.stem
            needs_fallback = records_needing_kmz_fallback(records)
            if stem in kmz_lookup and len(records) > 0 and needs_fallback:
                georeference_records_by_trace(records, kmz_lookup[stem])
                georeferenced_count += 1
                for fr in file_frames:
                    fr.assumptions.append(Assumption(
                        key="position_source",
                        value="kmz_fallback",
                        basis=(
                            "the file's own headers did not yield a geographic position "
                            "(absent, or projected with no declared CRS), so latitude, longitude "
                            "AND record.position were taken from the matching KMZ track. Any "
                            "projected header position is superseded, not retained; the header "
                            "coordinates themselves are preserved in metadata segy_x/segy_y."
                        ),
                        verified=True,
                    ))
            elif len(records) > 0:
                for fr in file_frames:
                    fr.assumptions.append(Assumption(
                        key="position_source",
                        value="segy_header",
                        basis=(
                            "the file's own trace headers supplied a usable geographic position; "
                            "KMZ georeferencing was NOT applied and did not overwrite it"
                            + ("" if stem in kmz_lookup else " (no matching KMZ placemark either)")
                        ),
                        verified=True,
                    ))

            all_records.extend(records)
            all_frames.extend(file_frames)
        except MissingDependencyError as e:
            per_file_errors.append(f"{file_path.name}: {e}")
        except Exception as e:
            per_file_errors.append(f"{file_path.name}: {e}")

    if not all_records:
        raise HTTPException(
            status_code=422,
            detail=f"All {len(supported_files)} supported file(s) failed to convert. Errors: {per_file_errors}",
        )

    report = validate_dataset(all_records, dataset_id=dataset_id, source_file=downloaded_path)

    if req.apply_preprocessing:
        all_records = run_pipeline(all_records, mode=req.preprocessing_mode)

    save_records(dataset_id, all_records)
    save_frames(dataset_id, all_frames)

    center_lat, center_lon = _geographic_centre(all_records)
    has_gt = any(r.ground_truth.value != "none" for r in all_records)

    dataset = Dataset(
        id=dataset_id, name=req.name or filename, source=req.source, source_url=req.url, license=req.license,
        sensor_type=req.sensor_type.value, original_format=f"zip({len(supported_files)} files)",
        checksum=report.checksum, quality_score=report.quality_score, record_count=report.record_count,
        raw_path=str(downloaded_path), has_ground_truth=has_gt, center_lat=center_lat, center_lon=center_lon,
        extra_metadata={
            "validation_issues": report.issues, "files_in_archive": len(supported_files),
            "per_file_errors": per_file_errors,
            # Recognised formats we could not read. Reported rather than
            # silently dropped, so a partially-ingested archive is visible.
            "recognized_unsupported": scan.unsupported_summary(),
        },
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    return {
        "dataset_id": dataset.id,
        "files_found_in_archive": len(supported_files),
        "files_converted_successfully": len(supported_files) - len(per_file_errors),
        "per_file_errors": per_file_errors,
        "record_count": report.record_count,
        "quality_score": report.quality_score,
        "issues": report.issues,
    }


@router.get("/debug/segy_headers")
def debug_segy_headers(path: str, n_traces: int = 5, _user=Depends(get_current_user)):
    """
    Diagnostic: dumps common trace header field values for the first
    n_traces of a SEG-Y file already on disk (e.g. one extracted by a
    prior /ingest_zip_from_url call). Different GPR export software
    doesn't always populate the standard SourceX/SourceY fields the way
    seismic SEG-Y does -- this shows which fields, if any, actually carry
    plausible non-zero position data for a given source, instead of
    guessing at a fix blind.
    """
    try:
        import segyio
    except ImportError:
        raise HTTPException(status_code=501, detail="segyio is required. Install with: pip install segyio")

    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = settings.data_root / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    candidate_fields = [
        "SourceX", "SourceY", "GroupX", "GroupY", "CDP_X", "CDP_Y",
        "ReceiverGroupElevation", "SourceSurfaceElevation",
        "ElevationScalar", "SourceGroupScalar",
        "INLINE_3D", "CROSSLINE_3D", "offset", "FieldRecord", "TRACE_SEQUENCE_LINE",
        "TRACE_SEQUENCE_FILE", "CDP", "EnergySourcePoint",
    ]

    results = []
    try:
        with segyio.open(str(file_path), "r", ignore_geometry=True) as f:
            f.mmap()
            n = min(n_traces, f.tracecount)
            for i in range(n):
                header = f.header[i]
                row = {}
                for fname in candidate_fields:
                    try:
                        field = getattr(segyio.TraceField, fname)
                        row[fname] = header.get(field, None)
                    except AttributeError:
                        row[fname] = "N/A (not a valid segyio field)"
                results.append(row)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not open as SEG-Y: {e}")

    return {
        "file": str(file_path),
        "trace_count_sampled": len(results),
        "header_samples": results,
        "note": "Look for a field with plausible non-zero, non-constant values across traces -- that's likely the real position field for this file's export software.",
    }


@router.get("/{dataset_id}/points")
def get_dataset_points(dataset_id: str, max_points: int = 20000, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    """
    Returns a (optionally downsampled) list of renderable points for this
    dataset — lat/lon/elevation/depth/signal/sensor_type/ground_truth —
    for the 3D viewer or any other client-side visualization.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    records = load_records(dataset_id)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    total = len(records)
    if total > max_points:
        rng = random.Random(42)
        records = rng.sample(records, max_points)

    points = [
        {
            "lat": r.latitude,
            "lon": r.longitude,
            "elevation": r.elevation,
            "absolute_elevation_m": (r.metadata or {}).get("absolute_elevation_m"),
            "depth": r.depth,
            "signal": r.signal[0] if r.signal else None,
            "sensor_type": r.sensor_type.value,
            "ground_truth": r.ground_truth.value,
            "trace_index": (r.metadata or {}).get("trace_index"),
            "anomaly_reliable": (r.metadata or {}).get("anomaly_reliable"),
            # What kind of position this point actually has, and where it came
            # from. "lat"/"lon" above are the legacy view and may be the (0,0)
            # placeholder; these say whether that is a real position.
            "position_kind": r.position.kind,
            "position_source": (r.metadata or {}).get("position_source"),
            # Distance along the survey line, for acquisitions positioned by a
            # wheel encoder rather than by GNSS. This is the ONLY coordinate an
            # odometry dataset has, so without it such a line cannot be plotted
            # at all. None for every other position kind.
            "along_track_m": getattr(r.position, "along_track_m", None),
        }
        for r in records
    ]

    position_kinds: dict[str, int] = {}
    for pnt in points:
        position_kinds[pnt["position_kind"]] = position_kinds.get(pnt["position_kind"], 0) + 1
    along = [p["along_track_m"] for p in points if p["along_track_m"] is not None]
    along_track_extent_m = (max(along) - min(along)) if along else None

    return {
        "dataset_id": dataset_id,
        "name": dataset.name,
        "sensor_type": dataset.sensor_type,
        "total_records": total,
        "returned_points": len(points),
        "position_kinds": position_kinds,
        "along_track_extent_m": along_track_extent_m,
        "points": points,
    }


@router.get("/{dataset_id}/depths")
def get_dataset_depths(dataset_id: str, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    """Lists distinct depth values present in this dataset with record counts -- for building a depth-slice-stacking control."""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    records = load_records(dataset_id)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    from preprocessing.spatial_grid import list_available_depths
    return {"dataset_id": dataset_id, "depths": list_available_depths(records)}


@router.get("/{dataset_id}/grid")
def get_dataset_grid(
    dataset_id: str,
    depth: Optional[float] = None,
    field: str = "signal",
    smooth: bool = True,
    smoothing_window: int = 3,
    db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access),
):
    """
    Returns a single depth layer as a 2D grid for heatmap/surface rendering
    -- read-only, does not modify stored records. field="signal" (default),
    "elevation", or "absolute_elevation_m" (for building a matching surface
    to drape the signal grid over). depth=None uses whichever layer has the
    most records. smooth=true applies light display-only smoothing (does
    not persist).
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    records = load_records(dataset_id)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    from preprocessing.spatial_grid import build_grid_for_records, _smooth_2d_nanaware
    try:
        grid, lat_centers, lon_centers, used_depth = build_grid_for_records(records, depth=depth, field=field)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if smooth:
        grid = _smooth_2d_nanaware(grid, window=smoothing_window)

    # NaN isn't valid JSON -- convert to null explicitly rather than relying
    # on a lenient encoder.
    grid_json = [[(None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)) for v in row] for row in grid.tolist()]

    return {
        "dataset_id": dataset_id,
        "name": dataset.name,
        "field": field,
        "depth": used_depth,
        "n_lat": len(lat_centers),
        "n_lon": len(lon_centers),
        "lat_centers": lat_centers.tolist(),
        "lon_centers": lon_centers.tolist(),
        "grid": grid_json,
    }


def _along_track_extent(values) -> Optional[float]:
    """Length of the survey line in metres, or None when it is not positioned."""
    known = [v for v in (values or []) if v is not None]
    return (max(known) - min(known)) if known else None


@router.get("/{dataset_id}/trace_grid")
def get_dataset_trace_grid(
    dataset_id: str,
    source_file: Optional[str] = None,
    field: str = "signal",
    include_reliability: bool = False,
    include_candidates: bool = False,
    db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access),
):
    """
    Returns one survey line's data as a dense (depth x trace) 2D grid --
    the radargram/B-scan view -- for genuine multi-sample GPR trace data
    (SEG-Y sourced, one record per sample). Unlike /grid (lat/lon-binned,
    meant for area-covering depth-slice surveys), this indexes by each
    trace's native position along the survey line, so a single-line
    survey renders as a dense image instead of a mostly-empty lat/lon
    raster. Also returns each trace's (lat, lon) so a caller can
    georeference any column. field="signal" (default), "pre_anomaly_signal",
    "elevation", or "absolute_elevation_m". source_file selects which line when
    a dataset holds several -- omit it to get the densest line PLUS the full
    "available_source_files" list, so a caller (e.g. the viewer) can offer
    an explicit choice instead of silently only ever showing one line.

    THE TWO DISPLAY PROJECTIONS. `signal` is what the record holds now, which
    after trace-local anomaly preprocessing is the z-score; `pre_anomaly_signal`
    is the value that same cell held immediately before. They are projections of
    the SAME records onto the SAME grid -- identical trace indices, depths,
    axis semantics, reliability mask and candidate footprints -- so switching
    between them cannot move a candidate or change an axis. Only the number in
    each cell differs.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Refused rather than defaulted: falling back from a requested signal to the
    # z-score would show a statistic under a signal's label.
    from schemas.radargram import DISPLAYABLE_FIELDS

    if field not in DISPLAYABLE_FIELDS and field not in ("elevation", "absolute_elevation_m"):
        raise HTTPException(
            status_code=422,
            detail=(f"unknown field {field!r}; this endpoint projects "
                    f"{', '.join(DISPLAYABLE_FIELDS)}, elevation or absolute_elevation_m"))

    records = load_records(dataset_id)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    # Composition gate, same definition the report, signal-chain route and
    # candidates API already share (`frame_modalities` / `identity.recorded_
    # modalities`): a non-empty composition without gpr is not "not genuine
    # multi-sample GPR trace data" -- that reason describes a GPR line that
    # failed a shape check, not a dataset that was never GPR. An empty
    # composition (nothing recorded, or no frames at all) falls through to
    # today's grid builder unchanged, same as every other slice-5 gate.
    all_frames = load_frames(dataset_id) or synthesize_frames_from_records(records)
    from schemas.dataset_report import frame_modalities

    composition = frame_modalities(all_frames)
    if composition and "gpr" not in composition:
        raise HTTPException(
            status_code=400,
            detail=(f"this dataset's recorded modality composition is "
                    f"{', '.join(composition)}; a radargram / trace-depth grid is a "
                    f"GPR-trace view and does not apply to it"),
        )

    from preprocessing.spatial_grid import build_trace_depth_grid_for_records
    try:
        result = build_trace_depth_grid_for_records(records, source_file=source_file, field=field)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    grid_json = [[(None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)) for v in row] for row in result["grid"].tolist()]

    # Surface the depth-axis velocity assumption (SEGYConverter's
    # depth = two_way_time_ns * velocity_m_per_ns / 2) rather than leaving
    # it implicit -- it's a default, not a site calibration (see
    # converters/segy_converter.py::DEFAULT_GPR_VELOCITY_M_PER_NS).
    velocity_values = {
        r.metadata["velocity_m_per_ns"] for r in records
        if r.metadata.get("source_file") == result["source_file"] and "velocity_m_per_ns" in r.metadata
    }
    velocity_assumption = sorted(velocity_values)[0] if len(velocity_values) == 1 else (sorted(velocity_values) or None)

    # This line's own acquisition frame: CRS, vertical axis and the
    # assumptions behind them. Reconstructed for datasets ingested before
    # frames existed rather than reported as absent. `all_frames` was already
    # computed above for the composition gate.
    match = next((f for f in all_frames if f.source_file == result["source_file"]), None)
    line_frame = None
    if match is not None:
        line_frame = {
            "frame_id": match.frame_id,
            "source_format": match.source_format,
            "modality": match.modality.value,
            "spatial_ref": match.spatial_ref.model_dump(mode="json"),
            "vertical_axis": match.vertical_axis.model_dump(mode="json"),
            "assumptions": [a.model_dump(mode="json") for a in match.assumptions],
        }

    # WHAT THE NUMBERS ARE AND WHAT THE AXES MEAN. Added for the radargram
    # viewer, which otherwise has to guess -- and would guess wrong: on a
    # dataset that has been through trace-local anomaly preprocessing,
    # `signal` holds the z-score, not the amplitude it was computed from.
    # `include_reliability` is opt-in because the mask roughly doubles the
    # payload and no existing caller needs it.
    from api import radargram as radargram_service

    reliability = (
        radargram_service.reliability_grid(
            records, result["source_file"], result["trace_indices"], result["depths"])
        if include_reliability else None
    )
    radargram_semantics = radargram_service.semantics(
        records=records, survey_frame=line_frame, field=field,
        velocity_m_per_ns=velocity_assumption if isinstance(velocity_assumption, float) else None,
        declared=radargram_service.velocity_is_declared(db, dataset_id),
        trace_geographic=result.get("trace_geographic"),
        trace_along_track=result.get("trace_along_track"),
        reliability=reliability,
        n_cells=len(result["depths"]) * len(result["trace_indices"]),
    )

    # WHERE THE CANDIDATES SIT ON THIS GRID. The join is done here because only
    # here are both sides present, and doing it in the browser would put a
    # second copy of the mapping rule in TypeScript where it could drift from
    # the tested one. Footprints are grid coordinates only -- the candidates
    # themselves stay on /api/candidates, which remains their single
    # representation.
    candidate_footprints = None
    if include_candidates:
        from database.candidates_store import load_candidates
        from schemas.radargram import map_candidates

        stored = load_candidates(dataset_id)
        line = [
            c.candidate.model_dump(mode="json") for c in (stored.candidates if stored else [])
            if c.candidate.evidence.source_file == result["source_file"]
        ]
        candidate_footprints = [
            f.model_dump(mode="json") for f in
            map_candidates(line, result["trace_indices"], result["depths"])
        ]

    return {
        "dataset_id": dataset_id,
        "name": dataset.name,
        "field": field,
        "semantics": radargram_semantics.model_dump(mode="json"),
        "reliability": reliability,
        "candidate_footprints": candidate_footprints,
        "source_file": result["source_file"],
        "available_source_files": result["available_source_files"],
        "n_depths": len(result["depths"]),
        "n_traces": len(result["trace_indices"]),
        "depths": result["depths"],
        "trace_indices": result["trace_indices"],
        "trace_lat": result["trace_lat"],
        "trace_lon": result["trace_lon"],
        # Whether each trace's (lat, lon) is a real geographic position or the
        # legacy placeholder -- a caller georeferencing a column needs to know
        # before treating those numbers as a location.
        "trace_position_kind": result.get("trace_position_kind"),
        "trace_geographic": result.get("trace_geographic"),
        # Distance of each trace along its own survey line. For an odometry
        # acquisition this is the real horizontal axis of the radargram: the
        # grid's columns are evenly spaced in trace index, not in metres, so a
        # caller plotting distance needs these values rather than the indices.
        "trace_along_track": result.get("trace_along_track"),
        "along_track_extent_m": _along_track_extent(result.get("trace_along_track")),
        "survey_frame": line_frame,
        "grid": grid_json,
        "velocity_m_per_ns": velocity_assumption,
        "velocity_note": (
            "Depth axis derived from two-way travel time using this assumed constant EM velocity "
            "(m/ns) -- a default, NOT calibrated for this specific site's soil conditions. Real "
            "depth could differ substantially if true velocity differs."
        ) if velocity_assumption is not None else None,
    }


@router.get("/{dataset_id}/info")
def get_dataset_info(dataset_id: str, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    """
    Richer dataset summary for the UI's dataset card: survey area, grid
    resolution, and active processing steps -- all computed from real
    stored data. Deliberately does NOT include fields like "ground
    conditions" or "estimated penetration depth" that would require domain
    assumptions we have no basis for; only what's actually derivable.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    records = load_records(dataset_id)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

    from preprocessing.spatial_grid import _compute_grid_dims, list_available_depths

    # Survey extent and grid resolution are lat/lon-derived, so they exist
    # only for records that HAVE a geographic position. A dataset with none
    # reports null rather than a fabricated zero-sized survey.
    positioned = [r for r in records if has_geographic_coordinates(r)]
    lat_span_m = lon_span_m = resolution_m = None
    if positioned:
        lats = [r.latitude for r in positioned]
        lons = [r.longitude for r in positioned]
        lat_span_m = (max(lats) - min(lats)) * 110540
        # longitude-to-meters depends on latitude; use the dataset's mean latitude
        mean_lat = sum(lats) / len(lats)
        lon_span_m = (max(lons) - min(lons)) * 111320 * math.cos(math.radians(mean_lat))
        n_lat, n_lon = _compute_grid_dims(np.array(lats), np.array(lons), len(positioned))
        if n_lat > 1 and n_lon > 1:
            resolution_m = round(min(lat_span_m / n_lat, lon_span_m / n_lon), 3)

    # Processing steps actually applied, if any -- pulled from record metadata
    # rather than assumed.
    sample_with_processing = next((r for r in records if "processing_applied" in r.metadata), None)
    processing_applied = sample_with_processing.metadata.get("processing_applied") if sample_with_processing else None

    # Acquisition provenance, read from the dataset's SurveyFrames. Datasets
    # ingested before frames existed have none stored, so reconstruct from
    # the records rather than reporting nothing.
    frames = load_frames(dataset_id) or synthesize_frames_from_records(records)
    frame_summaries = [
        {
            "frame_id": f.frame_id,
            "source_file": f.source_file,
            "source_format": f.source_format,
            "modality": f.modality.value,
            "modality_source": f.modality_source,
            "n_positions": f.n_positions,
            "position_index_name": f.position_index_name,
            "spatial_ref": f.spatial_ref.model_dump(mode="json"),
            "vertical_axis": f.vertical_axis.model_dump(mode="json"),
            "assumptions": [a.model_dump(mode="json") for a in f.assumptions],
        }
        for f in frames
    ]
    # Where each record's position actually came from, counted rather than
    # assumed. Replaces the previous hardcoded CRS claim below.
    position_sources: dict[str, int] = {}
    for r in records:
        key = r.metadata.get("position_source") or r.position.kind
        position_sources[str(key)] = position_sources.get(str(key), 0) + 1
    declared_refs = sorted({
        (f.spatial_ref.code or f.spatial_ref.kind.value) for f in frames
    })

    return {
        "dataset_id": dataset_id,
        "name": dataset.name,
        "sensor_type": dataset.sensor_type,
        "original_format": dataset.original_format,
        "source": dataset.source,
        "license": dataset.license,
        "record_count": dataset.record_count,
        "quality_score": dataset.quality_score,
        "has_ground_truth": dataset.has_ground_truth,
        # Reported from the dataset's own frames. This previously asserted a
        # hardcoded "EPSG:4326 (WGS84 lat/lon)" that was never checked
        # against the data.
        "coordinate_system": declared_refs[0] if len(declared_refs) == 1 else declared_refs,
        "position_sources": position_sources,
        "survey_frames": frame_summaries,
        "survey_area_m": ({"lat_span": round(lat_span_m, 1), "lon_span": round(lon_span_m, 1)}
                          if lat_span_m is not None else None),
        "geographic_record_count": len(positioned),
        "grid_resolution_m": resolution_m,
        "depth_layers": list_available_depths(records),
        "processing_applied": processing_applied,
        "dem_aligned": bool(dataset.extra_metadata and dataset.extra_metadata.get("dem_aligned")),
        "last_preprocessing_mode": dataset.extra_metadata.get("last_preprocessing_mode") if dataset.extra_metadata else None,
    }


@router.get("/{dataset_id}/acquisition")
def get_dataset_acquisition(dataset_id: str, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    """
    Where this dataset came from: the acquisition that produced it, and -- when
    a device session was involved -- the session and the device behind it.

    THE WHOLE CHAIN, ADDRESSABLE: device -> session -> acquisition -> dataset.
    A dataset that arrived through FileDrop reports the session and device as
    absent rather than having them invented.

    THE BOTTOM OF THE EVIDENCE CHAIN, made addressable. A dataset report says
    what Subterra understands; this says what arrived and when, with the
    checksum of the bytes as received. Together they answer "where did this come
    from" without anybody having to correlate a filename by hand.

    Datasets ingested before FileDrop -- including every published reference
    corpus -- have no acquisition record, and that is reported as an absence
    rather than reconstructed from a raw path. A plausible-looking origin is
    exactly the kind of provenance that must not be manufactured.
    """
    from database.models import ImportJob

    job = (
        db.query(ImportJob)
        .filter(ImportJob.dataset_id == dataset_id)
        .order_by(ImportJob.created_at.asc())
        .first()
    )
    if job is None:
        return {
            "dataset_id": dataset_id,
            "acquisition": None,
            "session": None,
            "device": None,
            "reason": ("this dataset predates the acquisition boundary, so how its "
                       "source file arrived was never recorded"),
        }

    # The rest of the chain, when a device session produced this. A FileDrop
    # acquisition reports both as absent rather than inventing a device: a file
    # is a source in its own right, not a session with a missing instrument.
    from database.models import AcquisitionSession, Device

    session = device = None
    if job.session_id:
        session = db.query(AcquisitionSession).filter(
            AcquisitionSession.id == job.session_id).first()
        if session is not None:
            device = db.query(Device).filter(Device.id == session.device_id).first()

    return {
        "dataset_id": dataset_id,
        "acquisition": job.to_dict(),
        "session": session.to_dict() if session is not None else None,
        "device": device.to_dict() if device is not None else None,
    }


@router.get("/{dataset_id}/signal-chain")
def get_dataset_signal_chain(dataset_id: str, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    """
    The recorded Phase 5 signal-processing chain, read straight from stored
    evidence on this dataset's records and frames -- never re-run.

    A THIN ROUTE, DELIBERATELY SEPARATE FROM `/report`. The full report is
    known to take tens of seconds to build on a dataset of any size (quality
    scoring and candidate staleness walk every record); the workspace shows
    this chain on every dataset open, the same way it shows acquisition and
    spatial readiness, so it cannot wait on that. This route does only what
    the chain needs: load the records and frames, read the same handful of
    fields (including the recorded modality composition, so a non-GPR
    dataset gets the right absence rather than "not recorded"), hand them
    to the same `build_signal_chain` the full report also calls, so the two
    can never disagree about what ran.
    """
    if not db.query(Dataset).filter(Dataset.id == dataset_id).first():
        raise HTTPException(status_code=404, detail="Dataset not found")

    from api.reports import _local_anomaly_stamp, _processing_applied
    from database.frames_store import load_frames, synthesize_frames_from_records
    from database.records_store import load_records
    from schemas.dataset_report import build_signal_chain, frame_modalities

    records = load_records(dataset_id)
    frames = load_frames(dataset_id) or (
        synthesize_frames_from_records(records) if records else [])
    return build_signal_chain(
        _processing_applied(records), frames, _local_anomaly_stamp(records),
        frame_modalities(frames),
    ).model_dump(mode="json")


@router.get("/{dataset_id}/report")
def get_dataset_report(dataset_id: str, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    """
    The Dataset Report: what this dataset is, what happened to it, how far it
    can be trusted, and what Subterra may legitimately do with it next.

    ONE CALL, ONE DOMAIN VALUE. The report deliberately does not leave the
    client to assemble this from `/info`, `/provenance/{id}/frames`,
    `/labels/{id}` and a view resolution -- four calls whose answers could
    disagree, and whose combination would put the readiness judgement in the
    browser where it cannot be tested or reused. Stage 8's spatial workflow
    and stage 17's reconstruction need the same assessment, and will call
    `api.reports.build_dataset_report` rather than this route.

    UNLIKE `/info`, A DATASET WITH NO RECORDS IS NOT A 404. "This dataset
    produced nothing" is one of the most important things a report can say,
    and answering 404 would make an empty dataset indistinguishable from a
    missing one.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    from api.reports import build_dataset_report

    return build_dataset_report(dataset).model_dump(mode="json")


@router.get("/")
def list_datasets(
    sensor_type: Optional[str] = None,
    min_quality: Optional[float] = None,
    has_ground_truth: Optional[bool] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Search datasets by sensor, quality score, and ground-truth availability.

    SCOPED IN THE QUERY, not after it. Loading every row and dropping some in
    Python is one forgotten filter away from leaking them, and the filter is
    trivially expressible in SQL: the caller's own datasets, plus the
    system/public reference corpora that belong to nobody.
    """
    query = visible_datasets(db, user)
    if sensor_type:
        query = query.filter(Dataset.sensor_type == sensor_type)
    if min_quality is not None:
        query = query.filter(Dataset.quality_score >= min_quality)
    if has_ground_truth is not None:
        query = query.filter(Dataset.has_ground_truth == has_ground_truth)
    results = query.all()

    # Status needs the originating import job, and duplicate awareness needs
    # every checksum in the result. Both are computed ONCE for the whole list:
    # a per-row query here is how a dataset list becomes slow enough to need
    # pagination for the wrong reason.
    #
    # Readiness is deliberately NOT included. Assessing it means loading a
    # dataset's records -- 157,040 for one of these -- and doing that per row
    # would make listing cost more than opening. The list says what a dataset
    # IS and links to the report, which says what can be done with it.
    jobs = lifecycle.latest_jobs_by_dataset(db, [d.id for d in results])
    duplicates = lifecycle.duplicate_groups(results)
    checksum_of_group = {
        dataset_id: checksum
        for checksum, ids in duplicates.items() for dataset_id in ids
    }

    out = []
    for d in results:
        row = _dataset_to_dict(d)
        status = lifecycle.status_for(d, jobs.get(d.id))
        row["status"] = status.value
        row["status_reason"] = status.reason
        row["job_state"] = status.job_state
        row["job_id"] = status.job_id
        checksum = checksum_of_group.get(d.id)
        row["shares_source_with"] = (
            [i for i in duplicates[checksum] if i != d.id] if checksum else []
        )
        out.append(row)
    return out


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, db: Session = Depends(get_db),
    _dataset=Depends(require_dataset_access)):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return _dataset_to_dict(dataset)


class RenameDatasetRequest(BaseModel):
    name: str = Field(..., max_length=lifecycle.MAX_NAME_LENGTH + 1)


@router.patch("/{dataset_id}")
def rename_dataset(dataset_id: str, body: RenameDatasetRequest,
    db: Session = Depends(get_db), dataset=Depends(require_owned_dataset)):
    """
    Change a dataset's human-facing name. Nothing else moves.

    THE ID IS NOT THE NAME. Every record, frame, label and artifact is keyed on
    the immutable dataset id, so a rename touches exactly one column. The raw
    source path, the checksum, the frames' `source_file` and every provenance
    entry are untouched -- which is what keeps "what the user calls it" and
    "what the file was" two separate facts. A test asserts the report's
    provenance is byte-identical across a rename.

    Names are not unique. Two datasets in this corpus are already both called
    "INGV-UNISA Site 1 GPR v3", and they are genuinely different ingestion
    events; enforcing uniqueness would either reject that or mangle it.
    """
    try:
        name = lifecycle.clean_dataset_name(body.name)
    except lifecycle.InvalidDatasetName as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    dataset.name = name
    dataset.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(dataset)
    logger.info("renamed dataset %s", dataset_id)
    return _dataset_to_dict(dataset)


@router.post("/{dataset_id}/rescore")
def rescore_dataset(dataset_id: str, db: Session = Depends(get_db),
    dataset=Depends(require_owned_dataset)):
    """
    Recompute the stored quality score from the records as they are now.

    THIS IS NOT `reprocess`, AND THE DIFFERENCE MATTERS. `POST /reprocess` runs
    the preprocessing pipeline and SAVES THE RESULT BACK -- dewow, gain,
    normalisation; it changes the science. Using it to correct a stale score
    would silently alter the measurements to fix a number about them.

    This endpoint reads the records, runs the existing validator, and writes one
    derived scalar plus its issue list. It is deterministic, it touches no
    record, frame, label or raw file, and running it twice changes nothing the
    first run did not. That is what makes it safe to offer as a button.

    It exists because the report can already detect that a stored score no
    longer matches the data (`score_is_stale`) -- two of the six datasets held
    were scored before `NoPosition` replaced the `(0, 0)` placeholder, and were
    being penalised for coordinates their format never had.
    """
    records = load_records(dataset_id)
    if not records:
        raise HTTPException(
            status_code=400,
            detail="this dataset has no stored records, so there is nothing to score")

    before = dataset.quality_score
    report = validate_dataset(records, dataset_id=dataset_id)
    dataset.quality_score = report.quality_score
    dataset.extra_metadata = {
        **(dataset.extra_metadata or {}),
        "validation_issues": report.issues,
    }
    dataset.updated_at = datetime.utcnow()
    db.commit()

    return {
        "dataset_id": dataset_id,
        "previous_quality_score": before,
        "quality_score": report.quality_score,
        "record_count": len(records),
        "issues": report.issues,
        "note": ("only the derived score was recomputed; no record, frame, label "
                 "or source file was modified"),
    }


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, db: Session = Depends(get_db),
    dataset=Depends(require_owned_dataset)):
    """
    Delete a dataset and the data derived from it.

    The policy is in `api/dataset_lifecycle.py` and comes down to one line:
    DERIVED DATA IS REMOVED, SOURCE DATA AND EVENT LOGS ARE RETAINED. The raw
    file survives because it is the bottom of the evidence chain, cannot be
    regenerated, and is demonstrably shared between datasets in this corpus. The
    import job survives because an import happened and deleting the record would
    make the history lie by omission.

    A dataset with an import in flight is REFUSED rather than deleted: removing
    the artifacts a running job is writing would race it, and the job would
    finish by recreating some of them.

    The response enumerates what went and what stayed. "deleted: true" is not an
    adequate answer for an irreversible operation over scientific data.
    """
    active = lifecycle.active_job_for(db, dataset_id)
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=(f"an import for this dataset is {active.state.lower()}; "
                    "wait for it to finish before deleting"))

    plan = lifecycle.delete_dataset_completely(db, dataset)
    return {
        "deleted": dataset_id,
        "removed": {
            "artifacts": plan.artifacts,
            "fusion_samples": len(plan.fusion_sample_ids),
            "spatial_declarations": len(plan.spatial_declaration_ids),
            "versions": plan.version_count,
        },
        "retained": {
            "raw_source": plan.retained_raw_path,
            "import_jobs": len(plan.retained_job_ids),
            "why": ("the raw source is the original measurement, cannot be regenerated, "
                    "and may be shared with other datasets; the import job records an "
                    "event that happened"),
        },
    }


def _dataset_to_dict(d: Dataset) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "source": d.source,
        "sensor_type": d.sensor_type,
        "original_format": d.original_format,
        "quality_score": d.quality_score,
        "record_count": d.record_count,
        "has_ground_truth": d.has_ground_truth,
        "center_lat": d.center_lat,
        "center_lon": d.center_lon,
        "version": d.version,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        # Added for dataset management. `source_file` is the ORIGINAL file this
        # came from and is kept distinct from `name`, which the user may change:
        # renaming a dataset must not rewrite what the file was.
        "source_file": Path(d.raw_path).name if d.raw_path else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "checksum": d.checksum,
        # NULL owner means the published reference corpora, which are readable
        # by everyone and writable by nobody. The UI needs this to know that
        # rename and delete will be refused.
        "is_system_dataset": d.owner_id is None,
    }

