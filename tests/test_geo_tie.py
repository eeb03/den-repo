"""
GeoTie: the only sanctioned route from an odometry frame to a geographic one.

An odometry acquisition knows how far along its line each trace sits and
nothing else. A tie is somebody ASSERTING where that line lies, with their
name on it -- and the positions that result are derived from an assertion,
never observed by an instrument. These tests pin that the distinction
survives, that a tie cannot be built from nothing, and that its quality is
measured where measurement is possible.
"""
import pytest

from ingestion.geo_tie import (
    GeoTieError, apply_geo_tie, assess_tie, build_geo_tie, tie_assumption,
    tied_spatial_ref,
)
from schemas.spatial import (
    POSITION_NATIVE, POSITION_REGISTERED, ControlPoint, CRSKind, CRSProvenance,
    GeoTie, NoPosition, OdometryPosition, PositionKind, effective_position,
    has_geographic_coordinates, position_provenance,
)
from schemas.subterra_record import SensorType, SubterraRecord

# A straight north-going line: 0.001 deg latitude is ~111 m.
STRAIGHT = [
    ControlPoint(along_track_m=0.0, lat=41.0000, lon=15.0, label="start"),
    ControlPoint(along_track_m=55.5, lat=41.0005, lon=15.0),
    ControlPoint(along_track_m=111.0, lat=41.0010, lon=15.0, label="end"),
]
ENDPOINTS = [STRAIGHT[0], STRAIGHT[-1]]


def _odometry_records(n=5, spacing=27.75, path="line"):
    return [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.GPR,
            position=OdometryPosition(along_track_m=i * spacing, path_id=path),
            signal=[1.0], depth=0.5,
            metadata={"source_file": "line.dt", "trace_index": i, "sample_index": 0},
        )
        for i in range(n)
    ]


# --- a tie cannot be built from nothing ---

def test_one_control_point_is_rejected():
    """One point fixes a location but not a bearing."""
    with pytest.raises(ValueError, match="at least two control points"):
        GeoTie(method="endpoints", supplied_by="s", control_points=[STRAIGHT[0]])


def test_duplicate_along_track_distances_are_rejected():
    with pytest.raises(ValueError, match="distinct along-track distances"):
        GeoTie(method="endpoints", supplied_by="s",
               control_points=[STRAIGHT[0], ControlPoint(along_track_m=0.0, lat=42.0, lon=15.0)])


def test_a_tie_records_who_supplied_it():
    tie = build_geo_tie(ENDPOINTS, supplied_by="site survey 2019-03-20")
    assert tie.supplied_by == "site survey 2019-03-20"
    assert tie.span_m == pytest.approx(111.0)


# --- quality is measured where measurement is possible ---

def test_two_points_cannot_be_checked_and_report_no_residual():
    """Two points define a line; a 0.0 residual would imply a check that never ran."""
    q = assess_tie(ENDPOINTS)
    assert q.checkable is False
    assert q.rms_residual_m is None
    assert "cannot disagree" in q.note


def test_a_straight_line_of_three_points_fits(rtol=1e-6):
    q = assess_tie(STRAIGHT)
    assert q.checkable is True
    assert q.rms_residual_m == pytest.approx(0.0, abs=0.01)


def test_a_curved_line_shows_up_in_the_residuals():
    """A survey that bends cannot be described by two endpoints, and says so."""
    curved = [
        ControlPoint(along_track_m=0.0, lat=41.0000, lon=15.0000),
        ControlPoint(along_track_m=55.5, lat=41.0005, lon=15.0010),   # off to the side
        ControlPoint(along_track_m=111.0, lat=41.0010, lon=15.0000),
    ]
    q = assess_tie(curved)
    assert q.checkable is True
    assert q.rms_residual_m > 10.0


def test_verification_requires_an_actual_check_that_passed():
    assert build_geo_tie(STRAIGHT, "s", max_rms_residual_m=1.0).verified is True
    # a curved line fails the same tolerance
    curved = STRAIGHT[:1] + [ControlPoint(along_track_m=55.5, lat=41.0005, lon=15.002)] + STRAIGHT[-1:]
    assert build_geo_tie(curved, "s", max_rms_residual_m=1.0).verified is False


