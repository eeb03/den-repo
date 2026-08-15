"""
AI preprocessing pipeline applied to Universal Subterra Records before
they're used for training or fusion: noise reduction, normalization,
outlier removal, and depth/coordinate interpolation for gaps.
"""
import numpy as np

from schemas.subterra_record import SubterraRecord
from utils.logger import get_logger

logger = get_logger(__name__)


def denoise_signal(signal: list[float], window: int = 5) -> list[float]:
    """Simple moving-average denoise. Swap in scipy.signal.wiener/savgol for production use."""
    if len(signal) < window:
        return signal
    arr = np.array(signal, dtype=float)
    kernel = np.ones(window) / window
    smoothed = np.convolve(arr, kernel, mode="same")
    return smoothed.tolist()


def normalize_signal(signal: list[float]) -> list[float]:
    """Z-score normalize; falls back to unchanged signal if zero variance."""
    if not signal:
        return signal
    arr = np.array(signal, dtype=float)
    std = arr.std()
    if std == 0:
        return signal
    return ((arr - arr.mean()) / std).tolist()


def remove_outliers(signal: list[float], z_thresh: float = 4.0) -> list[float]:
    """Clip values beyond z_thresh standard deviations."""
    if len(signal) < 3:
        return signal
    arr = np.array(signal, dtype=float)
    mean, std = arr.mean(), arr.std()
    if std == 0:
        return signal
    clipped = np.clip(arr, mean - z_thresh * std, mean + z_thresh * std)
    return clipped.tolist()


def interpolate_missing_depth(records: list[SubterraRecord]) -> list[SubterraRecord]:
    """Linearly interpolate missing `depth` values along the record sequence."""
    depths = [r.depth for r in records]
    indices = np.arange(len(depths))
    known = [i for i, d in enumerate(depths) if d is not None]

    if len(known) < 2:
        return records  # not enough anchor points to interpolate

    known_vals = [depths[i] for i in known]
    interpolated = np.interp(indices, known, known_vals)

    for r, val in zip(records, interpolated):
        if r.depth is None:
            r.depth = float(val)
    return records


