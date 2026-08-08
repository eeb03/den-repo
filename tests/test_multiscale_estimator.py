"""
The multi-scale candidate estimator, and the hook that lets it be compared.

Three things are protected.

**The baseline is untouched.** `detect_line`/`detect_scan` grew an `estimator`
parameter; its default must behave exactly as the pre-hook code did. The
regression tests below pin that against the baseline estimator called directly.

**The candidate changes scale and nothing else.** Restricted to its first
scale, the candidate must be bit-identical to the baseline -- if it is not,
some other difference crept in and any later benchmark result would be
uninterpretable. The baseline ring's lateral asymmetry is deliberately kept.

**The scale ladder is fixed in advance.** It was derived from the measured
baseline geometry before any benchmark ran, and a test pins its values so it
cannot drift toward whatever scores best.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from benchmark.detection import detect_line
from preprocessing.multiscale_anomaly import (
    SCALE_LABELS, SCALES, _reliability, combine_scales, describe_scales,
    multiscale_anomaly_grid, per_scale_grids, preprocess_traces,
)
from preprocessing.spatial_grid import (
    TRACE_ANOMALY_WINDOWS, _local_anomaly_grid, anomaly_grid_from_traces,
)


def _traces(seed=0, n_traces=120, n_samples=200, width=0, amplitude=1.0, height=10):
    rng = np.random.default_rng(seed)
    t = rng.normal(scale=0.01, size=(n_traces, n_samples))
    if width:
        c = n_traces // 2
        s = n_samples // 2
        t[c - width // 2:c - width // 2 + width, s - height // 2:s - height // 2 + height] += amplitude
    return t


def _same(a, b):
    return np.array_equal(np.nan_to_num(a, nan=-9e9), np.nan_to_num(b, nan=-9e9))


# ---------------------------------------------------------------- the hook

def test_the_default_estimator_matches_the_baseline_exactly():
    """The pre-hook behaviour: detect_line built its grid with the baseline."""
    t = _traces(seed=1, width=1)
    z = anomaly_grid_from_traces(t)
    mask = np.abs(np.nan_to_num(z, nan=0.0)) > 3.0
    labeled, n = ndimage.label(mask)
    expected = sum(1 for i in range(1, n + 1) if int((labeled == i).sum()) >= 3)
    assert len(detect_line(t, "s", 0, threshold=3.0, min_cells=3)) == expected


def test_passing_the_baseline_explicitly_changes_nothing():
    t = _traces(seed=2, width=1)
    a = detect_line(t, "s", 0)
    b = detect_line(t, "s", 0, estimator=anomaly_grid_from_traces)
    assert [d.__dict__ for d in a] == [d.__dict__ for d in b]


def test_the_hook_does_not_alter_threshold_or_min_cells_semantics():
    t = _traces(seed=3, width=1)
    strict = detect_line(t, "s", 0, threshold=5.0, min_cells=3)
    loose = detect_line(t, "s", 0, threshold=3.0, min_cells=3)
    big = detect_line(t, "s", 0, threshold=3.0, min_cells=50)
    assert len(strict) <= len(loose)
    assert len(big) <= len(loose)


def test_a_swapped_estimator_is_actually_used():
    """Guards against the parameter being accepted and then ignored."""
    assert detect_line(_traces(seed=4, width=1), "s", 0,
                       estimator=lambda tr: np.zeros((tr.shape[1], tr.shape[0]))) == []


# ---------------------------------------------------------------- scale only

def test_the_candidate_at_its_first_scale_is_the_baseline_bit_for_bit():
    """If this fails, the candidate differs by more than scale."""
    t = _traces(seed=5, width=3)
    assert _same(multiscale_anomaly_grid(t, scales=(SCALES[0],)), anomaly_grid_from_traces(t))


def test_the_first_scale_reproduces_the_baseline_window_constants():
    s0 = SCALES[0]
    assert s0["inner_window"] == TRACE_ANOMALY_WINDOWS["inner_window"]
    assert s0["outer_window"] == TRACE_ANOMALY_WINDOWS["outer_window"]
    assert s0["min_ring_count"] == TRACE_ANOMALY_WINDOWS["min_ring_count"]
    assert s0["min_row_ring_count"] == TRACE_ANOMALY_WINDOWS["min_row_ring_count"]
    assert s0["min_col_ring_count"] == TRACE_ANOMALY_WINDOWS["min_col_ring_count"]


def test_the_reliability_rule_is_derived_from_the_baseline_not_invented():
    """The baseline's own constants fall out of the general rule at its windows."""
    r = _reliability((5, 2), (15, 6))
    assert r == {"min_ring_count": 20, "min_row_ring_count": 10, "min_col_ring_count": 4}


