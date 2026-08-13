"""
Radargram semantics, and where a candidate sits on the grid.

WHY THE MAPPING TESTS MATTER MOST. A candidate drawn on the wrong traces is
worse than a candidate not drawn at all: a reviewer opens the region the picture
points at, sees nothing, and concludes the detector was wrong about something it
never proposed. The mapping is therefore exact-or-refused, and these tests hold
both halves -- that an exact match places, and that anything else does not place
rather than placing approximately.

THE AXIS TESTS GUARD A DIFFERENT LIE. The SEG-Y converter applies
`DEFAULT_GPR_VELOCITY_M_PER_NS = 0.1` so that a depth axis exists at all. That
number is a placeholder nobody measured on the surveyed ground, and calling the
resulting axis "Depth (m)" would report a measurement that was never made.
"""
import pytest

from schemas.radargram import (
    DEPTH_TOLERANCE_M, VelocitySource, VerticalAxisKind, describe_field,
    describe_horizontal_axis, describe_vertical_axis, map_candidate, map_candidates,
)

TRACES = [0, 1, 2, 3, 4, 5]
DEPTHS = [0.10, 0.20, 0.30, 0.40]


def candidate(cid="c1", traces=(1, 3), depths=(0.20, 0.30),
              peak_trace=2, peak_depth=0.20) -> dict:
    return {
        "id": cid,
        "evidence": {
            "trace_range": list(traces), "depth_range": list(depths),
            "peak_trace": peak_trace, "peak_depth": peak_depth,
        },
    }


def frame(kind="two_way_time_ns", conversion=None) -> dict:
    axis = {"kind": kind}
    if conversion:
        axis["conversion"] = conversion
    return {"vertical_axis": axis}


CONVERSION = {"method": "constant_velocity", "velocity_m_per_ns": 0.1,
              "target_axis": "depth_m"}


# ---------------------------------------------------------------------------
# the vertical axis
# ---------------------------------------------------------------------------

def test_a_default_velocity_is_not_a_declared_one():
    """
    The distinction this whole module exists for.

    A depth produced by the converter's placeholder is a different claim from
    one produced by a velocity somebody asserted for this site.
    """
    axis = describe_vertical_axis(frame(conversion=CONVERSION), 0.1,
                                  velocity_is_declared=False)
    assert axis.kind is VerticalAxisKind.DERIVED_DEPTH_DEFAULT
    assert axis.velocity_source is VelocitySource.CONVERTER_DEFAULT
    assert "default velocity" in axis.label
    assert "Nobody measured or declared this" in (axis.caveat or "")


def test_a_declared_velocity_is_still_derived_never_measured():
    axis = describe_vertical_axis(frame(conversion=CONVERSION), 0.1,
                                  velocity_is_declared=True)
    assert axis.kind is VerticalAxisKind.DERIVED_DEPTH_DECLARED
    assert axis.is_derived is True
    assert axis.kind is not VerticalAxisKind.MEASURED_DEPTH_M
    assert "not measured" in (axis.caveat or "")


def test_an_undeclared_velocity_defaults_to_the_weaker_claim():
    """An unknown must never be resolved in the direction of the stronger claim."""
    axis = describe_vertical_axis(frame(conversion=CONVERSION), 0.1)
    assert axis.velocity_source is VelocitySource.CONVERTER_DEFAULT


def test_without_a_velocity_the_axis_stays_the_instrument_time_axis():
    axis = describe_vertical_axis(frame(), None)
    assert axis.kind is VerticalAxisKind.TWO_WAY_TIME_NS
    assert axis.units == "ns"
    assert axis.is_derived is False
    assert "no velocity has been supplied" in axis.basis


def test_no_axis_label_says_metres_unless_the_axis_is_in_metres():
    for axis in (describe_vertical_axis(frame(), None),
                 describe_vertical_axis(None, None)):
        assert axis.units != "m"
        assert "depth" not in axis.label.lower()


def test_an_unknown_frame_falls_back_to_sample_positions():
    axis = describe_vertical_axis(None, None)
    assert axis.kind is VerticalAxisKind.SAMPLE_INDEX
    assert axis.units is None


def test_a_derived_axis_always_carries_a_caveat():
    for declared in (True, False):
        axis = describe_vertical_axis(frame(conversion=CONVERSION), 0.1, declared)
        assert axis.is_derived and axis.caveat


