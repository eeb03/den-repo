"""
Spatial-grid preprocessing: for sensors where each SubterraRecord carries
ONE scalar reading at a (lat, lon, depth) point — GPR depth slices,
magnetometer surveys, gravity grids — smoothing/normalization has to
happen across neighboring points in space, not within each record's own
(length-1) signal array. `preprocessing/pipeline.py::run_pipeline` handles
the other case (true multi-sample traces, e.g. SEG-Y). This module handles
this one.

Records are grouped by depth (so a multi-depth-slice dataset becomes a
stack of independent 2D layers), pivoted into a lat x lon grid per layer,
processed as a raster, then written back onto the original records.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from schemas.subterra_record import SubterraRecord
from utils.logger import get_logger

logger = get_logger(__name__)


MAX_GRID_CELLS = 4_000_000  # hard cap so a dense/irregular point cloud can't explode memory


def _infer_decimals(values: np.ndarray) -> int:
    """Round coordinates to collapse floating-point jitter onto a shared grid, inferring precision from the median spacing between distinct values. Only meaningful for genuinely regular/raster data — see _compute_grid_dims for the general case."""
    uniq = np.array(sorted(set(values)))
    if len(uniq) < 2:
        return 8
    diffs = np.diff(uniq)
    positive = diffs[diffs > 0]
    if len(positive) == 0:
        return 8
    median_step = np.median(positive)
    return max(0, int(np.ceil(-np.log10(median_step))) + 1)


def _compute_grid_dims(lat: np.ndarray, lon: np.ndarray, n_points: int) -> tuple[int, int]:
    """
    Pick a (n_lat_bins, n_lon_bins) grid sized to actual point density rather
    than coordinate precision. GPS-tracked survey data (scan lines with
    near-continuous, non-repeating lat/lon) has almost as many unique
    coordinate values as points — rounding to "enough decimals to keep
    points distinct" on such data produces a grid with as many rows/cols as
    points, i.e. a pivot table with rows*cols cells (billions, for a 157k-
    point dataset). Binning by target cell count keeps total cells
    proportional to n_points regardless of coordinate irregularity, and
    still reconstructs an exact raster when the input genuinely is one.
    """
    lat_span = float(lat.max() - lat.min()) or 1e-9
    lon_span = float(lon.max() - lon.min()) or 1e-9
    aspect = lon_span / lat_span
    n_lat = max(2, int(round((n_points / aspect) ** 0.5)))
    n_lon = max(2, int(round(n_points / max(n_lat, 1))))
    if n_lat * n_lon > MAX_GRID_CELLS:
        scale = (MAX_GRID_CELLS / (n_lat * n_lon)) ** 0.5
        n_lat = max(2, int(n_lat * scale))
        n_lon = max(2, int(n_lon * scale))
        logger.warning(
            f"preprocess_spatial_grid: point density would exceed {MAX_GRID_CELLS} grid cells; "
            f"downsampled to {n_lat}x{n_lon}. Multiple points will be averaged per cell."
        )
    return n_lat, n_lon


def _box_filter_1d(arr: np.ndarray, window: int, axis: int) -> np.ndarray:
    """Sliding-window sum along one axis via a cumulative-sum trick (fully vectorized)."""
    pad = window // 2
    pad_width = [(0, 0)] * arr.ndim
    pad_width[axis] = (pad, pad)
    padded = np.pad(arr, pad_width, mode="constant")
    csum = np.cumsum(padded, axis=axis)
    zero_shape = list(csum.shape)
    zero_shape[axis] = 1
    csum = np.concatenate([np.zeros(zero_shape), csum], axis=axis)
    n = arr.shape[axis]
    hi = np.take(csum, np.arange(window, window + n), axis=axis)
    lo = np.take(csum, np.arange(0, n), axis=axis)
    return hi - lo


def _smooth_2d_nanaware(grid: np.ndarray, window: int = 3) -> np.ndarray:
    """
    NaN-aware 2D box smoothing: each cell becomes the average of its
    window x window neighborhood, excluding missing (NaN) cells from both
    the sum and the divisor rather than treating them as zero. Box filter
    is separable, so the 2D window sum is a 1D pass along rows then columns.
    """
    if window < 3:
        return grid
    mask = (~np.isnan(grid)).astype(float)
    filled = np.nan_to_num(grid, nan=0.0)
    sums = _box_filter_1d(_box_filter_1d(filled, window, axis=0), window, axis=1)
    counts = _box_filter_1d(_box_filter_1d(mask, window, axis=0), window, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        result = sums / counts
    result[counts == 0] = np.nan
    return result


def _clip_outliers_2d(grid: np.ndarray, z_thresh: float = 4.0) -> np.ndarray:
    """Clip values beyond z_thresh std deviations, computed over the whole grid (not per-cell)."""
    mean, std = np.nanmean(grid), np.nanstd(grid)
    if not np.isfinite(std) or std == 0:
        return grid
    return np.clip(grid, mean - z_thresh * std, mean + z_thresh * std)


def _normalize_2d(grid: np.ndarray) -> np.ndarray:
    """Z-score normalize over the whole grid."""
    mean, std = np.nanmean(grid), np.nanstd(grid)
    if not np.isfinite(std) or std == 0:
        return grid
    return (grid - mean) / std


def _local_anomaly_grid(
    grid: np.ndarray, inner_window: int = 5, outer_window: int = 15, min_ring_count: int = 20
) -> tuple[np.ndarray, np.ndarray]:
    """
    Local (ring-based) anomaly z-score: for each cell, estimates the
    background mean/std from an ANNULUS between inner_window and
    outer_window -- explicitly excluding the cell's own immediate
    neighborhood -- so a real anomaly doesn't inflate its own background
    estimate and dilute its own score (verified: a naive single-window
    local mean/std gave a spike z=2.38; the ring estimator gives z=12.5+
    for the same spike). Cells whose ring has fewer than min_ring_count
    valid neighbors (edges/corners of the grid) are marked unreliable
    rather than producing a spuriously large or small z-score from too
    few samples.

    Returns (z_scores, unreliable_mask).
    """
    def box_sum_count(g, window):
        mask = (~np.isnan(g)).astype(float)
        filled = np.nan_to_num(g, nan=0.0)
        filled_sq = filled ** 2
        counts = _box_filter_1d(_box_filter_1d(mask, window, 0), window, 1)
        sums = _box_filter_1d(_box_filter_1d(filled, window, 0), window, 1)
        sums_sq = _box_filter_1d(_box_filter_1d(filled_sq, window, 0), window, 1)
        return sums, sums_sq, counts

    s_out, sq_out, c_out = box_sum_count(grid, outer_window)
    s_in, sq_in, c_in = box_sum_count(grid, inner_window)
    ring_sum, ring_sumsq, ring_count = s_out - s_in, sq_out - sq_in, c_out - c_in

    with np.errstate(invalid="ignore", divide="ignore"):
        mean = ring_sum / ring_count
        var = np.clip(ring_sumsq / ring_count - mean ** 2, 0, None)
        std = np.sqrt(var)

    unreliable = (ring_count < min_ring_count) | (std == 0) | np.isnan(std)
    mean_safe = np.where(unreliable, np.nan, mean)
    std_safe = np.where(unreliable, np.nan, std)
    with np.errstate(invalid="ignore"):
        z = (grid - mean_safe) / std_safe

    return z, unreliable


def preprocess_spatial_grid_anomaly(
    records: list[SubterraRecord],
    inner_window: int = 5,
    outer_window: int = 15,
    min_ring_count: int = 20,
) -> list[SubterraRecord]:
    """
    Computes a LOCAL anomaly z-score per record — how unusual each point is
    relative to its own surrounding background, not the whole dataset's
    statistics. This is what separates a real, spatially-small target (a
    pipe, a void) from being diluted into noise by a global z-score
    computed across an entire large survey.

    Overwrites record.signal with the anomaly z-score; the original raw
    value and background stats are preserved in metadata for reference.
    Records whose grid cell had too few background neighbors (edges of the
    survey) get metadata["anomaly_reliable"]=False rather than a
    potentially misleading extreme value.
    """
    if not records:
        return records

    rows = [
        {
            "idx": i, "lat": r.latitude, "lon": r.longitude,
            "depth": round(r.depth, 6) if r.depth is not None else 0.0,
            "value": r.signal[0] if r.signal else np.nan,
        }
        for i, r in enumerate(records)
    ]
    df = pd.DataFrame(rows)
    if df["value"].isna().all():
        logger.warning("preprocess_spatial_grid_anomaly: no scalar signal values found; skipping.")
        return records

    for depth_val, layer_df in df.groupby("depth"):
        layer_df = layer_df.copy()
        n_lat, n_lon = _compute_grid_dims(layer_df["lat"].to_numpy(), layer_df["lon"].to_numpy(), len(layer_df))
        layer_df["lat_bin"] = pd.cut(layer_df["lat"], bins=n_lat, labels=False, include_lowest=True)
        layer_df["lon_bin"] = pd.cut(layer_df["lon"], bins=n_lon, labels=False, include_lowest=True)

        pivot = layer_df.pivot_table(index="lat_bin", columns="lon_bin", values="value", aggfunc="mean")
        pivot = pivot.reindex(index=range(n_lat), columns=range(n_lon))
        grid = pivot.to_numpy(dtype=float)

        z_grid, unreliable_grid = _local_anomaly_grid(grid, inner_window, outer_window, min_ring_count)
        z_df = pd.DataFrame(z_grid, index=pivot.index, columns=pivot.columns)
        unreliable_df = pd.DataFrame(unreliable_grid, index=pivot.index, columns=pivot.columns)

        for row in layer_df.itertuples():
            raw_val = records[row.idx].signal[0] if records[row.idx].signal else None
            z_val = z_df.at[row.lat_bin, row.lon_bin]
            is_unreliable = bool(unreliable_df.at[row.lat_bin, row.lon_bin])
            records[row.idx].metadata["raw_signal"] = raw_val
            records[row.idx].metadata["anomaly_reliable"] = not is_unreliable
            records[row.idx].signal = [float(z_val)] if pd.notna(z_val) else [0.0]

    n_reliable = sum(1 for r in records if r.metadata.get("anomaly_reliable"))
    logger.info(
        f"preprocess_spatial_grid_anomaly: computed local anomaly scores for {len(records)} records "
        f"({n_reliable} reliable, inner_window={inner_window}, outer_window={outer_window})"
    )
    return records


def build_grid_for_records(
    records: list[SubterraRecord], depth: float | None = None, field: str = "signal"
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """
    Extracts a single depth layer as a 2D array for DISPLAY (heatmap/surface
    rendering) — read-only, doesn't mutate the records the way
    preprocess_spatial_grid does. Returns (grid, lat_centers, lon_centers,
    depth_used).

    field selects which quantity to grid: "signal" (the sensor reading),
    "elevation" (DEM-aligned ground surface elevation), or
    "absolute_elevation_m" (surface elevation - depth, from metadata) —
    the latter two let a caller build a matching elevation surface to drape
    the signal grid over in a 3D surface plot.

    depth=None picks whichever depth layer has the most records (the
    common case: a dataset with only one depth slice). Otherwise picks the
    nearest available depth to the requested value.
    """
    def get_value(r: SubterraRecord):
        if field == "signal":
            return r.signal[0] if r.signal else np.nan
        if field == "elevation":
            return r.elevation if r.elevation is not None else np.nan
        if field == "absolute_elevation_m":
            return (r.metadata or {}).get("absolute_elevation_m", np.nan)
        raise ValueError(f"Unknown field '{field}'")

    rows = [
        {
            "lat": r.latitude, "lon": r.longitude,
            "depth": round(r.depth, 6) if r.depth is not None else 0.0,
            "value": get_value(r),
        }
        for r in records
    ]
    df = pd.DataFrame(rows)

    available_depths = df["depth"].unique()
    if depth is not None:
        target_depth = min(available_depths, key=lambda d: abs(d - depth))
    else:
        target_depth = df["depth"].value_counts().idxmax()

    layer_df = df[df["depth"] == target_depth].copy()
    n_lat, n_lon = _compute_grid_dims(layer_df["lat"].to_numpy(), layer_df["lon"].to_numpy(), len(layer_df))
    layer_df["lat_bin"] = pd.cut(layer_df["lat"], bins=n_lat, labels=False, include_lowest=True)
    layer_df["lon_bin"] = pd.cut(layer_df["lon"], bins=n_lon, labels=False, include_lowest=True)

    pivot = layer_df.pivot_table(index="lat_bin", columns="lon_bin", values="value", aggfunc="mean")
    pivot = pivot.reindex(index=range(n_lat), columns=range(n_lon))
    grid = pivot.to_numpy(dtype=float)

    lat_edges = np.linspace(layer_df["lat"].min(), layer_df["lat"].max(), n_lat + 1)
    lon_edges = np.linspace(layer_df["lon"].min(), layer_df["lon"].max(), n_lon + 1)
    lat_centers = (lat_edges[:-1] + lat_edges[1:]) / 2
    lon_centers = (lon_edges[:-1] + lon_edges[1:]) / 2

    return grid, lat_centers, lon_centers, float(target_depth)


def list_available_depths(records: list[SubterraRecord]) -> list[dict]:
    """Returns sorted [{depth, count}, ...] for depth-slice stacking controls."""
    from collections import Counter
    counts = Counter(round(r.depth, 6) for r in records if r.depth is not None)
    return [{"depth": d, "count": counts[d]} for d in sorted(counts.keys())]


def preprocess_spatial_grid(
    records: list[SubterraRecord],
    denoise: bool = True,
    normalize: bool = True,
    remove_outliers: bool = True,
    smoothing_window: int = 3,
) -> list[SubterraRecord]:
    """
    Preprocess a dataset of single-value, spatially-gridded records (GPR
    depth slices, magnetometer/gravity surveys) as a raster. Statistics
    (mean/std for normalization and outlier clipping) are computed across
    the ENTIRE grid/layer, and smoothing considers real spatial neighbors —
    this is the fix for datasets where run_pipeline() was a no-op because
    each record's signal array only held a single sample.
    """
    if not records:
        return records

    rows = [
        {
            "idx": i,
            "lat": r.latitude,
            "lon": r.longitude,
            "depth": round(r.depth, 6) if r.depth is not None else 0.0,
            "value": r.signal[0] if r.signal else np.nan,
        }
        for i, r in enumerate(records)
    ]
    df = pd.DataFrame(rows)

    if df["value"].isna().all():
        logger.warning("preprocess_spatial_grid: no scalar signal values found on any record; skipping.")
        return records

    lat_arr = df["lat"].to_numpy()
    lon_arr = df["lon"].to_numpy()

    n_layers = df["depth"].nunique()
    for depth_val, layer_df in df.groupby("depth"):
        layer_lat = layer_df["lat"].to_numpy()
        layer_lon = layer_df["lon"].to_numpy()
        n_lat, n_lon = _compute_grid_dims(layer_lat, layer_lon, len(layer_df))

        layer_df = layer_df.copy()
        layer_df["lat_bin"] = pd.cut(layer_df["lat"], bins=n_lat, labels=False, include_lowest=True)
        layer_df["lon_bin"] = pd.cut(layer_df["lon"], bins=n_lon, labels=False, include_lowest=True)

        pivot = layer_df.pivot_table(index="lat_bin", columns="lon_bin", values="value", aggfunc="mean")
        pivot = pivot.reindex(index=range(n_lat), columns=range(n_lon))
        grid = pivot.to_numpy(dtype=float)

        if remove_outliers:
            grid = _clip_outliers_2d(grid)
        if denoise:
            grid = _smooth_2d_nanaware(grid, window=smoothing_window)
        if normalize:
            grid = _normalize_2d(grid)

        smoothed = pd.DataFrame(grid, index=pivot.index, columns=pivot.columns)

        for row in layer_df.itertuples():
            val = smoothed.at[row.lat_bin, row.lon_bin]
            if pd.notna(val):
                records[row.idx].signal = [float(val)]

    logger.info(
        f"preprocess_spatial_grid: processed {len(records)} records across "
        f"{n_layers} depth layer(s), window={smoothing_window}"
    )
    return records
