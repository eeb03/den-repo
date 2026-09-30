"""
The canonical radar depth model (schemas/depth_model.py).

Four quantities kept apart: the recording delay (where the recorded window
starts on the instrument clock -- already inside the raw time axis), radar
time zero (a separate declaration or estimate), the propagation velocity
(with the basis it rests on), and the depth reference. Depth is RESOLVED only
when all three inputs are stated and none is the platform default; it is
APPROXIMATE when a depth can be drawn but rests on an assumption; otherwise
UNAVAILABLE. "Resolved" never means "validated".
"""
import pytest

from schemas.depth_model import (
    DEFAULT_VELOCITY_M_PER_NS, DepthStatus, VelocityBasis, VelocityModel,
    assess_depth_readiness, corrected_time, two_way_time_to_depth, velocity_model_of,
)
from schemas.spatial import (
    AxisKind, DepthOriginOffset, OffsetEvidence, OriginReference, VerticalAxis,
)
from schemas.time_zero import TimeZeroMethod, TimeZeroResult, TimeZeroStatus


def axis(conversion=None, origin="instrument time-zero at each trace", offset=None):
    return VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns", origin=origin,
                        positive_down=True, conversion=conversion, origin_offset=offset)


def conv(v, **kw):
    return {"method": "constant_velocity", "velocity_m_per_ns": v, **kw}


DECLARED_T0 = TimeZeroResult(status=TimeZeroStatus.DECLARED,
                             method=TimeZeroMethod.OPERATOR_DECLARED,
                             correction_ns=12.0, basis="SUPPLIED BY CALLER: first break")


def ground_offset():
    return DepthOriginOffset(offset_m=0.0, measured_from=OriginReference.DEPTH_AXIS_ORIGIN,
                             evidence=OffsetEvidence.USER_DECLARATION,
                             supplied_by="field notes: ground-coupled antenna")


# --- the arithmetic -----------------------------------------------------------

def test_depth_is_half_the_round_trip():
    assert two_way_time_to_depth(40.0, 0.1) == pytest.approx(2.0)


def test_the_canonical_formula_is_bit_identical_to_the_converters():
    """Every converter used (t * v) / 2.0; the canonical one must not move a bit."""
    for t in (0.0, 0.2, 10.342, 55.043939, 97.0 / 1000 * 511):
        assert two_way_time_to_depth(t, 0.1) == (t * 0.1) / 2.0


def test_corrected_time_subtracts_the_correction_and_keeps_the_raw():
    assert corrected_time(50.0, 12.0) == pytest.approx(38.0)
    assert corrected_time(50.0, None) is None


# --- velocity ------------------------------------------------------------------

def test_the_platform_default_is_an_assumption():
    v = velocity_model_of(conv(DEFAULT_VELOCITY_M_PER_NS))
    assert v.basis is VelocityBasis.ASSUMED_DEFAULT
    assert v.independent_of_survey is False


def test_a_legacy_declaration_without_a_basis_is_user_declared():
    v = velocity_model_of(conv(0.12, basis="supplied by a caller", derived=True))
    assert v.basis is VelocityBasis.USER_DECLARED


def test_an_explicit_basis_is_carried():
    v = velocity_model_of(conv(0.0938, velocity_basis="estimated_from_same_survey",
                               velocity_method="migration_fit"))
    assert v.basis is VelocityBasis.ESTIMATED_FROM_SAME_SURVEY
    assert v.independent_of_survey is False
    assert v.method == "migration_fit"


def test_only_an_independent_measurement_is_independent():
    for b in VelocityBasis:
        v = VelocityModel(value_m_per_ns=0.1, basis=b)
        assert v.independent_of_survey is (b is VelocityBasis.INDEPENDENT_MEASUREMENT)


@pytest.mark.parametrize("value", [0.0, -0.1, 0.31, float("nan"), float("inf")])
def test_impossible_velocities_are_refused(value):
    with pytest.raises(ValueError, match="velocity"):
        VelocityModel(value_m_per_ns=value, basis=VelocityBasis.USER_DECLARED)


def test_negative_uncertainty_is_refused():
    with pytest.raises(ValueError, match="uncertainty"):
        VelocityModel(value_m_per_ns=0.1, basis=VelocityBasis.USER_DECLARED,
                      uncertainty_m_per_ns=-0.01)


