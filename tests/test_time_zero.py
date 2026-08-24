"""
Tests for the time-zero correction framework: `schemas.time_zero` and
`preprocessing.time_zero`. All synthetic -- no real dataset is required for
these; the real-data experiment lives separately (see the final report).
"""
from __future__ import annotations

import pytest

from preprocessing.time_zero import (
    MAX_CONSENSUS_SPREAD_NS,
    apply_time_zero_correction,
    direct_wave_consensus_time_zero,
    metadata_instrument_time_zero,
    operator_declared_time_zero,
    recompute_depth_with_time_zero,
)
from schemas.provenance import ProvenanceClass, record_provenance
from schemas.spatial import Assumption
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame
from schemas.time_zero import TimeZeroMethod, TimeZeroResult, TimeZeroStatus


def _record(depth=None, metadata=None, dataset_id="ds"):
    return SubterraRecord.model_construct(
        dataset_id=dataset_id, latitude=None, longitude=None, elevation=None,
        depth=depth, signal=[0.0], sensor_type=SensorType.GPR, ground_truth="none",
        metadata=metadata or {},
    )


def _trace_record(signal, dataset_id="ds", **meta):
    return SubterraRecord.model_construct(
        dataset_id=dataset_id, latitude=None, longitude=None, elevation=None,
        depth=None, signal=list(signal), sensor_type=SensorType.GPR, ground_truth="none",
        metadata=dict(meta),
    )


def _frame(assumptions=None):
    from schemas.spatial import CRSKind, SpatialRef
    return SurveyFrame.model_construct(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy", source_file="line.sgy",
        spatial_ref=SpatialRef(kind=CRSKind.UNKNOWN, name="none"),
        vertical_axis=None, n_positions=1, position_index_name="trace_index",
        assumptions=assumptions or [],
    )


def _pulse(n=200, onset=60, amp=5000.0, noise=1.0, seed=0):
    """A synthetic trace: quiet noise floor, then a sustained pulse at `onset`."""
    import random
    rng = random.Random(seed)
    trace = [rng.gauss(0, noise) for _ in range(n)]
    for i in range(onset, min(onset + 15, n)):
        trace[i] += amp * (1 - abs(i - onset - 7) / 8.0)
    return trace


# --- 1. Raw preservation --------------------------------------------------

class TestRawPreservation:
    def test_original_time_axis_is_never_overwritten(self):
        r = _record(metadata={"two_way_time_ns": 42.0})
        result = TimeZeroResult(status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
                                correction_ns=5.0, basis="derived from x", applied=True)
        apply_time_zero_correction([r], result)
        assert r.metadata["original_time_ns"] == 42.0
        assert r.metadata["two_way_time_ns"] == 42.0  # untouched field, still present

    def test_corrected_time_is_a_new_key_not_a_substitution(self):
        r = _record(metadata={"two_way_time_ns": 42.0})
        result = TimeZeroResult(status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
                                correction_ns=5.0, basis="derived from x", applied=True)
        apply_time_zero_correction([r], result)
        assert r.metadata["corrected_time_ns"] == pytest.approx(37.0)
        assert "two_way_time_ns" in r.metadata and "corrected_time_ns" in r.metadata


# --- 2-3. Declared t0 ------------------------------------------------------

class TestDeclaredTimeZero:
    def test_a_declared_correction_applies_correctly(self):
        result = operator_declared_time_zero(11.8, source="operator note", evidence="site log")
        assert result.status == TimeZeroStatus.DECLARED
        assert result.correction_ns == 11.8

    def test_provenance_remains_declared_not_derived_or_measured(self):
        result = operator_declared_time_zero(11.8, source="operator note", evidence="site log")
        assert result.method == TimeZeroMethod.OPERATOR_DECLARED
        assert result.status == TimeZeroStatus.DECLARED
        assert result.status != TimeZeroStatus.DERIVED
        assert result.status != TimeZeroStatus.MEASURED

    def test_a_non_finite_declared_value_fails_rather_than_being_stored(self):
        result = operator_declared_time_zero(float("nan"), source="x", evidence="y")
        assert result.status == TimeZeroStatus.FAILED
        assert result.correction_ns is None