def test_preprocessing_is_shared_with_the_baseline():
    t = _traces(seed=6, width=2)
    z, _ = _local_anomaly_grid(preprocess_traces(t), **TRACE_ANOMALY_WINDOWS)
    assert _same(z, anomaly_grid_from_traces(t))


def test_the_lateral_asymmetry_is_preserved_on_purpose():
    """Kept so scale stays the only variable; a symmetric ring is a later experiment."""
    for spec in SCALES:
        assert spec["outer_window"][1] % 2 == 0
        assert spec["inner_window"][1] % 2 == 0


# ---------------------------------------------------------------- the ladder

def test_the_scale_ladder_is_exactly_the_predefined_one():
    """Pinned so it cannot drift toward whatever scores best on a benchmark."""
    assert [s["outer_window"][1] for s in SCALES] == [6, 12, 24, 48]
    assert [s["outer_window"][0] for s in SCALES] == [15, 31, 61, 121]
    assert [s["inner_window"] for s in SCALES] == [(5, 2), (11, 4), (21, 8), (41, 16)]
    assert SCALE_LABELS == ("S0", "S1", "S2", "S3")


def test_the_ladder_is_described_for_the_record():
    rows = describe_scales()
    assert [r["lateral_support_traces"] for r in rows] == [6, 12, 24, 48]
    assert len(rows) == len(SCALES) == 4


# ---------------------------------------------------------------- combination

def test_the_combination_keeps_the_sign_of_the_winning_scale():
    """
    A DARK anomaly must stay negative. The background carries noise on purpose:
    on a perfectly uniform background the ring std is 0 and every scale is
    unreliable, which is the baseline's own behaviour, not a combination bug.
    """
    rng = np.random.default_rng(21)
    grid = rng.normal(scale=1.0, size=(160, 160))
    grid[80, 80] = -60.0
    z = combine_scales(grid)
    assert np.isfinite(z[80, 80])
    assert z[80, 80] < 0, "sign was discarded"


def test_the_combination_is_the_max_magnitude_over_scales():
    rng = np.random.default_rng(22)
    grid = rng.normal(scale=1.0, size=(160, 160))
    grid[80, 80] += 40.0
    z = combine_scales(grid)
    per = [_local_anomaly_grid(grid, **s) for s in SCALES]
    best = max(abs(zz[80, 80]) for zz, unrel in per
               if np.isfinite(zz[80, 80]) and not unrel[80, 80])
    assert abs(z[80, 80]) == pytest.approx(best)


def test_a_cell_unreliable_at_every_scale_stays_nan():
    assert np.isnan(combine_scales(np.zeros((30, 30)))).all()


def test_multiscale_coverage_is_a_superset_of_the_baseline():
    """Excluding a starved scale must never remove a cell the baseline could score."""
    t = _traces(seed=7, width=2)
    base = anomaly_grid_from_traces(t)
    cand = multiscale_anomaly_grid(t)
    assert np.isfinite(cand)[np.isfinite(base)].all()


def test_per_scale_grids_are_diagnostics_and_cover_every_scale():
    g = per_scale_grids(_traces(seed=8, width=2))
    assert set(g) == set(SCALE_LABELS)
    assert all(v.shape == g["S0"].shape for v in g.values())


# ---------------------------------------------------------------- mechanism

@pytest.mark.parametrize("width", [1, 3, 6, 13, 24])
def test_the_candidate_is_defined_at_every_width_the_baseline_is(width):
    t = _traces(seed=9, width=width)
    base = anomaly_grid_from_traces(t)
    cand = multiscale_anomaly_grid(t)
    assert cand.shape == base.shape


def test_the_baseline_saturates_on_a_wide_noiseless_target():
    """The failure this candidate exists to address, pinned as a fact."""
    g = np.zeros((200, 120))
    g[95:105, 54:67] = 1.0                    # 13 traces wide
    z, _ = _local_anomaly_grid(g, **TRACE_ANOMALY_WINDOWS)
    assert z[100, 60] == pytest.approx(0.774597, abs=1e-5)


def test_the_baseline_is_amplitude_invariant_when_saturated():
    vals = []
    for amp in (0.1, 1.0, 1000.0):
        g = np.zeros((200, 120))
        g[95:105, 54:67] = amp
        z, _ = _local_anomaly_grid(g, **TRACE_ANOMALY_WINDOWS)
        vals.append(z[100, 60])
    assert vals[0] == pytest.approx(vals[1]) == pytest.approx(vals[2])
