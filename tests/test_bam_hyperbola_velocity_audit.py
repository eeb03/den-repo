"""
Deterministic-math tests for `scripts.bam_hyperbola_velocity_audit`.

SYNTHETIC FIXTURES ONLY, deliberately. These tests exist to pin the
ARITHMETIC (the least-squares fit, the identifiability metric, leave-one-out,
sensitivity, permittivity conversion, classification thresholds) against
known, hand-computable numbers -- never to reproduce or assert the real
BAM Pk266 result, which only running the audit script against the real
archive can produce. A test asserting a specific real-data velocity would
silently start lying the moment a picking-methodology improvement changed
that number; these tests would not need to change at all in that event,
because they never touch real data.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.bam_hyperbola_velocity_audit import (
    C_M_PER_NS, CONFOUND_THRESHOLD, ArrivalPick, HyperbolaResult, MethodAResult, Target,
    TargetAssociation, classify, compare_methods, establish_time_axis, fit_method_a,
    leave_one_out, picking_sensitivity, relative_permittivity,
)

TRUE_T0_NS = 0.5
TRUE_V_M_PER_NS = 0.12


def _target(target_id: str, depth_mm: float, x_mm: float = 0.0) -> Target:
    return Target(target_id, x_mm, depth_mm, "synthetic_test_fixture", 0.0)


def _exact_pick(target: Target, t0_ns: float = TRUE_T0_NS, v: float = TRUE_V_M_PER_NS) -> ArrivalPick:
    """The arrival time an EXACT (noise-free) model would produce, so a fit against it must recover t0/v exactly."""
    t = t0_ns + 2 * (target.depth_mm / 1000.0) / v
    return ArrivalPick(target.x_mm, t, 0, 1.0, 100.0)


def _assoc(target: Target, pick: ArrivalPick, usable: bool = True) -> TargetAssociation:
    return TargetAssociation(target, 0, [0], 0, pick, [], usable, "synthetic")


# --- Method A: exact recovery and identifiability -------------------------

def test_exact_synthetic_data_recovers_t0_and_v():
    targets = [_target(f"t{i}", d) for i, d in enumerate([100.0, 500.0, 900.0, 1300.0])]
    associations = [_assoc(t, _exact_pick(t)) for t in targets]
    result = fit_method_a(associations)
    assert result.t0_ns == pytest.approx(TRUE_T0_NS, abs=1e-9)
    assert result.velocity_m_per_ns == pytest.approx(TRUE_V_M_PER_NS, abs=1e-9)
    assert result.rms_depth_error_mm == pytest.approx(0.0, abs=1e-6)
    for err in result.depth_error_mm.values():
        assert err == pytest.approx(0.0, abs=1e-6)


def test_well_spread_depths_are_identifiable():
    """Depths spanning a wide, non-degenerate range should separate t0 from v."""
    targets = [_target(f"t{i}", d) for i, d in enumerate([50.0, 600.0, 1800.0, 3000.0])]
    associations = [_assoc(t, _exact_pick(t)) for t in targets]
    result = fit_method_a(associations)
    assert result.identifiable is True
    assert result.slope_intercept_correlation is not None
    assert abs(result.slope_intercept_correlation) < CONFOUND_THRESHOLD


def test_narrowly_spread_depths_are_confounded():
    """
    Depths clustered tightly relative to their mean give the design matrix's
    two columns (2d and the constant) a large, but never exactly 1.0
    (that would need d itself to be identical), correlation -- the same
    confound the real BAM Pk266 depths exhibit.
    """
    targets = [_target(f"t{i}", d) for i, d in enumerate([1000.0, 1001.0, 1002.0, 1003.0])]
    associations = [_assoc(t, _exact_pick(t)) for t in targets]
    result = fit_method_a(associations)
    assert result.identifiable is False
    assert abs(result.slope_intercept_correlation) >= CONFOUND_THRESHOLD


def test_two_targets_are_never_marked_identifiable():
    targets = [_target("t0", 100.0), _target("t1", 500.0)]
    associations = [_assoc(t, _exact_pick(t)) for t in targets]
    result = fit_method_a(associations)
    assert result.identifiable is False
    assert "not independently checkable" in result.identifiability_note


def test_fewer_than_two_usable_targets_returns_no_fit():
    result = fit_method_a([_assoc(_target("t0", 100.0), _exact_pick(_target("t0", 100.0)))])
    assert result.velocity_m_per_ns is None
    assert result.t0_ns is None


def test_non_increasing_arrival_with_depth_is_non_physical():
    """A negative implied 1/v (arrival time decreasing with known depth) must be refused, not inverted."""
    t_shallow = _target("shallow", 100.0)
    t_deep = _target("deep", 2000.0)
    backwards = [
        _assoc(t_shallow, ArrivalPick(0, 5.0, 0, 1.0, 100.0)),
        _assoc(t_deep, ArrivalPick(0, 1.0, 0, 1.0, 100.0)),
        _assoc(_target("mid", 1000.0), ArrivalPick(0, 3.0, 0, 1.0, 100.0)),
    ]
    result = fit_method_a(backwards)
    assert result.velocity_m_per_ns is None
    assert "non-physical" in result.identifiability_note


# --- leave-one-out ----------------------------------------------------------

def test_leave_one_out_is_exact_for_noise_free_synthetic_data():
    targets = [_target(f"t{i}", d) for i, d in enumerate([50.0, 600.0, 1800.0, 3000.0])]
    associations = [_assoc(t, _exact_pick(t)) for t in targets]
    results = leave_one_out(associations)
    assert len(results) == 4
    for r in results:
        assert r["error_mm"] == pytest.approx(0.0, abs=1e-6)


def test_leave_one_out_reveals_an_outlier_pick():
    targets = [_target(f"t{i}", d) for i, d in enumerate([50.0, 600.0, 1800.0, 3000.0])]
    associations = [_assoc(t, _exact_pick(t)) for t in targets]
    # Corrupt one target's pick by a large, deliberate amount.
    bad = associations[0]
    associations[0] = _assoc(bad.target, ArrivalPick(0, bad.apex_pick.time_ns + 2.0, 0, 1.0, 100.0))
    results = leave_one_out(associations)
    held_out_bad = next(r for r in results if r["held_out"] == "t0")
    assert abs(held_out_bad["error_mm"]) > 10.0  # refit on the 3 good targets predicts far off


# --- picking sensitivity ----------------------------------------------------

def test_uniform_shift_intuition_does_not_apply_per_target_perturbation():
    """A single target's perturbation, unlike a uniform one, must move the fitted slope (v)."""
    targets = [_target(f"t{i}", d) for i, d in enumerate([50.0, 600.0, 1800.0, 3000.0])]
    associations = [_assoc(t, _exact_pick(t)) for t in targets]
    result = picking_sensitivity(associations, sample_interval_ns=0.03)
    assert result["max_velocity_delta_frac"] is not None
    assert result["max_velocity_delta_frac"] > 0.0


