"""
Groups a survey line's trace x depth anomaly z-score grid (produced by
preprocessing/spatial_grid.py::preprocess_trace_local_anomaly) into
connected-component "anomaly candidates" and characterizes each one.

This is a READ-ONLY interpretation layer: it never mutates records, never
writes SubterraRecord.ground_truth, and persists nothing by default.
Candidates are computed on demand from already-persisted records and
addressed by a deterministic ID that encodes exactly which dataset,
source_file, cluster, and detection parameters produced it -- so there is
no staleness risk from caching a result that no longer matches how the
data was actually processed.

Reuses existing, already-tested primitives rather than re-implementing
them:
- preprocessing/spatial_grid.py::build_trace_depth_grid_for_records for the
  dense (depth x trace) grid and per-trace (lat, lon) -- already enforces
  per-source_file separation.
- training/spatial_shapes.py::extract_cluster_shape_features for PCA-based
  shape statistics (elongation, compactness, area, centroid) -- this
  function is axis-agnostic (it only sees a boolean mask + a value grid),
  so it works unmodified on a trace x depth grid exactly as it already does
  on api/routes/training.py::detect_objects's (lat, lon) grid.
- fusion/sensor_fusion.py::haversine_m for real-world lateral distance
  between two traces' actual (lat, lon), instead of reinventing distance math.
- scipy.ndimage.label with its DEFAULT structure (4-connectivity), matching
  detect_objects's existing choice exactly, for connected-component grouping.

SCIENTIFIC FRAMING (do not weaken this when extending the module):
- A "candidate" is a statistically anomalous REGION of the processed
  signal. It is not, and must never be presented as, a confirmed physical
  object. `AnomalyInterpretation.anomaly_class` is restricted to neutral
  geometric descriptors (compact / trace-elongated / depth-elongated /
  diffuse) -- never a material or object name (pipe, cable, void, rock,
  concrete, utility, etc).
- Every candidate is split into four explicitly separate tiers -- evidence,
  characteristics, interpretation, confidence -- so a consumer cannot
  accidentally read a derived geometric label as if it were measured
  evidence, or a single reliability field as if it were the complete
  uncertainty picture (see AnomalyConfidence: no single combined
  "confidence score" is computed anywhere in this module; each existing
  uncertainty signal from the pipeline -- reliability fraction, boundary
  proximity, KMZ direction, DEM vertical datum, velocity assumption -- is
  surfaced separately and left for the consumer to weigh).
- threshold/min_cells are PROVISIONAL detection parameters, not
  scientifically validated constants. They are exposed as arguments
  specifically so they can be re-examined against real data rather than
  trusted blindly (see the real-data validation performed alongside this
  module's introduction).
"""
from __future__ import annotations

import base64
from typing import Optional

import numpy as np
from pydantic import BaseModel
from scipy import ndimage

from schemas.subterra_record import SubterraRecord
from preprocessing.spatial_grid import build_trace_depth_grid_for_records, _group_by_source_file
from training.spatial_shapes import extract_cluster_shape_features
from fusion.sensor_fusion import haversine_m
from utils.logger import get_logger

logger = get_logger(__name__)

# Provisional -- NOT scientifically validated. See this module's docstring
# and the real-data validation report produced alongside this milestone.
DEFAULT_ANOMALY_THRESHOLD = 3.0
DEFAULT_MIN_CELLS = 3


class AnomalyEvidence(BaseModel):
    """Directly measured from the processed signal grid -- no interpretation."""
    source_file: str
    trace_range: tuple[int, int]      # (min, max) real SEG-Y trace_index values spanned
    depth_range: tuple[float, float]  # (min, max) real depth in meters spanned
    n_supporting_cells: int
    peak_value: float                 # signed z-score with the largest |value|
    peak_trace: int
    peak_depth: float
    mean_value: float


class AnomalyCharacteristics(BaseModel):
    """Derived geometric/statistical measures of the candidate region -- still not an interpretation."""
    elongation: Optional[float] = None    # PCA eigenvalue ratio, bounded (0, 1]; None if too small to compute
    compactness: Optional[float] = None   # area / bounding-box area
    area_cells: float
    continuity_across_traces: float       # fraction of the spanned trace columns that have >=1 supporting cell
    continuity_across_depth: float        # fraction of the spanned depth rows that have >=1 supporting cell
    approx_lateral_extent_m: Optional[float] = None   # real-world distance between the candidate's edge traces; None when not derivable
    lateral_extent_source: Optional[str] = None       # "geographic" | "odometry"; which measurement produced it
    approx_depth_extent_m: float
    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    centroid_elevation_m: Optional[float] = None      # None if the dataset hasn't been DEM-aligned


