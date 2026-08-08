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

from schemas.spatial import has_geographic_coordinates
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


def _as_row_col_window(window: int | tuple[int, int]) -> tuple[int, int]:
    """Normalizes a window spec to (row_window, col_window). A bare int applies the same window to both axes (the existing isotropic behavior); a (row, col) tuple allows axis-specific windows for anisotropic grids (e.g. GPR trace x depth, where depth resolution is far finer than trace spacing)."""
    if isinstance(window, (tuple, list)):
        if len(window) != 2:
            raise ValueError(f"window tuple must have exactly 2 elements (row, col), got {window}")
        return int(window[0]), int(window[1])
    return int(window), int(window)


def _axis_ring_counts(n: int, inner_window: int, outer_window: int) -> np.ndarray:
    """
    1D ring neighbor count along ONE axis of length n (every position
    assumed valid) -- how many real neighbors fall in [outer] minus
    [inner] window around each position, correctly truncated at that
    axis's own edges.

    This exists because the JOINT 2D ring_count in `_local_anomaly_grid`
    is a product of both axes' extents: on a strongly anisotropic grid
    (e.g. a GPR radargram with hundreds of depth samples but only a few
    dozen traces), abundant depth-direction neighbors mathematically
    backfill the joint count even when a cell is genuinely starved of
    TRACE-direction neighbors (near the true edges of the survey line) --
    verified empirically: on the real 482x72 C1T_7,5_0001 grid shape, no
    min_ring_count up to 200+ ever flags the true leftmost/rightmost trace
    columns, because the depth axis alone supplies hundreds of valid
    neighbors regardless of how truncated the trace axis is. A per-axis
    marginal count decouples the two, so trace-direction scarcity can't be
    masked by depth-direction abundance (or vice versa).
    """
    ones = np.ones(n)
    outer = _box_filter_1d(ones, outer_window, axis=0)
    inner = _box_filter_1d(ones, inner_window, axis=0)
    return outer - inner


