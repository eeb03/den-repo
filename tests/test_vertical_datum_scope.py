"""
A vertical datum says what a quantity is measured from -- and WHICH quantity.

WHY THIS DISTINCTION HAD TO EXIST. A survey frame can carry more than one
vertical quantity, and they do not share a datum. The 4TU GPR lines forced it:
the frame's vertical AXIS is two-way time measured from instrument time zero,
which no geodetic datum describes, while the acquisition ELEVATION in the SEG-Y
headers is a GNSS height that Dr. ter Huurne states is WGS84 ellipsoidal.

Declaring one datum "for the frame" would have to pick one of those and silently
mislabel the other -- and worse, would advance the vertical-reference dimension
on evidence that says nothing about the depth axis.

WHAT IS DELIBERATELY UNCHANGED. A datum declared WITHOUT `applies_to` behaves
exactly as it always has: it lands on the vertical axis, and Stage 12's workflow
(datum, then depth origin, then the dimension settles) is untouched. The new
scope is opt-in and narrower, never a change to what existing callers get.
"""
import pytest

from api.spatial import (
    DEFAULT_VERTICAL_DATUM_APPLIES_TO, VERTICAL_DATUM_APPLIES_TO, DeclarationError,
    validate_declaration,
)
from schemas.spatial_reference import DeclarationKind


def validated(**value) -> dict:
    return validate_declaration(DeclarationKind.VERTICAL_DATUM, value)


# ---------------------------------------------------------------------------
# the scope vocabulary
# ---------------------------------------------------------------------------

def test_a_datum_without_a_scope_still_means_the_vertical_axis():
    """Every caller before this change meant the axis, and still gets it."""
    assert validated(code="NAP")["applies_to"] == "vertical_axis"
    assert DEFAULT_VERTICAL_DATUM_APPLIES_TO == "vertical_axis"


def test_the_acquisition_elevation_scope_exists_and_is_described():
    assert set(VERTICAL_DATUM_APPLIES_TO) == {"acquisition_elevation", "vertical_axis"}
    assert "not the depth axis" in VERTICAL_DATUM_APPLIES_TO["acquisition_elevation"]


def test_an_unknown_scope_is_refused_rather_than_defaulted():
    """
    Silently falling back to the axis would attach a datum to a quantity the
    caller did not name.
    """
    with pytest.raises(DeclarationError, match="applies_to must be one of"):
        validated(code="WGS84 ellipsoidal", applies_to="whatever")


def test_the_code_is_still_required():
    with pytest.raises(DeclarationError, match="code is required"):
        validated(applies_to="acquisition_elevation")


def test_the_field_name_is_carried_verbatim_when_given():
    """
    Which of several stored elevations was meant. Free text because the SEG-Y
    field names are the source's, not this platform's.
    """
    out = validated(code="WGS84 ellipsoidal", applies_to="acquisition_elevation",
                    field="SEG-Y bytes 45-48 (Source Surface Elevation)")
    assert out["field"] == "SEG-Y bytes 45-48 (Source Surface Elevation)"


def test_a_datum_is_never_recorded_as_measured():
    """A declaration is somebody's claim; provenance says so on every kind."""
    assert validated(code="NAP")["provenance"] == "supplied_by_caller"
    assert validated(code="WGS84 ellipsoidal",
                     applies_to="acquisition_elevation")["provenance"] == "supplied_by_caller"


# ---------------------------------------------------------------------------
# applying it
# ---------------------------------------------------------------------------

@pytest.fixture
def dataset(tmp_path, monkeypatch):
    """One GPR line with a two-way-time axis -- the 4TU shape."""
    from configs import settings as settings_mod
    from database.frames_store import save_frames
    from database.records_store import clear_records_cache, save_records
    from schemas.spatial import (
        AxisKind, CRSKind, CRSProvenance, GeographicPosition, SpatialRef, VerticalAxis,
    )
    from schemas.subterra_record import SensorType, SubterraRecord
    from schemas.survey_frame import SurveyFrame

    monkeypatch.setattr(type(settings_mod.settings), "processed_dir",
                        property(lambda self: tmp_path))
    clear_records_cache()

    frame = SurveyFrame(
        frame_id="d:line1", dataset_id="d", modality=SensorType.GPR,
        source_format="segy", source_file="line1.sgy", n_positions=2,
        spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                               crs_provenance=CRSProvenance.DECLARED_BY_SOURCE),
        vertical_axis=VerticalAxis(
            kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
            origin="instrument time-zero at each trace", positive_down=True))
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR,
                       position=GeographicPosition(lat=52.24 + i * 1e-4, lon=6.85),
                       latitude=52.24 + i * 1e-4, longitude=6.85,
                       frame_id="d:line1", signal=[0.1],
                       metadata={"source_file": "line1.sgy", "trace_index": i})
        for i in range(2)
    ]
    save_records("d", records)
    save_frames("d", [frame])
    yield "d"
    clear_records_cache()