# --- 4-5. Derived t0 --------------------------------------------------------

class TestDirectWaveConsensus:
    def test_consistent_onsets_across_traces_produce_derived_status(self):
        traces = [_trace_record(_pulse(onset=60, seed=i)) for i in range(20)]
        result = direct_wave_consensus_time_zero(traces, sample_interval_ns=0.5)
        assert result.status == TimeZeroStatus.DERIVED
        assert result.method == TimeZeroMethod.DIRECT_WAVE_CONSENSUS
        assert result.correction_ns == pytest.approx(30.0, abs=1.0)  # onset=60 samples * 0.5ns

    def test_method_and_evidence_are_recorded(self):
        traces = [_trace_record(_pulse(onset=60, seed=i)) for i in range(20)]
        result = direct_wave_consensus_time_zero(traces, sample_interval_ns=0.5)
        assert result.source == "direct_wave_consensus"
        assert "consensus" in result.basis
        assert result.traces_evaluated == 20
        assert result.successful_picks is not None and result.successful_picks > 0


# --- 6. No evidence ---------------------------------------------------------

class TestNoEvidence:
    def test_pure_noise_never_produces_a_guessed_correction(self):
        traces = [_trace_record([0.1 * ((i * 37 + s) % 7 - 3) for i in range(200)]) for s in range(20)]
        result = direct_wave_consensus_time_zero(traces, sample_interval_ns=0.5)
        assert result.status in (TimeZeroStatus.INCONCLUSIVE, TimeZeroStatus.UNAVAILABLE)
        assert result.correction_ns is None

    def test_no_documented_metadata_field_is_unavailable_not_a_default(self):
        frame = _frame(assumptions=[])
        result = metadata_instrument_time_zero(frame)
        assert result.status == TimeZeroStatus.UNAVAILABLE
        assert result.correction_ns is None

    def test_an_unresolved_vendor_field_is_never_promoted_to_time_zero(self):
        """Mirrors GSSI rhf_position / Grimsel SIGNAL POSITION: recorded, not applied."""
        frame = _frame(assumptions=[
            Assumption(key="time_zero_offset_not_applied", value=-15.0,
                      basis="rhf_position recorded; meaning unestablished", verified=False),
        ])
        result = metadata_instrument_time_zero(frame)
        # metadata_instrument_time_zero only trusts SEGY_ORIGIN_OFFSET_KEY;
        # the GSSI/vendor claim under a DIFFERENT key must not satisfy it.
        assert result.status == TimeZeroStatus.UNAVAILABLE

    def test_too_few_successful_picks_is_inconclusive(self):
        traces = ([_trace_record(_pulse(onset=60, seed=i)) for i in range(2)]
                 + [_trace_record([0.05 * ((i + s) % 5 - 2) for i in range(200)]) for s in range(18)])
        result = direct_wave_consensus_time_zero(traces, sample_interval_ns=0.5)
        assert result.status == TimeZeroStatus.INCONCLUSIVE
        assert result.correction_ns is None

    def test_wide_disagreement_across_traces_is_inconclusive_not_averaged(self):
        # Onsets deliberately scattered far apart -- must not silently average.
        traces = [_trace_record(_pulse(onset=onset, seed=i))
                 for i, onset in enumerate([50, 90, 130, 60, 100, 140, 55, 95, 135, 65])]
        result = direct_wave_consensus_time_zero(traces, sample_interval_ns=0.5)
        assert result.status == TimeZeroStatus.INCONCLUSIVE
        assert result.correction_ns is None


# --- 7. Corrected time -------------------------------------------------------

class TestCorrectedTime:
    def test_corrected_twt_equals_twt_minus_t0(self):
        r = _record(metadata={"two_way_time_ns": 50.0})
        result = TimeZeroResult(status=TimeZeroStatus.DECLARED, method=TimeZeroMethod.OPERATOR_DECLARED,
                                correction_ns=12.0, basis="x", applied=True)
        apply_time_zero_correction([r], result)
        assert r.metadata["corrected_time_ns"] == pytest.approx(38.0)

    def test_unresolved_result_leaves_corrected_time_unset(self):
        r = _record(metadata={"two_way_time_ns": 50.0})
        result = TimeZeroResult(status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.NONE,
                                basis="nothing recorded")
        apply_time_zero_correction([r], result)
        assert r.metadata["corrected_time_ns"] is None
        assert r.metadata["original_time_ns"] == 50.0


