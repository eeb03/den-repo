import math
import random
import shutil
from pathlib import Path
from typing import Optional

import numpy as np

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.session import get_db
from database.models import Dataset, gen_uuid
from schemas.subterra_record import SensorType
from converters.registry import get_converter
from converters.base import MissingDependencyError
from validators.dataset_validator import validate_dataset
from preprocessing.pipeline import run_pipeline
from database.records_store import save_records, load_records
from database.frames_store import save_frames, synthesize_frames_from_records
from schemas.spatial import Assumption
from ingestion.downloader import download_file, DownloadError
from converters.registry import supported_extensions
from preprocessing.dem_alignment import align_records_with_dem
from configs.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _run_ingest_pipeline(
    raw_path: Path,
    sensor_type: SensorType,
    name: str,
    db: Session,
    source: Optional[str] = None,
    license: Optional[str] = None,
    source_url: Optional[str] = None,
    apply_preprocessing: bool = True,
    preprocessing_mode: str = "trace",
    converter_kwargs: Optional[dict] = None,
) -> dict:
    """
    The core pipeline shared by every ingest entrypoint (direct upload,
    URL download, source-connector download, local file): convert ->
    validate -> (preprocess) -> persist records -> register metadata.

    preprocessing_mode="trace" (default) treats each record's signal as a
    multi-sample waveform. Use "spatial_grid" for single-value-per-point
    raster data (GPR depth slices, magnetometer/gravity surveys) so
    smoothing/normalization happens across real spatial neighbors instead
    of being a no-op on a length-1 array.

    converter_kwargs passes format-specific options through to the
    converter (e.g. {"stride": 1} for GeoTIFFConverter on a small DEM tile
    where the default stride=10 would sample almost nothing).
    """
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

    report = validate_dataset(records, dataset_id=dataset_id, source_file=raw_path)

    if apply_preprocessing:
        records = run_pipeline(records, mode=preprocessing_mode)

    save_records(dataset_id, records)
    # Converters not yet migrated to load() return no frames; reconstruct one
    # from the records so every dataset has frame coverage from ingest onward.
    save_frames(dataset_id, frames or synthesize_frames_from_records(records))

    center_lat = sum(r.latitude for r in records) / len(records) if records else None
    center_lon = sum(r.longitude for r in records) / len(records) if records else None
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
        extra_metadata={"validation_issues": report.issues},
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
    }


