"""
The 4TU characterisation runner.

This milestone's risk is not a crash; it is a quiet overstatement. So most
of what is pinned here is what the runner must REFUSE to do:

  - never default a velocity when the source publishes none;
  - never give a source-reported utility a coordinate;
  - never turn a detector candidate into a confirmed object;
  - never join trench information by anything other than LocationID.

Real-corpus assertions are guarded on the data being present; the contract
assertions run everywhere.
"""
import glob
import json
import os
from pathlib import Path

import pytest

from ingestion.four_tu_velocity import resolve_four_tu_velocity
from schemas.provenance import ProvenanceClass, frame_provenance
from scripts.characterise_4tu import (
    C_M_PER_NS, CORPUS, THRESHOLD_SWEEP, characterise_file, load_metadata,
    normalise_location_id, velocity_for,
)

REAL = pytest.mark.skipif(not CORPUS.exists(), reason="4TU corpus not present locally")


# --- velocity is never defaulted ---

@pytest.mark.parametrize("row,why", [
    (None, "no Metadata.csv row"),
    ({}, "publishes no relative permittivity"),
    ({"Ground relative permittivity": ""}, "publishes no relative permittivity"),
    ({"Ground relative permittivity": "  "}, "publishes no relative permittivity"),
    ({"Ground relative permittivity": "wet"}, "is not a number"),
    ({"Ground relative permittivity": "0.5"}, "not physical"),
])
def test_an_unusable_permittivity_yields_no_velocity(row, why):
    v, basis = velocity_for(row)
    assert v is None, "a velocity must never be defaulted"
    assert why in basis


def test_a_published_permittivity_becomes_a_velocity_labelled_as_an_estimate():
    v, basis = velocity_for({"Ground relative permittivity": "9.00"})
    assert v == pytest.approx(C_M_PER_NS / 3.0)
    assert "PROVIDER SITE ESTIMATE" in basis
    assert "not a measurement of the subsurface" in basis
    # DERIVED (from a declared quantity), never ASSUMED -- that distinction
    # is the whole point of the declared-permittivity velocity path.
    assert "derived from" in basis
    assert "not independently validated" in basis
    assert "assumed" not in basis.lower()


def test_permittivity_of_one_is_the_speed_of_light():
    v, _ = velocity_for({"Ground relative permittivity": "1.0"})
    assert v == pytest.approx(C_M_PER_NS)


# --- the LocationID join ---

def test_the_documented_zero_padding_mismatch_is_normalised():
    known = {"13.1", "01.1"}
    assert normalise_location_id("013.1", known) == ("13.1", True)
    assert normalise_location_id("01.1", known) == ("01.1", False)


def test_an_unknown_activity_is_left_alone_rather_than_guessed():
    known = {"13.1"}
    assert normalise_location_id("99.9", known) == ("99.9", False)


@REAL
def test_every_activity_directory_resolves_to_a_real_location_id():
    metadata = load_metadata(CORPUS)
    known = set(metadata)
    dirs = {Path(f).relative_to(CORPUS).parts[2]
            for f in glob.glob(str(CORPUS / "*/**/*.sgy"), recursive=True)}
    unresolved = [d for d in dirs if normalise_location_id(d, known)[0] not in known]
    assert unresolved == [], f"activities with no Metadata.csv row: {unresolved}"


@REAL
def test_metadata_publishes_no_trench_coordinates():
    """
    The premise of the whole evaluation rule. If this ever fails, the source
    gained coordinate truth and coordinate-level scoring becomes possible --
    which would be a reason to revisit the milestone, not to quietly score.
    """
    metadata = load_metadata(CORPUS)
    fields = {k.lower() for row in metadata.values() for k in row}
    for banned in ("lat", "lon", "latitude", "longitude", "easting", "northing",
                   "x", "y", "coordinate", "rd_x", "rd_y"):
        assert banned not in fields, f"Metadata.csv now has a {banned!r} column"


