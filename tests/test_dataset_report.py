"""
The Dataset Report.

WHAT THESE TESTS DEFEND. A report is a set of claims about a dataset, and the
damaging failure is not a crash -- it is a claim that is confidently wrong. So
the tests below are mostly about what the report must NOT say: that a depth is
placeable when no datum is declared, that a candidate is an object, that a
survey has an extent when nothing carries a position, that a capability is
ready when the evidence for it is absent.

Every case is built from constructed frames and records rather than from the
corpus, so each readiness branch is reached deliberately. A test that only ever
sees the six datasets currently held would pass while the BLOCKED path was
broken, because every one of them blocks for the same reason.
"""
from datetime import datetime

import pytest

from api.reports import build_dataset_report
from fusion.vertical_reference import assess
from schemas.dataset_report import (
    SIGNAL_CHAIN_STEP_ORDER,
    TIME_ZERO_ASSUMPTION_KEY,
    CandidateSummary,
    Capability,
    DatasetReport,
    QualityDimension,
    QualityReport,
    Readiness,
    assess_readiness,
    build_geometry,
    build_horizontal,
    build_identity,
    build_signal_chain,
    build_vertical,
    build_volume,
)
from schemas.provenance import LOCAL_ANOMALY_BASIS
from schemas.spatial import (
    Assumption,
    AxisKind,
    CRSKind,
    CRSProvenance,
    GeographicPosition,
    NoPosition,
    OdometryPosition,
    ProjectedPosition,
    SpatialRef,
    VerticalAxis,
    VerticalDatum,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame
from validators.dataset_validator import (
    quality_dimensions,
    score_from_dimensions,
    validate_dataset,
)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def frame(frame_id="d:line1", *, crs=None, axis=None, geo_tie=None, n_positions=10,
          assumptions=None):
    return SurveyFrame(
        frame_id=frame_id, dataset_id="d", modality=SensorType.GPR,
        source_format="segy", source_file=f"{frame_id}.sgy",
        spatial_ref=crs or SpatialRef(kind=CRSKind.UNKNOWN),
        vertical_axis=axis or VerticalAxis(
            kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
            origin="instrument time zero", positive_down=True, n_samples=512,
            sample_interval=0.4),
        n_positions=n_positions, geo_tie=geo_tie, assumptions=assumptions or [],
    )


GEOGRAPHIC = SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                        crs_provenance=CRSProvenance.DECLARED_BY_SOURCE,
                        horizontal_units="deg")
PROJECTED_UNDECLARED = SpatialRef(kind=CRSKind.PROJECTED)
ACQUISITION = SpatialRef(kind=CRSKind.ACQUISITION,
                         origin_description="along-track distance from line start")

TIME_AXIS = VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                         origin="instrument time zero", positive_down=True)
DEPTH_AXIS = VerticalAxis(kind=AxisKind.DEPTH_M, units="m",
                          origin="instrument time zero", positive_down=True,
                          conversion={"method": "constant_velocity", "v": 0.1})
GROUNDED_DEPTH_AXIS = VerticalAxis(
    kind=AxisKind.DEPTH_M, units="m", origin="ground surface at trace",
    positive_down=True, conversion={"method": "constant_velocity", "v": 0.1},
    vertical_datum=VerticalDatum(code="NAP", provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                                 name="NAP"))
SURFACE_AXIS = VerticalAxis(
    kind=AxisKind.ELEVATION_M, units="m", origin="NAP", positive_down=False,
    vertical_datum=VerticalDatum(code="NAP", provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                                 name="NAP"))
NO_AXIS = VerticalAxis(kind=AxisKind.NONE, units="", origin="", positive_down=True)


def record(i=0, *, position=None, signal=None, depth=None, timestamp=None,
           frame_id="d:line1"):
    return SubterraRecord(
        dataset_id="d", sensor_type=SensorType.GPR,
        position=position or NoPosition(reason="the format provides none"),
        latitude=getattr(position, "lat", None), longitude=getattr(position, "lon", None),
        frame_id=frame_id, depth=depth, timestamp=timestamp,
        signal=signal if signal is not None else [0.1, 0.2, 0.3],
        metadata={"source_file": "line1.sgy", "trace_index": i},
    )


def geographic_records(n=5):
    return [record(i, position=GeographicPosition(lat=52.0 + i * 1e-4, lon=4.3))
            for i in range(n)]


def record_with_bad_signal(i=99):
    """
    A record carrying NaN samples.

    `SubterraRecord` REJECTS these at construction -- "signal contains NaN/Inf
    values; run preprocessing before ingest" -- so this has to bypass
    validation to exist. That is the point: the validator's invalid-signal
    count and the report's signal-integrity dimension are defence in depth
    against records that arrive by a path which did not validate them (a
    legacy JSONL file, a converter writing flat dicts). Reaching the branch
    requires constructing one the same way such a path would.
    """
    return SubterraRecord.model_construct(
        dataset_id="d", sensor_type=SensorType.GPR,
        position=NoPosition(reason="the format provides none"),
        latitude=None, longitude=None, frame_id="d:line1",
        depth=None, timestamp=None, signal=[float("nan")], metadata={})


