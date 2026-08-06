"""
Classic GPR trace processing: dewow, background removal, time-varying gain.

These operate on MULTI-SAMPLE traces (each record's `signal` list holding
many samples along the time/depth axis, e.g. a SEG-Y trace) — not on the
single-value-per-point depth-slice CSVs that spatial_grid.py handles.
Applying dewow/gain to a length-1 signal is a no-op by construction; these
techniques only mean something on genuine raw radargram traces.

All three are verified against synthetic ground truth before being wired
into the pipeline: dewow removes slow drift while preserving faster real
signal (window size trades off how much drift vs. signal survives —
that's a genuine tunable, not a bug); background removal eliminates
banding common to every trace (antenna ringing) while preserving
localized real anomalies; gain compensates depth-attenuation so deeper
reflections don't look artificially weak.
"""
from __future__ import annotations

import numpy as np

from schemas.subterra_record import SubterraRecord
from utils.logger import get_logger

logger = get_logger(__name__)


def dewow(trace: list[float], window: int = 15) -> list[float]:
    """Moving-average high-pass filter: removes slow drift/DC wander, preserves faster signal content."""
    arr = np.array(trace, dtype=float)
    if len(arr) < window:
        return trace
    kernel = np.ones(window) / window
    trend = np.convolve(arr, kernel, mode="same")
    return (arr - trend).tolist()


def apply_gain(trace: list[float], gain_type: str = "linear", power: float = 1.0) -> list[float]:
    """Amplifies later samples more than earlier ones to compensate depth/time attenuation."""
    arr = np.array(trace, dtype=float)
    n = len(arr)
    if n <= 1:
        return trace
    t = np.arange(n) / (n - 1)
    if gain_type == "linear":
        curve = 1 + t * power
    elif gain_type == "exponential":
        curve = np.exp(t * power)
    else:
        raise ValueError(f"Unknown gain_type '{gain_type}'. Use 'linear' or 'exponential'.")
    return (arr * curve).tolist()


