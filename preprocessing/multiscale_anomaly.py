"""
Multi-scale ring anomaly estimator -- CANDIDATE, not the baseline.

Tests one hypothesis and nothing else:

    Does evaluating the SAME ring statistic at several spatial scales reduce
    the fixed-scale self-referencing failure measured in the baseline?

WHAT THE BASELINE DOES WRONG (measured, see docs/detector-multiscale-experiment.md).
`_local_anomaly_grid` estimates a cell's background from an annulus whose
lateral reach is 1-3 traces. Once a target is wider than the outer trace
window, the annulus lies INSIDE the target, so the background estimate becomes
the target's own amplitude and the numerator collapses. Measured on a noiseless
top-hat, z falls 3.87 -> 0.775 as width goes 1 -> 6 and then stays at 0.775
for every larger width, against a detection threshold of 3.0. It is also
amplitude-invariant there: z = 0.774597 at amplitude 0.1 and at 1000, so
contrast cannot rescue it.

WHAT THIS CHANGES: the spatial scale, and ONLY the spatial scale.

  * The statistic is the baseline's, called unmodified.
  * The preprocessing is the baseline's, in the same order.
  * **The baseline ring's lateral asymmetry is INTENTIONALLY PRESERVED.** The
    even-sized trace windows make the annulus off-centre (a bright column's
    neighbours score -0.378 on one side and -0.258 on the other). Fixing that
    here would introduce a second variable and make attribution impossible.
    A symmetric-ring candidate is a separate experiment.

WHAT IT COSTS, measured rather than assumed. On pure Gaussian noise the two
estimators fire at almost the same rate (fraction of |z| > 3: 0.0039 baseline
vs 0.0045 candidate). On REAL radargrams they do not: 0.0031 vs 0.0108 on the
BAM control (3.5x) and 0.0006 vs 0.0090 on a 4TU line (17x), because real data
carries structure at many scales and a max-over-scales statistic responds to
whichever scale that structure fits.

So the candidate CANNOT be compared with the baseline at the same threshold; it
must be calibrated on control ground first. NOTE that this firing difference is
a property of the estimator, not a nuisance to be corrected away -- it is why
calibration drives the threshold from 3.0 to 6.8, and why that threshold does
not transfer between corpora. No SNR improvement is claimed anywhere; see
docs/detector-multiscale-experiment.md section 0.1.
"""
from __future__ import annotations

import numpy as np

from preprocessing.spatial_grid import _local_anomaly_grid
from preprocessing.trace_processing import apply_gain, background_removal, dewow


def _reliability(inner: tuple[int, int], outer: tuple[int, int]) -> dict:
    """
    The baseline's own reliability convention, expressed generally.

    At the baseline's windows this REPRODUCES its hard-coded numbers exactly,
    which is why it is used rather than a fresh set of constants:

        row marginal  = outer_row - inner_row = 15 - 5 = 10  == min_row_ring_count
        col marginal  = outer_col - inner_col =  6 - 2 =  4  == min_col_ring_count
        joint interior= 15*6 - 5*2            = 80
        25% of joint  = 20                                   == min_ring_count

    So each scale flags edge-starved cells in proportion to its own support,
    exactly as the baseline does for its own.
    """
    row = outer[0] - inner[0]
    col = outer[1] - inner[1]
    joint = outer[0] * outer[1] - inner[0] * inner[1]
    return {
        "min_ring_count": int(round(joint * 0.25)),
        "min_row_ring_count": row,
        "min_col_ring_count": col,
    }


def _scale(inner: tuple[int, int], outer: tuple[int, int]) -> dict:
    return {"inner_window": inner, "outer_window": outer, **_reliability(inner, outer)}