class FakeDataset:
    """The dataset row, without a database."""

    def __init__(self, **kw):
        self.id = kw.get("id", "d")
        self.name = kw.get("name", "Test survey")
        self.source = kw.get("source")
        self.source_url = kw.get("source_url")
        self.license = kw.get("license")
        self.sensor_type = kw.get("sensor_type", "gpr")
        self.original_format = kw.get("original_format", "segy")
        self.collection_date = kw.get("collection_date")
        self.has_ground_truth = kw.get("has_ground_truth", False)
        self.version = kw.get("version", 1)
        self.checksum = kw.get("checksum")
        self.quality_score = kw.get("quality_score")
        self.record_count = kw.get("record_count", 0)
        self.owner_id = kw.get("owner_id")
        self.extra_metadata = kw.get("extra_metadata", {})
        self.created_at = kw.get("created_at", datetime(2026, 1, 1))
        self.updated_at = kw.get("updated_at", datetime(2026, 1, 1))


def all_readiness(records, frames):
    """Every capability assessed, from constructed data alone."""
    dims = quality_dimensions(records)
    return assess_readiness(
        build_volume(records, frames),
        build_horizontal(records, frames),
        build_vertical(frames, assess=assess),
        QualityReport(computed_score=score_from_dimensions(dims) if dims else None,
                      dimensions=dims),
        CandidateSummary(),
    )


def readiness_of(records, frames, capability):
    return next(c for c in all_readiness(records, frames) if c.capability == capability)


# ---------------------------------------------------------------------------
# the quality score is preserved exactly
# ---------------------------------------------------------------------------

def test_the_dimensions_reproduce_the_existing_score_exactly():
    """
    The refactor exposed the components of `quality_score`; it must not have
    moved the number, which dataset search filters on.
    """
    records = [
        record(0, position=GeographicPosition(lat=52.0, lon=4.3), depth=1.0,
               timestamp=datetime(2026, 1, 1)),
        record(1, position=NoPosition(reason="none")),
        record_with_bad_signal(2),
    ]
    report = validate_dataset(records, "d")
    assert report.quality_score == score_from_dimensions(quality_dimensions(records))


def test_the_score_is_the_weighted_sum_of_the_reported_dimensions():
    records = geographic_records(4)
    dims = quality_dimensions(records)
    expected = round(sum(d.weight * d.value for d in dims), 4)
    assert validate_dataset(records, "d").quality_score == expected


def test_an_empty_dataset_reports_no_dimensions_rather_than_zeroed_ones():
    """A dimension of 0.0 would claim perfectly bad quality; there is nothing
    to measure."""
    assert quality_dimensions([]) == []
    assert validate_dataset([], "d").quality_score == 0.0


def test_unweighted_dimensions_cannot_move_the_score():
    """The report adds reported-only dimensions; they must not disturb a number
    other things depend on."""
    dims = quality_dimensions(geographic_records(3))
    before = score_from_dimensions(dims)
    dims.append(QualityDimension(name="extra", value=0.0, weight=0.0, basis="reported only"))
    assert score_from_dimensions(dims) == before


# ---------------------------------------------------------------------------
# horizontal reference: coordinates existing is not coordinates being enough
# ---------------------------------------------------------------------------

def test_geographic_coordinates_are_earth_referenced():
    h = build_horizontal(geographic_records(3), [frame(crs=GEOGRAPHIC)])
    assert h.coordinates_present and h.earth_referenced
    assert h.positioned_record_count == 3


def test_odometry_coordinates_exist_but_are_not_earth_referenced():
    """
    The distinction the whole section exists for: an odometry frame genuinely
    knows how far along the line each trace sits, and genuinely does not know
    where the line is.
    """
    records = [record(i, position=OdometryPosition(along_track_m=i * 0.5))
               for i in range(4)]
    h = build_horizontal(records, [frame(crs=ACQUISITION)])
    assert h.coordinates_present is True
    assert h.earth_referenced is False
    assert any("GeoTie" in m for m in h.missing)


def test_projected_coordinates_without_a_declared_projection_are_not_enough():
    records = [record(i, position=ProjectedPosition(easting=501134.0, northing=4544705.0))
               for i in range(3)]
    h = build_horizontal(records, [frame(crs=PROJECTED_UNDECLARED)])
    assert h.coordinates_present is True
    assert h.earth_referenced is False
    assert any("EPSG" in m for m in h.missing)


def test_a_dataset_with_no_positions_says_so_and_names_what_is_missing():
    h = build_horizontal([record(i) for i in range(3)], [frame()])
    assert h.coordinates_present is False
    assert h.missing


