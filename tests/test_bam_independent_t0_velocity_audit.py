"""
Deterministic-math tests for `scripts.bam_independent_t0_velocity_audit`.

SYNTHETIC FIXTURES ONLY, same discipline as
`tests/test_bam_hyperbola_velocity_audit.py`: these pin the ARITHMETIC
(the fixed-t0 fit, sensitivity, leave-one-out, classification thresholds)
against known, hand-computable numbers -- never the real BAM Pk266 result,
which only running the audit against the real archive can produce (see
`artifacts/bam/bam_independent_t0_velocity_audit.json`).
"""
from __future__ import annotations

import numpy as np
import pytest

from schemas.time_zero import TimeZeroMethod, TimeZeroResult, TimeZeroStatus
from scripts.bam_hyperbola_velocity_audit import ArrivalPick, Target, TargetAssociation
from scripts.bam_independent_t0_velocity_audit import (
    classify,
    derive_independent_time_zero,
    fit_with_fixed_t0,
    leave_one_out_fixed_t0,
    sample_traces_for_time_zero,
    t0_sensitivity,
)

TRUE_T0_NS = 0.5
TRUE_V_M_PER_NS = 0.12


def _target(target_id: str, depth_mm: float, x_mm: float = 0.0) -> Target:
    return Target(target_id, x_mm, depth_mm, "synthetic_test_fixture", 0.0)


def _exact_pick(target: Target, t0_ns: float = TRUE_T0_NS, v: float = TRUE_V_M_PER_NS) -> ArrivalPick:
    t = t0_ns + 2 * (target.depth_mm / 1000.0) / v
    return ArrivalPick(target.x_mm, t, 0, 1.0, 100.0)


def _assoc(target: Target, pick, usable: bool = True) -> TargetAssociation:
    return TargetAssociation(target, 0, [0], 0, pick, [], usable, "synthetic")


def _resolved_t0(correction_ns=TRUE_T0_NS, spread_ns=0.0) -> TimeZeroResult:
    return TimeZeroResult(
        status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
        correction_ns=correction_ns, basis="synthetic test fixture",
        traces_evaluated=20, successful_picks=20, outliers_rejected=0, spread_ns=spread_ns,
    )


def _unresolved_t0(status=TimeZeroStatus.INCONCLUSIVE) -> TimeZeroResult:
    return TimeZeroResult(status=status, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
                          basis="too few picks agreed")


# --- fit_with_fixed_t0: exact recovery -------------------------------------

class TestFixedT0Fit:
    def test_exact_synthetic_data_recovers_v_with_zero_spread(self):
        targets = [_target(f"t{i}", d) for i, d in enumerate([100.0, 500.0, 900.0, 1300.0])]
        associations = [_assoc(t, _exact_pick(t)) for t in targets]
        result = fit_with_fixed_t0(associations, TRUE_T0_NS)
        assert result.usable
        assert result.mean_velocity_m_per_ns == pytest.approx(TRUE_V_M_PER_NS, abs=1e-9)
        assert result.velocity_spread_frac == pytest.approx(0.0, abs=1e-9)
        assert result.rms_depth_error_mm == pytest.approx(0.0, abs=1e-6)

    def test_an_apex_arriving_before_the_fixed_t0_is_excluded_not_clamped(self):
        excluded_target = _target("excluded", 100.0)
        # apex_pick time is BEFORE the fixed t0 -- non-physical, never guessed at.
        pick = ArrivalPick(0.0, TRUE_T0_NS - 0.1, 0, 1.0, 100.0)
        others = [_assoc(_target(f"other{i}", d), _exact_pick(_target(f"other{i}", d)))
                 for i, d in enumerate([500.0, 900.0])]
        associations = [_assoc(excluded_target, pick)] + others
        result = fit_with_fixed_t0(associations, TRUE_T0_NS)
        assert "excluded" not in result.per_target_velocity_m_per_ns
        assert result.usable  # the other two targets still carry the fit

    def test_fewer_than_two_physical_targets_is_unusable(self):
        target = _target("t0", 100.0)
        pick = ArrivalPick(0.0, TRUE_T0_NS - 0.1, 0, 1.0, 100.0)  # excluded
        result = fit_with_fixed_t0([_assoc(target, pick)], TRUE_T0_NS)
        assert not result.usable
        assert result.mean_velocity_m_per_ns is None

    def test_noisy_picks_produce_a_nonzero_but_bounded_spread(self):
        targets = [_target(f"t{i}", d) for i, d in enumerate([100.0, 500.0, 900.0, 1300.0])]
        picks = []
        for i, t in enumerate(targets):
            exact = _exact_pick(t)
            # a small, deliberate per-target time perturbation
            jitter = [0.01, -0.01, 0.02, -0.02][i]
            picks.append(ArrivalPick(exact.x_mm, exact.time_ns + jitter, 0, 1.0, 100.0))
        associations = [_assoc(t, p) for t, p in zip(targets, picks)]
        result = fit_with_fixed_t0(associations, TRUE_T0_NS)
        assert result.usable
        assert result.velocity_spread_frac > 0.0


