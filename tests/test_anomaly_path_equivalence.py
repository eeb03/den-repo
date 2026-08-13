"""
The record path and the array path must compute the same detector.

WHAT WENT WRONG, AND WHY A PASSING EQUIVALENCE TEST DID NOT CATCH IT. The two
IMPLEMENTATIONS were always equivalent -- `scripts/validate_arraywise.py`
measures them bitwise identical, and it is right. What diverged was the
COMPOSITION each caller used:

    BAM benchmark      anomaly_grid_from_traces          -> filters + ring
    4TU characterise   process_gpr_traces + anomaly      -> filters + ring
    regression pin     gpr_trace_processing + anomaly    -> filters + ring
    product ingest     mode="gpr_local_anomaly" ALONE    -> ring ONLY

So the product computed candidates from a detector no benchmark had measured.
On a real 4TU line the two compositions disagree about 95.7% of cells, and the
count of cells exceeding |z|>3 -- the ones that become candidates -- differs by
4.2x. The equivalence check never noticed because it never ran the ingest
composition.

THE TRAP THESE TESTS ARE BUILT TO AVOID. An equivalence test on a corpus where
background removal, dewow and gain happen to be no-ops proves nothing: both
sides would agree because neither did anything. So `filtered_fixture` below is
asserted to CHANGE the data before any equivalence is claimed on it, and that
assertion is a test in its own right.
"""
import numpy as np
import pytest

from preprocessing.pipeline import run_pipeline
from preprocessing.spatial_grid import (
    anomaly_grid_from_traces, build_trace_depth_grid_for_records,
    preprocess_trace_local_anomaly,
)
from preprocessing.trace_processing import process_gpr_traces
from schemas.subterra_record import SensorType, SubterraRecord

N_TRACES, N_SAMPLES = 40, 64


def _line() -> list[SubterraRecord]:
    """
    A B-scan the filters demonstrably act on.

    Constructed, not measured -- it exists to exercise the composition, and no
    result derived from it is reported as science. It carries the three things
    the filters exist to remove, so that "the filters did nothing" cannot be
    the reason a comparison passes:

      * a constant horizontal band across every trace (what background removal
        strips -- the direct wave and ground bounce)
      * a slow low-frequency drift down each trace (what dewow removes)
      * amplitudes decaying with depth (what gain compensates)
    """
    rng = np.random.default_rng(20260813)
    amplitude = rng.normal(0.0, 1.0, size=(N_TRACES, N_SAMPLES))

    sample = np.arange(N_SAMPLES)
    amplitude += 40.0 * np.exp(-sample / 4.0)          # direct wave, every trace
    amplitude += 6.0 * np.sin(sample / 30.0)           # low-frequency drift
    amplitude *= np.exp(-sample / 25.0)                # geometric decay
    amplitude[18:22, 28:32] += 12.0                    # something to find

    return [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.GPR,
            depth=round(0.01 * (s + 1), 6), signal=[float(amplitude[t, s])],
            metadata={"source_file": "line.sgy", "trace_index": t, "sample_index": s})
        for t in range(N_TRACES) for s in range(N_SAMPLES)
    ]


def _grid(records) -> np.ndarray:
    return np.asarray(
        build_trace_depth_grid_for_records(records, field="signal")["grid"], dtype=float)


def _traces_2d(records) -> np.ndarray:
    """(n_traces, n_samples), the shape the array path consumes."""
    out = np.full((N_TRACES, N_SAMPLES), np.nan)
    for r in records:
        out[r.metadata["trace_index"], r.metadata["sample_index"]] = r.signal[0]
    return out


# ---------------------------------------------------------------------------
# the fixture must not be a no-op -- this is the precondition for everything else
# ---------------------------------------------------------------------------