def test_mixed_earth_referencing_is_partial_not_ready():
    records = geographic_records(2) + [record(9, position=OdometryPosition(along_track_m=1.0))]
    frames = [frame("d:a", crs=GEOGRAPHIC), frame("d:b", crs=ACQUISITION)]
    assert readiness_of(records, frames, Capability.HORIZONTAL_REGISTRATION).readiness \
        == Readiness.PARTIAL


# ---------------------------------------------------------------------------
# vertical reference: the section the report exists for
# ---------------------------------------------------------------------------

def test_a_time_axis_with_no_velocity_has_no_depth_at_all():
    v = build_vertical([frame(axis=TIME_AXIS)], assess=assess)
    assert v.depth_axis_available is False
    assert v.time_to_depth_justified is False
    assert any("velocity" in m for m in v.missing)


def test_a_converted_depth_is_derived_and_still_not_placeable():
    """
    A velocity turns time into a distance. It does not say what that distance
    is measured FROM, which is the part an absolute Z needs.
    """
    v = build_vertical([frame(axis=DEPTH_AXIS)], assess=assess)
    assert v.depth_axis_available is True
    assert v.depth_basis.value == "derived"
    assert v.time_to_depth_justified is False   # origin is instrument time zero
    assert v.absolute_elevation_available is False
    assert any("ground surface" in r for r in v.reasons)


def test_an_undeclared_vertical_datum_is_reported_as_undeclared():
    v = build_vertical([frame(axis=DEPTH_AXIS)], assess=assess)
    assert v.vertical_datum_declared is False
    assert v.vertical_datums == []


def test_no_surface_model_is_itself_the_answer_not_a_missing_computation():
    v = build_vertical([frame(axis=DEPTH_AXIS)], assess=assess)
    assert v.surface_model_held is False
    assert v.relationship_kind is None
    assert any("surface elevation model" in m for m in v.missing)


def test_a_two_dimensional_dataset_has_no_depth_axis_origin_to_be_wrong_about():
    """`AxisKind.NONE` is the absence of a vertical axis, not a subsurface one."""
    v = build_vertical([frame(axis=NO_AXIS)], assess=assess)
    assert v.depth_axis_available is False
    assert not any("depth axis origin" in r for r in v.reasons)
    assert any("no subsurface vertical axis" in r for r in v.reasons)


def test_absolute_elevation_is_reported_only_when_everything_is_declared():
    """
    The one configuration in which a Z may be computed: both datums declared
    and equal, and the depth axis origin tied to the ground.
    """
    frames = [frame("d:gpr", axis=GROUNDED_DEPTH_AXIS), frame("d:dem", axis=SURFACE_AXIS)]
    v = build_vertical(frames, assess=assess)
    assert v.surface_model_held is True
    assert v.absolute_elevation_available is True
    assert v.relationship_kind == "absolute_elevation"


def test_one_registered_line_does_not_register_the_others():
    """The weakest frame is the dataset's state."""
    frames = [
        frame("d:good", axis=GROUNDED_DEPTH_AXIS),
        frame("d:bad", axis=DEPTH_AXIS),
        frame("d:dem", axis=SURFACE_AXIS),
    ]
    v = build_vertical(frames, assess=assess)
    assert v.absolute_elevation_available is False


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------

def test_an_empty_dataset_blocks_ingestion_rather_than_failing():
    c = readiness_of([], [], Capability.INGESTION)
    assert c.readiness == Readiness.BLOCKED
    assert c.missing


def test_records_without_a_signal_block_signal_processing():
    records = [record(i, signal=[]) for i in range(3)]
    assert readiness_of(records, [frame()], Capability.SIGNAL_PROCESSING).readiness \
        == Readiness.BLOCKED


def test_nan_samples_make_signal_processing_partial_not_blocked():
    records = geographic_records(3) + [record_with_bad_signal(9)]
    c = readiness_of(records, [frame(crs=GEOGRAPHIC)], Capability.SIGNAL_PROCESSING)
    assert c.readiness == Readiness.PARTIAL


def test_candidate_analysis_is_ready_without_any_position():
    """
    An anomaly lives in a trace. Requiring a position for candidate analysis
    would block the one thing an unpositioned GPR line CAN support.
    """
    records = [record(i) for i in range(3)]
    c = readiness_of(records, [frame()], Capability.CANDIDATE_ANALYSIS)
    assert c.readiness == Readiness.READY
    assert readiness_of(records, [frame()], Capability.HORIZONTAL_REGISTRATION).readiness \
        == Readiness.BLOCKED


def test_object_classification_is_blocked_for_every_dataset():
    """
    Not a property of any dataset: Subterra has no validated classifier. This
    is the structural guard against candidate becoming detection.
    """
    perfect = [frame("d:gpr", crs=GEOGRAPHIC, axis=GROUNDED_DEPTH_AXIS),
               frame("d:dem", crs=GEOGRAPHIC, axis=SURFACE_AXIS)]
    c = readiness_of(geographic_records(5), perfect, Capability.OBJECT_CLASSIFICATION)
    assert c.readiness == Readiness.BLOCKED
    assert "validated" in c.reason


