"""
Deterministic tests for the TestUM crosshole velocity audit's own math:
the joint t0/v fit, leave-one-out, permittivity, and classification. All
use synthetic fixtures only -- none hardcode the real TestUM result.
"""
from __future__ import annotations

import pytest

from scripts.testum_crosshole_velocity_audit import (
    C_M_PER_NS,
    PairResult,
    classify,
    fit_joint,
    leave_one_out,
    relative_permittivity,
    surveyed_separation_m,
)


def _pair(tx, rx, L, t, usable=True, n_traces=67, n_usable=60):
    return PairResult(tx=tx, rx=rx, file_name=f"{tx}_{rx}.DZT", separation_m=L,
                      n_traces=n_traces, n_usable=n_usable, n_unusable=n_traces - n_usable,
                      picked_times_ns=[t], picked_confidences=[10.0],
                      median_time_ns=t, time_spread_ns=1.0, usable=usable,
                      reason="synthetic")


_ID = "ABCDEFGHIJKLMNOP"


def _linear_pairs(true_t0, true_v, separations):
    return [_pair(_ID[2 * i], _ID[2 * i + 1], L, true_t0 + L / true_v)
           for i, L in enumerate(separations)]


class TestFitJoint:
    def test_a_clean_linear_design_recovers_the_true_velocity_and_t0(self):
        true_t0, true_v = 5.0, 0.05
        pairs = _linear_pairs(true_t0, true_v, (1.0, 2.0, 4.0, 8.0))
        fit = fit_joint(pairs)
        assert fit.velocity_m_per_ns == pytest.approx(true_v, rel=1e-6)
        assert fit.t0_ns == pytest.approx(true_t0, rel=1e-6)
        assert fit.identifiable is True

    def test_two_pairs_are_exactly_determined_not_independently_checkable(self):
        pairs = [_pair("A", "B", 1.0, 5.0 + 1.0 / 0.05), _pair("C", "D", 4.0, 5.0 + 4.0 / 0.05)]
        fit = fit_joint(pairs)
        assert fit.velocity_m_per_ns is not None
        assert fit.identifiable is False
        assert "exactly determined" in fit.identifiability_note

    def test_fewer_than_two_usable_pairs_fails_outright(self):
        fit = fit_joint([_pair("A", "B", 1.0, 30.0, usable=False)])
        assert fit.velocity_m_per_ns is None
        assert "only 1 usable" in fit.identifiability_note or fit.n_pairs == 0

    def test_a_non_physical_negative_velocity_is_rejected_not_reported(self):
        # Time DECREASING with separation -- physically impossible.
        pairs = [_pair("A", "B", 1.0, 50.0), _pair("C", "D", 4.0, 10.0), _pair("E", "F", 8.0, 5.0)]
        fit = fit_joint(pairs)
        assert fit.velocity_m_per_ns is None
        assert "non-physical" in fit.identifiability_note

    def test_a_velocity_outside_the_plausible_range_is_rejected(self):
        # Slope implies v = 10 m/ns, far outside any GPR-plausible range.
        pairs = [_pair("A", "B", 1.0, 0.1), _pair("C", "D", 10.0, 1.0), _pair("E", "F", 20.0, 2.0)]
        fit = fit_joint(pairs)
        assert fit.velocity_m_per_ns is None
        assert "outside the physically plausible range" in fit.identifiability_note

    def test_nearly_collinear_separations_are_confounded(self):
        # Separations all close together relative to their mean -> high leverage
        # correlation between t0 and slope, mirroring the real BAM/TestUM pattern.
        true_t0, true_v = 5.0, 0.04
        pairs = _linear_pairs(true_t0, true_v, (5.0, 5.2, 5.4, 5.6, 5.8))
        fit = fit_joint(pairs)
        assert fit.velocity_m_per_ns is not None
        assert fit.identifiable is False
        assert "CONFOUNDED" in fit.identifiability_note

    def test_unusable_pairs_are_excluded_from_the_fit(self):
        pairs = [
            _pair("A", "B", 1.0, 5.0 + 1.0 / 0.05),
            _pair("C", "D", 999.0, -1.0, usable=False),  # would break the fit if included
            _pair("E", "F", 4.0, 5.0 + 4.0 / 0.05),
            _pair("G", "H", 8.0, 5.0 + 8.0 / 0.05),
        ]
        fit = fit_joint(pairs)
        assert fit.n_pairs == 3
        assert fit.velocity_m_per_ns == pytest.approx(0.05, rel=1e-6)