# --- relative permittivity ---------------------------------------------------

def test_relative_permittivity_matches_the_known_physical_relation():
    rp = relative_permittivity(C_M_PER_NS)  # v = c => eps_r must be 1 (vacuum)
    assert rp["relative_permittivity"] == pytest.approx(1.0, abs=1e-9)


def test_relative_permittivity_of_none_velocity_is_none():
    assert relative_permittivity(None) is None


def test_relative_permittivity_nine_gives_the_products_own_default_velocity():
    """Sanity cross-check against converters/segy_converter.py's own constant."""
    v_default = 0.1
    rp = relative_permittivity(v_default)
    assert rp["relative_permittivity"] == pytest.approx(9.0, abs=0.05)


# --- classification ----------------------------------------------------------

def _method_a(velocity, t0, identifiable, note, depth_error_mm=None):
    return MethodAResult(["t0", "t1", "t2", "t3"], t0, velocity, -0.5, identifiable, note,
                         {}, {}, depth_error_mm or {}, 0.0, 0.0)


def _hyp(target_id, velocity, usable=True):
    return HyperbolaResult(target_id, usable, "ok" if usable else "no", velocity_m_per_ns=velocity)


def _comparison(v_a, v_b_mean, material):
    return {"comparable": True, "method_a_velocity_m_per_ns": v_a,
           "method_b_mean_velocity_m_per_ns": v_b_mean,
           "relative_disagreement": abs(v_a - v_b_mean) / v_a, "material_disagreement": material}


def _associations_for(depths_mm: dict) -> list:
    return [_assoc(_target(tid, d), _exact_pick(_target(tid, d))) for tid, d in depths_mm.items()]


DEPTHS = {"t0": 100.0, "t1": 600.0, "t2": 1800.0, "t3": 3000.0}


def test_classify_failed_when_fewer_than_two_usable():
    method_a = _method_a(None, None, False, "no fit")
    kind, reasons = classify(method_a, [], {}, {}, [], _associations_for({"t0": 100.0}))
    assert kind == "FAILED"


