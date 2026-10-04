"""
Adversarial tests for Method C's validity checks (`preprocessing.time_zero`).

Each refusal case reproduces a failure MECHANISM documented in
docs/timezero-method-c-validation.md section 3 on synthetic traces whose truth
is known by construction. The raw picker is shown to produce a confident,
line-consistent pick on each of them first -- the false `derived` the checks
exist to stop -- so these tests fail if a check is removed.

The acceptance cases pin the other direction: a clean bipolar wavelet, a
one-sided transient pulse, and a direct wave followed by strong ringing are
still DERIVED, at the same pick the unchecked picker gives (the checks only
refuse; they never move a pick).

No case here is drawn from, or tuned on, the operator-reference corpus.
"""
from __future__ import annotations

import math
import random
import statistics

import pytest

from preprocessing.time_zero import (
    REJECT_NOT_TRANSIENT, REJECT_QUIET_CONTAMINATED, REJECT_SLOW_RISE, _pick_onset_ns,
    apply_time_zero_for_dataset, direct_wave_consensus_time_zero,
)
from schemas.depth_model import DepthStatus, frame_depth_readiness
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.time_zero import TimeZeroStatus

DT = 0.5  # ns per sample
N = 400
N_TRACES = 20


def _rec(signal):
    return SubterraRecord.model_construct(
        dataset_id="ds", latitude=None, longitude=None, elevation=None, depth=None,
        signal=list(signal), sensor_type=SensorType.GPR, ground_truth="none", metadata={})


def _ricker(t_ns, f_ghz):
    a = (math.pi * f_ghz * t_ns) ** 2
    return (1 - 2 * a) * math.exp(-a)


def _noise(seed, sigma=1.0):
    rng = random.Random(seed)
    return [rng.gauss(0, sigma) for _ in range(N)]


def _wavelet_trace(seed, peak_ns=40.0, f_ghz=0.25, amp=3000.0, ringing=False):
    tr = _noise(seed)
    for i in range(N):
        t = i * DT - peak_ns
        tr[i] += amp * _ricker(t, f_ghz)
        if ringing and t > 0:
            tr[i] += 0.6 * amp * math.sin(2 * math.pi * f_ghz * t) * math.exp(-t / 60.0)
    return tr


def _line(make):
    return [_rec(make(seed)) for seed in range(N_TRACES)]


def _raw_picks(records):
    return [_pick_onset_ns(r.signal, DT) for r in records]


def _assert_raw_picker_is_fooled(records):
    """The unchecked picker returns a tight, confident consensus -- a false derived."""
    picks = [p[0] for p in _raw_picks(records) if p is not None]
    assert len(picks) == len(records)
    assert max(picks) - min(picks) <= 2.0


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------

class TestMethodCRefuses:
    def test_monotone_drift_with_no_direct_wave_is_refused(self):
        """Mode 3: a smooth drift crosses 5 sigma at the same time on every trace."""
        def drift(seed):
            return [x + 0.5 * max(0, i - 20) ** 2 for i, x in enumerate(_noise(seed))]
        records = _line(drift)
        _assert_raw_picker_is_fooled(records)
        result = direct_wave_consensus_time_zero(records, DT)
        assert result.status is TimeZeroStatus.INCONCLUSIVE
        assert result.correction_ns is None
        assert set(result.pick_rejections) <= {REJECT_NOT_TRANSIENT, REJECT_SLOW_RISE}
        assert sum(result.pick_rejections.values()) == N_TRACES

    def test_a_baseline_step_is_not_a_direct_wave(self):
        def step(seed):
            return [x + (400.0 if i >= 60 else 0.0) for i, x in enumerate(_noise(seed))]
        records = _line(step)
        _assert_raw_picker_is_fooled(records)
        result = direct_wave_consensus_time_zero(records, DT)
        assert result.status is TimeZeroStatus.INCONCLUSIVE
        assert result.pick_rejections.get(REJECT_NOT_TRANSIENT, 0) + \
            result.pick_rejections.get(REJECT_SLOW_RISE, 0) == N_TRACES

    def test_a_slow_wow_rising_over_a_large_part_of_the_window_is_refused(self):
        tau = 30.0  # samples; peak at tau, far beyond a direct wave's quarter period

        def wow(seed):
            return [x + 2000.0 * max(0, i - 10) / tau * math.exp(-max(0, i - 10) / tau)
                    for i, x in enumerate(_noise(seed))]
        records = _line(wow)
        _assert_raw_picker_is_fooled(records)
        # a 30-sample rise is under 10% of a 400-sample window, so shorten the record
        short = [_rec(r.signal[:200]) for r in records]
        result = direct_wave_consensus_time_zero(short, DT)
        assert result.status is TimeZeroStatus.INCONCLUSIVE
        assert REJECT_SLOW_RISE in result.pick_rejections

    def test_an_arrival_inside_the_quiet_window_is_refused(self):
        """Mode 2: the noise floor is estimated from samples that already hold the wave."""
        def early(seed):
            # wavelet energy starts around sample 4 of the 8-sample quiet window
            return _wavelet_trace(seed, peak_ns=5.5, f_ghz=0.25)
        records = _line(early)
        result = direct_wave_consensus_time_zero(records, DT)
        assert result.status is TimeZeroStatus.INCONCLUSIVE
        assert result.pick_rejections.get(REJECT_QUIET_CONTAMINATED, 0) > N_TRACES // 2

    def test_ringing_from_the_first_sample_has_no_defensible_time_zero(self):
        def ringing(seed):
            return [x + 300 * math.sin(2 * math.pi * i / 9.0) for i, x in enumerate(_noise(seed))]
        result = direct_wave_consensus_time_zero(_line(ringing), DT)
        assert result.status is TimeZeroStatus.INCONCLUSIVE
        assert result.correction_ns is None

    def test_a_weak_direct_wave_below_threshold_is_not_guessed(self):
        result = direct_wave_consensus_time_zero(
            _line(lambda s: _wavelet_trace(s, amp=2.0)), DT)
        assert result.status is TimeZeroStatus.INCONCLUSIVE
        assert result.correction_ns is None

    def test_drift_ahead_of_a_real_wave_is_refused_not_repicked_later(self):
        """The checks refuse; they never go looking for a later, nicer event."""
        def drift_then_wave(seed):
            tr = _wavelet_trace(seed, peak_ns=120.0)
            return [x + 0.5 * max(0, i - 20) ** 2 for i, x in enumerate(tr)]
        result = direct_wave_consensus_time_zero(_line(drift_then_wave), DT)
        assert result.status is TimeZeroStatus.INCONCLUSIVE

    def test_refusal_reasons_reach_the_processing_stamp(self):
        def drift(seed):
            return [x + 0.5 * max(0, i - 20) ** 2 for i, x in enumerate(_noise(seed))]
        result = direct_wave_consensus_time_zero(_line(drift), DT)
        stamp = result.as_processing_applied()
        assert stamp["time_zero_status"] == "inconclusive"
        assert sum(stamp["time_zero_pick_rejections"].values()) == N_TRACES
        assert "validity checks" in result.basis