def test_a_two_point_tie_is_never_verified():
    """Usable, but nothing about it was tested."""
    assert build_geo_tie(ENDPOINTS, "s", max_rms_residual_m=1.0).verified is False


def test_no_tolerance_means_no_verification_claim():
    assert build_geo_tie(STRAIGHT, "s").verified is False


# --- applying a tie ---

def test_registration_adds_a_position_without_touching_the_native_one():
    """The core contract: registration is additive, never destructive."""
    records = _odometry_records()
    native = [(r.position.kind, r.position.along_track_m) for r in records]
    assert apply_geo_tie(records, build_geo_tie(ENDPOINTS, "surveyor")) == len(records)

    # the acquisition's own coordinate is untouched
    assert [(r.position.kind, r.position.along_track_m) for r in records] == native
    assert all(r.position.kind == PositionKind.ODOMETRY for r in records)
    # and a registered one now exists alongside it
    assert all(r.registered_position.kind == PositionKind.GEOGRAPHIC for r in records)
    assert all(has_geographic_coordinates(r) for r in records)


def test_the_effective_position_is_the_registered_one():
    records = _odometry_records()
    assert effective_position(records[0]).kind == PositionKind.ODOMETRY
    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "surveyor"))
    assert effective_position(records[0]).kind == PositionKind.GEOGRAPHIC


def test_registration_can_be_redone_because_nothing_was_lost():
    """A corrected survey replaces the registration, not the measurement."""
    records = _odometry_records()
    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "first attempt"))
    first = [r.registered_position.lat for r in records]

    corrected = [ControlPoint(along_track_m=0.0, lat=42.0, lon=16.0),
                 ControlPoint(along_track_m=111.0, lat=42.001, lon=16.0)]
    apply_geo_tie(records, build_geo_tie(corrected, "corrected survey"))

    assert [r.registered_position.lat for r in records] != first
    assert all(r.position.kind == PositionKind.ODOMETRY for r in records)
    assert records[0].metadata["registered_by"] == "corrected survey"


def test_interpolation_is_linear_along_the_line():
    records = _odometry_records(n=5, spacing=27.75)   # 0, 27.75, 55.5, 83.25, 111
    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "surveyor"))
    lats = [r.registered_position.lat for r in records]
    assert lats[0] == pytest.approx(41.0000)
    assert lats[2] == pytest.approx(41.0005)          # midpoint
    assert lats[-1] == pytest.approx(41.0010)
    steps = [lats[i + 1] - lats[i] for i in range(len(lats) - 1)]
    assert all(s == pytest.approx(steps[0]) for s in steps)


def test_the_legacy_fields_follow_the_position():
    records = _odometry_records()
    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "surveyor"))
    for r in records:
        assert (r.latitude, r.longitude) == (r.registered_position.lat,
                                             r.registered_position.lon)


def test_a_registered_position_stays_distinguishable_from_a_surveyed_one():
    """The whole point: registered is not measured."""
    records = _odometry_records()
    assert all(position_provenance(r) == POSITION_NATIVE for r in records)

    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "surveyor"))

    for r in records:
        assert position_provenance(r) == POSITION_REGISTERED
        assert r.metadata["registration_source"] == "geo_tie"
        assert r.metadata["registered_by"] == "surveyor"
        assert r.metadata["registration_verified"] is False


def test_the_along_track_distance_is_preserved():
    """The measured coordinate must survive the derived one being added."""
    records = _odometry_records(spacing=27.75)
    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "surveyor"))
    assert [r.metadata["along_track_m"] for r in records] == \
           pytest.approx([0.0, 27.75, 55.5, 83.25, 111.0])


def test_applying_to_records_with_no_odometry_axis_is_refused():
    records = [SubterraRecord(dataset_id="ds", sensor_type=SensorType.GPR,
                              position=NoPosition(reason="none"))]
    with pytest.raises(GeoTieError, match="no record carries an odometry position"):
        apply_geo_tie(records, build_geo_tie(ENDPOINTS, "s"))


def test_non_odometry_records_are_left_untouched():
    """A tie maps one acquisition's axis; it says nothing about anyone else."""
    odo = _odometry_records(n=3)
    other = SubterraRecord(dataset_id="ds2", sensor_type=SensorType.SEISMIC,
                           latitude=10.0, longitude=20.0)
    promoted = apply_geo_tie(odo + [other], build_geo_tie(ENDPOINTS, "s"))
    assert promoted == 3
    assert (other.latitude, other.longitude) == (10.0, 20.0)


