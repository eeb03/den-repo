"""
Deterministic tests for the air-WARR cross-correlation t0 experiment and the
fixed-t0 crosshole velocity fit. All synthetic -- none depend on the
downloaded TestUM archive, and none hardcode the real (INCONCLUSIVE) result.
"""
from __future__ import annotations

import numpy as np
import pytest

from scripts.testum_air_warr_crosscorr_t0 import (
    MIN_PEAK_NCC,
    FileResult,
    ReferencePick,
    aggregate_t0,
    classify_overall,
    cross_correlate,
    detrend,
    fit_velocity_fixed_t0,
    leave_one_out_fixed_t0,
    pick_reference_absolute_time,
    sensitivity_to_pick_perturbation,
    sensitivity_to_t0_uncertainty,
)
from scripts.testum_crosshole_velocity_audit import PairResult


def _wavelet(n=200, center=100.0, width=6.0, amp=5000.0):
    """A single Ricker-like (Mexican-hat) pulse -- a stand-in for a real
    band-limited radar wavelet: oscillatory, localised, zero-mean tails."""
    t = np.arange(n, dtype=float)
    x = (t - center) / width
    return amp * (1 - x ** 2) * np.exp(-x ** 2 / 2)


def _with_baseline(signal, drift=3000.0):
    n = len(signal)
    t = np.arange(n, dtype=float)
    baseline = drift * np.sin(t / n * np.pi) - 2000.0
    return signal + baseline


def _pair(tx, rx, L, t, usable=True):
    return PairResult(tx=tx, rx=rx, file_name=f"{tx}_{rx}.DZT", separation_m=L,
                      n_traces=67, n_usable=60, n_unusable=7, picked_times_ns=[t],
                      picked_confidences=[10.0], median_time_ns=t, time_spread_ns=1.0,
                      usable=usable, reason="synthetic")


class TestDetrend:
    def test_a_pure_polynomial_baseline_is_removed_to_near_zero(self):
        n = 200
        x = np.arange(n, dtype=float)
        baseline = 0.001 * x ** 2 - 0.5 * x + 100.0
        detrended = detrend(list(baseline), degree=3)
        assert np.max(np.abs(detrended)) < 1e-6

    def test_a_wavelet_riding_on_a_baseline_keeps_most_of_its_own_shape(self):
        wavelet = _wavelet()
        combined = _with_baseline(wavelet)
        detrended = detrend(list(combined), degree=3)
        # The wavelet's own peak-to-peak structure should survive detrending.
        assert np.max(np.abs(detrended)) > np.max(np.abs(wavelet)) * 0.5


class TestCrossCorrelate:
    def test_an_identical_trace_aligns_at_zero_lag_with_perfect_correlation(self):
        w = detrend(list(_with_baseline(_wavelet())))
        result = cross_correlate(w, w, dt_ns=0.1)
        assert result.accepted
        assert result.lag_samples == pytest.approx(0.0, abs=1e-6)
        assert result.peak_ncc == pytest.approx(1.0, abs=1e-6)

    def test_a_known_integer_shift_is_recovered(self):
        base = _wavelet(n=300, center=150.0)
        shifted = _wavelet(n=300, center=145.0)  # other arrives 5 samples EARLIER
        ref = detrend(list(_with_baseline(base)))
        oth = detrend(list(_with_baseline(shifted)))
        result = cross_correlate(ref, oth, dt_ns=0.5)
        assert result.accepted
        # ref is later than oth by 5 samples -> lag should be +5
        assert result.lag_samples == pytest.approx(5.0, abs=0.5)
        assert result.lag_ns == pytest.approx(2.5, abs=0.25)

    def test_pure_noise_is_rejected_by_the_quality_gate(self):
        rng = np.random.default_rng(42)
        ref = rng.normal(size=300)
        oth = rng.normal(size=300)
        result = cross_correlate(ref, oth, dt_ns=0.1)
        assert not result.accepted

    def test_an_inverted_polarity_match_is_rejected_regardless_of_magnitude(self):
        base = _wavelet(n=300, center=150.0)
        inverted = -base  # perfect anti-correlation
        result = cross_correlate(base, inverted, dt_ns=0.5)
        assert result.peak_ncc < 0
        assert not result.accepted
        assert "anti-phase" in result.reason

    def test_a_zero_energy_trace_is_rejected_not_crashed_on(self):
        ref = _wavelet()
        zero = np.zeros_like(ref)
        result = cross_correlate(ref, zero, dt_ns=0.1)
        assert not result.accepted
        assert "zero-energy" in result.reason

    def test_acceptance_threshold_is_the_documented_constant(self):
        assert 0.0 < MIN_PEAK_NCC < 1.0