# --- 8. Negative time --------------------------------------------------------

class TestNegativeCorrectedTime:
    def test_negative_corrected_time_is_flagged_not_silently_valid(self):
        r = _record(metadata={"two_way_time_ns": 5.0})
        result = TimeZeroResult(status=TimeZeroStatus.DECLARED, method=TimeZeroMethod.OPERATOR_DECLARED,
                                correction_ns=12.0, basis="x", applied=True)  # 5 - 12 = -7
        apply_time_zero_correction([r], result)
        assert r.metadata["corrected_time_ns"] == pytest.approx(-7.0)
        assert r.metadata["time_zero_excluded"] is True

    def test_excluded_samples_are_never_clamped_to_zero(self):
        r = _record(metadata={"two_way_time_ns": 5.0})
        result = TimeZeroResult(status=TimeZeroStatus.DECLARED, method=TimeZeroMethod.OPERATOR_DECLARED,
                                correction_ns=12.0, basis="x", applied=True)
        apply_time_zero_correction([r], result)
        assert r.metadata["corrected_time_ns"] != 0.0

    def test_excluded_samples_get_no_depth(self):
        r = _record(metadata={"two_way_time_ns": 5.0})
        result = TimeZeroResult(status=TimeZeroStatus.DECLARED, method=TimeZeroMethod.OPERATOR_DECLARED,
                                correction_ns=12.0, basis="x", applied=True)
        apply_time_zero_correction([r], result)
        recompute_depth_with_time_zero([r], velocity_m_per_ns=0.1)
        assert r.depth is None


# --- 9-10. Depth --------------------------------------------------------------

class TestDepthIntegration:
    def test_depth_consumes_corrected_twt_not_raw_twt(self):
        r = _record(metadata={"two_way_time_ns": 50.0})
        result = TimeZeroResult(status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
                                correction_ns=10.0, basis="x", applied=True)
        apply_time_zero_correction([r], result)
        recompute_depth_with_time_zero([r], velocity_m_per_ns=0.1)
        # corrected = 40 ns; depth = 40 * 0.1 / 2 = 2.0
        assert r.depth == pytest.approx(2.0)
        raw_depth = 50.0 * 0.1 / 2.0
        assert r.depth != pytest.approx(raw_depth)

    def test_depth_provenance_reflects_both_t0_and_velocity_and_is_not_upgraded(self):
        r = _record(depth=2.0, metadata={
            "two_way_time_ns": 50.0, "corrected_time_ns": 40.0,
            "velocity_m_per_ns": 0.1, "velocity_source": "supplied_by_caller",
            "time_zero_status": "derived", "time_zero_correction_ns": 10.0,
            "time_zero_basis": "derived from a robust median consensus of traces",
        })
        entries = {p.quantity: p for p in record_provenance(r)}
        depth_p = entries["depth"]
        # Still DERIVED -- t0 existing does not upgrade it to MEASURED/validated.
        assert depth_p.provenance == ProvenanceClass.DERIVED
        assert "time-zero corrected" in depth_p.basis
        assert "does not make the velocity any more validated" in depth_p.basis
        tz_p = entries["time_zero"]
        assert tz_p.provenance == ProvenanceClass.DERIVED

    def test_a_declared_time_zero_quantity_is_supplied_by_caller_in_provenance(self):
        r = _record(metadata={
            "two_way_time_ns": 50.0, "time_zero_status": "declared",
            "time_zero_correction_ns": 10.0,
            "time_zero_basis": "SUPPLIED BY CALLER: declared from operator note",
        })
        entries = {p.quantity: p for p in record_provenance(r)}
        assert entries["time_zero"].provenance == ProvenanceClass.SUPPLIED_BY_CALLER


# --- 11. Failure / inconclusive ----------------------------------------------