# --- t0_sensitivity ---------------------------------------------------------

class TestT0Sensitivity:
    def test_zero_uncertainty_produces_no_delta(self):
        targets = [_target(f"t{i}", d) for i, d in enumerate([100.0, 500.0, 900.0, 1300.0])]
        associations = [_assoc(t, _exact_pick(t)) for t in targets]
        result = t0_sensitivity(associations, TRUE_T0_NS, t0_uncertainty_ns=0.0)
        assert result["max_velocity_delta_frac"] is None

    def test_shifting_t0_changes_the_recovered_velocity(self):
        targets = [_target(f"t{i}", d) for i, d in enumerate([100.0, 500.0, 900.0, 1300.0])]
        associations = [_assoc(t, _exact_pick(t)) for t in targets]
        result = t0_sensitivity(associations, TRUE_T0_NS, t0_uncertainty_ns=0.05)
        assert result["max_velocity_delta_frac"] is not None
        assert result["max_velocity_delta_frac"] > 0.0


# --- leave_one_out_fixed_t0 --------------------------------------------------

class TestLeaveOneOutFixedT0:
    def test_exact_for_noise_free_synthetic_data(self):
        targets = [_target(f"t{i}", d) for i, d in enumerate([100.0, 500.0, 900.0, 1300.0])]
        associations = [_assoc(t, _exact_pick(t)) for t in targets]
        loo = leave_one_out_fixed_t0(associations, TRUE_T0_NS)
        assert len(loo) == 4
        for r in loo:
            assert r["error_mm"] == pytest.approx(0.0, abs=1e-6)


# --- sample_traces_for_time_zero / derive_independent_time_zero ------------

class TestSampleTracesAndDeriveT0:
    def test_sample_traces_pulls_one_full_x_sweep_within_the_y_margin(self):
        n_x, n_y, n_z = 5, 10, 20
        volume = np.arange(n_x * n_y * n_z, dtype=float).reshape(n_x, n_y, n_z)

        class FakeGrid:
            x = np.linspace(0, 2000, n_x)
            y = np.linspace(0, 800, n_y)

        traces = sample_traces_for_time_zero(volume, FakeGrid(), y_margin_mm=100.0)
        assert len(traces) == n_x
        assert len(traces[0]) == n_z

    def test_empty_y_range_returns_no_traces(self):
        n_x, n_y, n_z = 5, 3, 20
        volume = np.zeros((n_x, n_y, n_z))

        class FakeGrid:
            x = np.linspace(0, 2000, n_x)
            y = np.array([0.0, 5.0, 10.0])  # narrower than the margin excludes everything

        traces = sample_traces_for_time_zero(volume, FakeGrid(), y_margin_mm=100.0)
        assert traces == []

    def test_derive_independent_time_zero_calls_the_real_framework_function(self):
        """
        A real pulse embedded in every trace should be picked consistently --
        confirms this wraps `preprocessing.time_zero.direct_wave_consensus_
        time_zero` correctly (record construction, sample_interval_ns
        plumbing), not a reimplementation.
        """
        n_x, n_y, n_z = 20, 5, 200
        onset_sample = 60
        sample_interval_ns = 0.5
        rng = np.random.default_rng(0)
        volume = rng.normal(0, 1.0, size=(n_x, n_y, n_z))
        for x in range(n_x):
            for i in range(onset_sample, onset_sample + 15):
                volume[x, :, i] += 5000.0 * (1 - abs(i - onset_sample - 7) / 8.0)

        class FakeGrid:
            x = np.linspace(0, 2000, n_x)
            y = np.linspace(0, 800, n_y)

        result = derive_independent_time_zero(volume, FakeGrid(), sample_interval_ns,
                                               y_margin_mm=0.0)
        assert result.status == TimeZeroStatus.DERIVED
        assert result.correction_ns == pytest.approx(onset_sample * sample_interval_ns, abs=1.0)


# --- classify ----------------------------------------------------------------

def _fixed_result(mean_v=0.12, spread_frac=0.05, depth_err=None, usable=True, reason="ok"):
    from scripts.bam_independent_t0_velocity_audit import FixedT0Result
    return FixedT0Result(
        t0_ns=TRUE_T0_NS, per_target_velocity_m_per_ns={"t0": mean_v}, usable_targets=["t0", "t1"],
        mean_velocity_m_per_ns=mean_v, velocity_spread_frac=spread_frac,
        depth_predicted_mm={}, depth_error_mm=depth_err or {}, rms_depth_error_mm=1.0,
        max_depth_error_mm=1.0, usable=usable, reason=reason,
    )