def test_3d_reconstruction_names_which_registration_blocks_it():
    c = readiness_of(geographic_records(3), [frame(crs=GEOGRAPHIC, axis=DEPTH_AXIS)],
                     Capability.RECONSTRUCTION_3D)
    assert c.readiness == Readiness.BLOCKED
    assert "vertical registration" in c.reason
    assert "horizontal registration" not in c.reason   # that one IS available
    assert Capability.VERTICAL_REGISTRATION in c.depends_on


def test_3d_reconstruction_blocks_on_both_when_both_are_absent():
    c = readiness_of([record(i) for i in range(3)], [frame(axis=TIME_AXIS)],
                     Capability.RECONSTRUCTION_3D)
    assert "horizontal registration and vertical registration" in c.reason


def test_3d_is_not_claimed_ready_even_when_registration_is_complete():
    """Registration is necessary, not sufficient -- stage 17 does not exist."""
    frames = [frame("d:gpr", crs=GEOGRAPHIC, axis=GROUNDED_DEPTH_AXIS),
              frame("d:dem", crs=GEOGRAPHIC, axis=SURFACE_AXIS)]
    c = readiness_of(geographic_records(5), frames, Capability.RECONSTRUCTION_3D)
    assert c.readiness == Readiness.PARTIAL
    assert c.readiness != Readiness.READY


def test_every_non_ready_capability_names_something_missing():
    """A blocker with no enumerated cause cannot be acted on."""
    for records, frames in (
        ([], []),
        ([record(i) for i in range(3)], [frame()]),
        (geographic_records(3), [frame(crs=GEOGRAPHIC, axis=DEPTH_AXIS)]),
    ):
        for c in all_readiness(records, frames):
            assert c.reason, f"{c.capability} states no reason"
            if c.readiness != Readiness.READY:
                assert c.missing, f"{c.capability} is {c.readiness} with nothing missing"


# ---------------------------------------------------------------------------
# geometry: never an extent that was not surveyed
# ---------------------------------------------------------------------------

def test_no_bounds_are_reported_without_geographic_positions():
    g = build_geometry([record(i) for i in range(3)], [frame()], bounds=None, spans=None)
    assert g.bounds is None
    assert g.lat_span_m is None
    assert any("zero-sized" in r for r in g.reasons)


def test_line_spacing_and_orientation_are_never_inferred():
    g = build_geometry(geographic_records(5), [frame(crs=GEOGRAPHIC)],
                       bounds={"min_lat": 1.0, "max_lat": 2.0, "min_lon": 3.0, "max_lon": 4.0},
                       spans={"lat_span": 100.0, "lon_span": 50.0})
    assert not hasattr(g, "line_spacing_m")
    assert not hasattr(g, "orientation_deg")
    assert any("never surveyed" in r for r in g.reasons)


def test_along_track_extent_is_measured_only_where_odometry_exists():
    records = [record(i, position=OdometryPosition(along_track_m=i * 2.0)) for i in range(4)]
    g = build_geometry(records, [frame(crs=ACQUISITION)])
    assert g.along_track_extent_m == {"d:line1": 6.0}


# ---------------------------------------------------------------------------
# identity: absence is named, never filled
# ---------------------------------------------------------------------------

def test_undeclared_metadata_is_listed_rather_than_invented():
    identity = build_identity(FakeDataset(), [frame()])
    assert identity.manufacturer is None
    assert identity.device_model is None
    assert "manufacturer" in identity.undeclared
    assert "acquisition date" in identity.undeclared


def test_a_format_is_not_a_manufacturer():
    """`.dt` implies IDS to a human. It must not imply it to the report."""
    identity = build_identity(FakeDataset(original_format="ids_dt"), [frame()])
    assert identity.manufacturer is None


def test_a_null_owner_means_system_not_unknown():
    assert build_identity(FakeDataset(owner_id=None), []).is_system_dataset is True
    assert build_identity(FakeDataset(owner_id="u1"), []).is_system_dataset is False


# ---------------------------------------------------------------------------
# candidates are never detections
# ---------------------------------------------------------------------------

def test_the_candidate_summary_cannot_express_a_detection():
    fields = set(CandidateSummary.model_fields)
    for forbidden in ("detections", "detected_objects", "object_class",
                      "probability", "confidence"):
        assert forbidden not in fields
    assert CandidateSummary().classified_object_count == 0


def test_a_dataset_with_no_candidate_analysis_says_not_analysed():
    summary = CandidateSummary()
    assert summary.analysed is False
    assert summary.candidate_count == 0
    assert "not detected objects" in summary.note


# ---------------------------------------------------------------------------
# the Phase 5 signal-processing chain: recorded, not re-run, never invented
# ---------------------------------------------------------------------------

def test_no_applied_entry_means_not_recorded_not_an_error():
    chain = build_signal_chain(None)
    assert chain.recorded is False
    assert chain.steps == []
    assert "not recorded" in chain.reason