class TestFailureInconclusive:
    def test_a_failed_declaration_never_produces_a_correction_value(self):
        result = operator_declared_time_zero(float("inf"), source="x", evidence="y")
        assert result.status == TimeZeroStatus.FAILED
        assert result.correction_ns is None
        assert result.applied is False

    def test_inconclusive_result_is_not_applied(self):
        traces = [_trace_record([0.05 * ((i + s) % 5 - 2) for i in range(200)]) for s in range(20)]
        result = direct_wave_consensus_time_zero(traces, sample_interval_ns=0.5)
        assert result.applied is False
        assert not result.resolved


# --- 12. Reproducibility -------------------------------------------------------

class TestReproducibility:
    def test_same_input_same_method_gives_the_same_result(self):
        traces_a = [_trace_record(_pulse(onset=60, seed=i)) for i in range(20)]
        traces_b = [_trace_record(_pulse(onset=60, seed=i)) for i in range(20)]
        r1 = direct_wave_consensus_time_zero(traces_a, sample_interval_ns=0.5)
        r2 = direct_wave_consensus_time_zero(traces_b, sample_interval_ns=0.5)
        assert r1.status == r2.status
        assert r1.correction_ns == r2.correction_ns
        assert r1.spread_ns == r2.spread_ns


# --- 13. Backward compatibility ------------------------------------------------

class TestBackwardCompatibility:
    def test_a_record_never_touched_by_this_module_is_unaffected(self):
        r = _record(depth=3.0, metadata={"two_way_time_ns": 60.0, "velocity_m_per_ns": 0.1,
                                         "velocity_source": "supplied_by_caller"})
        entries = {p.quantity: p for p in record_provenance(r)}
        assert "time_zero" not in entries
        assert entries["depth"].provenance == ProvenanceClass.DERIVED
        assert "time-zero corrected" not in entries["depth"].basis

    def test_existing_depth_only_provenance_wording_is_unchanged_when_no_t0(self):
        r = _record(depth=3.0, metadata={"velocity_m_per_ns": 0.1, "velocity_source": "supplied_by_caller"})
        entries = {p.quantity: p for p in record_provenance(r)}
        assert "not a measurement of it" in entries["depth"].basis


# --- 14. API/report: TimeZeroResult / as_processing_applied serialization -----

class TestSerializationAndReport:
    def test_time_zero_result_round_trips_through_json(self):
        result = TimeZeroResult(status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
                                correction_ns=12.4, basis="derived from consensus",
                                traces_evaluated=986, successful_picks=812, spread_ns=1.7)
        dumped = result.model_dump(mode="json")
        restored = TimeZeroResult.model_validate(dumped)
        assert restored == result

    def test_as_processing_applied_carries_the_keys_dataset_report_already_reads(self):
        result = TimeZeroResult(status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
                                correction_ns=12.4, basis="derived from consensus", applied=True,
                                traces_evaluated=986, successful_picks=812, spread_ns=1.7)
        stamp = result.as_processing_applied()
        assert stamp["time_zero"] is True
        assert stamp["time_zero_method"] == "direct_wave_consensus"
        assert stamp["time_zero_correction_ns"] == 12.4

    def test_apply_time_zero_correction_stamps_processing_applied_for_the_report(self):
        r = _record(metadata={"two_way_time_ns": 50.0})
        result = TimeZeroResult(status=TimeZeroStatus.DERIVED, method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS,
                                correction_ns=10.0, basis="x", applied=True)
        apply_time_zero_correction([r], result)
        applied = r.metadata["processing_applied"]
        assert applied["time_zero"] is True
        assert applied["time_zero_status"] == "derived"

    def test_not_run_is_distinguishable_from_unavailable(self):
        not_run = TimeZeroResult(status=TimeZeroStatus.NOT_RUN, method=TimeZeroMethod.NONE,
                                 basis="no attempt was made")
        unavailable = TimeZeroResult(status=TimeZeroStatus.UNAVAILABLE, method=TimeZeroMethod.METADATA_INSTRUMENT,
                                     basis="no documented field exists")
        assert not_run.status != unavailable.status
        assert not not_run.resolved and not unavailable.resolved