class TestReferencePick:
    def test_a_clear_pulse_in_the_search_window_is_picked_with_high_confidence(self):
        dt = 0.0732421875  # real file's own sample interval
        n = 400
        # place a pulse at ~10 ns (within [2, 30] ns search window)
        idx = int(10.0 / dt)
        trace = np.zeros(n)
        trace[idx - 3:idx + 4] = [100, 500, 3000, 8000, 3000, 500, 100]
        result = pick_reference_absolute_time(trace, dt)
        assert result.accepted
        assert 8.0 < result.time_ns < 12.0

    def test_flat_noise_is_rejected(self):
        rng = np.random.default_rng(1)
        dt = 0.1
        trace = rng.normal(scale=10.0, size=400)
        result = pick_reference_absolute_time(trace, dt)
        assert not result.accepted

    def test_a_search_window_too_narrow_for_the_sampling_is_reported_not_crashed(self):
        result = pick_reference_absolute_time(np.zeros(5), dt_ns=50.0)
        assert not result.accepted
        assert "too narrow" in result.reason


class TestAggregateT0:
    def _file(self, t0, confirmed=True, date="2023-01-01"):
        return FileResult(
            file_name=f"f_{date}.DZT", date=date, slot="end", x_start_m=1.0, x_end_m=3.0, dx_m=0.2,
            n_traces=11, reference_index=10, reference_pick=ReferencePick(10.0, 8.0, True, "ok"),
            observations=[], n_accepted=3, n_rejected=8, slope_fit_attempted=True,
            fitted_slope_ns_per_m=3.336, fitted_t0_ns=t0, slope_error_pct=1.0,
            geometry_confirmed=confirmed, usable=confirmed, reason="synthetic",
        )

    def test_tightly_agreeing_files_are_independently_identifiable(self):
        files = [self._file(20.0, date="2023-01-01"), self._file(20.5, date="2023-01-02"),
                self._file(19.8, date="2023-01-03")]
        agg = aggregate_t0(files)
        assert agg["t0_independently_identifiable"] is True
        assert agg["fitted_t0_stats"]["n"] == 3

    def test_widely_disagreeing_files_are_not_independently_identifiable(self):
        files = [self._file(15.0, date="2023-01-01"), self._file(25.0, date="2023-01-02")]
        agg = aggregate_t0(files)
        assert agg["t0_independently_identifiable"] is False

    def test_a_single_confirmed_file_is_not_enough_to_call_it_identifiable(self):
        files = [self._file(20.0), self._file(0.0, confirmed=False)]
        agg = aggregate_t0(files)
        assert agg["files_geometry_confirmed"] == 1
        assert agg["t0_independently_identifiable"] is False

    def test_no_confirmed_files_reports_the_honest_zero_state(self):
        files = [self._file(0.0, confirmed=False), self._file(0.0, confirmed=False)]
        agg = aggregate_t0(files)
        assert agg["files_geometry_confirmed"] == 0
        assert agg["fitted_t0_stats"] is None
        assert agg["t0_independently_identifiable"] is False


class TestFixedT0VelocityFit:
    def test_a_clean_design_recovers_the_true_velocity(self):
        true_t0, true_v = 10.0, 0.04
        pairs = [_pair("A", "B", L, true_t0 + L / true_v) for L in (1.0, 2.0, 3.0, 4.0)]
        fit = fit_velocity_fixed_t0(pairs, true_t0)
        assert fit.velocity_m_per_ns == pytest.approx(true_v, rel=1e-6)
        assert fit.rms_residual_ns == pytest.approx(0.0, abs=1e-6)

    def test_a_single_pair_still_produces_a_velocity_with_one_free_parameter(self):
        pairs = [_pair("A", "B", 2.0, 10.0 + 2.0 / 0.04)]
        fit = fit_velocity_fixed_t0(pairs, 10.0)
        assert fit.velocity_m_per_ns == pytest.approx(0.04, rel=1e-6)

    def test_a_t0_exceeding_the_observed_time_is_non_physical_and_rejected(self):
        pairs = [_pair("A", "B", 1.0, 5.0)]
        fit = fit_velocity_fixed_t0(pairs, t0_ns=10.0)  # t0 > observed time
        assert fit.velocity_m_per_ns is None
        assert "exceeds the observed arrival time" in fit.note

    def test_no_usable_pairs_is_reported_not_crashed(self):
        fit = fit_velocity_fixed_t0([_pair("A", "B", 1.0, 5.0, usable=False)], t0_ns=1.0)
        assert fit.velocity_m_per_ns is None
        assert fit.n_pairs == 0

    def test_unusable_pairs_are_excluded_from_the_fit(self):
        pairs = [
            _pair("A", "B", 1.0, 10.0 + 1.0 / 0.04),
            _pair("C", "D", 999.0, -1.0, usable=False),
            _pair("E", "F", 3.0, 10.0 + 3.0 / 0.04),
        ]
        fit = fit_velocity_fixed_t0(pairs, 10.0)
        assert fit.n_pairs == 2
        assert fit.velocity_m_per_ns == pytest.approx(0.04, rel=1e-6)