def test_extrapolation_beyond_the_control_points_still_works_but_warns(caplog):
    """A short tie on a long line extrapolates; the caller is told."""
    import logging
    records = _odometry_records(n=5, spacing=100.0)     # 0..400 m
    short = [ControlPoint(along_track_m=0.0, lat=41.0, lon=15.0),
             ControlPoint(along_track_m=20.0, lat=41.0002, lon=15.0)]
    with caplog.at_level(logging.WARNING):
        apply_geo_tie(records, build_geo_tie(short, "s"))
    assert any("EXTRAPOLATED" in m for m in caplog.messages)
    assert records[-1].registered_position.lat > records[0].registered_position.lat


# --- frame-level provenance ---

def test_the_frame_assumption_says_the_positions_are_derived():
    tie = build_geo_tie(STRAIGHT, "site survey", max_rms_residual_m=1.0)
    a = tie_assumption(tie)
    assert a.key == "geo_tie" and a.value == "site survey"
    assert "SUPPLIED BY CALLER" in a.basis
    assert "not observed by an instrument" in a.basis
    assert a.verified is True


def test_an_unverified_tie_says_so_on_the_frame():
    a = tie_assumption(build_geo_tie(ENDPOINTS, "eyeballed from a map"))
    assert a.verified is False
    assert "not measurable with two control points" in a.basis


def test_the_tied_reference_is_geographic_and_caller_supplied():
    ref = tied_spatial_ref(build_geo_tie(ENDPOINTS, "surveyor"))
    assert ref.kind == CRSKind.GEOGRAPHIC
    assert ref.code == "EPSG:4326"
    assert ref.crs_provenance == CRSProvenance.SUPPLIED_BY_CALLER
    assert "carries no geographic reference" in ref.name


def test_a_frame_without_a_tie_is_not_georeferenced():
    """Absence is a legitimate terminal state, not a gap awaiting a guess."""
    from schemas.spatial import AxisKind, SpatialRef, VerticalAxis
    from schemas.survey_frame import SurveyFrame

    frame = SurveyFrame(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="ids_dt", source_file="line.dt",
        spatial_ref=SpatialRef(kind=CRSKind.ACQUISITION, name="wheel odometry"),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="time-zero", positive_down=True),
    )
    assert frame.geo_tie is None


# --- one tie per survey line ------------------------------------------------

def _two_lines():
    return _odometry_records(n=3, spacing=55.5, path="lineA") + \
           _odometry_records(n=3, spacing=55.5, path="lineB")


def test_a_multi_line_dataset_without_a_named_line_is_refused():
    """Applying one line's tie to another would invent that line's geometry."""
    with pytest.raises(GeoTieError, match="span 2 survey lines"):
        apply_geo_tie(_two_lines(), build_geo_tie(ENDPOINTS, "s"))


def test_a_tie_registers_only_the_line_it_names():
    records = _two_lines()
    tie = build_geo_tie(ENDPOINTS, "surveyor", applies_to="lineA")
    assert apply_geo_tie(records, tie) == 3

    registered = [r for r in records if r.registered_position is not None]
    assert {r.position.path_id for r in registered} == {"lineA"}
    untouched = [r for r in records if r.position.path_id == "lineB"]
    assert all(r.registered_position is None for r in untouched)
    assert all(r.latitude is None for r in untouched)


def test_path_id_overrides_the_ties_own_target():
    records = _two_lines()
    tie = build_geo_tie(ENDPOINTS, "surveyor", applies_to="lineA")
    assert apply_geo_tie(records, tie, path_id="lineB") == 3
    assert {r.position.path_id for r in records if r.registered_position} == {"lineB"}


def test_naming_a_line_that_is_not_present_is_refused():
    with pytest.raises(GeoTieError, match="no record belongs to line"):
        apply_geo_tie(_two_lines(), build_geo_tie(ENDPOINTS, "s", applies_to="lineZ"))