def _local_anomaly_grid(
    grid: np.ndarray,
    inner_window: int | tuple[int, int] = 5,
    outer_window: int | tuple[int, int] = 15,
    min_ring_count: int = 20,
    min_row_ring_count: int | None = None,
    min_col_ring_count: int | None = None,
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

    inner_window/outer_window accept a bare int (isotropic, same window on
    both axes -- the original behavior, used by the (lat, lon) area-survey
    "local_anomaly" mode) OR a (row, col) tuple for axis-specific windows.

    min_row_ring_count/min_col_ring_count (optional, default None = no
    effect on existing callers): additional reliability checks based on
    each axis's OWN marginal neighbor count in isolation -- see
    `_axis_ring_counts` for why the joint min_ring_count alone can't
    detect axis-specific edge starvation on a strongly anisotropic grid.

    Returns (z_scores, unreliable_mask).
    """
    inner_row, inner_col = _as_row_col_window(inner_window)
    outer_row, outer_col = _as_row_col_window(outer_window)

    def box_sum_count(g, window_row, window_col):
        mask = (~np.isnan(g)).astype(float)
        filled = np.nan_to_num(g, nan=0.0)
        filled_sq = filled ** 2
        counts = _box_filter_1d(_box_filter_1d(mask, window_row, 0), window_col, 1)
        sums = _box_filter_1d(_box_filter_1d(filled, window_row, 0), window_col, 1)
        sums_sq = _box_filter_1d(_box_filter_1d(filled_sq, window_row, 0), window_col, 1)
        return sums, sums_sq, counts

    s_out, sq_out, c_out = box_sum_count(grid, outer_row, outer_col)
    s_in, sq_in, c_in = box_sum_count(grid, inner_row, inner_col)
    ring_sum, ring_sumsq, ring_count = s_out - s_in, sq_out - sq_in, c_out - c_in

    with np.errstate(invalid="ignore", divide="ignore"):
        mean = ring_sum / ring_count
        var = np.clip(ring_sumsq / ring_count - mean ** 2, 0, None)
        std = np.sqrt(var)

    unreliable = (ring_count < min_ring_count) | (std == 0) | np.isnan(std)

    if min_row_ring_count is not None:
        row_ring_counts = _axis_ring_counts(grid.shape[0], inner_row, outer_row)
        unreliable = unreliable | (row_ring_counts[:, None] < min_row_ring_count)
    if min_col_ring_count is not None:
        col_ring_counts = _axis_ring_counts(grid.shape[1], inner_col, outer_col)
        unreliable = unreliable | (col_ring_counts[None, :] < min_col_ring_count)

    mean_safe = np.where(unreliable, np.nan, mean)
    std_safe = np.where(unreliable, np.nan, std)
    with np.errstate(invalid="ignore"):
        z = (grid - mean_safe) / std_safe

    return z, unreliable


#: The ring windows `preprocess_trace_local_anomaly` uses, in the
#: (depth, trace) axis order `_local_anomaly_grid` expects. Named once here so
#: the record path and the array path cannot drift apart.
TRACE_ANOMALY_WINDOWS = {
    "inner_window": (5, 2),
    "outer_window": (15, 6),
    "min_ring_count": 20,
    "min_row_ring_count": 10,   # depth axis
    "min_col_ring_count": 4,    # trace axis
}


def anomaly_grid_from_traces(traces_2d) -> np.ndarray:
    """
    The trace-local anomaly z-grid for one survey line, computed from an
    array instead of from one SubterraRecord per cell.

    Takes (n_traces, n_samples) and returns (n_samples, n_traces) -- the
    (depth, trace) orientation `_trace_depth_grid` builds, so the result is
    directly comparable with the record path.

    WHY IT TAKES AN ARRAY. Peak memory on a real corpus is dominated by the
    per-(trace, sample) records, not by the science: a 14,516 x 512 radargram
    is a 59 MB float array but roughly 5 GB of pydantic objects. This calls
    the IDENTICAL functions in the IDENTICAL order that
    `preprocess_trace_local_anomaly` does -- background_removal -> dewow ->
    apply_gain -> `_local_anomaly_grid` with `TRACE_ANOMALY_WINDOWS` -- on the
    array directly. Nothing is chunked, so the ring statistic still sees the
    whole line at once and there are no chunk boundaries to correct for.

    It is NOT an approximation of the record path; `scripts/characterise_4tu.py
    --verify-arraywise` asserts the two produce the same grid. What it does not
    produce is per-candidate characterisation, which legitimately needs the
    per-cell records.
    """
    from preprocessing.trace_processing import apply_gain, background_removal, dewow

    traces = np.asarray(traces_2d, dtype=float)
    traces = np.asarray(background_removal(traces.tolist()), dtype=float)
    processed = np.array(
        [apply_gain(dewow(t.tolist(), window=15), gain_type="linear", power=1.0)
         for t in traces],
        dtype=float,
    )
    z_grid, _unreliable = _local_anomaly_grid(processed.T, **TRACE_ANOMALY_WINDOWS)
    return z_grid


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

    Overwrites record.signal with the anomaly z-score. Records whose grid
    cell had too few background neighbors (edges of the survey) get
    metadata["anomaly_reliable"]=False rather than a potentially
    misleading extreme value. metadata["pre_anomaly_signal"] preserves the
    value as it was immediately before this step (not necessarily the
    original raw sensor reading, if earlier preprocessing already ran).
    """
    if not records:
        return records

    # (lat, lon) binning is only meaningful for geographic records. Others are
    # left out of the grid entirely rather than binned at a missing
    # coordinate, and keep their original index so the results still scatter
    # back onto the right record.
    rows = [
        {
            "idx": i, "lat": r.latitude, "lon": r.longitude,
            "depth": round(r.depth, 6) if r.depth is not None else 0.0,
            "value": r.signal[0] if r.signal else np.nan,
        }
        for i, r in enumerate(records) if has_geographic_coordinates(r)
    ]
    if not rows:
        logger.warning(
            f"preprocess_spatial_grid_anomaly: none of the {len(records)} record(s) carry a "
            f"geographic position, so no (lat, lon) grid can be built -- skipping."
        )
        return records
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
            records[row.idx].metadata["pre_anomaly_signal"] = raw_val
            records[row.idx].metadata["anomaly_reliable"] = not is_unreliable
            records[row.idx].signal = [float(z_val)] if pd.notna(z_val) else [0.0]

    n_reliable = sum(1 for r in records if r.metadata.get("anomaly_reliable"))
    logger.info(
        f"preprocess_spatial_grid_anomaly: computed local anomaly scores for {len(records)} records "
        f"({n_reliable} reliable, inner_window={inner_window}, outer_window={outer_window})"
    )
    return records


def _trace_depth_grid(records: list[SubterraRecord], field: str = "signal") -> tuple[np.ndarray, list, list]:
    """
    Pivots records sharing metadata["trace_index"] + real `depth` into a
    dense (n_depths x n_traces) 2D array -- the native radargram/B-scan
    structure for ONE GPR survey line. Unlike the (lat, lon)-binned grid
    `build_grid_for_records`/`preprocess_spatial_grid*` use (built for
    area-covering depth-slice surveys), this is always fully dense: every
    trace shares the exact same depth axis by construction (see
    SEGYConverter), so there are no missing cells the way binning a
    handful of line-transect points into a lat/lon area grid would produce.

    Internal building block shared by `preprocess_trace_local_anomaly`
    (mutates records) and `build_trace_depth_grid_for_records` (read-only,
    for API/visualization).
    """
    def get_value(r: SubterraRecord):
        if field == "signal":
            return r.signal[0] if r.signal else np.nan
        if field == "elevation":
            return r.elevation if r.elevation is not None else np.nan
        if field == "absolute_elevation_m":
            return (r.metadata or {}).get("absolute_elevation_m", np.nan)
        raise ValueError(f"Unknown field '{field}'")

    trace_ids = sorted({r.metadata["trace_index"] for r in records})
    depths = sorted({round(r.depth, 6) for r in records})
    trace_pos = {t: i for i, t in enumerate(trace_ids)}
    depth_pos = {d: i for i, d in enumerate(depths)}

    grid = np.full((len(depths), len(trace_ids)), np.nan)
    for r in records:
        grid[depth_pos[round(r.depth, 6)], trace_pos[r.metadata["trace_index"]]] = get_value(r)

    return grid, trace_ids, depths


def _group_by_source_file(records: list[SubterraRecord]) -> dict[str, list[SubterraRecord]]:
    """Groups records by metadata['source_file'] -- trace_index is only unique WITHIN one file's acquisition, so multi-line datasets (a zip of several .sgy lines) must be processed independently per line."""
    by_file: dict[str, list[SubterraRecord]] = {}
    for r in records:
        by_file.setdefault(r.metadata.get("source_file", ""), []).append(r)
    return by_file


def preprocess_trace_local_anomaly(
    records: list[SubterraRecord],
    trace_inner_window: int = 2,
    trace_outer_window: int = 6,
    depth_inner_window: int = 5,
    depth_outer_window: int = 15,
    min_ring_count: int = 20,
    min_trace_ring_count: int = 4,
    min_depth_ring_count: int = 10,
) -> list[SubterraRecord]:
    """
    LOCAL anomaly z-score for genuine multi-sample GPR trace data (SEG-Y
    sourced, one record per (trace, depth) sample) -- the trace-aware
    counterpart to `preprocess_spatial_grid_anomaly`.

    A single (or few) survey LINE(s) make a poor (lat, lon) "area": at any
    one depth, a handful-to-hundreds of trace positions strung along a
    line bin into a mostly-EMPTY 2D lat/lon raster, starving the ring
    background estimate. Indexed by (trace_index, depth) instead, the same
    data is a fully dense, physically meaningful 2D image (a radargram),
    so this reuses the exact same `_local_anomaly_grid` ring statistic --
    only the axes differ, not the anomaly math (no second implementation).

    Trace and depth axes get INDEPENDENT window parameters rather than one
    isotropic window, because they are not remotely comparable in scale on
    real data: on the real C1T_7,5_0001 line, depth spacing is ~0.0146
    m/sample vs. ~0.246 m/trace (~17x). Reusing one square window sized for
    a (lat, lon) area grid made the reliability check meaningless here: the
    joint ring_count is a PRODUCT of both axes' extents, so on this
    72-trace-wide, 482-depth-tall grid the abundant depth axis backfills
    the joint count even when a cell is genuinely starved of TRACE
    neighbors -- verified empirically, no min_ring_count up to 200+ ever
    flagged the true leftmost/rightmost trace columns. min_trace_ring_count
    / min_depth_ring_count check each axis's OWN marginal neighbor count in
    isolation (see `_axis_ring_counts`), so trace-direction edge scarcity
    can no longer be masked by depth-direction abundance. Defaults were
    derived from and verified against the real 482x72 grid shape: with
    (trace_inner=2, trace_outer=6), the trace-axis marginal count plateaus
    to its interior value of 4 by the 4th trace in from either end, so
    min_trace_ring_count=4 flags exactly the 3 outermost traces on each
    side as unreliable; with (depth_inner=5, depth_outer=15), the
    depth-axis marginal count plateaus to 10 by the 7th sample, so
    min_depth_ring_count=10 flags the 7 shallowest/deepest samples.

    Datasets spanning multiple source files (several survey lines in one
    zip) are processed independently per file, since trace_index is only
    unique within one file's acquisition.

    Same convention as `preprocess_spatial_grid_anomaly`: overwrites
    record.signal with the z-score, preserves the pre-this-step value in
    metadata["pre_anomaly_signal"], and flags low-confidence cells (too
    few ring neighbors -- e.g. near a trace/depth edge) via
    metadata["anomaly_reliable"]=False rather than a misleading extreme
    value.
    """
    if not records:
        return records

    by_file = _group_by_source_file(records)
    n_lines_processed = 0

    for file_key, sub_records in by_file.items():
        if any(r.metadata.get("trace_index") is None or r.depth is None for r in sub_records):
            logger.warning(
                f"preprocess_trace_local_anomaly: records for '{file_key or '(no source_file)'}' are "
                f"missing trace_index/depth metadata -- not genuine multi-sample GPR trace data, skipping."
            )
            continue

        grid, trace_ids, depths = _trace_depth_grid(sub_records, field="signal")
        trace_pos = {t: i for i, t in enumerate(trace_ids)}
        depth_pos = {d: i for i, d in enumerate(depths)}

        z_grid, unreliable_grid = _local_anomaly_grid(
            grid,
            inner_window=(depth_inner_window, trace_inner_window),
            outer_window=(depth_outer_window, trace_outer_window),
            min_ring_count=min_ring_count,
            min_row_ring_count=min_depth_ring_count,
            min_col_ring_count=min_trace_ring_count,
        )

        for r in sub_records:
            di = depth_pos[round(r.depth, 6)]
            ti = trace_pos[r.metadata["trace_index"]]
            raw_val = r.signal[0] if r.signal else None
            z_val = z_grid[di, ti]
            is_unreliable = bool(unreliable_grid[di, ti])
            r.metadata["pre_anomaly_signal"] = raw_val
            r.metadata["anomaly_reliable"] = not is_unreliable
            r.metadata["trace_depth_grid_shape"] = [len(depths), len(trace_ids)]
            r.signal = [float(z_val)] if np.isfinite(z_val) else [0.0]

        n_lines_processed += 1

    n_reliable = sum(1 for r in records if r.metadata.get("anomaly_reliable"))
    logger.info(
        f"preprocess_trace_local_anomaly: processed {n_lines_processed} survey line(s), {len(records)} records "
        f"({n_reliable} reliable, trace_window=({trace_inner_window},{trace_outer_window}), "
        f"depth_window=({depth_inner_window},{depth_outer_window}))"
    )
    return records


def build_trace_depth_grid_for_records(
    records: list[SubterraRecord], source_file: str | None = None, field: str = "signal"
) -> dict:
    """
    Read-only counterpart to `build_grid_for_records`, indexed by
    (trace_index, depth) instead of (lat, lon) -- the radargram/B-scan
    view for ONE GPR survey line, dense with no missing cells (unlike
    binning a line-transect's points into a lat/lon area grid). Also
    returns each trace's (lat, lon) so a caller can georeference any
    column of the grid.

    `source_file` selects which survey line when a dataset holds several
    (defaults to whichever has the most records if not given -- callers
    that need to let a user choose explicitly should first inspect the
    returned "available_source_files" list rather than relying on this
    default, since which file is "densest" isn't necessarily the one a
    user wants to inspect).
    """
    if not records:
        raise ValueError("No records provided.")

    by_file = _group_by_source_file(records)
    available_source_files = sorted(by_file.keys())
    if source_file is None:
        source_file = max(by_file, key=lambda k: len(by_file[k]))
    sub_records = by_file.get(source_file)
    if not sub_records:
        raise ValueError(f"No records found for source_file={source_file!r}. Available: {available_source_files}")
    if any(r.metadata.get("trace_index") is None or r.depth is None for r in sub_records):
        raise ValueError("Records are missing trace_index/depth metadata -- not genuine multi-sample GPR trace data.")

    grid, trace_ids, depths = _trace_depth_grid(sub_records, field=field)

    # Every sample of a trace shares one (lat, lon) -- see SEGYConverter /
    # georeference_records_by_trace -- so the first record seen per trace suffices.
    trace_latlon = {}
    trace_kind = {}
    trace_geographic = {}
    trace_along_track = {}
    for r in sub_records:
        t = r.metadata["trace_index"]
        trace_latlon.setdefault(t, (r.latitude, r.longitude))
        # Whether that (lat, lon) is a real geographic position or the legacy
        # placeholder. Consumers computing real-world distances need to know:
        # a haversine between two placeholders returns 0.0 metres, which is a
        # fabricated measurement rather than a missing one.
        kind = getattr(r.position, "kind", None)
        trace_kind.setdefault(t, kind)
        trace_geographic.setdefault(t, has_geographic_coordinates(r))
        # Along-track distance, for acquisitions positioned by odometry.
        trace_along_track.setdefault(
            t, getattr(r.position, "along_track_m", None) if kind == "odometry" else None)

    return {
        "source_file": source_file,
        "available_source_files": available_source_files,
        "grid": grid,
        "trace_indices": trace_ids,
        "depths": depths,
        "trace_lat": [trace_latlon[t][0] for t in trace_ids],
        "trace_lon": [trace_latlon[t][1] for t in trace_ids],
        "trace_position_kind": [trace_kind[t] for t in trace_ids],
        "trace_geographic": [trace_geographic[t] for t in trace_ids],
        "trace_along_track": [trace_along_track[t] for t in trace_ids],
    }


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
        for r in records if has_geographic_coordinates(r)
    ]
    if not rows:
        raise ValueError(
            "No record carries a geographic position, so no (lat, lon) grid can be built. "
            "Use /trace_grid for line data indexed by trace, or supply a CRS at ingest."
        )
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
        for i, r in enumerate(records) if has_geographic_coordinates(r)
    ]
    if not rows:
        logger.warning(
            f"preprocess_spatial_grid: none of the {len(records)} record(s) carry a geographic "
            f"position, so no (lat, lon) raster can be built -- skipping."
        )
        return records
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