def test_classify_inconclusive_when_not_identifiable():
    method_a = _method_a(0.12, 0.5, False, "confounded")
    kind, _ = classify(method_a, [_hyp("t0", 0.12)], {}, {}, [], _associations_for(DEPTHS))
    assert kind == "INCONCLUSIVE"


def test_classify_estimated_not_validated_when_no_hyperbola_converges():
    method_a = _method_a(0.12, 0.5, True, "separable")
    kind, reasons = classify(method_a, [_hyp("t0", None, usable=False)], {}, {}, [],
                             _associations_for(DEPTHS))
    assert kind == "ESTIMATED BUT NOT VALIDATED"
    assert any("no per-target hyperbola" in r for r in reasons)


def test_classify_estimated_not_validated_on_material_disagreement():
    method_a = _method_a(0.12, 0.5, True, "separable")
    comparison = _comparison(0.12, 0.20, material=True)
    kind, reasons = classify(method_a, [_hyp("t0", 0.20)], comparison, {}, [],
                             _associations_for(DEPTHS))
    assert kind == "ESTIMATED BUT NOT VALIDATED"
    assert any("disagree" in r for r in reasons)


def test_classify_estimated_not_validated_on_large_depth_error():
    method_a = _method_a(0.12, 0.5, True, "separable",
                         depth_error_mm={"t0": 50.0})  # 50 mm on a 100 mm target = 50%
    comparison = _comparison(0.12, 0.121, material=False)
    kind, reasons = classify(method_a, [_hyp("t0", 0.121)], comparison, {}, [],
                             _associations_for(DEPTHS))
    assert kind == "ESTIMATED BUT NOT VALIDATED"
    assert any("exceeds" in r for r in reasons)


def test_classify_validated_when_everything_agrees():
    method_a = _method_a(0.12, 0.5, True, "separable", depth_error_mm={"t0": 1.0})
    comparison = _comparison(0.12, 0.121, material=False)
    sensitivity = {"max_velocity_delta_frac": 0.01}
    loo = [{"held_out": "t0", "error_mm": 1.0}]
    kind, reasons = classify(method_a, [_hyp("t0", 0.121)], comparison, sensitivity, loo,
                             _associations_for(DEPTHS))
    assert kind == "VALIDATED VELOCITY"


def test_classify_never_returns_validated_without_every_check_passing():
    """A single failing check anywhere must not be overridable by the others looking good."""
    method_a = _method_a(0.12, 0.5, True, "separable", depth_error_mm={"t0": 1.0})
    comparison = _comparison(0.12, 0.121, material=False)
    unstable_sensitivity = {"max_velocity_delta_frac": 0.50}  # far exceeds materiality
    loo = [{"held_out": "t0", "error_mm": 1.0}]
    kind, _ = classify(method_a, [_hyp("t0", 0.121)], comparison, unstable_sensitivity, loo,
                       _associations_for(DEPTHS))
    assert kind != "VALIDATED VELOCITY"


# --- time axis ---------------------------------------------------------------

def test_time_axis_reports_consistency_with_a_matching_dzt_header():
    z = np.linspace(0.0, 15.0, 512)
    scan = SimpleNamespace(grid=SimpleNamespace(z=z),
                           dzt_header={"range_ns": 15.0, "n_samples": 512,
                                     "position_ns": None, "epsr": None})
    axis = establish_time_axis(scan)
    assert axis.consistent_with_dzt is True
    assert axis.n_samples == 512
    assert axis.sample_interval_ns == pytest.approx(15.0 / 511, abs=1e-9)


def test_time_axis_reports_inconsistency_with_a_disagreeing_dzt_header():
    z = np.linspace(0.0, 15.0, 512)
    scan = SimpleNamespace(grid=SimpleNamespace(z=z),
                           dzt_header={"range_ns": 30.0, "n_samples": 256,
                                     "position_ns": None, "epsr": None})
    axis = establish_time_axis(scan)
    assert axis.consistent_with_dzt is False
    assert "does NOT agree" in axis.note


def test_time_axis_without_a_dzt_header_is_reported_not_hidden():
    z = np.linspace(0.0, 15.0, 512)
    scan = SimpleNamespace(grid=SimpleNamespace(z=z), dzt_header={})
    axis = establish_time_axis(scan)
    assert axis.consistent_with_dzt is False
    assert "did not supply" in axis.note
