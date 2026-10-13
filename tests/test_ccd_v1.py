"""
CCD-V1 Stage 0/1 helpers (docs/ccd-v1-stage0-1-protocol.md): exact statistics
and the per-line feature primitives, on analytic fixtures only. No BAM, 4TU
or corpus data is read here.
"""
import math

import numpy as np
import pytest

from scripts.ccd_v1_stats import (
    clopper_pearson, exact_binomial_upper, exact_mann_whitney, mann_whitney_u,
)
from scripts.ccd_v1_stage1 import continuity_run, polarity, ref_nodes, step_of


def test_exact_mann_whitney_4v4_extremes():
    r = exact_mann_whitney([5, 6, 7, 8], [1, 2, 3, 4], "greater")
    assert r["U"] == 16 and r["n_splits"] == 70
    assert r["p_exact"] == pytest.approx(1 / 70) and r["min_attainable_p"] == pytest.approx(1 / 70)
    assert r["hodges_lehmann_shift"] == 4 and r["pairwise_difference_range"] == [1, 7]
    two = exact_mann_whitney([5, 6, 7, 8], [1, 2, 3, 4], "two-sided")
    assert two["p_exact"] == pytest.approx(2 / 70)


def test_exact_mann_whitney_one_discordant_pair():
    # U = 15 -> P(U >= 15) = 2/70 ; U = 14 -> 4/70 > 0.05
    assert exact_mann_whitney([3.5, 6, 7, 8], [1, 2, 3, 4], "greater")["p_exact"] == pytest.approx(2 / 70)
    assert exact_mann_whitney([2.5, 4.5, 7, 8], [1, 2, 3, 4], "greater")["p_exact"] == pytest.approx(4 / 70)


def test_mann_whitney_ties_count_half():
    assert mann_whitney_u([1, 2], [1, 2]) == 2.0


def test_binomial_and_clopper_pearson():
    assert exact_binomial_upper(4, 4) == pytest.approx(1 / 16)
    assert exact_binomial_upper(7, 8) == pytest.approx(9 / 256)
    lo, hi = clopper_pearson(4, 4)
    assert hi == 1.0 and lo == pytest.approx(0.025 ** 0.25, abs=1e-6)
    lo, hi = clopper_pearson(0, 4)
    assert lo == 0.0 and hi == pytest.approx(1 - 0.025 ** 0.25, abs=1e-6)


def _ricker(t, f, t0):
    a = (math.pi * f * (t - t0)) ** 2
    return (1 - 2 * a) * np.exp(-a)


def test_polarity_sign():
    t = np.arange(400) * 0.02
    w = _ricker(t, 1.5, 4.0)
    p = int(np.argmax(np.abs(w)))
    assert polarity(w, p, w, p, 20) == pytest.approx(1.0)
    assert polarity(-w, p, w, p, 20) == pytest.approx(-1.0)


def test_continuity_run_half_maximum():
    a = np.array([0.1, 0.2, 0.6, 0.9, 1.0, 0.7, 0.4, 0.8, 0.9])
    r = continuity_run(a, 5.0)
    assert r["argmax_index"] == 4 and r["run_index_range"] == [2, 5] and r["run_mm"] == 15.0


def test_reference_nodes_stay_in_step_and_off_edges():
    x = np.arange(0, 2001, 5.0)
    rn = ref_nodes(x, 250.0)
    xs = x[rn]
    assert all(120 <= abs(v - 250) <= 200 for v in xs)
    assert all(60 <= v <= 440 for v in xs) and step_of(250.0) == 0
    assert step_of(1999.0) == 3 and step_of(2000.0) == 3
