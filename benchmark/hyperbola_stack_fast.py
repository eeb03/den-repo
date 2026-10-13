"""
EXPERIMENTAL. A faster implementation of benchmark.hyperbola_stack.hyperbola_stack:
the SAME statistic (docs/hyperbola-v2-experiment.md §5, gate C3), not a new
detector. No production path imports it.

Profiling the original (cProfile, one BAM dev line, 401 x 512) put ~65% of
the time in per-cell sqrt / masking over an (n_samples, n_apex_traces) array
for every trace offset k and velocity, and ~30% in take_along_axis gathers.
Both are redundant on uniformly spaced traces, where the curve's sample
position depends only on (v, |k|, apex time) -- never on the apex trace:

* one (rows,) template per (v, |k|): sqrt once per row, not per cell;
* the time-shifted envelope G = env[s0] (1 - frac) + env[s0 + 1] frac is a
  ROW gather, shared by +k and -k;
* only rows whose aperture and window admit offset k are touched;
* the flat-line sum and the trace count are prefix-sum differences, O(1)
  per cell instead of O(k).

Non-uniform spacing (> UNIFORM_TOL relative) falls back to the original.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import maximum_filter1d

from benchmark.hyperbola_stack import (
    DEFAULT_CONE_DEG, MIN_HALF_APERTURE, MIN_TRACES, VELOCITY_GRID, envelope, hyperbola_stack,
)

UNIFORM_TOL = 1e-6


def is_uniform(x_m: np.ndarray) -> bool:
    x = np.asarray(x_m, dtype=float)
    if x.size < 2:
        return True
    d = np.diff(x)
    step = float(np.median(np.abs(d)))
    return step > 0 and bool(np.all(np.abs(np.abs(d) - step) <= UNIFORM_TOL * step)) and (
        bool(np.all(d > 0)) or bool(np.all(d < 0)))


def _offsets_within(limit: np.ndarray, step: float, cap: int) -> np.ndarray:
    """Largest integer k >= 0 with k * step <= limit (exact in float), capped;
    -1 where even k = 0 fails."""
    with np.errstate(invalid="ignore"):
        k = np.floor(np.where(limit >= 0, limit, -1.0) / step).astype(np.int64)
    k = np.minimum(k, cap + 1)
    k = np.where((k + 1) * step <= limit, k + 1, k)
    k = np.where((k >= 0) & (k * step > limit), k - 1, k)
    return np.minimum(np.maximum(k, -1), cap)


def hyperbola_stack_fast(traces: np.ndarray, x_m: np.ndarray, dt_s: float, time_offset_s: float,
                         time_zero_s: float, f_nominal_hz: float | None = None,
                         cone_half_angle_deg: float = DEFAULT_CONE_DEG, tolerance_periods: float = 0.0,
                         velocities=VELOCITY_GRID, env: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Same contract and output as hyperbola_stack. `env` may pass a
    precomputed (n_traces, n_samples) envelope (before the tolerance filter)."""
    if not is_uniform(x_m):
        return hyperbola_stack(traces, x_m, dt_s, time_offset_s, time_zero_s, f_nominal_hz,
                               cone_half_angle_deg, tolerance_periods, velocities)
    if env is None:
        env = envelope(np.asarray(traces, dtype=float))
    if tolerance_periods > 0:
        if not f_nominal_hz:
            raise ValueError("a time tolerance needs the antenna's nominal frequency")
        half_w = int(round(tolerance_periods / f_nominal_hz / dt_s))
        if half_w > 0:
            env = maximum_filter1d(env, size=2 * half_w + 1, axis=1, mode="nearest")
    n_tr, n_s = env.shape
    x = np.asarray(x_m, dtype=float)
    t0 = time_offset_s + np.arange(n_s) * dt_s
    tau0 = np.maximum(t0 - time_zero_s, 0.0)
    step = float(np.median(np.abs(np.diff(x)))) if n_tr > 1 else 1.0
    tan_t = math.tan(math.radians(cone_half_angle_deg))
    env_t = np.ascontiguousarray(env.T)                       # (n_s, n_tr)
    cs = np.zeros((n_s, n_tr + 1))
    np.cumsum(env_t, axis=1, out=cs[:, 1:])
    tau_max = (n_s - 1) * dt_s + time_offset_s - time_zero_s  # s <= n_s - 1
    i0 = np.arange(n_tr)
    after_t0 = (tau0 > 0)[:, None]

    best = np.full((n_s, n_tr), -np.inf)
    v_hat = np.full((n_s, n_tr), np.nan)
    valid_any = np.zeros((n_s, n_tr), dtype=bool)
    for v in velocities:
        half_ap = np.maximum(tan_t * v * tau0 / 2, MIN_HALF_APERTURE * step * (1 + 1e-9))
        with np.errstate(invalid="ignore"):
            reach = v / 2 * np.sqrt(np.maximum(tau_max ** 2 - tau0 ** 2, 0.0))
        reach = np.where(tau0 <= tau_max, reach, -1.0)
        k_row = np.minimum(_offsets_within(half_ap, step, n_tr - 1),
                           _offsets_within(reach, step, n_tr - 1))  # (n_s,), -1 = none
        hi = np.minimum(i0[None, :] + k_row[:, None], n_tr - 1)
        lo = np.maximum(i0[None, :] - k_row[:, None], 0)
        count = np.where(k_row[:, None] >= 0, hi - lo + 1, 0)
        rows = np.arange(n_s)[:, None]
        s_flat = np.where(count > 0, cs[rows, hi + 1] - cs[rows, lo], 0.0)
        s_hyp = np.zeros((n_s, n_tr))
        for k in range(int(k_row.max()) + 1 if k_row.max() >= 0 else 0):
            r = np.nonzero(k_row >= k)[0]
            tau = np.sqrt(tau0[r] ** 2 + (2 * k * step / v) ** 2)
            s = (tau + time_zero_s - time_offset_s) / dt_s
            s0 = np.clip(np.floor(s).astype(np.int64), 0, n_s - 2)
            frac = np.clip(s - s0, 0.0, 1.0)[:, None]
            g = env_t[s0] * (1 - frac) + env_t[s0 + 1] * frac   # (len(r), n_tr)
            if k == 0:
                s_hyp[r] += g
            elif k < n_tr:
                s_hyp[r, : n_tr - k] += g[:, k:]
                s_hyp[r, k:] += g[:, : n_tr - k]
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
