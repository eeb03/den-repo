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