def run_pipeline(
    records: list[SubterraRecord],
    denoise: bool = True,
    normalize: bool = True,
    remove_outliers_flag: bool = True,
    interpolate_depth: bool = True,
    mode: str = "trace",
    smoothing_window: int = 3,
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
) -> list[SubterraRecord]:
    """
    Apply the standard preprocessing chain.

    mode="trace" (default): treats each record's `signal` list as a
    multi-sample waveform (e.g. a SEG-Y trace) and denoises/normalizes
    within that record. A no-op for single-value records.

    mode="spatial_grid": for datasets where each record carries ONE scalar
    reading at a (lat, lon, depth) point — GPR depth slices, magnetometer/
    gravity surveys — delegates to preprocessing/spatial_grid.py, which
    reshapes the dataset into a lat x lon raster (grouped by depth) and
    smooths/normalizes across real spatial neighbors instead.

    mode="local_anomaly": like spatial_grid, but instead of a global
    z-score, computes each point's deviation from its own LOCAL background
    (a ring between inner_window and outer_window around it). This is what
    surfaces a spatially small real target that a whole-dataset z-score
    would dilute into noise. Bins by (lat, lon) per depth layer -- meant
    for area-covering depth-slice surveys.

    mode="gpr_local_anomaly": the same ring-based local anomaly statistic
    as "local_anomaly", but indexed by (trace_index, depth) instead of
    (lat, lon) -- for genuine multi-sample GPR trace data (SEG-Y sourced).
    A single survey line's points bin into a mostly-empty lat/lon area
    grid; indexed by their native trace position they form a dense
    radargram image instead. Uses its OWN independent trace-axis/depth-axis
    window parameters (trace_inner_window, trace_outer_window,
    depth_inner_window, depth_outer_window, min_trace_ring_count,
    min_depth_ring_count) rather than the (lat, lon)-grid's inner_window/
    outer_window/min_ring_count, because trace and depth spacing are not
    remotely comparable in scale on real data (e.g. ~0.246 m/trace vs.
    ~0.0146 m/sample on the real C1T_7,5_0001 line) -- see
    preprocessing/spatial_grid.py::preprocess_trace_local_anomaly for the
    full reasoning and how the defaults were derived.

    mode="gpr_full": the validated GPR chain -- "gpr_trace_processing" followed
    by "gpr_local_anomaly", which is the pairing the regression baseline pins
    and the composition both benchmarks measure. Use this for a GPR ingest;
    the two single-step modes remain available for callers that compose them
    themselves.
    """
    if mode == "spatial_grid":
        from preprocessing.spatial_grid import preprocess_spatial_grid
        return preprocess_spatial_grid(
            records, denoise=denoise, normalize=normalize,
            remove_outliers=remove_outliers_flag, smoothing_window=smoothing_window,
        )

    if mode == "local_anomaly":
        from preprocessing.spatial_grid import preprocess_spatial_grid_anomaly
        return preprocess_spatial_grid_anomaly(
            records, inner_window=inner_window, outer_window=outer_window, min_ring_count=min_ring_count,
        )

    if mode == "gpr_local_anomaly":
        from preprocessing.spatial_grid import preprocess_trace_local_anomaly
        return preprocess_trace_local_anomaly(
            records,
            trace_inner_window=trace_inner_window, trace_outer_window=trace_outer_window,
            depth_inner_window=depth_inner_window, depth_outer_window=depth_outer_window,
            min_ring_count=min_ring_count,
            min_trace_ring_count=min_trace_ring_count, min_depth_ring_count=min_depth_ring_count,
        )

    if mode == "gpr_trace_processing":
        from preprocessing.trace_processing import process_gpr_traces
        return process_gpr_traces(
            records,
            dewow_enabled=dewow_enabled, dewow_window=dewow_window,
            background_removal_enabled=background_removal_enabled,
            gain_enabled=gain_enabled, gain_type=gain_type, gain_power=gain_power,
        )

    if mode == "gpr_full":
        # THE VALIDATED GPR CHAIN, IN ONE CALL.
        #
        # The two modes above are single steps, and composing them is the
        # caller's job -- `tests/test_gpr_regression_baseline.py` has pinned
        # exactly this pairing since the interpretation baseline. But every
        # ingest route applies ONE mode (`run_pipeline(records,
        # mode=preprocessing_mode)`), so the validated chain was unreachable
        # through the API: ingesting with "gpr_local_anomaly" ran the ring
        # statistic on unfiltered traces.
        #
        # That is not what any benchmark measures. `anomaly_grid_from_traces`
        # (BAM) and `scripts/characterise_4tu.py` (4TU) both filter first, and
        # on a real 4TU line the two compositions disagree about 95.7% of cells
        # -- 39 cells over |z|>3 unfiltered against 164 filtered. So the product
        # was generating candidates from a detector no benchmark had measured.
        #
        # Added as a NEW mode rather than by changing "gpr_local_anomaly",
        # because that mode's filter-free behaviour is correct, is what the
        # regression baseline pins, and is what the composition depends on.
        # See docs/anomaly-path-equivalence.md.
        from preprocessing.spatial_grid import preprocess_trace_local_anomaly
        from preprocessing.trace_processing import process_gpr_traces

        records = process_gpr_traces(
            records,
            dewow_enabled=dewow_enabled, dewow_window=dewow_window,
            background_removal_enabled=background_removal_enabled,
            gain_enabled=gain_enabled, gain_type=gain_type, gain_power=gain_power,
        )
        return preprocess_trace_local_anomaly(
            records,
            trace_inner_window=trace_inner_window, trace_outer_window=trace_outer_window,
            depth_inner_window=depth_inner_window, depth_outer_window=depth_outer_window,
            min_ring_count=min_ring_count,
            min_trace_ring_count=min_trace_ring_count, min_depth_ring_count=min_depth_ring_count,
        )

    for r in records:
        if r.signal:
            if remove_outliers_flag:
                r.signal = remove_outliers(r.signal)
            if denoise:
                r.signal = denoise_signal(r.signal)
            if normalize:
                r.signal = normalize_signal(r.signal)

    if interpolate_depth:
        records = interpolate_missing_depth(records)

    logger.info(f"Preprocessing pipeline (mode={mode}) applied to {len(records)} records")
    return records