def test_an_empty_dict_is_treated_the_same_as_no_entry():
    chain = build_signal_chain({})
    assert chain.recorded is False
    assert chain.steps == []


def test_the_chain_reports_every_step_in_the_order_it_actually_ran():
    applied = {
        "dewow": True, "dewow_window": 15,
        "background_removal": True,
        "gain": True, "gain_type": "linear", "gain_power": 1.0,
    }
    chain = build_signal_chain(applied)
    assert chain.recorded is True
    assert [s.step for s in chain.steps] == list(SIGNAL_CHAIN_STEP_ORDER)
    assert [s.step for s in chain.steps] == ["time_zero", "background_removal", "dewow", "gain"]
    # time_zero has no evidence here (no applied keys, no frame claim) -- it
    # is still present, just not ran.
    math_steps = [s for s in chain.steps if s.step != "time_zero"]
    assert all(s.ran for s in math_steps)
    time_zero = next(s for s in chain.steps if s.step == "time_zero")
    assert time_zero.ran is False


def test_parameters_are_named_verbatim_for_the_steps_that_carry_them():
    applied = {
        "dewow": True, "dewow_window": 21,
        "background_removal": True,
        "gain": True, "gain_type": "agc", "gain_power": 2.0,
    }
    chain = build_signal_chain(applied)
    by_step = {s.step: s for s in chain.steps}
    assert by_step["dewow"].parameters == {"dewow_window": 21}
    assert by_step["gain"].parameters == {"gain_type": "agc", "gain_power": 2.0}
    # background_removal carries no recorded parameters -- nothing is invented.
    assert by_step["background_removal"].parameters == {}


def test_a_step_that_did_not_run_carries_no_parameters():
    applied = {
        "dewow": False, "dewow_window": None,
        "background_removal": True,
        "gain": False, "gain_type": None, "gain_power": None,
    }
    chain = build_signal_chain(applied)
    by_step = {s.step: s for s in chain.steps}
    assert by_step["dewow"].ran is False
    assert by_step["dewow"].parameters == {}
    assert by_step["gain"].ran is False
    assert by_step["gain"].parameters == {}
    assert by_step["background_removal"].ran is True


def test_the_chain_never_invents_a_default_when_nothing_was_run(stored):
    """A record with no `processing_applied` entry at all -- e.g. depth-slice
    CSVs process_gpr_traces has nothing to act on -- must not read as the
    platform's own dewow/background/gain defaults having applied."""
    from database.records_store import save_records

    save_records("d", geographic_records(3))
    report = build_dataset_report(FakeDataset(id="d"))
    assert report.signal_chain.recorded is False
    assert report.signal_chain.steps == []


def test_the_chain_reads_the_same_processing_applied_entry_the_preprocessing_stage_reads(stored):
    """One definition, not two that could disagree about what ran."""
    from database.records_store import save_records

    applied = {
        "dewow": True, "dewow_window": 15,
        "background_removal": True,
        "gain": True, "gain_type": "linear", "gain_power": 1.0,
    }
    records = geographic_records(3)
    for r in records:
        r.metadata["processing_applied"] = applied
    save_records("d", records)

    report = build_dataset_report(FakeDataset(id="d"))
    assert report.signal_chain.recorded is True
    math_steps = [s for s in report.signal_chain.steps if s.step != "time_zero"]
    assert all(s.ran for s in math_steps)
    preprocessing = next(p for p in report.processing if p.stage == "preprocessing")
    assert preprocessing.status == "completed"


# ---------------------------------------------------------------------------
# the time_zero step: a converter's recorded-but-withheld claim, never
# promoted to a correction, never omitted once the chain is recorded
# ---------------------------------------------------------------------------

def _time_zero_claim(value=99.04):
    return Assumption(
        key=TIME_ZERO_ASSUMPTION_KEY, value=value,
        basis=(
            f"the header's rhf_position is {value} ns, but it is NOT applied. "
            f"The axis starts at instrument time-zero and the raw value is "
            f"preserved here."
        ),
        verified=False,
    )


def test_a_frame_claim_makes_time_zero_the_first_step_ran_false_verbatim():
    applied = {
        "dewow": True, "dewow_window": 15, "background_removal": True,
        "gain": True, "gain_type": "linear", "gain_power": 1.0,
    }
    claimant = frame(assumptions=[_time_zero_claim(99.04)])
    chain = build_signal_chain(applied, [claimant])

    assert chain.steps[0].step == "time_zero"
    assert chain.steps[0].ran is False
    assert chain.steps[0].parameters == {TIME_ZERO_ASSUMPTION_KEY: 99.04}
    assert "NOT applied" in chain.steps[0].reason
    assert "99.04" in chain.steps[0].reason


