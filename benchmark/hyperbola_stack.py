"""
CANDIDATE detector: a diffraction-hyperbola stack. EXPERIMENTAL; no
production path imports it. It exists to be compared against the ring
z-score (`preprocessing.spatial_grid.anomaly_grid_from_traces`) under the
pre-registration in docs/detector-saturation-experiment.md, and replaces
nothing.

WHY. The ring z-score compares each cell with an annulus a few traces and
samples away. A buried pipe, cable, rock or void does not look like a blob
in a B-scan; it looks like a hyperbola as wide as the scan, so the annulus
sits on the target's own limbs and the score saturates (|z| <= 2.7 on every
simulated target in PR #11; measured on real lines 2026-08-06). A detector
that asks "does energy line up along a diffraction hyperbola with its apex
here?" uses the limbs as evidence instead.

DETECTION (this module) is separate from LOCALISATION (the peak cell of a
detection: lateral position, apex time, and v_hat, from which depth follows)
and from CLASSIFICATION (not attempted).

THE STATISTIC, for one line already through a background step:

1. The production filters, unchanged: dewow(15) -> linear gain, then the
   Hilbert envelope per trace (so polarity and phase do not matter). With a
   time tolerance delta > 0 the envelope is replaced by its running maximum
   over +/- delta, so a hyperbola that is not exactly the model curve
   (finite radius, antenna offset, interference) still stacks.
2. For every candidate apex (trace i0, time t0) and every velocity v in
   VELOCITY_GRID, the zero-offset point-diffractor curve
       t_i = tz + sqrt((t0 - tz)^2 + (2 (x_i - x_i0) / v)^2)
   over the traces inside a cone of half-angle theta,
       |x_i - x_i0| <= tan(theta) * v (t0 - tz) / 2,
   never narrower than +/- MIN_HALF_APERTURE traces. tz is time zero,
   ESTIMATED FROM THE DATA (estimate_time_zero), never taken from a model.
   S_hyp = mean (tolerant) envelope along the curve, linearly interpolated;
   S_flat = mean along the flat line t = t0 over the same traces.
   A flat event (direct wave, layer, back wall) gives S_hyp = S_flat; a
   diffraction gives S_hyp > S_flat. Contrast C_v = S_hyp - S_flat.
3. C = max over v of C_v; v_hat is the velocity achieving it.
4. z = (C - median C) / (1.4826 MAD C) over cells whose aperture holds at
   least MIN_TRACES traces and whose apex lies after time zero; negative z
   is set to 0 (one-sided: only "more hyperbolic than flat" is evidence);
   other cells are NaN, as the ring marks unreliable cells. MAD = 0 gives
   all zeros.

The z-grid goes through `benchmark.detection.detect_line` -- the SAME
threshold, 4-connected labelling and min_cells rule the ring uses.

INPUTS AT INFERENCE: traces, trace positions, sample interval, time offset,
the antenna's nominal frequency (only for delta), and the data-derived time
zero. Nothing else -- no soil velocity, no target, no model twin.

KNOWN LIMITS, stated before any result: point diffractor (large-radius
targets are flatter at the apex); zero offset (bends shallow curves);
VELOCITY_GRID = eps_r 3-25, the synthetic generator's own range, which
flatters this detector on the corpus.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import maximum_filter1d
from scipy.signal import hilbert

from preprocessing.trace_processing import apply_gain, dewow

C0 = 299_792_458.0
#: eps_r 3..25, geometric: 9 velocities from c/5 to c/sqrt(3).
VELOCITY_GRID = tuple(float(C0 / np.sqrt(e)) for e in np.geomspace(3.0, 25.0, 9))
MIN_HALF_APERTURE = 2
MIN_TRACES = 3
DEFAULT_CONE_DEG = 45.0


def envelope(traces: np.ndarray) -> np.ndarray:
    filtered = np.array(
        [apply_gain(dewow(t.tolist(), window=15), gain_type="linear", power=1.0) for t in traces],
        dtype=float,
    )
    return np.abs(hilbert(filtered, axis=1))


def estimate_time_zero(raw_traces: np.ndarray, dt_s: float, time_offset_s: float) -> float:
    """Time of the envelope peak of the median RAW trace (the direct wave),
    searched in the first half of the window. Data only. Must be given the
    line BEFORE any background step, which would remove the direct wave."""
    med = np.median(np.asarray(raw_traces, dtype=float), axis=0)
    env = np.abs(hilbert(med))
    half = max(2, env.size // 2)
    return time_offset_s + int(np.argmax(env[:half])) * dt_s


def hyperbola_stack(traces: np.ndarray, x_m: np.ndarray, dt_s: float, time_offset_s: float,
                    time_zero_s: float, f_nominal_hz: float | None = None,
                    cone_half_angle_deg: float = DEFAULT_CONE_DEG, tolerance_periods: float = 0.0,
                    velocities=VELOCITY_GRID) -> tuple[np.ndarray, np.ndarray]:
    """Returns (z, v_hat), both (n_samples, n_traces) -- the orientation of
    `anomaly_grid_from_traces`, so `detect_line` takes z as an estimator."""
    env = envelope(np.asarray(traces, dtype=float))          # (n_traces, n_samples)
    if tolerance_periods > 0:
        if not f_nominal_hz:
            raise ValueError("a time tolerance needs the antenna's nominal frequency")
        half_w = int(round(tolerance_periods / f_nominal_hz / dt_s))
        if half_w > 0:
            env = maximum_filter1d(env, size=2 * half_w + 1, axis=1, mode="nearest")
    n_tr, n_s = env.shape
    x = np.asarray(x_m, dtype=float)
    t0 = time_offset_s + np.arange(n_s) * dt_s
    tau0 = np.maximum(t0 - time_zero_s, 0.0)                  # (n_s,)
    step = float(np.median(np.abs(np.diff(x)))) if n_tr > 1 else 1.0
    tan_t = math.tan(math.radians(cone_half_angle_deg))
    env_t = env.T                                             # (n_s, n_tr)

    best = np.full((n_s, n_tr), -np.inf)
    v_hat = np.full((n_s, n_tr), np.nan)
    valid_any = np.zeros((n_s, n_tr), dtype=bool)
    after_t0 = (tau0 > 0)[:, None]
    for v in velocities:
        half_ap = np.maximum(tan_t * v * tau0 / 2, MIN_HALF_APERTURE * step * (1 + 1e-9))  # (n_s,)
        k_max = min(n_tr - 1, int(np.ceil(half_ap.max() / step)) + 1)
        s_hyp = np.zeros((n_s, n_tr))
        s_flat = np.zeros((n_s, n_tr))
        count = np.zeros((n_s, n_tr))
        for k in range(-k_max, k_max + 1):
            lo, hi = max(0, -k), min(n_tr, n_tr - k)          # apex traces i0 with i0 + k in range
            if lo >= hi:
                continue
            i0 = np.arange(lo, hi)
            dx = np.abs(x[i0 + k] - x[i0])                    # (m,)
            inside = dx[None, :] <= half_ap[:, None]          # (n_s, m)
            tau = np.sqrt(tau0[:, None] ** 2 + (2 * dx[None, :] / v) ** 2)
            s = (tau + time_zero_s - time_offset_s) / dt_s
            use = inside & (s <= n_s - 1)
            s0 = np.clip(np.floor(s).astype(int), 0, n_s - 2)
            frac = np.clip(s - s0, 0.0, 1.0)
            col = env_t[:, i0 + k]                            # (n_s, m), the neighbour trace
            val = (np.take_along_axis(col, s0, axis=0) * (1 - frac)
                   + np.take_along_axis(col, s0 + 1, axis=0) * frac)
            s_hyp[:, lo:hi] += np.where(use, val, 0.0)
            s_flat[:, lo:hi] += np.where(use, col, 0.0)
            count[:, lo:hi] += use
        with np.errstate(invalid="ignore", divide="ignore"):
            c = (s_hyp - s_flat) / count
        ok = (count >= MIN_TRACES) & after_t0
        valid_any |= ok
        better = ok & (c > best)
        best = np.where(better, c, best)
        v_hat = np.where(better, v, v_hat)

    z = np.full((n_s, n_tr), np.nan)
    vals = best[valid_any]
    if vals.size:
        med = np.median(vals)
        mad = 1.4826 * np.median(np.abs(vals - med))
        z[valid_any] = 0.0 if mad == 0 else np.maximum((vals - med) / mad, 0.0)
    return z, v_hat