# ---------------------------------------------------------------------------
# the horizontal axis
# ---------------------------------------------------------------------------

def test_without_odometry_the_axis_is_trace_index():
    axis = describe_horizontal_axis([False, False], [None, None])
    assert axis.kind == "trace_index"
    assert axis.geographic_available is False


def test_measured_along_track_becomes_a_distance_reading_not_a_respacing():
    axis = describe_horizontal_axis([False], [0.0, 0.5])
    assert axis.kind == "along_track_m"
    assert "evenly spaced by trace index" in axis.basis


def test_geographic_availability_reflects_the_data_not_a_default():
    assert describe_horizontal_axis([True, False], None).geographic_available is True
    assert describe_horizontal_axis([False, False], None).geographic_available is False
    assert describe_horizontal_axis(None, None).geographic_available is False


# ---------------------------------------------------------------------------
# what the values are
# ---------------------------------------------------------------------------

def test_a_preprocessed_signal_is_labelled_a_statistic_not_the_signal():
    """
    `preprocess_trace_local_anomaly` overwrites `signal` with the z-score.
    Calling that the signal presents statistical evidence as a measurement.
    """
    semantics = describe_field("signal", anomaly_processed=True)
    assert semantics.is_statistic is True
    assert "z-score" in semantics.label.lower()
    assert semantics.units == "σ"
    assert "not the signal" in semantics.description


def test_an_unprocessed_signal_claims_neither_amplitude_nor_a_unit():
    """
    TIGHTENED IN STAGE 17, not weakened. This previously asserted the label said
    "amplitude", which was itself an overclaim: `SubterraRecord.signal` is
    documented as "raw or processed trace/measurement" and no converter
    establishes a unit for it. The honest label says what the value IS -- the
    stored sample -- and claims nothing about what it measures.
    """
    semantics = describe_field("signal", anomaly_processed=False)
    assert semantics.is_statistic is False
    assert semantics.units is None
    assert "amplitude" not in semantics.label.lower()
    assert "no physical unit is established" in semantics.description


# ---------------------------------------------------------------------------
# candidate -> grid, exactly or not at all
# ---------------------------------------------------------------------------

def test_a_candidate_maps_to_the_exact_columns_and_rows():
    f = map_candidate(candidate(), TRACES, DEPTHS)
    assert f.placeable
    assert (f.first_column, f.last_column) == (1, 3)
    assert (f.first_row, f.last_row) == (1, 2)
    assert (f.peak_column, f.peak_row) == (2, 1)


def test_a_candidate_on_the_first_trace_maps_to_column_zero():
    f = map_candidate(candidate(traces=(0, 0), depths=(0.10, 0.10)), TRACES, DEPTHS)
    assert (f.first_column, f.last_column) == (0, 0)
    assert (f.first_row, f.last_row) == (0, 0)


def test_a_candidate_on_the_last_trace_maps_to_the_last_column():
    f = map_candidate(candidate(traces=(5, 5), depths=(0.40, 0.40)), TRACES, DEPTHS)
    assert (f.first_column, f.last_column) == (5, 5)
    assert (f.first_row, f.last_row) == (3, 3)


def test_a_candidate_spanning_many_traces_keeps_its_full_span():
    f = map_candidate(candidate(traces=(0, 5), depths=(0.10, 0.40)), TRACES, DEPTHS)
    assert f.n_columns == 6
    assert f.n_rows == 4


def test_a_single_cell_candidate_spans_one_column_and_one_row():
    f = map_candidate(candidate(traces=(2, 2), depths=(0.30, 0.30)), TRACES, DEPTHS)
    assert f.n_columns == 1 and f.n_rows == 1


def test_a_trace_outside_the_grid_is_refused_not_clamped():
    """
    The rule that matters. Clamping would point a reviewer at traces the
    detector never proposed.
    """
    f = map_candidate(candidate(traces=(9, 12)), TRACES, DEPTHS)
    assert f.placeable is False
    assert f.first_column is None and f.last_column is None
    assert "not in this grid" in f.reason


def test_a_depth_outside_the_grid_is_refused():
    f = map_candidate(candidate(depths=(9.0, 9.5)), TRACES, DEPTHS)
    assert f.placeable is False
    assert "do not appear in this grid" in f.reason


