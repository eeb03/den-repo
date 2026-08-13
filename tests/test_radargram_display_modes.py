"""
Two projections of one grid: the anomaly statistic, and the signal it came from.

WHAT THE TOGGLE IS AND IS NOT. It changes which stored value is projected into
each cell. It is not a second grid, a second dataset, a reprocessing step or a
recalculation, and the tests below pin that by asserting that everything except
the values is identical between the two modes -- trace indices, depths, axis
semantics, reliability mask and, most importantly, candidate footprints. A
reviewer who switches representation must not see a candidate move.

WHY THE RELIABILITY MASK IS NOT SHARED. Measured on a real 160,768-cell line:
all 6,886 unreliable cells still hold a perfectly good stored pre-anomaly value,
and all 6,886 had their z-score forced to 0.0. The mask describes the ANOMALY
STATISTIC -- the cells whose ring had too few neighbours to estimate a
background from -- and not the signal that statistic was computed from. Fading
those cells in the pre-anomaly view would present sound measurements as
untrustworthy, so the backend states which representation the mask applies to
rather than leaving the viewer to assume.

WHAT IS DELIBERATELY NOT CLAIMED. No unit. `SubterraRecord.signal` is described
as "raw or processed trace/measurement", and the converters document units for
the time axis and never for amplitude. `pre_anomaly_signal` is therefore the
value held before the anomaly step and nothing stronger -- not "raw amplitude",
not "calibrated", not "physical".
"""
import numpy as np
import pytest

from preprocessing.spatial_grid import (
    build_trace_depth_grid_for_records, preprocess_trace_local_anomaly,
)
from schemas.radargram import DISPLAYABLE_FIELDS, describe_field, map_candidates
from schemas.subterra_record import SensorType, SubterraRecord


def _record(trace: int, sample: int, value: float) -> SubterraRecord:
    return SubterraRecord(
        dataset_id="ds", sensor_type=SensorType.GPR,
        depth=round(0.01 * (sample + 1), 6), signal=[value],
        metadata={"source_file": "line.sgy", "trace_index": trace,
                  "sample_index": sample})


def _line(n_traces: int = 24, n_samples: int = 24) -> list[SubterraRecord]:
    """
    A small B-scan with one strong feature, run through the REAL preprocessing.

    Constructed to exercise the projection machinery; nothing measured is
    claimed from it and no result derived from it is reported as science. The
    values that matter for these tests are the ones the real
    `preprocess_trace_local_anomaly` writes.
    """
    rng = np.random.default_rng(0)
    amplitude = rng.normal(0.0, 1.0, size=(n_traces, n_samples))
    amplitude[10:14, 10:14] += 20.0
    return [_record(t, s, float(amplitude[t, s]))
            for t in range(n_traces) for s in range(n_samples)]


@pytest.fixture
def processed() -> list[SubterraRecord]:
    return preprocess_trace_local_anomaly(_line())


# ---------------------------------------------------------------------------
# what each projection is
# ---------------------------------------------------------------------------

def test_the_anomaly_projection_is_the_stored_zscore(processed):
    grid = build_trace_depth_grid_for_records(processed, field="signal")
    by_cell = {(r.metadata["trace_index"], round(r.depth, 6)): r.signal[0]
               for r in processed}

    traces, depths = grid["trace_indices"], grid["depths"]
    for row, depth in enumerate(depths):
        for column, trace in enumerate(traces):
            assert grid["grid"][row][column] == pytest.approx(by_cell[(trace, depth)])


def test_the_pre_anomaly_projection_is_the_stored_pre_anomaly_value(processed):
    """Values come from the record, not from a recomputation."""
    grid = build_trace_depth_grid_for_records(processed, field="pre_anomaly_signal")
    by_cell = {(r.metadata["trace_index"], round(r.depth, 6)):
               r.metadata["pre_anomaly_signal"] for r in processed}

    traces, depths = grid["trace_indices"], grid["depths"]
    for row, depth in enumerate(depths):
        for column, trace in enumerate(traces):
            assert grid["grid"][row][column] == pytest.approx(by_cell[(trace, depth)])


def test_the_two_projections_hold_different_numbers(processed):
    anomaly = build_trace_depth_grid_for_records(processed, field="signal")["grid"]
    pre = build_trace_depth_grid_for_records(
        processed, field="pre_anomaly_signal")["grid"]
    assert not np.allclose(np.nan_to_num(anomaly), np.nan_to_num(pre))


def test_selecting_a_projection_does_not_reprocess_anything(processed):
    """Display selection is a read. It must not touch a single record."""
    before = [r.model_dump_json() for r in processed]

    build_trace_depth_grid_for_records(processed, field="signal")
    build_trace_depth_grid_for_records(processed, field="pre_anomaly_signal")

    assert [r.model_dump_json() for r in processed] == before


# ---------------------------------------------------------------------------
# the grid is the SAME grid
# ---------------------------------------------------------------------------

def test_both_projections_share_trace_and_depth_indices(processed):
    anomaly = build_trace_depth_grid_for_records(processed, field="signal")
    pre = build_trace_depth_grid_for_records(processed, field="pre_anomaly_signal")

    assert anomaly["trace_indices"] == pre["trace_indices"]
    assert anomaly["depths"] == pre["depths"]
    assert np.shape(anomaly["grid"]) == np.shape(pre["grid"])