def test_the_filters_actually_change_this_fixture():
    """
    Without this, an equivalence test could pass by proving nothing happened.
    """
    before = _traces_2d(_line())
    after = _traces_2d(process_gpr_traces(_line()))

    assert not np.allclose(before, after), "the fixture must exercise the filters"
    changed = (np.abs(before - after) > 1e-9).mean()
    assert changed > 0.9, f"only {changed:.1%} of cells changed; fixture too tame"


def test_the_filters_change_the_anomaly_result_too():
    """A filter that moved the data but not the statistic would also prove little."""
    unfiltered = _grid(preprocess_trace_local_anomaly(_line()))
    filtered = _grid(preprocess_trace_local_anomaly(process_gpr_traces(_line())))

    assert not np.allclose(np.nan_to_num(unfiltered), np.nan_to_num(filtered))


# ---------------------------------------------------------------------------
# the ingest composition is the benchmarked one
# ---------------------------------------------------------------------------

def test_the_composite_mode_applies_the_trace_filters():
    """
    THE REGRESSION THIS FILE EXISTS FOR.

    `run_pipeline(mode="gpr_full")` must produce what the benchmarks
    measure. Before Stage 18 it produced the unfiltered statistic instead.
    """
    ingest = _grid(run_pipeline(_line(), mode="gpr_full"))
    benchmarked = _grid(preprocess_trace_local_anomaly(process_gpr_traces(_line())))

    assert np.allclose(np.nan_to_num(ingest), np.nan_to_num(benchmarked), atol=0, rtol=0)


def test_the_composite_mode_is_not_the_unfiltered_statistic():
    """The explicit negative: a silent revert must fail loudly."""
    composite = _grid(run_pipeline(_line(), mode="gpr_full"))
    unfiltered = _grid(preprocess_trace_local_anomaly(_line()))

    assert not np.allclose(np.nan_to_num(composite), np.nan_to_num(unfiltered))


def test_the_single_step_anomaly_mode_stays_filter_free():
    """
    The regression baseline composes the two steps itself and pins the result.
    Making the single-step mode filter would double-filter it.
    """
    single = _grid(run_pipeline(_line(), mode="gpr_local_anomaly"))
    bare = _grid(preprocess_trace_local_anomaly(_line()))

    assert np.allclose(np.nan_to_num(single), np.nan_to_num(bare), atol=0, rtol=0)


def test_the_composite_mode_matches_the_array_path_bitwise():
    """
    The array path is what the BAM benchmark runs. Ingest must agree with it
    exactly, not approximately.
    """
    ingest = _grid(run_pipeline(_line(), mode="gpr_full"))
    array = anomaly_grid_from_traces(_traces_2d(_line()))

    assert ingest.shape == array.shape
    difference = np.abs(np.nan_to_num(ingest) - np.nan_to_num(array))
    assert difference.max() == 0.0, f"max difference {difference.max()}"


# ---------------------------------------------------------------------------
# the two implementations, compared directly
# ---------------------------------------------------------------------------

def test_the_filtered_record_composition_equals_the_array_path():
    record = _grid(preprocess_trace_local_anomaly(process_gpr_traces(_line())))
    array = anomaly_grid_from_traces(_traces_2d(_line()))
    assert np.abs(np.nan_to_num(record) - np.nan_to_num(array)).max() == 0.0


def test_the_unfiltered_record_path_is_NOT_the_array_path():
    """
    Stated as a test because a docstring claimed the opposite for several
    stages, and the product was built on that claim.
    """
    record = _grid(preprocess_trace_local_anomaly(_line()))
    array = anomaly_grid_from_traces(_traces_2d(_line()))
    assert np.abs(np.nan_to_num(record) - np.nan_to_num(array)).max() > 0.1


def test_both_paths_agree_on_shape_and_dtype():
    record = _grid(preprocess_trace_local_anomaly(process_gpr_traces(_line())))
    array = anomaly_grid_from_traces(_traces_2d(_line()))
    assert record.shape == array.shape == (N_SAMPLES, N_TRACES)
    assert record.dtype == array.dtype == np.dtype("float64")


