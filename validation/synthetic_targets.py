"""
Controlled synthetic-target sensitivity analysis for the GPR anomaly detector.

Injects a target of KNOWN lateral width and amplitude into a background,
pushes it through the EXACT production preprocessing chain, and measures
what survives. Because the target is known, "did the detector find it" has
a definite answer -- which is what makes this a sensitivity measurement
rather than an interpretation.

Target generators are reused from training/synthetic_gpr.py rather than
reimplemented, so the shapes tested here are the same ones the classifier
was built against.

KEY MEASURED RESULT, pinned by tests/test_validation_harness.py:
peak |z| SATURATES with target amplitude once a target is wider than the
ring statistic's trace-direction exclusion zone. A target 5 traces wide
scores the same |z| at 1000x amplitude as at 3x, because it contaminates
its own background estimate. This is a property of the estimator's
geometry, not of the data.

This module MEASURES the detector. It does not tune it: every production
parameter below is imported or mirrored, never chosen here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from preprocessing.spatial_grid import _local_anomaly_grid
from preprocessing.trace_processing import apply_gain, background_removal, dewow
from training.synthetic_gpr import _hyperbola_patch, _planar_patch

# Mirrors preprocessing/pipeline.py::run_pipeline defaults verbatim. These are
# the values the production detector runs with; validation must not diverge
# from them, so a drift here should be treated as a bug in this file.
DEWOW_WINDOW = 15
GAIN_TYPE, GAIN_POWER = "linear", 1.0
TRACE_INNER, TRACE_OUTER = 2, 6
DEPTH_INNER, DEPTH_OUTER = 5, 15
MIN_RING_COUNT, MIN_TRACE_RING, MIN_DEPTH_RING = 20, 4, 10

STAGE_ORDER = ("raw", "background_removed", "dewowed", "gained")


def processed_stages(traces: np.ndarray) -> dict[str, np.ndarray]:
    """
    Runs the production chain and returns EVERY intermediate stage.

    `traces` is (n_traces, n_samples). Order matches process_gpr_traces
    exactly: background removal across all traces, then dewow and gain per
    trace.
    """
    arr = np.asarray(traces, dtype=float)
    out = {"raw": arr.copy()}
    out["background_removed"] = np.asarray(background_removal(arr.tolist()), dtype=float)
    out["dewowed"] = np.asarray(
        [dewow(list(t), window=DEWOW_WINDOW) for t in out["background_removed"]], dtype=float
    )
    out["gained"] = np.asarray(
        [apply_gain(list(t), gain_type=GAIN_TYPE, power=GAIN_POWER) for t in out["dewowed"]],
        dtype=float,
    )
    return out


def anomaly_grid(processed: np.ndarray) -> np.ndarray:
    """
    Ring z-score of a processed (n_traces, n_samples) array, returned in the
    production (n_depths, n_traces) orientation with unreliable cells set to
    0.0 -- exactly the array find_anomaly_candidates consumes.
    """
    z, _unreliable = _local_anomaly_grid(
        np.asarray(processed, dtype=float).T,
        inner_window=(DEPTH_INNER, TRACE_INNER),
        outer_window=(DEPTH_OUTER, TRACE_OUTER),
        min_ring_count=MIN_RING_COUNT,
        min_row_ring_count=MIN_DEPTH_RING,
        min_col_ring_count=MIN_TRACE_RING,
    )
    return np.where(np.isfinite(z), z, 0.0)


def make_target(
    kind: str, n_traces: int, n_samples: int, width: int, depth_index: int,
    amplitude: float, rng: np.random.Generator, pulse_width: float = 2.5,
    curvature: float = 0.15,
) -> tuple[np.ndarray, tuple[int, int]]:
    """
    A target-only field of exactly `width` traces, centred laterally.

    kind="reflector" -> laterally continuous flat reflector (_planar_patch)
    kind="hyperbola" -> localized diffraction (_hyperbola_patch)

    Returns (field, (first_trace, last_trace_exclusive)).
    """
    field_arr = np.zeros((n_traces, n_samples))
    w = min(int(width), n_traces)
    start = (n_traces - w) // 2
    if kind == "reflector":
        patch = _planar_patch(w, n_samples, reflector_time=float(depth_index),
                              amplitude=amplitude, polarity=1.0, width=pulse_width, rng=rng)
    elif kind == "hyperbola":
        patch = _hyperbola_patch(w, n_samples, apex_time=float(depth_index),
                                 curvature=curvature, amplitude=amplitude,
                                 polarity=1.0, width=pulse_width, rng=rng)
    else:
        raise ValueError(f"Unknown target kind {kind!r}; use 'reflector' or 'hyperbola'")
    field_arr[start:start + w, :] = patch
    return field_arr, (start, start + w)


@dataclass
class DetectabilityResult:
    """What a single injected target produced. Measurements only."""
    kind: str
    width: int
    depth_index: int
    amplitude_sigma: float
    support_cells: int
    peak_abs_z: float
    peak_abs_z_background_only: float
    cells_over_threshold: dict[float, int] = field(default_factory=dict)
    attenuation_by_stage: dict[str, float] = field(default_factory=dict)

    def detected_at(self, threshold: float) -> bool:
        """Whether ANY cell of the known target reaches the threshold."""
        return self.peak_abs_z > threshold


def measure_detectability(
    background: np.ndarray, kind: str, width: int, depth_index: int,
    amplitude_sigma: float, rng: np.random.Generator,
    thresholds: tuple[float, ...] = (2.0, 2.5, 3.0, 3.5, 4.0),
    support_fraction: float = 0.25,
) -> DetectabilityResult:
    """
    Injects one target into `background` (n_traces, n_samples) and measures
    how much of it survives to the anomaly grid.

    `amplitude_sigma` is in units of the background's own standard
    deviation, so results are comparable across backgrounds.

    The three pre-z stages are linear, so a target's response through them
    is measured exactly by running the chain on the target alone.
    """
    bg = np.asarray(background, dtype=float)
    n_traces, n_samples = bg.shape
    sigma = float(bg.std())

    target, _span = make_target(kind, n_traces, n_samples, width, depth_index,
                                amplitude_sigma * sigma, rng)
    peak_raw = float(np.abs(target).max())
    support = np.abs(target) >= support_fraction * peak_raw

    target_stages = processed_stages(target)
    attenuation = {
        stage: float(np.abs(target_stages[stage][support]).max()) / peak_raw
        for stage in STAGE_ORDER
    }

    bg_stages = processed_stages(bg)
    z_with = anomaly_grid(bg_stages["gained"] + target_stages["gained"])
    z_without = anomaly_grid(bg_stages["gained"])

    support_dt = support.T  # (n_depths, n_traces)
    abs_with = np.abs(z_with)[support_dt]
    abs_without = np.abs(z_without)[support_dt]

    return DetectabilityResult(
        kind=kind, width=int(width), depth_index=int(depth_index),
        amplitude_sigma=float(amplitude_sigma),
        support_cells=int(support.sum()),
        peak_abs_z=float(abs_with.max()) if abs_with.size else 0.0,
        peak_abs_z_background_only=float(abs_without.max()) if abs_without.size else 0.0,
        cells_over_threshold={t: int((abs_with >= t).sum()) for t in thresholds},
        attenuation_by_stage=attenuation,
    )


def amplitude_saturation_curve(
    background: np.ndarray, kind: str, width: int, depth_index: int,
    amplitudes: tuple[float, ...], rng: np.random.Generator,
) -> dict[float, float]:
    """
    Peak |z| as a function of target amplitude, at fixed width.

    A detector whose score grows with target strength produces an increasing
    curve. A FLAT curve means the statistic has saturated: the target is
    setting its own background scale, so no amount of additional signal can
    raise its score. Returns {amplitude_sigma: peak_abs_z}.
    """
    return {
        a: measure_detectability(background, kind, width, depth_index, a, rng).peak_abs_z
        for a in amplitudes
    }