@router.post("/ingest")
async def ingest_dataset(
    file: UploadFile = File(...),
    sensor_type: SensorType = Form(...),
    name: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    license: Optional[str] = Form(None),
    apply_preprocessing: bool = Form(True),
    preprocessing_mode: str = Form("trace", description="'trace' for multi-sample waveforms, 'spatial_grid' for single-value raster/depth-slice data (GPR, magnetometer, gravity)"),
    db: Session = Depends(get_db),
):
    """
    Full ingest pipeline from a direct file upload: save -> convert ->
    validate -> (preprocess) -> register. This is the PRD's "Data
    Conversion Engine" + "Dataset Validator" + "Metadata Database" wired
    together.
    """
    raw_path = settings.raw_dir / file.filename
    with open(raw_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return _run_ingest_pipeline(
        raw_path, sensor_type, name or file.filename, db,
        source=source, license=license, apply_preprocessing=apply_preprocessing,
        preprocessing_mode=preprocessing_mode,
    )


class IngestFromURLRequest(BaseModel):
    url: str
    sensor_type: SensorType
    name: Optional[str] = None
    source: Optional[str] = None
    license: Optional[str] = None
    expected_sha256: Optional[str] = None
    apply_preprocessing: bool = True
    preprocessing_mode: str = "trace"


@router.post("/ingest_from_url")
def ingest_from_url(req: IngestFromURLRequest, db: Session = Depends(get_db)):
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

    records = load_records(dataset_id)
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


@router.post("/{dataset_id}/align_dem")
def align_dataset_with_dem(dataset_id: str, dem_filename: str, db: Session = Depends(get_db)):
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

    records = load_records(dataset_id)
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
    preprocessing_mode: str = "trace"
    geotiff_stride: Optional[int] = None


@router.post("/ingest_local_file")
def ingest_local_file(req: IngestLocalFileRequest, db: Session = Depends(get_db)):
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

    existing_records = load_records(dataset_id)
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
def ingest_depth_slice(dataset_id: str, req: IngestDepthSliceLocalRequest, db: Session = Depends(get_db)):
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
def ingest_depth_slice_from_url(dataset_id: str, req: IngestDepthSliceURLRequest, db: Session = Depends(get_db)):
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
    preprocessing_mode: str = "trace"
    max_files: int = 20  # safety cap -- large archives can contain hundreds of files


@router.post("/ingest_zip_from_url")
def ingest_zip_from_url(req: IngestZipFromURLRequest, db: Session = Depends(get_db)):
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
    from ingestion.downloader import scan_archive

    filename = req.name or req.url.split("/")[-1].split("?")[0] or "download.zip"
    try:
        downloaded_path = download_file(req.url, dest_filename=filename, expected_sha256=req.expected_sha256)
    except DownloadError as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        scan = scan_archive(downloaded_path)
        supported_files = scan.supported
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

    from ingestion.kmz_georeference import find_matching_kmz_files, build_georeference_lookup, georeference_records_by_trace
    kmz_files = find_matching_kmz_files(supported_files[0].parent.parent if supported_files else downloaded_path.parent)
    # search from the extraction root, not just alongside the data files -- KMZ often sits in the same
    # subdirectory as its SEG-Y files, but walk up to be safe about sibling directory layouts
    if not kmz_files:
        kmz_files = find_matching_kmz_files(downloaded_path.parent)
    kmz_lookup = build_georeference_lookup(kmz_files) if kmz_files else {}
    if kmz_lookup:
        logger.info(f"ingest_zip_from_url: found {len(kmz_files)} KMZ file(s) with {len(kmz_lookup)} named path(s) for georeferencing")

    for file_path in supported_files:
        try:
            converter = get_converter(file_path)
            result = converter.load(file_path, dataset_id=dataset_id, sensor_type=req.sensor_type)
            records = result.records
            file_frames = result.frames or synthesize_frames_from_records(records)

            # If this file's SEG-Y header coordinates are unusable, map
            # positions from a matching KMZ placemark instead -- this
            # source's SourceX/SourceY are projected (UTM-scale) values,
            # not real per-trace GPS.
            #
            # This updates latitude/longitude ONLY. `record.position`
            # continues to hold what the FILE said, and the frame's
            # spatial_ref describes that. Neither source overwrites the
            # other, because which one is authoritative is genuinely not
            # yet known -- see the recorded assumption below.
            stem = file_path.stem
            if stem in kmz_lookup and len(records) > 0:
                georeference_records_by_trace(records, kmz_lookup[stem])
                georeferenced_count += 1
                for fr in file_frames:
                    fr.assumptions.append(Assumption(
                        key="position_source_discrepancy",
                        value="latitude/longitude from KMZ track; record.position from the file's own header",
                        basis=(
                            "UNRESOLVED: the two position sources have not been cross-validated. "
                            "ingestion/kmz_georeference.py documents SEG-Y SourceX/SourceY as one "
                            "static placeholder per file, but they were measured to vary per trace "
                            "(67 distinct positions across 72 traces on C1T_7,5_0001.SGY). Until "
                            "header-derived positions are compared against the KMZ polyline for the "
                            "same line, neither is treated as authoritative and neither overwrites "
                            "the other. That comparison would also independently test the KMZ "
                            "direction assumption, which is itself unverified."
                        ),
                        verified=False,
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

    center_lat = sum(r.latitude for r in all_records) / len(all_records) if all_records else None
    center_lon = sum(r.longitude for r in all_records) / len(all_records) if all_records else None
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
def debug_segy_headers(path: str, n_traces: int = 5):
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
def get_dataset_points(dataset_id: str, max_points: int = 20000, db: Session = Depends(get_db)):
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
        }
        for r in records
    ]

    return {
        "dataset_id": dataset_id,
        "name": dataset.name,
        "sensor_type": dataset.sensor_type,
        "total_records": total,
        "returned_points": len(points),
        "points": points,
    }


@router.get("/{dataset_id}/depths")
def get_dataset_depths(dataset_id: str, db: Session = Depends(get_db)):
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


@router.get("/{dataset_id}/trace_grid")
def get_dataset_trace_grid(
    dataset_id: str,
    source_file: Optional[str] = None,
    field: str = "signal",
    db: Session = Depends(get_db),
):
    """
    Returns one survey line's data as a dense (depth x trace) 2D grid --
    the radargram/B-scan view -- for genuine multi-sample GPR trace data
    (SEG-Y sourced, one record per sample). Unlike /grid (lat/lon-binned,
    meant for area-covering depth-slice surveys), this indexes by each
    trace's native position along the survey line, so a single-line
    survey renders as a dense image instead of a mostly-empty lat/lon
    raster. Also returns each trace's (lat, lon) so a caller can
    georeference any column. field="signal" (default), "elevation", or
    "absolute_elevation_m". source_file selects which line when a dataset
    holds several -- omit it to get the densest line PLUS the full
    "available_source_files" list, so a caller (e.g. the viewer) can offer
    an explicit choice instead of silently only ever showing one line.
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    records = load_records(dataset_id)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")

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

    return {
        "dataset_id": dataset_id,
        "name": dataset.name,
        "field": field,
        "source_file": result["source_file"],
        "available_source_files": result["available_source_files"],
        "n_depths": len(result["depths"]),
        "n_traces": len(result["trace_indices"]),
        "depths": result["depths"],
        "trace_indices": result["trace_indices"],
        "trace_lat": result["trace_lat"],
        "trace_lon": result["trace_lon"],
        "grid": grid_json,
        "velocity_m_per_ns": velocity_assumption,
        "velocity_note": (
            "Depth axis derived from two-way travel time using this assumed constant EM velocity "
            "(m/ns) -- a default, NOT calibrated for this specific site's soil conditions. Real "
            "depth could differ substantially if true velocity differs."
        ) if velocity_assumption is not None else None,
    }


@router.get("/{dataset_id}/info")
def get_dataset_info(dataset_id: str, db: Session = Depends(get_db)):
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

    lats = [r.latitude for r in records]
    lons = [r.longitude for r in records]
    lat_span_m = (max(lats) - min(lats)) * 110540
    # longitude-to-meters depends on latitude; use the dataset's mean latitude
    mean_lat = sum(lats) / len(lats)
    lon_span_m = (max(lons) - min(lons)) * 111320 * math.cos(math.radians(mean_lat))

    from preprocessing.spatial_grid import _compute_grid_dims, list_available_depths
    n_lat, n_lon = _compute_grid_dims(np.array(lats), np.array(lons), len(records))
    resolution_m = None
    if n_lat > 1 and n_lon > 1:
        resolution_m = round(min(lat_span_m / n_lat, lon_span_m / n_lon), 3)

    # Processing steps actually applied, if any -- pulled from record metadata
    # rather than assumed.
    sample_with_processing = next((r for r in records if "processing_applied" in r.metadata), None)
    processing_applied = sample_with_processing.metadata.get("processing_applied") if sample_with_processing else None

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
        "coordinate_system": "EPSG:4326 (WGS84 lat/lon)",
        "survey_area_m": {"lat_span": round(lat_span_m, 1), "lon_span": round(lon_span_m, 1)},
        "grid_resolution_m": resolution_m,
        "depth_layers": list_available_depths(records),
        "processing_applied": processing_applied,
        "dem_aligned": bool(dataset.extra_metadata and dataset.extra_metadata.get("dem_aligned")),
        "last_preprocessing_mode": dataset.extra_metadata.get("last_preprocessing_mode") if dataset.extra_metadata else None,
    }


@router.get("/")
def list_datasets(
    sensor_type: Optional[str] = None,
    min_quality: Optional[float] = None,
    has_ground_truth: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """Search datasets by sensor, quality score, and ground-truth availability."""
    query = db.query(Dataset)
    if sensor_type:
        query = query.filter(Dataset.sensor_type == sensor_type)
    if min_quality is not None:
        query = query.filter(Dataset.quality_score >= min_quality)
    if has_ground_truth is not None:
        query = query.filter(Dataset.has_ground_truth == has_ground_truth)
    results = query.all()
    return [_dataset_to_dict(d) for d in results]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return _dataset_to_dict(dataset)


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    db.delete(dataset)
    db.commit()
    return {"deleted": dataset_id}


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
    }

