"""
The depth-axis origin, relative to the ground.

WHAT THIS STAGE CLOSES. Stage 8 enumerated three things an absolute elevation
needs, and stage 11 supplied one of them (a usable surface). The third -- how far
the depth axis's zero sits from the ground -- had a declaration form since stage
8 whose value NOTHING READ: `assess` decided whether depth zero was the ground by
searching a free-text `origin` string for the words "ground surface", so no
declaration could ever satisfy it.

WHAT IT DELIBERATELY DOES NOT DO. It moves no sample, converts no time to metres,
validates no depth, and does not make a dataset vertically registered on its own.
Most of what follows checks that.
"""
import pytest

from api import spatial as service
from fusion.vertical_reference import assess
from schemas.spatial import (
    OFFSET_POSITIVE_MEANS,
    AxisKind,
    CRSProvenance,
    DepthOriginOffset,
    OffsetEvidence,
    OriginReference,
    VerticalAxis,
    VerticalDatum,
)
from schemas.spatial_reference import DeclarationKind

NAP = VerticalDatum(code="NAP", provenance=CRSProvenance.SUPPLIED_BY_CALLER, name="NAP")


def offset(metres=0.45, measured_from=OriginReference.DEPTH_AXIS_ORIGIN,
           evidence=OffsetEvidence.FIELD_MEASUREMENT):
    return DepthOriginOffset(offset_m=metres, measured_from=measured_from,
                             evidence=evidence, supplied_by="field team 2019-03-20")


def subsurface(origin="instrument time zero", origin_offset=None, datum=NAP,
               kind=AxisKind.DEPTH_M, conversion=None):
    class Frame:
        frame_id = "gpr:line1"
        vertical_axis = VerticalAxis(
            kind=kind, units="m" if kind == AxisKind.DEPTH_M else "ns", origin=origin,
            positive_down=True, vertical_datum=datum, origin_offset=origin_offset,
            conversion=conversion)
    return Frame()


def surface(datum=NAP):
    class Frame:
        frame_id = "dem:tile"
        vertical_axis = VerticalAxis(
            kind=AxisKind.ELEVATION_M, units="m", origin="raster band 1 value",
            positive_down=False, vertical_datum=datum)
    return Frame()


# ---------------------------------------------------------------------------
# the gap, reproduced
# ---------------------------------------------------------------------------

def test_without_an_offset_the_origin_is_the_missing_piece():
    relationship = assess(subsurface(), surface())

    assert relationship.absolute_elevation_available is False
    assert any("not the ground surface" in r for r in relationship.reasons)
    assert any("offset from the depth-axis origin" in m for m in relationship.missing)


# ---------------------------------------------------------------------------
# the declaration closes it
# ---------------------------------------------------------------------------

def test_a_declared_axis_origin_offset_removes_that_missing_piece():
    relationship = assess(subsurface(origin_offset=offset()), surface())

    assert not any("offset from the depth-axis origin" in m
                   for m in relationship.missing)
    assert any("declared to sit 0.45 m above the ground" in r
               for r in relationship.reasons)


def test_the_declaration_is_reported_as_a_declaration():
    relationship = assess(subsurface(origin_offset=offset()), surface())
    assert any("nothing has verified it" in r for r in relationship.reasons)


def test_a_phase_centre_height_does_not_answer_the_question():
    """
    A real measurement that relates the ANTENNA to the ground, not the axis
    ZERO to the ground. Time zero is set by the electronics.
    """
    relationship = assess(
        subsurface(origin_offset=offset(
            measured_from=OriginReference.SENSOR_PHASE_CENTRE)), surface())

    assert relationship.absolute_elevation_available is False
    assert any("not from the depth-axis origin" in r for r in relationship.reasons)
    assert any("DEPTH-AXIS ORIGIN" in m for m in relationship.missing)


def test_an_axis_whose_origin_is_already_the_ground_still_works():
    """The pre-existing route is untouched."""
    relationship = assess(subsurface(origin="ground surface at trace"), surface())
    assert relationship.absolute_elevation_available is True


# ---------------------------------------------------------------------------
# the sign convention
# ---------------------------------------------------------------------------

def test_positive_means_the_reference_point_is_above_the_ground():
    assert OFFSET_POSITIVE_MEANS == "the reference point is above the ground"
    relationship = assess(subsurface(origin_offset=offset(0.45)), surface())
    assert any("0.45 m above the ground" in r for r in relationship.reasons)