def apply(dataset_id, **value):
    from api.spatial import apply_declaration

    return apply_declaration(
        dataset_id, DeclarationKind.VERTICAL_DATUM,
        validate_declaration(DeclarationKind.VERTICAL_DATUM, value),
        supplied_by="Dr. ter Huurne (4TU dataset author), direct correspondence")


def frames_of(dataset_id):
    from database.frames_store import load_frames

    return load_frames(dataset_id)


def test_the_default_scope_still_writes_the_datum_onto_the_axis(dataset):
    """Stage 12's workflow depends on this and must not change."""
    result = apply(dataset, code="NAP")

    assert result["frames_changed"] == ["d:line1"]
    assert not result["vertical_axis_not_changed"]
    assert frames_of(dataset)[0].vertical_axis.vertical_datum.code == "NAP"


def test_an_acquisition_elevation_datum_is_not_written_onto_the_time_axis(dataset):
    """
    THE POINT OF THE STAGE. The author's statement is about the GNSS elevation
    field. Writing it onto a two-way-time axis would assert that instrument
    time zero is referenced to the WGS84 ellipsoid, which is false.
    """
    result = apply(dataset, code="WGS84 ellipsoidal",
                   applies_to="acquisition_elevation",
                   field="SEG-Y bytes 45-48 (Source Surface Elevation)")

    assert result["frames_changed"] == []
    assert frames_of(dataset)[0].vertical_axis.vertical_datum is None, \
        "the depth axis has not acquired a geodetic datum"


def test_the_datum_lands_on_the_acquisition_elevation_instead(dataset):
    """Not written onto the axis, but not thrown away either: it has a home."""
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation",
          field="SEG-Y bytes 45-48 (Source Surface Elevation)")

    declared = frames_of(dataset)[0].acquisition_elevation_datum
    assert declared.datum.code == "WGS84 ellipsoidal"
    assert declared.datum.provenance.value == "supplied_by_caller"
    assert declared.field == "SEG-Y bytes 45-48 (Source Surface Elevation)"


def test_the_default_scope_leaves_the_acquisition_elevation_undeclared(dataset):
    """The two slots are independent; filling one must not fill the other."""
    apply(dataset, code="NAP")
    assert frames_of(dataset)[0].acquisition_elevation_datum is None


def test_the_skipped_frame_says_why_and_names_the_field(dataset):
    result = apply(dataset, code="WGS84 ellipsoidal",
                   applies_to="acquisition_elevation",
                   field="SEG-Y bytes 45-48 (Source Surface Elevation)")

    skipped = result["vertical_axis_not_changed"]
    assert len(skipped) == 1
    assert skipped[0]["axis_kind"] == "two_way_time_ns"
    assert "bytes 45-48" in skipped[0]["reason"]
    assert "instrument time-zero" in skipped[0]["reason"]


def test_the_evidence_is_still_recorded_on_the_frame(dataset):
    """
    Not written onto the axis is NOT the same as discarded. The attributed
    assumption is what carries the claim forward.
    """
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation",
          field="SEG-Y bytes 45-48 (Source Surface Elevation)")

    assumptions = frames_of(dataset)[0].assumptions
    declared = [a for a in assumptions if a.key == "declared_vertical_datum"]
    assert len(declared) == 1
    assert "ter Huurne" in declared[0].basis
    assert declared[0].verified is False


def test_the_attribution_is_the_authority_not_the_platform(dataset):
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation")

    declared = next(a for a in frames_of(dataset)[0].assumptions
                    if a.key == "declared_vertical_datum")
    assert "This is a declaration, not a measurement." in declared.basis
    assert "SUPPLIED BY CALLER" in declared.basis


def test_the_assumption_says_which_quantity_the_datum_is_for(dataset):
    """
    "vertical datum WGS84 ellipsoidal" on a two-way-time frame reads as a claim
    about the axis. The scope is what makes the sentence true.
    """
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation",
          field="SEG-Y bytes 45-48 (Source Surface Elevation)")
    basis = next(a for a in frames_of(dataset)[0].assumptions
                 if a.key == "declared_vertical_datum").basis

    assert "for the acquisition elevation" in basis
    assert "SEG-Y bytes 45-48" in basis
    assert "NOT the vertical axis" in basis


