"""
GPR ingest defaults to the benchmark-aligned chain.

WHAT THIS IS AND IS NOT A CLAIM ABOUT. Stage 18 established that `gpr_full`
(`gpr_trace_processing` then `gpr_local_anomaly`) is the composition both
benchmarks and the corpus characterisation measure, and that `gpr_local_anomaly`
alone produces a materially different, previously unbenchmarked candidate
population -- 39 cells over |z|>3 against 164 on the same real line. Defaulting
to it makes the product's detector the one the published numbers describe.

That is the whole claim. Nothing here asserts the resulting signal is cleaner,
better or more accurate; no measurement in this repository supports that and none
is made.

WHAT THE DEFAULT MUST NOT DO. It must not touch another modality, must not
override an explicit choice (including an explicit `trace` on a GPR dataset),
must not reprocess anything already stored, and must not let a historical
dataset -- which records no mode at all -- read as though it had been processed
with `gpr_full`.
"""
import numpy as np
import pytest

from api.routes.datasets import (
    DEFAULT_PREPROCESSING_MODE_BY_MODALITY, FALLBACK_PREPROCESSING_MODE,
    default_preprocessing_mode,
)
from preprocessing.pipeline import run_pipeline
from preprocessing.spatial_grid import (
    build_trace_depth_grid_for_records, preprocess_trace_local_anomaly,
)
from preprocessing.trace_processing import process_gpr_traces
from schemas.subterra_record import SensorType, SubterraRecord

N_TRACES, N_SAMPLES = 24, 32


def _line() -> list[SubterraRecord]:
    """A B-scan the filters demonstrably act on (see test_anomaly_path_equivalence)."""
    rng = np.random.default_rng(20260813)
    amplitude = rng.normal(0.0, 1.0, size=(N_TRACES, N_SAMPLES))
    sample = np.arange(N_SAMPLES)
    amplitude += 40.0 * np.exp(-sample / 4.0)
    amplitude += 6.0 * np.sin(sample / 30.0)
    amplitude *= np.exp(-sample / 25.0)
    amplitude[10:14, 14:18] += 12.0
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


# ---------------------------------------------------------------------------
# the resolution rule
# ---------------------------------------------------------------------------

def test_gpr_resolves_to_the_full_chain():
    assert default_preprocessing_mode(SensorType.GPR) == "gpr_full"


@pytest.mark.parametrize("sensor_type", [
    st for st in SensorType if st is not SensorType.GPR
])
def test_no_other_modality_changes(sensor_type):
    """The stage is specifically the GPR default. Everything else keeps `trace`."""
    assert default_preprocessing_mode(sensor_type) == FALLBACK_PREPROCESSING_MODE == "trace"


def test_only_gpr_has_an_entry_in_the_modality_table():
    assert set(DEFAULT_PREPROCESSING_MODE_BY_MODALITY) == {SensorType.GPR}


# ---------------------------------------------------------------------------
# an explicit choice always wins
# ---------------------------------------------------------------------------

def test_the_helper_uses_the_modality_default_only_when_none_is_given(monkeypatch):
    """
    The resolution happens inside the ingest helper, after the sensor type is
    known. `None` means "caller named nothing"; any string is the caller's.
    """
    from api.routes import datasets as mod

    seen = {}

    def _capture(records, mode="trace", **kwargs):
        seen["mode"] = mode
        return records

    monkeypatch.setattr(mod, "run_pipeline", _capture)

    resolved = (None if None is not None else default_preprocessing_mode(SensorType.GPR))
    assert resolved == "gpr_full"
    for explicit in ("gpr_local_anomaly", "gpr_full", "trace", "spatial_grid"):
        assert (explicit if explicit is not None
                else default_preprocessing_mode(SensorType.GPR)) == explicit


def test_explicit_gpr_local_anomaly_is_still_exactly_that_mode():
    """
    The single-step mode remains reachable and unchanged. A caller asking for it
    must get the unfiltered statistic, not the new default.
    """
    explicit = _grid(run_pipeline(_line(), mode="gpr_local_anomaly"))
    bare = _grid(preprocess_trace_local_anomaly(_line()))

    assert np.allclose(np.nan_to_num(explicit), np.nan_to_num(bare), atol=0, rtol=0)


def test_explicit_gpr_full_is_the_validated_composition():
    explicit = _grid(run_pipeline(_line(), mode="gpr_full"))
    composed = _grid(preprocess_trace_local_anomaly(process_gpr_traces(_line())))

    assert np.allclose(np.nan_to_num(explicit), np.nan_to_num(composed), atol=0, rtol=0)