def test_both_projections_share_the_trace_geometry(processed):
    anomaly = build_trace_depth_grid_for_records(processed, field="signal")
    pre = build_trace_depth_grid_for_records(processed, field="pre_anomaly_signal")

    for key in ("trace_lat", "trace_lon", "trace_position_kind",
                "trace_geographic", "trace_along_track", "source_file"):
        assert anomaly[key] == pre[key], f"{key} must not depend on the projection"


def test_candidate_footprints_are_identical_between_projections(processed):
    """
    THE INVARIANT THIS STAGE MUST NOT BREAK.

    A candidate is found in the anomaly grid. Switching representation must
    leave it over exactly the same supporting cells -- a marker that moved would
    send a reviewer to inspect traces the detector never proposed.
    """
    from interpretation.anomaly_candidates import find_anomaly_candidates_all_lines

    anomaly = build_trace_depth_grid_for_records(processed, field="signal")
    pre = build_trace_depth_grid_for_records(processed, field="pre_anomaly_signal")

    found = find_anomaly_candidates_all_lines(processed)
    candidates = [c.model_dump(mode="json")
                  for group in found.values() for c in group]
    assert candidates, "the fixture must produce at least one candidate to compare"

    in_anomaly = map_candidates(candidates, anomaly["trace_indices"], anomaly["depths"])
    in_pre = map_candidates(candidates, pre["trace_indices"], pre["depths"])

    assert [f.model_dump() for f in in_anomaly] == [f.model_dump() for f in in_pre]


# ---------------------------------------------------------------------------
# missing stays missing
# ---------------------------------------------------------------------------

def test_a_cell_without_a_pre_anomaly_value_stays_missing(processed):
    """
    NOT filled in from `signal`, which after preprocessing is the z-score.
    Substituting one for the other would show a statistic under a signal label.
    """
    target = processed[0]
    target.metadata["pre_anomaly_signal"] = None

    grid = build_trace_depth_grid_for_records(processed, field="pre_anomaly_signal")
    row = grid["depths"].index(round(target.depth, 6))
    column = grid["trace_indices"].index(target.metadata["trace_index"])

    assert np.isnan(grid["grid"][row][column])
    assert grid["grid"][row][column] != target.signal[0]


def test_an_unprocessed_dataset_has_no_pre_anomaly_values_at_all():
    """A dataset that never went through the anomaly step has nothing to show."""
    grid = build_trace_depth_grid_for_records(_line(4, 4), field="pre_anomaly_signal")
    assert np.isnan(np.asarray(grid["grid"], dtype=float)).all()


def test_an_unknown_field_is_refused():
    with pytest.raises(ValueError, match="Unknown field"):
        build_trace_depth_grid_for_records(_line(4, 4), field="amplitude")


# ---------------------------------------------------------------------------
# semantics: what each projection is allowed to claim
# ---------------------------------------------------------------------------

def test_the_displayable_fields_are_exactly_the_two_representations():
    assert DISPLAYABLE_FIELDS == ("signal", "pre_anomaly_signal")


def test_the_pre_anomaly_projection_claims_no_unit():
    semantics = describe_field("pre_anomaly_signal", anomaly_processed=True)
    assert semantics.units is None
    assert semantics.is_statistic is False
    assert "NO physical unit" in semantics.description
    assert "no calibration" in semantics.description


def test_the_pre_anomaly_projection_is_not_called_raw_amplitude():
    """
    The repository establishes no such thing. `signal` is documented as "raw or
    processed", so what the value is depends on what ran before the anomaly
    step -- and the honest name says only that.
    """
    semantics = describe_field("pre_anomaly_signal", anomaly_processed=True)
    for overclaim in ("raw amplitude", "true amplitude", "physical amplitude",
                      "calibrated", "ground truth"):
        assert overclaim.lower() not in semantics.label.lower()
        assert overclaim.lower() not in semantics.description.lower()


def test_the_anomaly_projection_still_declares_itself_a_statistic():
    semantics = describe_field("signal", anomaly_processed=True)
    assert semantics.is_statistic is True
    assert semantics.units == "σ"


def test_the_reliability_mask_applies_to_the_statistic_not_the_signal():
    """
    Measured, not assumed: unreliable cells hold good stored values, and it is
    their z-score that was forced to 0.0.
    """
    assert describe_field("signal", True).reliability_applies is True
    assert describe_field("pre_anomaly_signal", True).reliability_applies is False
    assert "still holds a perfectly good stored signal" in (
        describe_field("pre_anomaly_signal", True).reliability_note or "")


def test_unreliable_cells_keep_their_pre_anomaly_value(processed):
    """The claim above, verified against the real preprocessing output."""
    unreliable = [r for r in processed
                  if r.metadata.get("anomaly_reliable") is False]
    assert unreliable, "the fixture must produce unreliable edge cells"

    assert all(r.metadata.get("pre_anomaly_signal") is not None for r in unreliable)
    assert all(r.signal == [0.0] for r in unreliable), \
        "an unreliable cell's z-score is forced to 0.0, which is why it is faded"