def background_removal(traces_2d: list[list[float]]) -> list[list[float]]:
    """
    Subtracts the mean trace across ALL traces in the survey — removes
    banding that appears identically in every trace (antenna coupling,
    ringing), while a real localized anomaly (present in only some traces)
    survives.
    """
    arr = np.array(traces_2d, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 2:
        return traces_2d
    mean_trace = arr.mean(axis=0)
    return (arr - mean_trace).tolist()


def _reconstruct_traces_by_index(records: list[SubterraRecord]) -> dict | None:
    """
    Groups per-SAMPLE GPR records (one record per (trace, depth) sample --
    the shape SEGYConverter emits, so depth-slice/local-anomaly tooling has
    a real per-sample depth) back into full per-trace sample sequences,
    ordered by depth. Returns None if `records` aren't in this shape
    (missing trace_index/depth metadata, or already multi-sample-per-
    record), so the caller falls back to the original single-record-per-
    trace path unchanged.

    Keyed by (source_file, trace_index), NOT trace_index alone: SEGYConverter
    numbers traces 0..N-1 independently PER FILE, so a dataset combining
    multiple SEG-Y lines (e.g. via ingest_zip_from_url) will have colliding
    trace_index values across files. Grouping by trace_index alone would
    silently interleave unrelated survey lines' samples into one fake
    "trace" -- confirmed by direct reproduction, not hypothetical.
    """
    if not records:
        return None
    if any(len(r.signal) != 1 for r in records):
        return None  # not the one-sample-per-record shape
    if any(r.metadata.get("trace_index") is None or r.depth is None for r in records):
        return None  # no trace/depth identity to reconstruct traces from

    by_trace: dict = {}
    for r in records:
        key = (r.metadata.get("source_file", ""), r.metadata["trace_index"])
        by_trace.setdefault(key, []).append(r)
    for recs in by_trace.values():
        recs.sort(key=lambda r: r.depth)
    return by_trace


def process_gpr_traces(
    records: list[SubterraRecord],
    dewow_enabled: bool = True,
    dewow_window: int = 15,
    background_removal_enabled: bool = True,
    gain_enabled: bool = True,
    gain_type: str = "linear",
    gain_power: float = 1.0,
) -> list[SubterraRecord]:
    """
    Applies the classic GPR processing chain -- background removal (needs
    all traces at once) -> dewow (per trace) -> gain (per trace) -- in the
    standard order. Records with a single-value signal and no trace
    identity (depth-slice CSVs, not raw traces) are left unchanged --
    there's nothing for these operations to act on.

    Handles two input shapes:
    1. One record per full trace (`signal` is the whole multi-sample
       waveform) -- the shape this module was originally written for.
    2. One record per (trace, depth) SAMPLE, each holding a length-1
       signal, identified via metadata["trace_index"] + real `depth` --
       what SEGYConverter emits so depth-slice/local-anomaly tooling has a
       genuine per-sample depth. Real traces are reconstructed by
       grouping + depth-sorting case 2 before the same dewow/background/
       gain math runs, then results are scattered back onto the original
       per-sample records -- the actual signal-processing math is
       identical either way.
    """
    by_trace = _reconstruct_traces_by_index(records)

    if by_trace is not None:
        # Group reconstructed traces by source_file so background_removal's
        # "mean trace across the survey" is computed within ONE acquisition
        # only -- averaging traces from unrelated SEG-Y lines together would
        # be as wrong as merging them in the first place.
        keys_by_file: dict = {}
        for key in by_trace:
            source_file, _trace_idx = key
            keys_by_file.setdefault(source_file, []).append(key)

        processing_applied = {
            "dewow": dewow_enabled, "dewow_window": dewow_window if dewow_enabled else None,
            "background_removal": background_removal_enabled,
            "gain": gain_enabled, "gain_type": gain_type if gain_enabled else None, "gain_power": gain_power if gain_enabled else None,
        }

        for source_file, keys in keys_by_file.items():
            trace_arrays = [[r.signal[0] for r in by_trace[k]] for k in keys]

            if background_removal_enabled:
                max_len = max(len(t) for t in trace_arrays)
                uniform = all(len(t) == max_len for t in trace_arrays)
                if uniform:
                    trace_arrays = background_removal(trace_arrays)
                else:
                    logger.warning(
                        f"process_gpr_traces: reconstructed traces for '{source_file or '(no source_file)'}' "
                        f"have inconsistent sample counts -- skipping background removal for this line."
                    )

            for key, trace in zip(keys, trace_arrays):
                if dewow_enabled:
                    trace = dewow(trace, window=dewow_window)
                if gain_enabled:
                    trace = apply_gain(trace, gain_type=gain_type, power=gain_power)
                for r, val in zip(by_trace[key], trace):
                    r.signal = [float(val)]
                    r.metadata["processing_applied"] = processing_applied

        logger.info(
            f"process_gpr_traces: reconstructed and processed {len(by_trace)} trace(s) across "
            f"{len(keys_by_file)} source file(s) from {len(records)} per-sample records"
        )
        return records

    # --- original shape: one record per full multi-sample trace ---
    trace_records = [r for r in records if len(r.signal) > 1]
    if not trace_records:
        logger.warning(
            "process_gpr_traces: no multi-sample traces found (dataset is single-value-per-point "
            "depth-slice data, not raw traces) -- nothing to process."
        )
        return records

    if background_removal_enabled:
        max_len = max(len(r.signal) for r in trace_records)
        uniform = all(len(r.signal) == max_len for r in trace_records)
        if uniform:
            traces_2d = [r.signal for r in trace_records]
            cleaned = background_removal(traces_2d)
            for r, c in zip(trace_records, cleaned):
                r.signal = c
        else:
            logger.warning("process_gpr_traces: traces have inconsistent lengths -- skipping background removal.")

    for r in trace_records:
        if dewow_enabled:
            r.signal = dewow(r.signal, window=dewow_window)
        if gain_enabled:
            r.signal = apply_gain(r.signal, gain_type=gain_type, power=gain_power)
        r.metadata["processing_applied"] = {
            "dewow": dewow_enabled, "dewow_window": dewow_window if dewow_enabled else None,
            "background_removal": background_removal_enabled,
            "gain": gain_enabled, "gain_type": gain_type if gain_enabled else None, "gain_power": gain_power if gain_enabled else None,
        }

    logger.info(f"process_gpr_traces: processed {len(trace_records)}/{len(records)} multi-sample traces")
    return records