def test_the_paths_agree_away_from_the_boundary_as_well_as_at_it():
    """
    A comparison that only held in the interior would hide an edge-handling
    difference, and one that only held at edges would hide everything else.
    """
    record = _grid(preprocess_trace_local_anomaly(process_gpr_traces(_line())))
    array = anomaly_grid_from_traces(_traces_2d(_line()))
    interior = (slice(20, N_SAMPLES - 20), slice(8, N_TRACES - 8))

    assert np.abs(np.nan_to_num(record) - np.nan_to_num(array)).max() == 0.0
    assert np.abs(np.nan_to_num(record[interior]) - np.nan_to_num(array[interior])).max() == 0.0


# ---------------------------------------------------------------------------
# the one difference that is real, and is not a value difference
# ---------------------------------------------------------------------------

def test_the_record_path_writes_zero_where_the_array_path_leaves_nan():
    """
    Measured on a real line: 6,886 cells, all at a ring-window boundary. The
    record path stores 0.0 for a non-finite z because `SubterraRecord` rejects
    NaN; the array path has no such constraint.

    It does not change candidates -- `detect_line` maps NaN to 0.0 before
    thresholding, so both sides end up identical there -- but it IS a real
    difference between the representations and is asserted rather than left as
    a surprise for the next reader.
    """
    record = _grid(preprocess_trace_local_anomaly(process_gpr_traces(_line())))
    array = anomaly_grid_from_traces(_traces_2d(_line()))

    assert not np.isnan(record).any(), "records cannot hold NaN"
    assert np.isnan(array).any(), "the array path preserves non-finite cells as NaN"
    assert ((array_nan := np.isnan(array)) & (record == 0.0)).sum() == array_nan.sum()


def test_the_unreliable_flag_marks_exactly_the_cells_the_array_path_nans():
    processed = preprocess_trace_local_anomaly(process_gpr_traces(_line()))
    array = anomaly_grid_from_traces(_traces_2d(_line()))

    unreliable = sum(1 for r in processed if r.metadata["anomaly_reliable"] is False)
    assert unreliable == int(np.isnan(array).sum())


# ---------------------------------------------------------------------------
# what the validator actually validates
# ---------------------------------------------------------------------------

def test_the_validator_compares_the_filtered_composition():
    """
    `validate_arraywise` is correct and was never the problem: it compares
    filtered-record against array. This pins that it keeps doing so, because a
    validator that silently dropped `process_gpr_traces` would start comparing
    the wrong thing and would still pass.
    """
    import ast
    from pathlib import Path

    source = Path("scripts/validate_arraywise.py").read_text()
    tree = ast.parse(source)
    nested = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "preprocess_trace_local_anomaly"
        and node.args
        and getattr(getattr(node.args[0], "func", None), "id", None) == "process_gpr_traces"
    ]
    assert nested, "the validator must compare the FILTERED record composition"


def test_no_module_claims_a_verify_arraywise_flag_exists():
    """
    Three docstrings referenced `--verify-arraywise` as though it were a real
    CLI flag. It has never existed; `scripts/validate_arraywise.py` is the tool.
    """
    from pathlib import Path

    for path in ("preprocessing/spatial_grid.py", "benchmark/detection.py",
                 "scripts/characterise_4tu.py"):
        source = Path(path).read_text()
        for line in source.splitlines():
            if "--verify-arraywise" in line:
                assert "has never existed" in source, \
                    f"{path} still presents --verify-arraywise as a real flag"


def test_characterise_4tu_still_filters_before_the_anomaly_step():
    """The 4TU numbers describe the filtered detector; that must not drift."""
    from pathlib import Path

    source = Path("scripts/characterise_4tu.py").read_text()
    assert "records = process_gpr_traces(records)" in source
    assert "records = preprocess_trace_local_anomaly(records)" in source
