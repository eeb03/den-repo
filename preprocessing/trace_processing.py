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
    Applies the classic GPR processing chain to every multi-sample trace in
    the dataset, in the standard order: background removal (needs all
    traces at once) -> dewow (per trace) -> gain (per trace). Records with
    a single-value signal (depth-slice CSVs, not raw traces) are left
    unchanged -- there's nothing for these operations to act on.
    """
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