class TestClassify:
    def test_failed_when_t0_did_not_resolve(self):
        result, reasons = classify(_unresolved_t0(), _fixed_result(), {}, {}, [], [])
        assert result == "FAILED"

    def test_failed_when_fixed_fit_is_unusable(self):
        result, reasons = classify(_resolved_t0(), _fixed_result(usable=False, mean_v=None,
                                                                  reason="too few targets"),
                                   {}, {}, [], [])
        assert result == "FAILED"

    def test_inconclusive_when_targets_disagree_with_each_other(self):
        result, reasons = classify(_resolved_t0(), _fixed_result(spread_frac=0.30), {}, {}, [], [])
        assert result == "INCONCLUSIVE"

    def test_estimated_not_validated_when_comparison_is_not_comparable(self):
        comparison = {"comparable": False, "reason": "no hyperbola converged"}
        result, reasons = classify(_resolved_t0(), _fixed_result(), comparison, {}, [], [])
        assert result == "ESTIMATED BUT NOT VALIDATED"

    def test_estimated_not_validated_on_material_disagreement_with_method_b(self):
        comparison = {"comparable": True, "material_disagreement": True,
                      "method_a_velocity_m_per_ns": 0.12, "method_b_mean_velocity_m_per_ns": 0.20,
                      "relative_disagreement": 0.67}
        result, reasons = classify(_resolved_t0(), _fixed_result(), comparison, {}, [], [])
        assert result == "ESTIMATED BUT NOT VALIDATED"

    def test_estimated_not_validated_on_large_depth_error(self):
        associations = [_assoc(_target("t0", 100.0), _exact_pick(_target("t0", 100.0)))]
        comparison = {"comparable": True, "material_disagreement": False}
        fixed = _fixed_result(depth_err={"t0": 50.0})  # 50mm on a 100mm target = 50%, way over 8%
        result, reasons = classify(_resolved_t0(), fixed, comparison, {}, [], associations)
        assert result == "ESTIMATED BUT NOT VALIDATED"

    def test_estimated_not_validated_when_unstable_to_t0_uncertainty(self):
        comparison = {"comparable": True, "material_disagreement": False}
        sensitivity = {"max_velocity_delta_frac": 0.40, "t0_uncertainty_ns": 0.2}
        result, reasons = classify(_resolved_t0(), _fixed_result(depth_err={}), comparison,
                                   sensitivity, [], [])
        assert result == "ESTIMATED BUT NOT VALIDATED"

    def test_validated_when_every_check_passes(self):
        associations = [_assoc(_target("t0", 100.0), _exact_pick(_target("t0", 100.0)))]
        comparison = {"comparable": True, "material_disagreement": False}
        sensitivity = {"max_velocity_delta_frac": 0.01, "t0_uncertainty_ns": 0.05}
        fixed = _fixed_result(depth_err={"t0": 0.5})
        result, reasons = classify(_resolved_t0(), fixed, comparison, sensitivity, [], associations)
        assert result == "VALIDATED VELOCITY"

    def test_never_returns_validated_without_every_check_passing(self):
        """The same 'conservative by construction' guarantee
        test_bam_hyperbola_velocity_audit.py already pins for the original
        classify() -- every downgrade branch really does downgrade."""
        associations = [_assoc(_target("t0", 100.0), _exact_pick(_target("t0", 100.0)))]
        good_comparison = {"comparable": True, "material_disagreement": False}
        good_sensitivity = {"max_velocity_delta_frac": 0.01, "t0_uncertainty_ns": 0.05}
        good_fixed = _fixed_result(depth_err={"t0": 0.5})

        bad_t0 = classify(_unresolved_t0(), good_fixed, good_comparison, good_sensitivity, [],
                          associations)
        bad_spread = classify(_resolved_t0(), _fixed_result(spread_frac=0.5, depth_err={"t0": 0.5}),
                              good_comparison, good_sensitivity, [], associations)
        bad_comparison = classify(_resolved_t0(), good_fixed,
                                  {"comparable": True, "material_disagreement": True,
                                   "method_a_velocity_m_per_ns": 0.12,
                                   "method_b_mean_velocity_m_per_ns": 0.30,
                                   "relative_disagreement": 1.5},
                                  good_sensitivity, [], associations)
        for outcome, _ in (bad_t0, bad_spread, bad_comparison):
            assert outcome != "VALIDATED VELOCITY"