# --- readiness -----------------------------------------------------------------

def test_no_velocity_means_no_depth():
    r = assess_depth_readiness(axis(), time_zero=DECLARED_T0)
    assert r.status is DepthStatus.UNAVAILABLE
    assert any("velocity" in x for x in r.reasons)


def test_the_default_velocity_gives_approximate_depth_never_resolved():
    r = assess_depth_readiness(axis(conv(0.1), offset=ground_offset()), time_zero=DECLARED_T0)
    assert r.status is DepthStatus.APPROXIMATE
    assert any("default" in x for x in r.reasons)


def test_an_unresolved_time_zero_keeps_depth_approximate():
    r = assess_depth_readiness(axis(conv(0.12, velocity_basis="independent_measurement"),
                                    offset=ground_offset()), time_zero=None)
    assert r.status is DepthStatus.APPROXIMATE
    assert any("time zero" in x for x in r.reasons)


def test_an_unknown_reference_keeps_depth_approximate():
    r = assess_depth_readiness(axis(conv(0.12, velocity_basis="independent_measurement")),
                               time_zero=DECLARED_T0)
    assert r.status is DepthStatus.APPROXIMATE
    assert any("below what" in x for x in r.reasons)


def test_all_three_stated_gives_resolved_and_names_them():
    r = assess_depth_readiness(axis(conv(0.12, velocity_basis="independent_measurement",
                                         velocity_method="CMP")),
                               time_zero=DECLARED_T0, reference=None)
    assert r.status is DepthStatus.APPROXIMATE        # still no reference
    r = assess_depth_readiness(axis(conv(0.12, velocity_basis="independent_measurement",
                                         velocity_method="CMP"), offset=ground_offset()),
                               time_zero=DECLARED_T0)
    assert r.status is DepthStatus.RESOLVED
    assert r.reasons == []
    d = r.as_dict()
    assert d["time_zero"]["method"] == "operator_declared"
    assert d["velocity"]["basis"] == "independent_measurement"
    assert d["reference"]["known"] is True
    assert d["validated"] is False           # resolved is not validated


def test_a_same_survey_estimate_can_resolve_but_is_flagged_not_independent():
    r = assess_depth_readiness(axis(conv(0.0938, velocity_basis="estimated_from_same_survey"),
                                    offset=ground_offset()), time_zero=DECLARED_T0)
    assert r.status is DepthStatus.RESOLVED
    assert r.as_dict()["velocity"]["independent_of_survey"] is False
    assert any("same survey" in n for n in r.notes)


def test_a_recording_delay_is_not_a_time_zero():
    """A frame whose only timing fact is the SEG-Y delay has no time zero."""
    r = assess_depth_readiness(axis(conv(0.1)), time_zero=None, recording_delay_ns=10.342)
    assert r.as_dict()["time_zero"]["status"] == "unavailable"
    assert r.as_dict()["recording_delay_ns"] == 10.342
    assert any("recording delay" in n for n in r.notes)


def test_an_impossible_stored_velocity_is_reported_not_raised():
    """A legacy frame with a bad conversion must not crash the spatial assessment."""
    r = assess_depth_readiness(axis(conv(3.0)), time_zero=DECLARED_T0)
    assert r.status is DepthStatus.UNAVAILABLE
    assert any("not physically possible" in x for x in r.reasons)


# --- the stored-depth invariant --------------------------------------------------

def _frame_and_records(conversion, n=5, dt=2.0, velocity_on_records=0.1):
    from schemas.spatial import CRSKind, SpatialRef
    from schemas.subterra_record import SensorType, SubterraRecord
    from schemas.survey_frame import SurveyFrame
    frame = SurveyFrame(
        frame_id="d:l", dataset_id="d", modality=SensorType.GPR, source_format="segy",
        source_file="l.sgy", spatial_ref=SpatialRef(kind=CRSKind.UNKNOWN, name="none"),
        vertical_axis=axis(conversion), n_positions=1, position_index_name="trace_index")
    records = [SubterraRecord.model_construct(
        dataset_id="d", latitude=None, longitude=None, elevation=None,
        depth=two_way_time_to_depth(i * dt, velocity_on_records), signal=[0.0],
        sensor_type=SensorType.GPR, ground_truth="none", frame_id="d:l",
        metadata={"trace_index": 0, "sample_index": i, "two_way_time_ns": i * dt,
                  "velocity_m_per_ns": velocity_on_records}) for i in range(n)]
    return frame, records