class TestLeaveOneOutFixedT0:
    def test_a_perfect_design_predicts_the_held_out_point_exactly(self):
        true_t0, true_v = 10.0, 0.04
        pairs = [_pair(chr(65 + i), chr(66 + i), L, true_t0 + L / true_v)
                for i, L in enumerate((1.0, 2.0, 3.0, 4.0))]
        loo = leave_one_out_fixed_t0(pairs, true_t0)
        assert len(loo) == 4
        for r in loo:
            assert r["error_ns"] == pytest.approx(0.0, abs=1e-6)


class TestSensitivityToT0Uncertainty:
    def test_zero_uncertainty_produces_zero_velocity_spread(self):
        true_t0, true_v = 10.0, 0.04
        pairs = [_pair(chr(65 + i), chr(66 + i), L, true_t0 + L / true_v)
                for i, L in enumerate((1.0, 2.0, 3.0, 4.0))]
        result = sensitivity_to_t0_uncertainty(pairs, true_t0, t0_uncertainty=0.0)
        assert result["max_velocity_delta_frac"] == pytest.approx(0.0, abs=1e-9)

    def test_larger_t0_uncertainty_produces_larger_or_equal_velocity_spread(self):
        true_t0, true_v = 10.0, 0.04
        pairs = [_pair(chr(65 + i), chr(66 + i), L, true_t0 + L / true_v)
                for i, L in enumerate((1.0, 2.0, 3.0, 4.0))]
        small = sensitivity_to_t0_uncertainty(pairs, true_t0, t0_uncertainty=0.5)
        large = sensitivity_to_t0_uncertainty(pairs, true_t0, t0_uncertainty=5.0)
        assert large["max_velocity_delta_frac"] >= small["max_velocity_delta_frac"]


class TestSensitivityToPickPerturbation:
    def test_perturbing_one_pair_at_a_time_moves_velocity_away_from_the_base_fit(self):
        true_t0, true_v = 10.0, 0.04
        pairs = [_pair(chr(65 + i), chr(66 + i), L, true_t0 + L / true_v)
                for i, L in enumerate((1.0, 2.0, 3.0, 4.0, 5.0))]
        result = sensitivity_to_pick_perturbation(pairs, true_t0, sample_interval_ns=0.1465)
        assert result["base_velocity_m_per_ns"] == pytest.approx(true_v, rel=1e-6)
        assert result["max_velocity_delta_frac"] is not None
        assert result["max_velocity_delta_frac"] > 0


class TestClassifyOverall:
    def _t0_agg(self, identifiable, note="synthetic"):
        return {"t0_independently_identifiable": identifiable, "identifiability_note": note}

    def test_t0_not_identifiable_is_inconclusive_and_all_claims_false(self):
        cls, claims, reasons = classify_overall(self._t0_agg(False), None, [], None)
        assert cls == "INCONCLUSIVE"
        assert claims["t0_independently_constrained"] is False
        assert claims["velocity_independently_validated"] is False

    def test_an_identifiable_t0_but_failed_velocity_fit_is_failed(self):
        from scripts.testum_air_warr_crosscorr_t0 import FixedT0FitResult
        fit = FixedT0FitResult(10.0, 0, None, None, None, {}, "no usable pairs")
        cls, claims, reasons = classify_overall(self._t0_agg(True), fit, [], None)
        assert cls == "FAILED"

    def test_never_reaches_validated_velocity_even_when_everything_else_passes(self):
        from scripts.testum_air_warr_crosscorr_t0 import FixedT0FitResult
        fit = FixedT0FitResult(10.0, 5, 0.05, 0.5, 1.0, {}, "clean fit")
        loo = [{"error_ns": 0.1}, {"error_ns": 0.2}]
        sens = {"max_velocity_delta_frac": 0.01}
        cls, claims, reasons = classify_overall(self._t0_agg(True), fit, loo, sens)
        assert cls != "VALIDATED VELOCITY"
        assert claims["velocity_independently_validated"] is False

    def test_an_implausible_velocity_is_failed_even_with_identifiable_t0(self):
        from scripts.testum_air_warr_crosscorr_t0 import FixedT0FitResult
        fit = FixedT0FitResult(10.0, 3, 5.0, 0.1, 0.2, {}, "implausible")  # 5 m/ns, absurd
        cls, claims, reasons = classify_overall(self._t0_agg(True), fit, [], None)
        assert cls == "FAILED"
        assert claims["velocity_physically_plausible"] is False