def test_a_stale_candidate_from_a_reprocessed_line_is_refused_with_a_reason():
    """A candidate generated under a different depth conversion cannot be placed."""
    f = map_candidate(candidate(depths=(0.15, 0.25)), TRACES, DEPTHS)
    assert f.placeable is False
    assert "different depth conversion" in f.reason


def test_a_candidate_with_no_ranges_is_refused_rather_than_raising():
    f = map_candidate({"id": "x", "evidence": {}}, TRACES, DEPTHS)
    assert f.placeable is False
    assert "no trace or depth range" in f.reason


def test_an_empty_grid_places_nothing():
    f = map_candidate(candidate(), [], [])
    assert f.placeable is False


def test_float_noise_within_tolerance_still_matches():
    """Depths survive a JSON round trip; the last bits may not."""
    nudged = candidate(depths=(0.20 + DEPTH_TOLERANCE_M / 2,
                               0.30 - DEPTH_TOLERANCE_M / 2))
    assert map_candidate(nudged, TRACES, DEPTHS).placeable


def test_a_depth_between_samples_does_not_match():
    """Tolerance is for float noise, not for snapping to the nearest row."""
    assert not map_candidate(candidate(depths=(0.25, 0.30)), TRACES, DEPTHS).placeable


def test_reversed_ranges_are_normalised():
    f = map_candidate(candidate(traces=(3, 1), depths=(0.30, 0.20)), TRACES, DEPTHS)
    assert (f.first_column, f.last_column) == (1, 3)
    assert (f.first_row, f.last_row) == (1, 2)


def test_mapping_many_candidates_preserves_order_and_count():
    cands = [candidate("a"), candidate("b", traces=(99, 99)), candidate("c")]
    out = map_candidates(cands, TRACES, DEPTHS)
    assert [f.candidate_id for f in out] == ["a", "b", "c"]
    assert [f.placeable for f in out] == [True, False, True]


def test_no_candidates_maps_to_no_footprints():
    assert map_candidates([], TRACES, DEPTHS) == []


# ---------------------------------------------------------------------------
# reliability, and the difference from missing
# ---------------------------------------------------------------------------

def test_reliability_is_none_when_no_anomaly_preprocessing_ran():
    """An all-True grid would invent reliability information nobody computed."""
    from api.radargram import reliability_grid
    from schemas.subterra_record import SensorType, SubterraRecord

    raw = [SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, depth=0.1,
                          signal=[1.0], metadata={"source_file": "a.sgy",
                                                  "trace_index": 0})]
    assert reliability_grid(raw, "a.sgy", [0], [0.1]) is None


def test_a_cell_with_no_record_stays_none_rather_than_becoming_reliable():
    from api.radargram import reliability_grid
    from schemas.subterra_record import SensorType, SubterraRecord

    records = [SubterraRecord(
        dataset_id="d", sensor_type=SensorType.GPR, depth=0.1, signal=[1.0],
        metadata={"source_file": "a.sgy", "trace_index": 0, "anomaly_reliable": True})]
    grid = reliability_grid(records, "a.sgy", [0, 1], [0.1])

    assert grid[0][0] is True
    assert grid[0][1] is None, "a cell nobody recorded is neither reliable nor unreliable"


def test_unreliable_cells_are_reported_as_unreliable():
    from api.radargram import reliability_grid
    from schemas.subterra_record import SensorType, SubterraRecord

    records = [SubterraRecord(
        dataset_id="d", sensor_type=SensorType.GPR, depth=0.1, signal=[1.0],
        metadata={"source_file": "a.sgy", "trace_index": 0, "anomaly_reliable": False})]
    assert reliability_grid(records, "a.sgy", [0], [0.1])[0][0] is False


def test_the_semantics_note_distinguishes_unreliable_from_empty():
    from schemas.radargram import RadargramSemantics

    notes = RadargramSemantics(
        vertical=describe_vertical_axis(None, None),
        horizontal=describe_horizontal_axis(None, None),
        field=describe_field("signal", False))
    assert "not a cell where nothing was found" in notes.reliability_note
    assert "never as zero" in notes.missing_note


def test_a_declared_velocity_is_only_claimed_when_a_declaration_exists():
    """Without a database session the answer must be the weaker claim."""
    from api.radargram import velocity_is_declared

    assert velocity_is_declared(None, "d") is False