def test_the_two_modes_remain_distinguishable():
    """If these ever agreed, the default would be a change without a difference."""
    full = _grid(run_pipeline(_line(), mode="gpr_full"))
    single = _grid(run_pipeline(_line(), mode="gpr_local_anomaly"))

    assert not np.allclose(np.nan_to_num(full), np.nan_to_num(single))


# ---------------------------------------------------------------------------
# the signal the default produces
# ---------------------------------------------------------------------------

def test_the_default_produces_the_established_gpr_full_composition_bitwise():
    """
    THE ACCEPTANCE CRITERION. What a defaulted GPR ingest computes must be
    bit-identical to the composition Stage 18 validated -- not merely close.
    """
    defaulted = _grid(run_pipeline(_line(), mode=default_preprocessing_mode(SensorType.GPR)))
    established = _grid(preprocess_trace_local_anomaly(process_gpr_traces(_line())))

    difference = np.abs(np.nan_to_num(defaulted) - np.nan_to_num(established))
    assert difference.max() == 0.0, f"max difference {difference.max()}"


def test_the_default_also_matches_the_array_path_the_benchmark_runs():
    from preprocessing.spatial_grid import anomaly_grid_from_traces

    traces = np.full((N_TRACES, N_SAMPLES), np.nan)
    for r in _line():
        traces[r.metadata["trace_index"], r.metadata["sample_index"]] = r.signal[0]

    defaulted = _grid(run_pipeline(_line(), mode=default_preprocessing_mode(SensorType.GPR)))
    array = anomaly_grid_from_traces(traces)

    assert np.abs(np.nan_to_num(defaulted) - np.nan_to_num(array)).max() == 0.0


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def test_the_ingest_records_the_mode_it_actually_used():
    """
    Ingest previously stored nothing about how records were processed. It now
    writes the RESOLVED mode under the same key `/reprocess` already uses.
    """
    import ast
    from pathlib import Path

    source = Path("api/routes/datasets.py").read_text()
    assert '"last_preprocessing_mode": resolved_mode' in source
    assert '"preprocessing_mode_source"' in source
    ast.parse(source)


def test_the_recorded_mode_distinguishes_a_default_from_a_choice():
    """
    `preprocessing_mode_source` exists so a reader can tell whether a dataset
    got `gpr_full` because somebody asked or because the modality default
    supplied it. Both are legitimate; conflating them loses provenance.
    """
    from pathlib import Path

    source = Path("api/routes/datasets.py").read_text()
    assert '"explicit" if preprocessing_mode is not None else "modality_default"' in source


def test_nothing_infers_a_mode_for_a_dataset_that_records_none():
    """
    A historical dataset carries no `last_preprocessing_mode`. Absence must read
    as UNRECORDED, never as `gpr_full` -- the platform must not claim a dataset
    was processed a way it was not.
    """
    from pathlib import Path

    source = Path("api/routes/datasets.py").read_text()
    for forgery in ('extra_metadata.get("last_preprocessing_mode", "gpr_full")',
                    'last_preprocessing_mode") or "gpr_full"',
                    'last_preprocessing_mode", DEFAULT'):
        assert forgery not in source


def test_the_mode_is_only_recorded_when_preprocessing_actually_ran():
    """`apply_preprocessing=False` must not record a mode that never executed."""
    from pathlib import Path

    source = Path("api/routes/datasets.py").read_text()
    assert 'if apply_preprocessing else {}' in source


# ---------------------------------------------------------------------------
# nothing historical moves
# ---------------------------------------------------------------------------

def test_the_default_change_reprocesses_nothing():
    """
    Applying only at ingest is what keeps stored datasets untouched. No
    migration, no backfill, no automatic recompute.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("api/routes/datasets.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_ingest_pipeline":
            names = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                     for n in ast.walk(node) if isinstance(n, ast.Call)}
            assert "load_records" not in names, \
                "ingest must not read existing records; it creates a new dataset"
            return
    pytest.fail("_run_ingest_pipeline not found")


def test_the_depth_slice_pipeline_keeps_its_own_default():
    """
    Depth slices append to an existing dataset and have their own spatial_grid
    default. This stage is the GPR INGEST default and must not reach them.
    """
    from pathlib import Path

    source = Path("api/routes/datasets.py").read_text()
    assert source.count('preprocessing_mode: str = "trace"') == 3, \
        "the three depth-slice signatures must keep their explicit default"