def test_recorded_with_no_time_zero_claim_still_names_time_zero_first_not_omitted():
    applied = {
        "dewow": True, "dewow_window": 15, "background_removal": True,
        "gain": True, "gain_type": "linear", "gain_power": 1.0,
    }
    chain = build_signal_chain(applied, [frame()])   # no assumption on this frame

    assert chain.steps[0].step == "time_zero"
    assert chain.steps[0].ran is False
    assert chain.steps[0].parameters == {}
    assert "does not apply a time-zero correction" in chain.steps[0].reason
    assert "none" in chain.steps[0].reason.lower() or "no" in chain.steps[0].reason.lower()


def test_a_claim_alone_with_no_processing_applied_still_recorded():
    """process_gpr_traces never ran, but a converter already recorded a
    time-zero claim -- that alone makes the chain `recorded`, with only the
    time_zero step (no evidence exists for the other three)."""
    claimant = frame(assumptions=[_time_zero_claim(-10)])
    chain = build_signal_chain(None, [claimant])

    assert chain.recorded is True
    assert [s.step for s in chain.steps] == ["time_zero"]
    assert chain.steps[0].ran is False
    assert chain.steps[0].parameters == {TIME_ZERO_ASSUMPTION_KEY: -10}


def test_no_processing_applied_and_no_claim_stays_not_recorded():
    """The existing not-recorded meaning survives unchanged when nothing at
    all was recorded -- no processing_applied, no time-zero claim."""
    chain = build_signal_chain(None, [frame()])
    assert chain.recorded is False
    assert chain.steps == []
    assert "not recorded" in chain.reason


def test_the_first_frames_claim_is_used_when_several_frames_are_present():
    claimant = frame("d:line1", assumptions=[_time_zero_claim(5.0)])
    bystander = frame("d:line2")
    chain = build_signal_chain(None, [claimant, bystander])
    assert chain.steps[0].parameters == {TIME_ZERO_ASSUMPTION_KEY: 5.0}


def test_the_report_reads_a_stored_frame_claim_end_to_end(stored):
    from database.frames_store import save_frames
    from database.records_store import save_records

    save_records("d", geographic_records(3))
    save_frames("d", [frame(assumptions=[_time_zero_claim(99.04)])])

    report = build_dataset_report(FakeDataset(id="d"))
    assert report.signal_chain.recorded is True
    assert report.signal_chain.steps[0].step == "time_zero"
    assert report.signal_chain.steps[0].parameters == {TIME_ZERO_ASSUMPTION_KEY: 99.04}


def test_the_signal_chain_endpoint_and_the_report_still_agree_with_a_time_zero_claim(api, stored):
    from database.frames_store import save_frames
    from database.records_store import save_records

    save_records("ds1", geographic_records(3))
    save_frames("ds1", [frame(assumptions=[_time_zero_claim(99.04)])])

    thin = api.get("/api/datasets/ds1/signal-chain").json()
    report = api.get("/api/datasets/ds1/report").json()
    assert thin == report["signal_chain"]
    assert thin["steps"][0]["step"] == "time_zero"


# ---------------------------------------------------------------------------
# the local_anomaly step: only when preprocess_trace_local_anomaly actually
# overwrote record.signal with a z-score, never invented, reason shared
# verbatim with the provenance projection
# ---------------------------------------------------------------------------

_APPLIED = {
    "dewow": True, "dewow_window": 15, "background_removal": True,
    "gain": True, "gain_type": "linear", "gain_power": 1.0,
}


def test_anomaly_reliable_appends_local_anomaly_last_ran_true_reason_verbatim():
    local_anomaly = {"anomaly_reliable": True, "pre_anomaly_signal": 0.42,
                      "trace_depth_grid_shape": [482, 72]}
    chain = build_signal_chain(_APPLIED, [frame()], local_anomaly)

    assert [s.step for s in chain.steps] == \
        ["time_zero", "background_removal", "dewow", "gain", "local_anomaly"]
    last = chain.steps[-1]
    assert last.ran is True
    assert last.reason == LOCAL_ANOMALY_BASIS
    assert "not a physical unit" in last.reason
    assert last.parameters == {"trace_depth_grid_shape": [482, 72]}
    # The raw per-record amplitude is not summarised at chain level -- there
    # is no single "the" value across every record.
    assert "pre_anomaly_signal" not in last.parameters


def test_anomaly_reliable_false_still_means_the_step_ran():
    """`anomaly_reliable=False` says a CELL had too few ring neighbours, not
    that the step never ran -- presence of the key is what matters."""
    local_anomaly = {"anomaly_reliable": False}
    chain = build_signal_chain(_APPLIED, [frame()], local_anomaly)
    last = chain.steps[-1]
    assert last.step == "local_anomaly"
    assert last.ran is True


def test_no_anomaly_reliable_stamp_does_not_grow_a_local_anomaly_step():
    chain = build_signal_chain(_APPLIED, [frame()], None)
    assert [s.step for s in chain.steps] == \
        ["time_zero", "background_removal", "dewow", "gain"]


