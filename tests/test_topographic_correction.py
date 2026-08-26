"""
Tests for the topographic/air-gap correction framework:
`schemas.topographic_correction` and `preprocessing.topographic_correction`.

All synthetic, hand-computable fixtures -- same discipline as
`tests/test_dem_alignment.py` and `tests/test_four_tu_topographic_correction_audit.py`:
these pin the arithmetic and status transitions against known numbers, never
the real 4TU result (that lives in `artifacts/4tu/topographic_correction_audit.json`,
produced only by running the audit against the real archive and DEM tiles).
"""
from __future__ import annotations

import pytest

from ingestion.four_tu_velocity import C_M_PER_NS
from preprocessing.topographic_correction import (
    MIN_VALID_TRACES,
    apply_topographic_correction,
    dem_antenna_differential_correction,
    resolve_topographic_correction_for_records,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.topographic_correction import (
    TopographicCorrectionMethod, TopographicCorrectionResult, TopographicCorrectionStatus,
)


def _record(elevation=None, metadata=None, dataset_id="ds"):
    return SubterraRecord.model_construct(
        dataset_id=dataset_id, latitude=None, longitude=None, elevation=elevation,
        depth=None, signal=[0.0], sensor_type=SensorType.GPR, ground_truth="none",
        metadata=metadata or {},
    )


# --- 1. The core arithmetic -------------------------------------------------

class TestDemAntennaDifferentialCorrection:
    def test_flat_terrain_following_acquisition_is_not_material(self):
        """Antenna elevation tracks ground elevation exactly (constant
        height-above-ground) -- zero deviation, so no correction is
        warranted at any sample interval."""
        antenna = {0: 20.0, 1: 21.0, 2: 22.0}
        ground = {0: 10.0, 1: 11.0, 2: 12.0}  # height-above-ground constant at 10.0
        result = dem_antenna_differential_correction(antenna, ground, sample_interval_ns=0.1)
        assert result.status == TopographicCorrectionStatus.NOT_MATERIAL
        assert result.per_trace_correction_ns is None
        assert result.resolved is False

    def test_a_constant_datum_offset_between_sources_cancels_out(self):
        """A large, arbitrary constant bias between the two elevation
        sources must not appear in the result at all -- only the real
        +-0.1 m signal on top of it should."""
        antenna = {0: 1020.0, 1: 1020.1, 2: 1019.9}
        ground = {0: 10.0, 1: 10.0, 2: 10.0}
        result = dem_antenna_differential_correction(antenna, ground, sample_interval_ns=1e-6)
        assert result.status == TopographicCorrectionStatus.DERIVED
        # deviation: 0.0, +0.1, -0.1 (median height-above-ground = 1010.0)
        expected_1 = 2 * 0.1 / C_M_PER_NS
        assert result.per_trace_correction_ns[1] == pytest.approx(expected_1, abs=1e-9)
        assert result.per_trace_correction_ns[2] == pytest.approx(-expected_1, abs=1e-9)
        assert result.per_trace_correction_ns[0] == pytest.approx(0.0, abs=1e-9)

    def test_a_correction_exceeding_the_sample_interval_is_derived(self):
        antenna = {0: 20.0, 1: 20.5, 2: 19.5}  # +-0.5 m deviation
        ground = {0: 10.0, 1: 10.0, 2: 10.0}
        result = dem_antenna_differential_correction(antenna, ground, sample_interval_ns=1.0)
        expected_max = 2 * 0.5 / C_M_PER_NS  # ~3.34 ns, exceeds 1.0 ns
        assert result.status == TopographicCorrectionStatus.DERIVED
        assert result.max_abs_correction_ns == pytest.approx(expected_max, abs=1e-9)
        assert result.method == TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL

    def test_a_correction_below_the_sample_interval_is_not_material(self):
        antenna = {0: 20.0, 1: 20.01, 2: 19.99}  # +-0.01 m deviation -> ~0.067 ns
        ground = {0: 10.0, 1: 10.0, 2: 10.0}
        result = dem_antenna_differential_correction(antenna, ground, sample_interval_ns=1.0)
        assert result.status == TopographicCorrectionStatus.NOT_MATERIAL
        assert result.per_trace_correction_ns is None
        assert result.max_abs_correction_ns is not None  # still reported as a diagnostic

    def test_fewer_than_the_minimum_valid_traces_is_unavailable(self):
        antenna = {0: 20.0, 1: 21.0}
        ground = {0: 10.0, 1: 10.0}
        assert len(antenna) < MIN_VALID_TRACES
        result = dem_antenna_differential_correction(antenna, ground, sample_interval_ns=1.0)
        assert result.status == TopographicCorrectionStatus.UNAVAILABLE
        assert result.resolved is False

    def test_only_traces_present_in_both_sources_are_used(self):
        """A trace missing from either source (e.g. outside the DEM tile) is excluded, not treated as a zero."""
        antenna = {0: 20.0, 1: 21.0, 2: 22.0, 3: 99.0}
        ground = {0: 10.0, 1: 10.0, 2: 10.0}  # trace 3 has no ground elevation
        result = dem_antenna_differential_correction(antenna, ground, sample_interval_ns=0.001)
        assert result.n_traces_evaluated == 3
        assert 3 not in (result.per_trace_correction_ns or {})


# --- 2. Applying the result --------------------------------------------------

class TestApplyTopographicCorrection:
    def test_derived_correction_refines_the_time_zero_corrected_axis(self):
        records = [
            _record(metadata={"trace_index": 0, "corrected_time_ns": 5.0}),
            _record(metadata={"trace_index": 1, "corrected_time_ns": 5.0}),
        ]
        result = TopographicCorrectionResult(
            status=TopographicCorrectionStatus.DERIVED,
            method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
            per_trace_correction_ns={0: 0.2, 1: -0.3},
            basis="test",
        )
        applied = apply_topographic_correction(records, result)
        assert applied[0].metadata["topographic_corrected_time_ns"] == pytest.approx(4.8)
        assert applied[1].metadata["topographic_corrected_time_ns"] == pytest.approx(5.3)
        # the time-zero-corrected axis itself is never touched
        assert applied[0].metadata["corrected_time_ns"] == 5.0

    def test_not_material_applies_no_per_trace_correction(self):
        records = [_record(metadata={"trace_index": 0, "corrected_time_ns": 5.0})]
        result = TopographicCorrectionResult(
            status=TopographicCorrectionStatus.NOT_MATERIAL,
            method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
            basis="test",
        )
        applied = apply_topographic_correction(records, result)
        assert applied[0].metadata["topographic_corrected_time_ns"] is None
        assert applied[0].metadata["processing_applied"]["topographic_correction_status"] == "not_material"

    def test_a_trace_missing_from_the_correction_map_gets_no_value_not_a_copy(self):
        records = [_record(metadata={"trace_index": 5, "corrected_time_ns": 5.0})]
        result = TopographicCorrectionResult(
            status=TopographicCorrectionStatus.DERIVED,
            method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
            per_trace_correction_ns={0: 0.2},  # trace 5 is absent
            basis="test",
        )
        applied = apply_topographic_correction(records, result)
        assert applied[0].metadata["topographic_corrected_time_ns"] is None

    def test_processing_applied_is_merged_not_replaced(self):
        records = [_record(metadata={
            "trace_index": 0, "corrected_time_ns": 5.0,
            "processing_applied": {"time_zero": True, "time_zero_status": "measured"},
        })]
        result = TopographicCorrectionResult(
            status=TopographicCorrectionStatus.NOT_MATERIAL,
            method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
            basis="test",
        )
        applied = apply_topographic_correction(records, result)
        stamp = applied[0].metadata["processing_applied"]
        assert stamp["time_zero_status"] == "measured"  # earlier stamp survives
        assert stamp["topographic_correction_status"] == "not_material"


# --- 3. Production wiring: reading real record shapes -----------------------

class TestResolveForRecords:
    def test_reads_pre_dem_elevation_and_ground_elevation(self):
        """Mirrors what preprocessing.dem_alignment.align_records_with_dem leaves behind."""
        records = [
            _record(elevation=10.0, metadata={"trace_index": 0, "pre_dem_elevation_m": 20.0}),
            _record(elevation=10.0, metadata={"trace_index": 1, "pre_dem_elevation_m": 20.5}),
            _record(elevation=10.0, metadata={"trace_index": 2, "pre_dem_elevation_m": 19.5}),
        ]
        result = resolve_topographic_correction_for_records(records, sample_interval_ns=1.0)
        assert result.status == TopographicCorrectionStatus.DERIVED
        assert result.per_trace_correction_ns is not None

    def test_a_dataset_never_dem_aligned_is_unavailable(self):
        """No `pre_dem_elevation_m` anywhere -- this dataset was never DEM-aligned."""
        records = [_record(elevation=None, metadata={"trace_index": 0})]
        result = resolve_topographic_correction_for_records(records, sample_interval_ns=1.0)
        assert result.status == TopographicCorrectionStatus.UNAVAILABLE

    def test_a_sensor_with_no_elevation_of_its_own_is_unavailable(self):
        """DEM-aligned, but the sensor never carried its own elevation to preserve in the first place."""
        records = [_record(elevation=10.0, metadata={"trace_index": 0})]  # no pre_dem_elevation_m
        result = resolve_topographic_correction_for_records(records, sample_interval_ns=1.0)
        assert result.status == TopographicCorrectionStatus.UNAVAILABLE


# --- 4. Serialization / stamp contract --------------------------------------

class TestSerializationAndStamp:
    def test_as_processing_applied_carries_the_namespaced_keys(self):
        result = TopographicCorrectionResult(
            status=TopographicCorrectionStatus.DERIVED,
            method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
            per_trace_correction_ns={0: 0.2}, max_abs_correction_ns=0.2,
            sample_interval_ns=0.1, n_traces_evaluated=3, n_traces_valid=3,
            basis="test", applied=True,
        )
        stamp = result.as_processing_applied()
        assert stamp["topographic_correction"] is True
        assert stamp["topographic_correction_status"] == "derived"
        assert stamp["topographic_correction_method"] == "dem_antenna_differential"
        assert stamp["topographic_correction_max_abs_ns"] == 0.2

    def test_round_trips_through_json(self):
        result = TopographicCorrectionResult(
            status=TopographicCorrectionStatus.DERIVED,
            method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
            per_trace_correction_ns={0: 0.2, 1: -0.1}, basis="test",
        )
        restored = TopographicCorrectionResult.model_validate_json(result.model_dump_json())
        assert restored.per_trace_correction_ns == {0: 0.2, 1: -0.1}
        assert restored.status == TopographicCorrectionStatus.DERIVED

    def test_not_material_and_unavailable_are_never_resolved(self):
        for status in (TopographicCorrectionStatus.NOT_MATERIAL, TopographicCorrectionStatus.UNAVAILABLE,
                      TopographicCorrectionStatus.NOT_RUN, TopographicCorrectionStatus.INCONCLUSIVE):
            result = TopographicCorrectionResult(
                status=status, method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL, basis="test",
            )
            assert result.resolved is False
