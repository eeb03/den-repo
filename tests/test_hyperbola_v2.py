"""
Hyperbola detector V2 pieces (docs/hyperbola-v2-experiment.md): the fast
stack's equivalence (C3), the component rule, grouping, the calibrated
threshold and the canonical input. Analytic fixtures only.
"""
import math

import numpy as np
import pytest

from benchmark.detection import detect_line
from benchmark.hyperbola_stack import VELOCITY_GRID, hyperbola_stack
from benchmark.hyperbola_stack_fast import hyperbola_stack_fast, is_uniform
from benchmark.hyperbola_v2 import (
    GROUPING_GRID, LAMBDA0_GRID, R_CAL, Z_FLOOR, StackContext, calibrated_threshold, canonical_line,
    components, detections_at, group, null_peaks, stack_line,
)

F = 1e9
DT = 1 / (F * 20)
V = VELOCITY_GRID[4]


def _ricker(t, f):
    a = (math.pi * f * t) ** 2
    return (1 - 2 * a) * np.exp(-a)


def _line(apexes, n_tr=81, n_s=300, step=0.01, noise=1e-3, seed=0, flat_at=None):
    """Point diffractors (x0, tau0) at velocity V, plus a direct wave at t=0.5 ns."""
    x = np.arange(n_tr) * step
    t = np.arange(n_s) * DT
    tz = 0.5e-9
    rng = np.random.default_rng(seed)
    tr = np.array([_ricker(t - tz, F) for _ in x]) * 5.0
    for x0, tau0 in apexes:
        for i, xi in enumerate(x):
            tt = tz + math.sqrt(tau0 ** 2 + (2 * (xi - x0) / V) ** 2)
            tr[i] += _ricker(t - tt, F)
    if flat_at is not None:
        tr += _ricker(t - flat_at, F)[None, :]
    return tr + noise * rng.standard_normal(tr.shape), x, tz


@pytest.mark.parametrize("tol", [0.0, 0.25])
def test_fast_stack_equals_original(tol):
    tr, x, tz = _line([(0.3, 3e-9), (0.55, 5e-9)])
    bg = tr - tr.mean(axis=0)
    z0, v0 = hyperbola_stack(bg, x, DT, 0.0, tz, F, 45, tol)
    z1, v1 = hyperbola_stack_fast(bg, x, DT, 0.0, tz, F, 45, tol)
    assert np.array_equal(np.isnan(z0), np.isnan(z1))
    assert np.nanmax(np.abs(z0 - z1)) < 1e-6
    m = (z0 > 1) & ~np.isnan(z0)
    assert np.array_equal(v0[m], v1[m])


def test_fast_stack_falls_back_on_irregular_spacing():
    tr, x, tz = _line([(0.3, 3e-9)])
    x = x + np.linspace(0, 0.003, x.size) ** 2 * 50
    assert not is_uniform(x)
    bg = tr - tr.mean(axis=0)
    z0, _ = hyperbola_stack(bg, x, DT, 0.0, tz, F, 45, 0.25)
    z1, _ = hyperbola_stack_fast(bg, x, DT, 0.0, tz, F, 45, 0.25)
    assert np.array_equal(np.nan_to_num(z0), np.nan_to_num(z1))


def test_components_is_the_detect_line_rule():
    rng = np.random.default_rng(1)
    z = rng.normal(0, 2, (60, 40))
    ours = components(z, 3.0)
    theirs = detect_line(np.zeros((40, 60)), "s", 0, threshold=3.0, min_cells=3, estimator=lambda _t: z)
    assert [(d["sample"], d["trace"]) for d in ours] == [(d.peak_sample, d.peak_trace) for d in theirs]


def _ctx_and_dets(apexes, thr=6.0, **kw):
    tr, x, tz = _line(apexes, **kw)
    bg = tr - tr.mean(axis=0)
    z, v_hat, env = stack_line(bg, x, DT, 0.0, tz, F)
    return StackContext.build(bg, x, DT, 0.0, tz, F, env), detections_at(z, v_hat, thr), x


def test_grouping_merges_a_detection_on_the_same_curve():
    ctx, dets, x = _ctx_and_dets([(0.4, 3e-9)])
    strongest = max(dets, key=lambda d: d["z"])
    # a synthetic second detection ON the strongest one's curve, 4 traces away
    i = strongest["trace"] + 4
    tau = strongest["sample"] * DT - ctx.time_zero_s
    t_on = ctx.time_zero_s + math.sqrt(tau ** 2 + (2 * (x[i] - x[strongest["trace"]]) / strongest["v"]) ** 2)
    limb = {"sample": int(round(t_on / DT)), "trace": i, "z": strongest["z"] / 3, "v": strongest["v"]}
    kept = group([strongest, limb], ctx, {"delta_periods": 0.5, "kappa": math.inf, "rho": 0.3})
    assert len(kept) == 1 and kept[0]["merged"] == 1


def test_grouping_keeps_two_distinct_targets():
    ctx, dets, x = _ctx_and_dets([(0.25, 3e-9), (0.55, 3e-9)])
    for cfg in GROUPING_GRID:
        kept = group(dets, ctx, cfg)
        near = [min(abs(x[d["trace"]] - x0) for d in kept) for x0 in (0.25, 0.55)]
        assert max(near) <= 0.03, cfg


def test_grouping_has_no_suppression_radius():
    # same apex trace, different time far off the curve: never merged
    ctx, dets, x = _ctx_and_dets([(0.4, 3e-9)])
    a = max(dets, key=lambda d: d["z"])
    b = {**a, "sample": a["sample"] + 40, "z": a["z"] / 2}
    assert len(group([a, b], ctx, GROUPING_GRID[-1])) == 2


def test_calibrated_threshold_rule():
    peaks = sorted([20.0, 9.0, 7.0, 5.0, 4.0], reverse=True)
    assert calibrated_threshold(peaks, 0.25) == 9.0          # ceil(0.25 * 8) = 2 -> the 2nd largest
    assert calibrated_threshold(peaks, 0.5) == 5.0           # ceil(0.5 * 8) = 4 -> the 4th largest
    assert calibrated_threshold(peaks, 1.0) == Z_FLOOR        # needs 8 peaks, has 5
    assert calibrated_threshold([2.0] * 20, 0.5) == Z_FLOOR   # floored
    assert calibrated_threshold(peaks, 0.1) == 20.0


def test_null_peaks_are_seeded_by_line_identity_and_ignore_truth():
    tr, x, tz = _line([(0.4, 3e-9)])
    bg = tr - tr.mean(axis=0)
    a = null_peaks(bg, x, DT, 0.0, tz, F, "line-A", GROUPING_GRID[0])
    b = null_peaks(bg, x, DT, 0.0, tz, F, "line-A", GROUPING_GRID[0])
    assert a == b and a == sorted(a, reverse=True) and all(p > Z_FLOOR for p in a)
    assert len(LAMBDA0_GRID) == 4 and R_CAL == 8


def test_canonical_line_resamples_and_regularises():
    tr, x, tz = _line([(0.4, 3e-9)])
    can = canonical_line(tr, x, DT, 0.0, F)
    assert not can.resampled and not can.regularised          # already 20 spp, uniform
    can = canonical_line(tr, x, DT / 2, 0.0, F)
    assert can.resampled and can.traces.shape[1] == tr.shape[1] // 2
    xi = x.copy()
    xi[10:] += 0.002
    can = canonical_line(tr, xi, DT, 0.0, F)
    assert can.regularised and is_uniform(can.x_m)
    assert can.original_trace(float(xi[50])) == 50