# --------------------------------------------------------------------------
# acceptances: the checks must not refuse a real direct wave
# --------------------------------------------------------------------------

class TestMethodCStillAccepts:
    @pytest.mark.parametrize("ringing", [False, True])
    def test_a_bipolar_wavelet_is_derived_at_the_unchecked_pick(self, ringing):
        records = _line(lambda s: _wavelet_trace(s, ringing=ringing))
        result = direct_wave_consensus_time_zero(records, DT)
        assert result.status is TimeZeroStatus.DERIVED
        assert not result.pick_rejections
        raw = statistics.median(p[0] for p in _raw_picks(records))
        assert result.correction_ns == pytest.approx(raw, abs=1e-9)
        # the onset is before the wavelet peak, never after it
        assert result.correction_ns < 40.0

    def test_a_one_sided_transient_pulse_is_still_accepted(self):
        def tri(seed):
            tr = _noise(seed)
            for i in range(60, 75):
                tr[i] += 5000 * (1 - abs(i - 67) / 8.0)
            return tr
        result = direct_wave_consensus_time_zero(_line(tri), DT)
        assert result.status is TimeZeroStatus.DERIVED
        assert result.correction_ns == pytest.approx(30.0, abs=1.0)

    def test_a_minority_of_flagged_traces_does_not_veto_the_line(self):
        def mixed(seed):
            if seed < 4:
                return [x + 0.5 * max(0, i - 20) ** 2 for i, x in enumerate(_noise(seed))]
            return _wavelet_trace(seed)
        result = direct_wave_consensus_time_zero(_line(mixed), DT)
        assert result.status is TimeZeroStatus.DERIVED
        assert sum(result.pick_rejections.values()) == 4

    def test_noise_only_quiet_windows_are_rarely_flagged(self):
        """Per-trace false-flag rate of the contamination rule on Gaussian noise."""
        from preprocessing.time_zero import _quiet_window_contaminated
        rng = random.Random(7)
        flagged = sum(_quiet_window_contaminated([rng.gauss(0, 1) for _ in range(8)])
                      for _ in range(20000))
        assert flagged / 20000 < 0.04


# --------------------------------------------------------------------------
# end to end: a refused time zero never becomes depth from a physical event
# --------------------------------------------------------------------------

def test_a_drift_line_gets_no_corrected_time_and_depth_stays_approximate():
    from schemas.spatial import AxisKind, CRSKind, SpatialRef, VerticalAxis
    from schemas.survey_frame import SurveyFrame

    frame = SurveyFrame(
        frame_id="ds:drift", dataset_id="ds", modality=SensorType.GPR, source_format="segy",
        source_file="d.sgy", spatial_ref=SpatialRef(kind=CRSKind.UNKNOWN, name="none"),
        vertical_axis=VerticalAxis(
            kind=AxisKind.TWO_WAY_TIME_NS, units="ns", origin="instrument time zero",
            positive_down=True,
            conversion={"method": "constant_velocity", "velocity_m_per_ns": 0.12,
                        "velocity_basis": "user_declared", "basis": "site note"}),
        n_positions=N_TRACES, position_index_name="trace_index")
    records = []
    for t in range(N_TRACES):
        tr = [x + 0.5 * max(0, i - 20) ** 2 for i, x in enumerate(_noise(t))]
        for i, v in enumerate(tr):
            records.append(SubterraRecord.model_construct(
                dataset_id="ds", latitude=None, longitude=None, elevation=None,
                depth=i * DT * 0.12 / 2, signal=[v], sensor_type=SensorType.GPR,
                ground_truth="none", frame_id="ds:drift",
                metadata={"source_file": "d.sgy", "trace_index": t, "sample_index": i,
                          "two_way_time_ns": i * DT, "velocity_m_per_ns": 0.12}))
    _, results = apply_time_zero_for_dataset(records, [frame])
    assert results["ds:drift"].status is TimeZeroStatus.INCONCLUSIVE
    assert all(r.metadata["corrected_time_ns"] is None for r in records)
    readiness = frame_depth_readiness(frame)
    assert readiness.status is DepthStatus.APPROXIMATE
    assert any("time zero is not established" in r for r in readiness.reasons)
    assert readiness.as_dict()["scientifically_sufficient"] is False