class TestLeaveOneOut:
    def test_a_perfectly_linear_design_predicts_the_held_out_point_exactly(self):
        true_t0, true_v = 5.0, 0.05
        pairs = _linear_pairs(true_t0, true_v, (1.0, 2.0, 4.0, 8.0))
        loo = leave_one_out(pairs)
        assert len(loo) == 4
        for r in loo:
            assert r["error_ns"] == pytest.approx(0.0, abs=1e-6)

    def test_a_noisy_point_produces_a_nonzero_but_bounded_error(self):
        true_t0, true_v = 5.0, 0.05
        pairs = _linear_pairs(true_t0, true_v, (1.0, 2.0, 4.0, 8.0))
        pairs[0] = _pair(pairs[0].tx, pairs[0].rx, 1.0, true_t0 + 1.0 / true_v + 5.0)  # perturbed
        loo = leave_one_out(pairs)
        held = next(r for r in loo if r["held_out"] == f"{pairs[0].tx}-{pairs[0].rx}")
        assert held["error_ns"] is not None
        assert abs(held["error_ns"]) > 0.1


class TestRelativePermittivity:
    def test_the_speed_of_light_implies_unit_permittivity(self):
        rp = relative_permittivity(C_M_PER_NS)
        assert rp["relative_permittivity"] == pytest.approx(1.0, rel=1e-6)

    def test_a_water_like_velocity_falls_inside_the_saturated_reference_range(self):
        v_water = C_M_PER_NS / (80.0 ** 0.5)
        rp = relative_permittivity(v_water)
        assert rp["within_saturated_reference_range"] is True

    def test_none_in_none_out(self):
        assert relative_permittivity(None) is None


class TestClassify:
    def _fit(self, identifiable, v=0.04, note="ok"):
        from scripts.testum_crosshole_velocity_audit import JointFitResult
        return JointFitResult(n_pairs=5, t0_ns=10.0, velocity_m_per_ns=v,
                              parameter_correlation=-0.5 if identifiable else -0.99,
                              identifiable=identifiable, identifiability_note=note,
                              residuals_ns={}, rms_residual_ns=1.0, max_residual_ns=2.0)

    def test_fewer_than_two_usable_pairs_is_failed(self):
        pairs = [_pair("A", "B", 1.0, 30.0, usable=False)]
        from scripts.testum_crosshole_velocity_audit import JointFitResult
        fit = JointFitResult(0, None, None, None, False, "only 0 usable pair(s)", {}, None, None)
        cls, reasons = classify(fit, pairs, [])
        assert cls == "FAILED"

    def test_a_confounded_fit_is_inconclusive_not_downgraded_further(self):
        pairs = _linear_pairs(10.0, 0.04, (1.0, 2.0, 3.0, 4.0, 5.0))
        fit = self._fit(identifiable=False)
        cls, reasons = classify(fit, pairs, [])
        assert cls == "INCONCLUSIVE"

    def test_an_identifiable_fit_with_no_independent_depth_truth_is_capped(self):
        pairs = _linear_pairs(10.0, 0.04, (1.0, 2.0, 3.0, 4.0, 5.0))
        fit = self._fit(identifiable=True)
        cls, reasons = classify(fit, pairs, [])
        assert cls == "ESTIMATED BUT NOT VALIDATED"
        assert cls != "VALIDATED VELOCITY"

    def test_an_identifiable_but_unstable_loo_is_also_capped_at_estimated(self):
        pairs = _linear_pairs(10.0, 0.04, (1.0, 2.0, 3.0, 4.0, 5.0))
        fit = self._fit(identifiable=True)
        loo = [{"held_out": "A-B", "error_ns": 25.0}]
        cls, reasons = classify(fit, pairs, loo)
        assert cls == "ESTIMATED BUT NOT VALIDATED"
        assert any("leave-one-out" in r for r in reasons)


class TestSurveyedSeparation:
    def test_a_known_right_triangle_gives_the_expected_distance(self):
        wells = {"A": (0.0, 0.0), "B": (3.0, 4.0)}
        assert surveyed_separation_m(wells, "A", "B") == pytest.approx(5.0)

    def test_a_missing_well_fails_loudly_not_silently(self):
        from scripts.testum_crosshole_velocity_audit import AuditError
        wells = {"A": (0.0, 0.0)}
        with pytest.raises(AuditError):
            surveyed_separation_m(wells, "A", "Z")