def test_anomaly_reliable_alone_makes_recorded_true_with_only_time_zero_and_local_anomaly():
    """process_gpr_traces never ran (no processing_applied), but
    preprocess_trace_local_anomaly did -- gpr_local_anomaly mode."""
    local_anomaly = {"anomaly_reliable": True}
    chain = build_signal_chain(None, [frame()], local_anomaly)

    assert chain.recorded is True
    assert [s.step for s in chain.steps] == ["time_zero", "local_anomaly"]
    assert chain.steps[0].ran is False       # time_zero: no evidence either way
    assert chain.steps[1].ran is True        # local_anomaly: it ran


def test_no_processing_applied_no_time_zero_and_no_anomaly_stamp_stays_not_recorded():
    chain = build_signal_chain(None, [frame()], None)
    assert chain.recorded is False
    assert chain.steps == []


def test_the_signal_chain_endpoint_and_the_report_agree_with_an_anomaly_stamp(api, stored):
    from database.records_store import save_records

    records = geographic_records(3)
    for r in records:
        r.metadata["anomaly_reliable"] = True
        r.metadata["trace_depth_grid_shape"] = [10, 3]
    save_records("ds1", records)

    thin = api.get("/api/datasets/ds1/signal-chain").json()
    report = api.get("/api/datasets/ds1/report").json()
    assert thin == report["signal_chain"]
    assert thin["steps"][-1]["step"] == "local_anomaly"
    assert thin["steps"][-1]["reason"] == LOCAL_ANOMALY_BASIS


# ---------------------------------------------------------------------------
# the whole report, assembled
# ---------------------------------------------------------------------------