# --- one real radargram through the real pipeline ---

@REAL
def test_a_real_radargram_runs_the_whole_existing_chain():
    files = sorted(glob.glob(str(CORPUS / "01/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    out = characterise_file(Path(files[0]), "t", 0.1)
    assert out["records"] > 0 and out["traces"] > 0
    assert out["reliable_cells"] + out["unreliable_cells"] == out["records"]
    assert out["samples_per_trace"] == 512
    assert out["spatial_ref_code"] in ("EPSG:4326", None)
    assert set(out["candidate_sweep"]) == {str(t) for t in THRESHOLD_SWEEP}


@REAL
def test_a_real_4tu_activity_gets_the_declared_permittivity_velocity_and_it_is_derived():
    """
    End to end, on the real archive: a genuine 4TU LocationID resolves a
    declared velocity, the frame's assumptions classify it DERIVED (not
    ASSUMED) with the permittivity itself DECLARED_BY_SOURCE, and a non-4TU
    dataset_id on the SAME file falls back to today's exact default behaviour.
    """
    from converters.segy_converter import DEFAULT_GPR_VELOCITY_M_PER_NS, SEGYConverter
    from schemas.subterra_record import SensorType

    files = sorted(glob.glob(str(CORPUS / "01/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    resolution = resolve_four_tu_velocity("4tu_01.1")
    assert resolution is not None, "activity 01.1 is expected to publish a usable permittivity"

    out = characterise_file(Path(files[0]), "4tu_01.1", resolution.velocity_m_per_ns, resolution)
    assert out["records"] > 0

    result = SEGYConverter().load(
        Path(files[0]), dataset_id="4tu_01.1", sensor_type=SensorType.GPR,
        coordinate_encoding="ieee_nmea", velocity_m_per_ns=resolution.velocity_m_per_ns,
        velocity_basis=resolution.velocity_basis,
        velocity_source_quantity="relative permittivity", velocity_source_value=resolution.eps_r,
        velocity_source_basis=resolution.permittivity_basis,
    )
    by_quantity = {p.quantity: p for p in frame_provenance(result.frames[0])}
    assert by_quantity["assumption:gpr_velocity"].provenance == ProvenanceClass.DERIVED
    assert by_quantity["assumption:gpr_velocity_source_quantity"].provenance == \
        ProvenanceClass.DECLARED_BY_SOURCE
    assert result.records[0].metadata.get("velocity_source") == "declared:relative permittivity"

    # A non-4TU dataset_id on the identical file must NOT pick up 4TU's
    # velocity or basis -- the default-velocity path stays untouched.
    default_result = SEGYConverter().load(
        Path(files[0]), dataset_id="unrelated_dataset", sensor_type=SensorType.GPR,
        coordinate_encoding="ieee_nmea",
    )
    assert default_result.records[0].metadata.get("velocity_m_per_ns") == DEFAULT_GPR_VELOCITY_M_PER_NS
    assert "velocity_source" not in default_result.records[0].metadata
    default_by_quantity = {p.quantity: p for p in frame_provenance(default_result.frames[0])}
    assert default_by_quantity["assumption:gpr_velocity"].provenance == ProvenanceClass.ASSUMED


@REAL
def test_candidates_carry_evidence_not_object_claims():
    """A candidate is geometry plus statistics. It is never a utility."""
    files = sorted(glob.glob(str(CORPUS / "01/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    for f in files[:6]:
        out = characterise_file(Path(f), "t", 0.1)
        for c in out["candidate_summary"]:
            assert c["anomaly_class"] in {"compact", "trace-elongated", "depth-elongated",
                                          "diffuse", "unclassified"}
            for banned in ("utility", "pipe", "cable", "material", "diameter",
                           "confirmed", "object", "class_label"):
                assert banned not in c
        if out["candidate_summary"]:
            return
    pytest.skip("no candidates in the sampled files; nothing to assert on")


@REAL
def test_raising_the_threshold_never_increases_candidates():
    """Monotonicity: a stricter threshold cannot admit more components."""
    files = sorted(glob.glob(str(CORPUS / "01/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    out = characterise_file(Path(files[len(files) // 2]), "t", 0.1)
    counts = [out["candidate_sweep"][str(t)] for t in sorted(THRESHOLD_SWEEP)]
    assert counts == sorted(counts, reverse=True), counts


# --- the threshold-sweep optimisation is equivalent to the detector ---

@REAL
def test_the_sweep_counter_matches_the_real_detector_exactly():
    """
    The sweep counts components on the grid the authoritative detector already
    built, instead of calling find_anomaly_candidates once per threshold and
    rebuilding the grid each time. That is a PERFORMANCE change only, so it
    must agree with the detector at every threshold, not just the default.
    """
    from interpretation.anomaly_candidates import (
        DEFAULT_MIN_CELLS, find_anomaly_candidates,
    )
    from preprocessing.spatial_grid import (
        build_trace_depth_grid_for_records, preprocess_trace_local_anomaly,
    )
    from preprocessing.trace_processing import process_gpr_traces
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    from scripts.characterise_4tu import count_components

    files = sorted(glob.glob(str(CORPUS / "01/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    for f in files[:3]:
        recs = SEGYConverter().load(Path(f), dataset_id="t", sensor_type=SensorType.GPR,
                                    coordinate_encoding="ieee_nmea",
                                    velocity_m_per_ns=0.0999).records
        recs = preprocess_trace_local_anomaly(process_gpr_traces(recs))
        grid = build_trace_depth_grid_for_records(
            recs, source_file=Path(f).name, field="signal")["grid"]
        for thr in THRESHOLD_SWEEP:
            authoritative = len(find_anomaly_candidates(
                recs, source_file=Path(f).name, threshold=thr,
                min_cells=DEFAULT_MIN_CELLS))
            assert count_components(grid, thr, DEFAULT_MIN_CELLS) == authoritative, (
                f"{Path(f).name} threshold={thr}")


@REAL
def test_every_characterised_file_records_that_the_sweep_agreed():
    files = sorted(glob.glob(str(CORPUS / "01/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    out = characterise_file(Path(files[0]), "t", 0.0999)
    assert out["sweep_agrees_with_detector_at_default"] is True


# --- the memory-safe array path is equivalent, not an approximation ---

@REAL
def test_the_array_path_reproduces_the_record_path_bit_for_bit():
    """
    The array path exists because per-cell SubterraRecords, not the science,
    dominate memory: the largest radargram is a 59 MB float array but roughly
    5 GB of records. It calls the identical functions in the identical order
    on the array, so it must produce the identical grid -- not a close one.
    """
    import numpy as np
    from converters.segy_converter import SEGYConverter
    from preprocessing.spatial_grid import (
        build_trace_depth_grid_for_records, preprocess_trace_local_anomaly,
    )
    from preprocessing.trace_processing import process_gpr_traces
    from schemas.subterra_record import SensorType
    from scripts.characterise_4tu import anomaly_grid_arraywise, count_components

    files = sorted(glob.glob(str(CORPUS / "*/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    for f in (files[0], files[len(files) // 3], files[len(files) // 2]):
        p = Path(f)
        recs = SEGYConverter().load(p, dataset_id="e", sensor_type=SensorType.GPR,
                                    coordinate_encoding="ieee_nmea",
                                    velocity_m_per_ns=0.0999).records
        recs = preprocess_trace_local_anomaly(process_gpr_traces(recs))
        from_records = np.asarray(build_trace_depth_grid_for_records(
            recs, source_file=p.name, field="signal")["grid"], dtype=float)
        from_array = anomaly_grid_arraywise(p)
        assert from_array.shape == from_records.shape, p.name
        assert np.array_equal(np.nan_to_num(from_records), np.nan_to_num(from_array)), (
            f"{p.name}: array path diverged from the record path")
        for thr in THRESHOLD_SWEEP:
            assert (count_components(from_records, thr, 3)
                    == count_components(from_array, thr, 3)), f"{p.name} @ {thr}"


@REAL
def test_no_trace_is_lost_on_the_array_path():
    from scripts.characterise_4tu import anomaly_grid_arraywise, read_trace_array
    files = sorted(glob.glob(str(CORPUS / "*/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    for f in files[:3]:
        traces, n_samples = read_trace_array(Path(f))
        on_disk = (os.path.getsize(f) - 3600) // (240 + n_samples * 2)
        assert traces.shape[0] == on_disk, f
        assert anomaly_grid_arraywise(Path(f)).shape == (n_samples, on_disk)


@REAL
def test_an_oversized_radargram_is_characterised_rather_than_skipped():
    """010.15 is a single 14,516-trace line -- the case that used to be dropped."""
    from scripts.characterise_4tu import characterise_file_arraywise
    big = sorted(glob.glob(str(CORPUS / "010/010/010.15/**/*.sgy"), recursive=True))
    if not big:
        pytest.skip("activity 010.15 not present")
    out = characterise_file_arraywise(Path(big[0]), 0.0999)
    assert out["processing_mode"] == "arraywise"
    assert out["traces"] > 10_000
    assert out["candidate_detail_available"] is False
    assert "memory constraint" in out["candidate_detail_reason"]
    assert out["candidates"] >= 0 and out["candidate_sweep"]


# --- the produced artifact keeps the states separate ---

ARTIFACT = Path("artifacts/4tu/characterisation.json")
HAS_ARTIFACT = pytest.mark.skipif(not ARTIFACT.exists(),
                                  reason="characterisation has not been run")


@HAS_ARTIFACT
def test_the_artifact_records_that_no_pipeline_parameter_was_changed():
    run = json.loads(ARTIFACT.read_text())
    assert run["pipeline"]["parameters_changed_by_this_script"] == "none"
    assert run["pipeline"]["threshold"] == 3.0
    assert run["pipeline"]["min_cells"] == 3


@HAS_ARTIFACT
def test_every_activity_states_its_velocity_provenance():
    run = json.loads(ARTIFACT.read_text())
    for loc, a in run["activities"].items():
        assert a["velocity_provenance"] == "derived_from_provider_site_estimate"
        assert "not a measurement of the subsurface" in a["velocity_basis"]


@HAS_ARTIFACT
def test_source_reported_information_is_never_given_a_position():
    run = json.loads(ARTIFACT.read_text())
    for a in run["activities"].values():
        src = a["source_reported"]
        assert "LocationID only" in src["join"]
        for key in src:
            assert key not in ("lat", "lon", "easting", "northing", "position")


@HAS_ARTIFACT
def test_the_artifact_never_claims_the_sweep_disagreed():
    run = json.loads(ARTIFACT.read_text())
    for a in run["activities"].values():
        for f in a.get("files", []):
            agreed = f["sweep_agrees_with_detector_at_default"]
            # None on the array path, which has no separate authoritative call.
            assert agreed in (True, None), f["file"]


@HAS_ARTIFACT
def test_every_activity_declares_its_coverage_and_processing_mode():
    run = json.loads(ARTIFACT.read_text())
    for loc, a in run["activities"].items():
        assert a["coverage"] in ("complete", "partial", "failed"), loc
        if a["coverage"] != "failed":
            assert a["processing_modes"], loc


@HAS_ARTIFACT
def test_skipped_and_failed_work_is_reported_not_dropped():
    run = json.loads(ARTIFACT.read_text())
    assert isinstance(run["skipped"], list) and isinstance(run["errors"], list)
    for s in run["skipped"]:
        assert s["reason"] and s["location_id"]
    for e in run["errors"]:
        assert e["error"] and e["file"]