class AnomalyInterpretation(BaseModel):
    """Neutral geometric description ONLY. Never a physical-object claim."""
    anomaly_class: str   # "compact" | "trace-elongated" | "depth-elongated" | "diffuse" | "unclassified"
    note: str


class AnomalyConfidence(BaseModel):
    """
    Every existing uncertainty signal, kept SEPARATE -- deliberately no
    single combined confidence score, so none of these can silently mask
    another.
    """
    reliable_fraction: float                          # fraction of supporting cells with anomaly_reliable=True
    touches_trace_boundary: bool
    touches_depth_boundary: bool
    kmz_direction_verified: Optional[bool] = None      # None if records weren't KMZ-georeferenced at all
    dem_vertical_datum_verified: Optional[bool] = None  # None if the dataset hasn't been DEM-aligned
    velocity_m_per_ns: Optional[float] = None          # None only if inconsistent across supporting cells


class AnomalyCandidate(BaseModel):
    id: str
    dataset_id: str
    evidence: AnomalyEvidence
    characteristics: AnomalyCharacteristics
    interpretation: AnomalyInterpretation
    confidence: AnomalyConfidence


def encode_candidate_id(dataset_id: str, source_file: str, label_id: int, threshold: float, min_cells: int) -> str:
    """
    Deterministic, self-describing candidate ID: encodes exactly which
    dataset/source_file/cluster/parameters produced it, so a candidate_id
    computed under one threshold is never silently confused with one
    computed under another (no persistence, no staleness risk).
    """
    raw = f"{dataset_id}\x1f{source_file}\x1f{label_id}\x1f{threshold}\x1f{min_cells}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_candidate_id(candidate_id: str) -> dict:
    """Inverse of encode_candidate_id."""
    raw = base64.urlsafe_b64decode(candidate_id.encode()).decode()
    dataset_id, source_file, label_id, threshold, min_cells = raw.split("\x1f")
    return {
        "dataset_id": dataset_id,
        "source_file": source_file,
        "label_id": int(label_id),
        "threshold": float(threshold),
        "min_cells": int(min_cells),
    }


def _require_anomaly_processed(records: list[SubterraRecord], source_file: str) -> None:
    """
    Refuses to silently interpret raw amplitude as if it were z-score
    anomaly evidence. preprocess_trace_local_anomaly sets
    metadata["anomaly_reliable"] on every record it touches -- its absence
    means anomaly preprocessing hasn't run on this data yet.
    """
    if any(r.metadata.get("anomaly_reliable") is None for r in records):
        raise ValueError(
            f"Records for source_file={source_file!r} are missing metadata['anomaly_reliable'] -- "
            "trace-local anomaly preprocessing has not been run on this dataset yet "
            "(preprocessing_mode='gpr_local_anomaly'). Detecting anomaly candidates on raw amplitude "
            "would silently misinterpret physical signal units as statistical z-score evidence."
        )


def _classify_shape(elongation: Optional[float], compactness: Optional[float], bbox_h: int, bbox_w: int) -> tuple[str, str]:
    """
    Neutral geometric classification ONLY -- never a material/object name.
    bbox_h/bbox_w are in GRID CELLS (depth rows / trace columns respectively,
    not meters -- depth and trace spacing are different units and must not
    be compared as if they were the same physical scale).
    """
    note = (
        "Geometric descriptor derived from the shape of the connected anomaly region only -- "
        "NOT a physical material or object identification. No ground truth was consulted."
    )
    if elongation is None:
        return "unclassified", note
    if elongation > 0.8:
        return ("trace-elongated" if bbox_w >= bbox_h else "depth-elongated"), note
    if compactness is not None and compactness > 0.5 and elongation < 0.65:
        return "compact", note
    return "diffuse", note