def test_a_negative_offset_reads_as_below_the_ground():
    """A sensor lowered into a trench. Physically meaningful, and rare."""
    relationship = assess(subsurface(origin_offset=offset(-0.30)), surface())
    assert any("-0.3 m below the ground" in r for r in relationship.reasons)


def test_zero_is_a_claim_and_is_accepted_as_one():
    """It says the origin was ON the ground -- which must be declared, never assumed."""
    value = service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {
        "offset_m": 0, "measured_from": "depth_axis_origin",
        "evidence": "field_measurement"})
    assert value["offset_m"] == 0.0


def test_the_convention_is_carried_on_every_declaration():
    value = service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {
        "offset_m": 0.45, "measured_from": "depth_axis_origin",
        "evidence": "acquisition_documentation"})
    assert value["sign_convention"] == OFFSET_POSITIVE_MEANS


# ---------------------------------------------------------------------------
# validation: syntax is not physics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "half a metre", None, 45, -45])
def test_an_unusable_offset_is_refused(bad):
    with pytest.raises(service.DeclarationError):
        service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {
            "offset_m": bad, "measured_from": "depth_axis_origin",
            "evidence": "field_measurement"})


def test_the_unit_is_stated_when_a_centimetre_value_is_mistyped():
    with pytest.raises(service.DeclarationError) as exc:
        service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {
            "offset_m": 45, "measured_from": "depth_axis_origin",
            "evidence": "field_measurement"})
    assert "45 cm is 0.45" in str(exc.value)


def test_the_reference_point_is_required_and_not_defaulted():
    with pytest.raises(service.DeclarationError) as exc:
        service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {"offset_m": 0.45})
    assert "measured_from is required" in str(exc.value)


def test_the_evidence_kind_is_required_and_not_defaulted():
    with pytest.raises(service.DeclarationError) as exc:
        service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {
            "offset_m": 0.45, "measured_from": "depth_axis_origin"})
    assert "evidence is required" in str(exc.value)


@pytest.mark.parametrize("evidence", [e.value for e in OffsetEvidence])
def test_each_evidence_kind_is_preserved(evidence):
    value = service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {
        "offset_m": 0.45, "measured_from": "depth_axis_origin", "evidence": evidence})
    assert value["evidence"] == evidence


def test_nothing_is_ever_marked_verified():
    """Subterra cannot check an offset against anything."""
    for evidence in OffsetEvidence:
        value = service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {
            "offset_m": 0.45, "measured_from": "depth_axis_origin",
            "evidence": evidence.value})
        assert value["verified"] is False


# ---------------------------------------------------------------------------
# the dependency graph is respected
# ---------------------------------------------------------------------------

def test_an_offset_alone_does_not_register_a_survey_vertically():
    """No datum on either side; the offset changes nothing about that."""
    relationship = assess(
        subsurface(origin_offset=offset(), datum=None), surface(datum=None))
    assert relationship.absolute_elevation_available is False
    assert any("declares no vertical datum" in r for r in relationship.reasons)


def test_a_time_axis_with_no_velocity_stays_unregistered_however_good_the_offset():
    """
    THE CASE THE ROADMAP NAMES. Knowing where the axis begins does not turn
    nanoseconds into metres.
    """
    relationship = assess(
        subsurface(kind=AxisKind.TWO_WAY_TIME_NS, origin_offset=offset()), surface())

    assert relationship.absolute_elevation_available is False
    assert any("no velocity was supplied" in r for r in relationship.reasons)
    assert any("velocity" in m for m in relationship.missing)


def test_everything_present_finally_yields_absolute_elevation():
    """Datums declared and equal, a depth axis, and a declared origin offset."""
    relationship = assess(subsurface(origin_offset=offset()), surface())

    assert relationship.absolute_elevation_available is True
    assert any("declared offset to the ground" in r for r in relationship.reasons)


def test_the_offset_does_not_move_the_axis_origin_string():
    """
    It records a RELATIONSHIP. Rewriting `origin` would make the frame claim its
    zero had moved, and every stored sample would silently mean something else.
    """
    frame = subsurface(origin_offset=offset())
    assert frame.vertical_axis.origin == "instrument time zero"


def test_the_declaration_writes_only_the_axis_relationship():
    """No record, no sample, no stored depth is touched by applying one."""
    import ast
    import inspect

    source = inspect.getsource(service.apply_declaration)
    block = source.split("DeclarationKind.ANTENNA_OFFSET")[1].split("elif kind ==")[0]
    tree = ast.parse("if True:\n" + "\n".join(
        "    " + line for line in block.splitlines()[1:] if line.strip()))
    called = {getattr(n.func, "attr", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "save_records" not in called