#: PREDEFINED octave ladder, anchored on the measured baseline geometry.
#:
#: Phase 1 measured saturation onset exactly at the outer TRACE window, so that
#: window is the widest target a scale can still see. Octaves from the baseline
#: give lateral supports 6 / 12 / 24 / 48 traces. Parity is preserved on both
#: axes so every scale centres its ring the same way the baseline does.
#:
#: These were fixed BEFORE any benchmark was run and must not be changed after
#: seeing BAM or 4TU results. The candidate is the max-over-ALL-scales
#: estimator, not whichever scale performs best.
SCALES: tuple[dict, ...] = (
    _scale((5, 2), (15, 6)),        # S0 -- identical to the baseline
    _scale((11, 4), (31, 12)),      # S1 -- 12-trace lateral support
    _scale((21, 8), (61, 24)),      # S2 -- 24-trace lateral support
    _scale((41, 16), (121, 48)),    # S3 -- 48-trace lateral support
)

SCALE_LABELS = ("S0", "S1", "S2", "S3")


def preprocess_traces(traces_2d) -> np.ndarray:
    """
    Background removal -> dewow -> gain, then transposed to (depth, trace).

    The same three functions in the same order that
    `preprocessing.spatial_grid.anomaly_grid_from_traces` applies. Equivalence
    is not assumed: a test asserts that this module, restricted to S0, returns
    a grid bit-identical to the baseline's.
    """
    traces = np.asarray(traces_2d, dtype=float)
    traces = np.asarray(background_removal(traces.tolist()), dtype=float)
    processed = np.array(
        [apply_gain(dewow(t.tolist(), window=15), gain_type="linear", power=1.0)
         for t in traces],
        dtype=float,
    )
    return processed.T


def multiscale_anomaly_grid(traces_2d, scales: tuple[dict, ...] = SCALES) -> np.ndarray:
    """
    Per-cell maximum |z| across scales, as a signed z-grid.

    Combination rule, stated because it drives everything downstream:

      * a cell takes the value of the scale where |z| is largest, keeping that
        scale's SIGN, so a bright and a dark anomaly stay distinguishable;
      * scales at which the cell is unreliable are excluded from the maximum,
        not counted as zero -- treating a starved ring as "no anomaly" would
        quietly convert missing information into evidence of absence;
      * a cell is NaN only when EVERY scale is unreliable. Small scales starve
        less at edges than large ones, so multi-scale coverage is a superset of
        the baseline's, never a subset.

    Returns (n_samples, n_traces), matching the baseline's orientation.
    """
    grid = preprocess_traces(traces_2d)
    return combine_scales(grid, scales)


def combine_scales(grid: np.ndarray, scales: tuple[dict, ...] = SCALES) -> np.ndarray:
    """Max-|z| combination on an ALREADY preprocessed (depth, trace) grid."""
    best = np.full(grid.shape, np.nan)
    best_abs = np.full(grid.shape, -np.inf)

    for spec in scales:
        z, unreliable = _local_anomaly_grid(grid, **spec)
        usable = np.isfinite(z) & ~unreliable
        magnitude = np.where(usable, np.abs(z), -np.inf)
        take = magnitude > best_abs
        best_abs = np.where(take, magnitude, best_abs)
        best = np.where(take, z, best)

    return best


def per_scale_grids(traces_2d, scales: tuple[dict, ...] = SCALES) -> dict[str, np.ndarray]:
    """
    Each scale's z-grid separately -- diagnostics only.

    Provided so the experiment can SHOW which scale carries a response, without
    ever selecting a scale by benchmark outcome. The candidate under test is
    always the full max-over-scales estimator.
    """
    grid = preprocess_traces(traces_2d)
    out = {}
    for label, spec in zip(SCALE_LABELS, scales):
        z, unreliable = _local_anomaly_grid(grid, **spec)
        out[label] = np.where(unreliable, np.nan, z)
    return out


def describe_scales(scales: tuple[dict, ...] = SCALES) -> list[dict]:
    """The ladder as data, for the experiment record."""
    rows = []
    for label, spec in zip(SCALE_LABELS, scales):
        inner, outer = spec["inner_window"], spec["outer_window"]
        rows.append({
            "scale": label,
            "inner_depth": inner[0], "inner_trace": inner[1],
            "outer_depth": outer[0], "outer_trace": outer[1],
            "lateral_support_traces": outer[1],
            "depth_support_samples": outer[0],
            "min_ring_count": spec["min_ring_count"],
            "min_row_ring_count": spec["min_row_ring_count"],
            "min_col_ring_count": spec["min_col_ring_count"],
        })
    return rows