def _characterize_cluster(
    cluster_mask: np.ndarray,
    grid: np.ndarray,
    label_id: int,
    threshold: float,
    min_cells: int,
    trace_ids: list,
    depths: list,
    trace_lat: list,
    trace_lon: list,
    trace_position_kind: list | None,
    trace_geographic: list | None,
    trace_along_track: list | None,
    cell_index: dict,
    source_file: str,
    dataset_id: str,
) -> AnomalyCandidate:
    n_depths, n_traces = grid.shape
    ys, xs = np.where(cluster_mask)  # ys = depth-row indices, xs = trace-col indices

    row_min, row_max = int(ys.min()), int(ys.max())
    col_min, col_max = int(xs.min()), int(xs.max())

    trace_range = (int(trace_ids[col_min]), int(trace_ids[col_max]))
    depth_range = (float(depths[row_min]), float(depths[row_max]))

    values = grid[ys, xs]
    peak_pos = int(np.argmax(np.abs(values)))
    peak_value = float(values[peak_pos])
    peak_trace = int(trace_ids[int(xs[peak_pos])])
    peak_depth = float(depths[int(ys[peak_pos])])
    mean_value = float(values.mean())
    n_supporting_cells = int(len(ys))

    unique_cols = len(set(xs.tolist()))
    unique_rows = len(set(ys.tolist()))
    continuity_across_traces = unique_cols / (col_max - col_min + 1)
    continuity_across_depth = unique_rows / (row_max - row_min + 1)

    shape_feats = extract_cluster_shape_features(cluster_mask, grid)
    elongation = shape_feats["elongation"] if shape_feats else None
    compactness = shape_feats["compactness"] if shape_feats else None
    area_cells = shape_feats["area"] if shape_feats else float(n_supporting_cells)

    bbox_h = row_max - row_min + 1
    bbox_w = col_max - col_min + 1
    anomaly_class, note = _classify_shape(elongation, compactness, bbox_h, bbox_w)

    # Lateral extent is measurable from whichever positioning the acquisition
    # actually has, and is None when it has none. Before this, an
    # un-georeferenced line (whose legacy lat/lon are the (0,0) placeholder)
    # reported haversine_m(0,0, 0,0) = exactly 0.0 metres -- a fabricated
    # measurement in the evidence tier, indistinguishable from a genuinely
    # single-trace candidate.
    #
    # Two sources, never mixed, and the winner is named in
    # `lateral_extent_source` so a consumer can tell a GPS distance from a
    # wheel-encoder one:
    #   geographic  real lat/lon (the trace's own, or a KMZ track's) -> haversine
    #   odometry    along-track distance from a wheel encoder -> difference
    # A projected-but-CRS-less or unpositioned line yields neither.
    def _endpoints(values) -> bool:
        return (values is not None and values[col_min] is not None
                and values[col_max] is not None)

    approx_lateral_extent_m = None
    lateral_extent_source = None
    if _endpoints(trace_geographic) and trace_geographic[col_min] and trace_geographic[col_max]:
        lateral_extent_source = "geographic"
        approx_lateral_extent_m = (
            haversine_m(trace_lat[col_min], trace_lon[col_min],
                        trace_lat[col_max], trace_lon[col_max])
            if col_max > col_min else 0.0
        )
    elif _endpoints(trace_along_track):
        lateral_extent_source = "odometry"
        approx_lateral_extent_m = abs(
            trace_along_track[col_max] - trace_along_track[col_min])
    approx_depth_extent_m = float(depth_range[1] - depth_range[0])

    if shape_feats:
        centroid_col_idx = max(0, min(n_traces - 1, int(round(shape_feats["centroid_col"]))))
    else:
        centroid_col_idx = (col_min + col_max) // 2
    centroid_lat = float(trace_lat[centroid_col_idx])
    centroid_lon = float(trace_lon[centroid_col_idx])

    reliable_flags, kmz_flags, dem_flags, velocities, elevations = [], [], [], set(), []
    for row, col in zip(ys.tolist(), xs.tolist()):
        rec = cell_index.get((trace_ids[col], round(depths[row], 6)))
        if rec is None:
            continue
        reliable_flags.append(bool(rec.metadata.get("anomaly_reliable")))
        if "kmz_direction_verified" in rec.metadata:
            kmz_flags.append(rec.metadata["kmz_direction_verified"])
        if "dem_vertical_datum_verified" in rec.metadata:
            dem_flags.append(rec.metadata["dem_vertical_datum_verified"])
        if "velocity_m_per_ns" in rec.metadata:
            velocities.add(rec.metadata["velocity_m_per_ns"])
        if rec.elevation is not None:
            elevations.append(rec.elevation)

    reliable_fraction = (sum(reliable_flags) / len(reliable_flags)) if reliable_flags else 0.0
    kmz_direction_verified = kmz_flags[0] if kmz_flags and len(set(kmz_flags)) == 1 else None
    dem_vertical_datum_verified = dem_flags[0] if dem_flags and len(set(dem_flags)) == 1 else None
    velocity_m_per_ns = sorted(velocities)[0] if len(velocities) == 1 else None
    centroid_elevation_m = float(np.mean(elevations)) if elevations else None

    touches_trace_boundary = (col_min == 0) or (col_max == n_traces - 1)
    touches_depth_boundary = (row_min == 0) or (row_max == n_depths - 1)

    return AnomalyCandidate(
        id=encode_candidate_id(dataset_id, source_file, label_id, threshold, min_cells),
        dataset_id=dataset_id,
        evidence=AnomalyEvidence(
            source_file=source_file,
            trace_range=trace_range,
            depth_range=depth_range,
            n_supporting_cells=n_supporting_cells,
            peak_value=peak_value,
            peak_trace=peak_trace,
            peak_depth=peak_depth,
            mean_value=mean_value,
        ),
        characteristics=AnomalyCharacteristics(
            elongation=elongation,
            compactness=compactness,
            area_cells=area_cells,
            continuity_across_traces=continuity_across_traces,
            continuity_across_depth=continuity_across_depth,
            approx_lateral_extent_m=approx_lateral_extent_m,
            lateral_extent_source=lateral_extent_source,
            approx_depth_extent_m=approx_depth_extent_m,
            centroid_lat=centroid_lat,
            centroid_lon=centroid_lon,
            centroid_elevation_m=centroid_elevation_m,
        ),
        interpretation=AnomalyInterpretation(anomaly_class=anomaly_class, note=note),
        confidence=AnomalyConfidence(
            reliable_fraction=reliable_fraction,
            touches_trace_boundary=touches_trace_boundary,
            touches_depth_boundary=touches_depth_boundary,
            kmz_direction_verified=kmz_direction_verified,
            dem_vertical_datum_verified=dem_vertical_datum_verified,
            velocity_m_per_ns=velocity_m_per_ns,
        ),
    )