def test_each_line_can_carry_its_own_tie():
    records = _two_lines()
    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "sA", applies_to="lineA"))
    apply_geo_tie(records, build_geo_tie(
        [ControlPoint(along_track_m=0.0, lat=50.0, lon=5.0),
         ControlPoint(along_track_m=111.0, lat=50.001, lon=5.0)], "sB", applies_to="lineB"))
    by_line = {}
    for r in records:
        by_line.setdefault(r.position.path_id, []).append(r.registered_position.lat)
    assert all(v == pytest.approx(41.0, abs=0.01) for v in by_line["lineA"])
    assert all(v == pytest.approx(50.0, abs=0.01) for v in by_line["lineB"])


# --- pipelines keep working with no tie at all ------------------------------

def test_untied_records_behave_exactly_as_before():
    """Requirement: existing pipelines operate correctly when no tie exists."""
    from fusion.sensor_fusion import partition_by_spatial_ref

    records = _odometry_records()
    assert all(r.registered_position is None for r in records)
    assert all(position_provenance(r) == POSITION_NATIVE for r in records)
    assert not any(has_geographic_coordinates(r) for r in records)
    assert [p.kind for p in partition_by_spatial_ref(records)] == ["odometry"]


def test_registration_makes_a_line_fusable():
    """The concrete payoff: a registered line can be related to other sensors."""
    from fusion.sensor_fusion import partition_by_spatial_ref

    records = _odometry_records()
    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "surveyor"))
    partitions = partition_by_spatial_ref(records)
    assert [p.kind for p in partitions] == ["geographic"]
    assert partitions[0].fusable is True


# --- SpatialRef compatibility after registration ----------------------------

def test_the_frame_keeps_its_acquisition_ref_and_gains_a_registered_one():
    from schemas.spatial import AxisKind, SpatialRef, VerticalAxis, assert_position_matches_ref
    from schemas.survey_frame import SurveyFrame

    tie = build_geo_tie(STRAIGHT, "surveyor", max_rms_residual_m=1.0)
    frame = SurveyFrame(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="ids_dt", source_file="line.dt",
        spatial_ref=SpatialRef(kind=CRSKind.ACQUISITION, name="wheel odometry"),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="time-zero", positive_down=True),
        geo_tie=tie,
        registered_spatial_ref=tied_spatial_ref(tie),
        assumptions=[tie_assumption(tie)],
    )
    # the acquisition's own reference is unchanged...
    assert frame.spatial_ref.kind == CRSKind.ACQUISITION
    assert frame.spatial_ref.code is None
    # ...and the registered one coexists with it
    assert frame.registered_spatial_ref.kind == CRSKind.GEOGRAPHIC
    assert frame.registered_spatial_ref.code == "EPSG:4326"

    records = _odometry_records(n=3, spacing=55.5)
    apply_geo_tie(records, tie)
    # each position agrees with the ref that describes it
    assert_position_matches_ref(records[0].position, frame.spatial_ref)
    assert_position_matches_ref(records[0].registered_position, frame.registered_spatial_ref)


def test_a_registered_frame_round_trips_through_the_store(tmp_path, monkeypatch):
    from configs import settings as settings_mod
    from database.frames_store import load_frames, save_frames
    from schemas.spatial import AxisKind, SpatialRef, VerticalAxis
    from schemas.survey_frame import SurveyFrame

    monkeypatch.setattr(type(settings_mod.settings), "processed_dir",
                        property(lambda self: tmp_path))
    tie = build_geo_tie(STRAIGHT, "surveyor", applies_to="line", max_rms_residual_m=1.0)
    frame = SurveyFrame(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="ids_dt", source_file="line.dt",
        spatial_ref=SpatialRef(kind=CRSKind.ACQUISITION, name="wheel odometry"),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="time-zero", positive_down=True),
        geo_tie=tie, registered_spatial_ref=tied_spatial_ref(tie),
    )
    save_frames("ds", [frame])
    back = load_frames("ds")[0]
    assert back.geo_tie == tie
    assert back.geo_tie.applies_to == "line"
    assert back.registered_spatial_ref.code == "EPSG:4326"


def test_a_registered_record_round_trips_through_serialization():
    records = _odometry_records(n=2)
    apply_geo_tie(records, build_geo_tie(ENDPOINTS, "surveyor"))
    back = SubterraRecord.model_validate_json(records[0].model_dump_json())
    assert back.position.kind == PositionKind.ODOMETRY
    assert back.registered_position.kind == PositionKind.GEOGRAPHIC
    assert position_provenance(back) == POSITION_REGISTERED