def test_the_default_assumption_still_names_the_axis(dataset):
    apply(dataset, code="NAP")
    basis = next(a for a in frames_of(dataset)[0].assumptions
                 if a.key == "declared_vertical_datum").basis

    assert "vertical datum NAP for the vertical axis" in basis


# ---------------------------------------------------------------------------
# what must NOT move
# ---------------------------------------------------------------------------

def test_an_acquisition_elevation_datum_does_not_resolve_the_vertical_reference(dataset):
    """
    The dimension concerns what the DEPTH axis is referenced to. A datum for a
    stored elevation says nothing about it, and must not advance it.
    """
    from schemas.spatial_reference import SpatialDimension, assess_spatial_reference

    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation")

    assessment = assess_spatial_reference("d", frames_of(dataset), [])
    vertical = assessment.dimension(SpatialDimension.VERTICAL_REFERENCE)
    assert vertical.state == "unresolved"
    assert vertical.missing


def test_the_assessment_stops_claiming_nothing_is_declared(dataset):
    """
    It used to ask for exactly this datum and then not see it. Reporting
    "no frame declares a vertical datum" once one does would be false.
    """
    from schemas.spatial_reference import SpatialDimension, assess_spatial_reference

    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation",
          field="SEG-Y bytes 45-48 (Source Surface Elevation)")

    vertical = assess_spatial_reference("d", frames_of(dataset), []).dimension(
        SpatialDimension.VERTICAL_REFERENCE)
    assert "WGS84 ellipsoidal" in vertical.reason
    assert "bytes 45-48" in vertical.reason
    assert "two_way_time_ns" in vertical.reason
    assert vertical.detail.get("validated") is False


def test_the_missing_list_names_the_depth_axis_not_the_elevation(dataset):
    """The next thing needed is about the axis; asking again for what was just
    given would be the workflow failing to notice it."""
    from schemas.spatial_reference import SpatialDimension, assess_spatial_reference

    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation")

    vertical = assess_spatial_reference("d", frames_of(dataset), []).dimension(
        SpatialDimension.VERTICAL_REFERENCE)
    assert any("vertical axis itself" in m for m in vertical.missing)
    assert any("relative to the ground" in m for m in vertical.missing)
    assert not any("acquisition elevation" in m for m in vertical.missing)


def test_an_elevation_axis_is_not_asked_where_its_depth_zero_is(dataset):
    """There is no depth axis on an elevation frame; asking is asking about
    nothing, and a missing[] entry nobody can satisfy is not a gap."""
    from database.frames_store import load_frames, save_frames
    from schemas.spatial import AxisKind
    from schemas.spatial_reference import SpatialDimension, assess_spatial_reference

    frames = load_frames(dataset)
    frames[0].vertical_axis = frames[0].vertical_axis.model_copy(
        update={"kind": AxisKind.ELEVATION_M, "units": "m",
                "origin": "an elevation reference nobody has named"})
    save_frames(dataset, frames)
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation")

    vertical = assess_spatial_reference("d", frames_of(dataset), []).dimension(
        SpatialDimension.VERTICAL_REFERENCE)
    assert vertical.missing == ["a declared vertical datum for the vertical axis itself"]


def test_no_depth_origin_offset_is_created(dataset):
    """
    The author is explicit that no time-zero correction was applied. Declaring
    a datum must not place the axis origin at the ground.
    """
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation")
    assert frames_of(dataset)[0].vertical_axis.origin_offset is None


def test_no_velocity_or_depth_conversion_is_created(dataset):
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation")
    assert frames_of(dataset)[0].vertical_axis.conversion is None


def test_the_records_are_not_rewritten(dataset):
    """A declaration edits frame metadata, never a measured value."""
    from database.records_store import load_records

    before = [r.model_dump_json() for r in load_records(dataset)]
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation")
    after = [r.model_dump_json() for r in load_records(dataset)]

    assert after == before


def test_the_axis_kind_and_origin_are_untouched(dataset):
    apply(dataset, code="WGS84 ellipsoidal", applies_to="acquisition_elevation")
    axis = frames_of(dataset)[0].vertical_axis

    assert axis.kind.value == "two_way_time_ns"
    assert axis.origin == "instrument time-zero at each trace"