def find_anomaly_candidates(
    records: list[SubterraRecord],
    source_file: str,
    threshold: float = DEFAULT_ANOMALY_THRESHOLD,
    min_cells: int = DEFAULT_MIN_CELLS,
) -> list[AnomalyCandidate]:
    """
    Finds connected-component anomaly candidates in ONE survey line's
    z-score grid. `source_file` is REQUIRED (no auto-pick default, unlike
    build_trace_depth_grid_for_records) -- a connected component must never
    be allowed to silently span more than one source_file, so there is no
    code path here that builds a grid from more than one line at a time.

    threshold/min_cells are PROVISIONAL (see module docstring) -- callers
    should treat the defaults as a starting point to validate against real
    data, not a scientifically settled choice.

    Raises ValueError if source_file has no records, or if those records
    haven't been through trace-local anomaly preprocessing yet.
    """
    by_file = _group_by_source_file(records)
    sub_records = by_file.get(source_file)
    if not sub_records:
        raise ValueError(f"No records found for source_file={source_file!r}. Available: {sorted(by_file)}")

    _require_anomaly_processed(sub_records, source_file)

    grid_result = build_trace_depth_grid_for_records(sub_records, source_file=source_file, field="signal")
    grid = grid_result["grid"]
    trace_ids = grid_result["trace_indices"]
    depths = grid_result["depths"]
    trace_lat = grid_result["trace_lat"]
    trace_lon = grid_result["trace_lon"]
    trace_position_kind = grid_result.get("trace_position_kind")
    trace_geographic = grid_result.get("trace_geographic")
    trace_along_track = grid_result.get("trace_along_track")
    dataset_id = sub_records[0].dataset_id

    cell_index = {(r.metadata["trace_index"], round(r.depth, 6)): r for r in sub_records}

    mask = np.abs(np.nan_to_num(grid, nan=0.0)) > threshold
    # Default `structure` = 4-connectivity, matching
    # api/routes/training.py::detect_objects's existing ndimage.label(mask) call exactly.
    labeled, n_labels = ndimage.label(mask)

    candidates = []
    for label_id in range(1, n_labels + 1):
        cluster_mask = labeled == label_id
        if int(cluster_mask.sum()) < min_cells:
            continue
        candidates.append(
            _characterize_cluster(
                cluster_mask, grid, label_id, threshold, min_cells,
                trace_ids, depths, trace_lat, trace_lon, trace_position_kind,
                trace_geographic, trace_along_track, cell_index,
                source_file, dataset_id,
            )
        )

    logger.info(
        f"find_anomaly_candidates: source_file={source_file!r}, threshold={threshold}, min_cells={min_cells} "
        f"-> {n_labels} raw component(s), {len(candidates)} candidate(s) after min_cells filter"
    )
    return candidates


def find_anomaly_candidates_all_lines(
    records: list[SubterraRecord],
    threshold: float = DEFAULT_ANOMALY_THRESHOLD,
    min_cells: int = DEFAULT_MIN_CELLS,
) -> dict[str, list[AnomalyCandidate]]:
    """
    Convenience wrapper for a multi-line dataset: runs find_anomaly_candidates
    independently per source_file and returns {source_file: [candidates]}.
    Never builds a single grid spanning multiple lines -- each call below is
    fully independent.
    """
    by_file = _group_by_source_file(records)
    return {
        source_file: find_anomaly_candidates(records, source_file=source_file, threshold=threshold, min_cells=min_cells)
        for source_file in sorted(by_file)
    }