def test_an_ingest_derivation_satisfies_the_invariant():
    from schemas.depth_model import verify_stored_depth
    frame, records = _frame_and_records(conv(0.1, velocity_basis="assumed_default"))
    assert verify_stored_depth(frame, records) == []


def test_changing_the_velocity_without_rederiving_is_caught_and_never_resolved():
    """The guard the whole design exists for: frame says X, records say Y."""
    from schemas.depth_model import frame_depth_readiness, rederive_depth, verify_stored_depth
    frame, records = _frame_and_records(conv(0.1, velocity_basis="assumed_default"))
    rederive_depth(frame, records)
    frame.vertical_axis = frame.vertical_axis.model_copy(update={"conversion": conv(
        0.12, velocity_basis="independent_measurement", velocity_method="CMP", derived=True,
        declaration_id="decl-2")})
    problems = verify_stored_depth(frame, records)
    assert problems and any("superseded velocity" in p for p in problems)
    r = frame_depth_readiness(frame)
    assert r.status is not DepthStatus.RESOLVED
    assert any("superseded" in x for x in r.reasons)

    rederive_depth(frame, records)
    assert verify_stored_depth(frame, records) == []
    assert records[3].depth == two_way_time_to_depth(6.0, 0.12)
    assert records[3].metadata["velocity_source"] == "declaration:decl-2"


def test_rederive_never_writes_raw_time():
    from schemas.depth_model import rederive_depth
    frame, records = _frame_and_records(conv(0.1))
    before = [r.metadata["two_way_time_ns"] for r in records]
    rederive_depth(frame, records)
    assert [r.metadata["two_way_time_ns"] for r in records] == before


def test_no_velocity_means_no_stored_depth_after_rederive():
    from schemas.depth_model import rederive_depth, verify_stored_depth
    frame, records = _frame_and_records(None)
    for r in records:
        r.metadata.pop("velocity_m_per_ns")
    rederive_depth(frame, records)
    assert all(r.depth is None for r in records)
    assert verify_stored_depth(frame, records) == []


# --- operational vs scientific time zero ------------------------------------------

def test_an_automatic_time_zero_is_usable_but_not_scientifically_sufficient():
    derived = TimeZeroResult(status=TimeZeroStatus.DERIVED,
                             method=TimeZeroMethod.DIRECT_WAVE_CONSENSUS, correction_ns=18.342,
                             basis="median of 2159 direct-wave picks")
    r = assess_depth_readiness(axis(conv(0.12, velocity_basis="independent_measurement",
                                         velocity_method="CMP"), offset=ground_offset()),
                               time_zero=derived).as_dict()
    assert r["time_zero"]["operationally_available"] is True
    assert r["time_zero"]["scientifically_sufficient"] is False
    assert r["scientifically_sufficient"] is False
    assert any("automatic" in n for n in r["notes"])


def test_a_declared_time_zero_and_independent_velocity_are_scientifically_sufficient():
    r = assess_depth_readiness(axis(conv(0.12, velocity_basis="independent_measurement",
                                         velocity_method="CMP"), offset=ground_offset()),
                               time_zero=DECLARED_T0).as_dict()
    assert r["time_zero"]["scientifically_sufficient"] is True
    assert r["velocity"]["scientifically_sufficient"] is True
    assert r["scientifically_sufficient"] is True
    assert r["validated"] is False


def test_a_depth_names_its_derivation_chain_in_its_provenance():
    from schemas.depth_model import rederive_depth
    from schemas.provenance import record_provenance
    frame, records = _frame_and_records(conv(0.12, velocity_basis="literature", derived=True,
                                             declaration_id="decl-7"))
    rederive_depth(frame, records)
    depth = next(q for q in record_provenance(records[2], frame) if q.quantity == "depth")
    for part in ("two_way_time_ns", "declaration decl-7", "literature",
                 "constant-velocity-twt/2@1"):
        assert part in depth.basis, part
    # an older derivation id on the record is called out, not passed off as current
    records[2].metadata["depth_derivation_id"] = "old"
    depth = next(q for q in record_provenance(records[2], frame) if q.quantity == "depth")
    assert "superseded" in depth.basis