@pytest.fixture
def stored(tmp_path, monkeypatch):
    """Point the JSONL stores at a temporary directory."""
    from configs.settings import settings

    # `data_root` is a pydantic-settings FIELD, not a property, so the patch
    # goes on the instance. The subdirectories are created here because
    # `configs/settings.py` makes them once at import, for the real root only.
    monkeypatch.setattr(settings, "data_root", tmp_path)
    for name in ("processed", "raw", "metadata"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_a_report_assembles_for_a_dataset_with_nothing_stored(stored):
    report = build_dataset_report(FakeDataset(id="empty"))
    assert isinstance(report, DatasetReport)
    assert report.volume.record_count == 0
    assert report.capability(Capability.INGESTION).readiness == Readiness.BLOCKED
    # and it still answers every capability rather than omitting the unanswerable
    assert len(report.readiness) == len(Capability)


def test_the_report_is_json_serialisable(stored):
    payload = build_dataset_report(FakeDataset(id="empty")).model_dump(mode="json")
    import json

    assert json.loads(json.dumps(payload))["report_version"]


def test_a_stale_stored_score_is_flagged_rather_than_hidden(stored):
    from database.records_store import save_records

    save_records("d", geographic_records(4))
    report = build_dataset_report(FakeDataset(id="d", quality_score=0.30))
    assert report.quality.stored_score == 0.30
    assert report.quality.computed_score != 0.30
    assert report.quality.score_is_stale is True


def test_the_report_never_contains_a_fabricated_coordinate(stored):
    """
    The (0, 0) placeholder is the specific failure the spatial abstraction was
    built to prevent; a report must not reintroduce it.
    """
    from database.records_store import save_records

    save_records("d", [record(i) for i in range(3)])
    report = build_dataset_report(FakeDataset(id="d"))
    assert report.spatial.geometry.bounds is None
    assert report.spatial.horizontal.positioned_record_count == 0


# ---------------------------------------------------------------------------
# the endpoint
# ---------------------------------------------------------------------------
#
# Authorisation is covered exhaustively in tests/test_auth_and_ownership.py --
# `/api/datasets/{id}/report` is in ID_ROUTES, so the cross-user 404 and the
# route-enumerating guard both already apply to it. What is tested here is the
# behaviour that is specific to the report.

@pytest.fixture
def api(stored):
    """The app, with a database of its own and the default test identity."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from api.main import app
    from database.models import Dataset
    from database.session import Base, get_db

    engine = create_engine(f"sqlite:///{stored / 'report.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    session = Session()
    session.add(Dataset(id="ds1", name="Seeded survey", sensor_type="gpr",
                        original_format="segy", quality_score=0.9, record_count=0))
    session.commit()
    session.close()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_report_endpoint_returns_the_whole_report(api):
    body = api.get("/api/datasets/ds1/report").json()
    assert body["report_version"]
    for section in ("identity", "volume", "spatial", "processing", "signal_chain",
                    "quality", "candidates", "readiness", "provenance"):
        assert section in body, f"the report is missing {section}"


def test_a_nonexistent_dataset_is_a_404(api):
    assert api.get("/api/datasets/does-not-exist/report").status_code == 404


# ---------------------------------------------------------------------------
# GET /{id}/signal-chain -- the thin route the workspace pane calls, kept
# separate from /report because the report is too slow for every page open
# ---------------------------------------------------------------------------

def test_a_nonexistent_dataset_is_a_404_for_signal_chain(api):
    assert api.get("/api/datasets/does-not-exist/signal-chain").status_code == 404


def test_the_signal_chain_endpoint_reports_not_recorded_for_a_dataset_with_no_processing(api):
    body = api.get("/api/datasets/ds1/signal-chain").json()
    assert body["recorded"] is False
    assert body["steps"] == []


def test_the_signal_chain_endpoint_reports_the_recorded_steps_in_order(api, stored):
    from database.records_store import save_records

    applied = {
        "dewow": True, "dewow_window": 15,
        "background_removal": True,
        "gain": True, "gain_type": "linear", "gain_power": 1.0,
    }
    records = geographic_records(3)
    for r in records:
        r.metadata["processing_applied"] = applied
    save_records("ds1", records)

    body = api.get("/api/datasets/ds1/signal-chain").json()
    assert body["recorded"] is True
    assert [s["step"] for s in body["steps"]] == \
        ["time_zero", "background_removal", "dewow", "gain"]
    by_step = {s["step"]: s for s in body["steps"]}
    assert by_step["time_zero"]["ran"] is False
    assert by_step["background_removal"]["ran"] is True
    assert by_step["dewow"]["parameters"] == {"dewow_window": 15}
    assert by_step["gain"]["parameters"] == {"gain_type": "linear", "gain_power": 1.0}


def test_the_signal_chain_endpoint_and_the_report_agree(api, stored):
    """One route is thin and one is not, but both call `build_signal_chain`
    on the same `processing_applied` entry -- they must not disagree."""
    from database.records_store import save_records

    applied = {
        "dewow": True, "dewow_window": 15,
        "background_removal": True,
        "gain": True, "gain_type": "linear", "gain_power": 1.0,
    }
    records = geographic_records(3)
    for r in records:
        r.metadata["processing_applied"] = applied
    save_records("ds1", records)

    thin = api.get("/api/datasets/ds1/signal-chain").json()
    report = api.get("/api/datasets/ds1/report").json()
    assert thin == report["signal_chain"]


def test_a_dataset_with_no_records_reports_rather_than_404ing(api):
    """
    Unlike `/info`. "This dataset produced nothing" is one of the most useful
    things a report can say, and a 404 would make an empty dataset
    indistinguishable from a missing one.
    """
    assert api.get("/api/datasets/ds1/info").status_code == 404

    response = api.get("/api/datasets/ds1/report")
    assert response.status_code == 200
    assert response.json()["volume"]["record_count"] == 0


def test_the_report_answers_every_capability(api):
    body = api.get("/api/datasets/ds1/report").json()
    reported = {c["capability"] for c in body["readiness"]}
    assert reported == {c.value for c in Capability}


def test_every_blocked_capability_gives_a_reason_over_the_wire(api):
    for c in api.get("/api/datasets/ds1/report").json()["readiness"]:
        assert c["reason"]
        if c["readiness"] != "ready":
            assert c["missing"]


def test_the_report_never_ships_a_detection(api):
    """
    The wire format itself must be incapable of carrying one, so no client can
    render a candidate as a confirmed object.
    """
    body = api.get("/api/datasets/ds1/report").json()
    assert body["candidates"]["classified_object_count"] == 0
    for forbidden in ("detected", "probability", "confidence"):
        assert forbidden not in body["candidates"]


def test_the_report_counts_records_live_rather_than_trusting_the_stored_column(api, stored):
    """
    `datasets.record_count` is a stored number and can go stale, the same way
    `quality_score` does -- and a report whose volume section repeated a stale
    column would be describing a dataset that no longer exists. The report
    counts what is actually there.
    """
    from database.records_store import save_records

    save_records("ds1", geographic_records(6))   # the row still says 0

    body = api.get("/api/datasets/ds1/report").json()
    assert body["volume"]["record_count"] == 6
    assert api.get("/api/datasets/ds1/info").json()["record_count"] == 0


def test_the_report_agrees_with_info_about_the_same_dataset(api, stored):
    """
    Two endpoints describing one dataset must not disagree about it. `/info`
    is the older surface and stays the authority for what it already reports,
    so the overlapping fields are pinned against each other.
    """
    from database.models import Dataset
    from database.records_store import save_records
    from database.session import get_db

    from api.main import app

    save_records("ds1", geographic_records(6))
    # Keep the stored column consistent, as a real ingest would.
    session = next(app.dependency_overrides[get_db]())
    session.query(Dataset).filter(Dataset.id == "ds1").update({"record_count": 6})
    session.commit()

    report = api.get("/api/datasets/ds1/report").json()
    info = api.get("/api/datasets/ds1/info").json()

    assert report["volume"]["record_count"] == info["record_count"]
    assert report["identity"]["name"] == info["name"]
    assert report["spatial"]["horizontal"]["positioned_record_count"] == \
        info["geographic_record_count"]
    assert report["quality"]["stored_score"] == info["quality_score"]
