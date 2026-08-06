"""
Backfilling SurveyFrames for datasets ingested before frames existed.

The properties that matter: it never touches records, never replaces a
frame written at ingest with a reconstruction, writes nothing unless asked,
and is safe to re-run.
"""
import json

import pytest

from database.frames_store import load_frames, save_frames
from schemas.spatial import (
    AxisKind, CRSKind, CRSProvenance, GeographicPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame
from scripts.backfill_survey_frames import (
    backfill, backfill_dataset, known_dataset_ids, load_records_for_synthesis,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from configs import settings as settings_mod
    monkeypatch.setattr(type(settings_mod.settings), "processed_dir",
                        property(lambda self: tmp_path))
    return tmp_path


def _write_records(store, dataset_id, source_files=("line.SGY",), n_traces=3, n_samples=4):
    records = [
        SubterraRecord(
            dataset_id=dataset_id, sensor_type=SensorType.GPR,
            latitude=41.0 + t * 1e-4, longitude=15.0,
            position=GeographicPosition(lat=41.0 + t * 1e-4, lon=15.0),
            depth=round(d * 0.01, 6), signal=[float(d)],
            metadata={"source_file": sf, "trace_index": t, "sample_index": d,
                      "two_way_time_ns": d * 2.0, "velocity_m_per_ns": 0.1,
                      "sample_count": n_samples},
        )
        for sf in source_files for t in range(n_traces) for d in range(n_samples)
    ]
    path = store / f"{dataset_id}.jsonl"
    with open(path, "w") as fh:
        for r in records:
            fh.write(json.dumps(r.to_flat_dict(), default=str) + "\n")
    return records


# --- discovery ---

def test_known_dataset_ids_lists_record_files(store):
    _write_records(store, "ds_a")
    _write_records(store, "ds_b")
    assert known_dataset_ids() == ["ds_a", "ds_b"]


def test_a_dataset_with_no_record_file_is_an_error(store):
    r = backfill_dataset("missing", apply=True)
    assert r.status == "error" and "no record file" in r.detail


# --- streaming reduction ---

def test_synthesis_input_keeps_one_record_per_trace(store):
    """482 samples per trace on real data; loading them all to derive frames is waste."""
    _write_records(store, "ds", n_traces=3, n_samples=4)
    reduced = load_records_for_synthesis("ds")
    assert len(reduced) == 3                      # not 12
    assert {r.metadata["trace_index"] for r in reduced} == {0, 1, 2}


def test_reduction_keeps_one_record_per_trace_per_source_file(store):
    _write_records(store, "ds", source_files=("a.SGY", "b.SGY"), n_traces=3, n_samples=4)
    reduced = load_records_for_synthesis("ds")
    assert len(reduced) == 6
    assert {r.metadata["source_file"] for r in reduced} == {"a.SGY", "b.SGY"}


def test_reduction_preserves_what_synthesis_reads(store):
    """A frame built from the reduction must equal one built from every record."""
    from database.frames_store import synthesize_frames_from_records
    full = _write_records(store, "ds", source_files=("a.SGY", "b.SGY"))
    assert synthesize_frames_from_records(load_records_for_synthesis("ds")) == \
           synthesize_frames_from_records(full)


# --- dry run is the default ---

def test_dry_run_writes_nothing(store):
    _write_records(store, "ds")
    result = backfill_dataset("ds")
    assert result.status == "would_write" and result.frame_count == 1
    assert load_frames("ds") == []
    assert not (store / "ds.frames.json").exists()


def test_apply_writes_the_frames(store):
    _write_records(store, "ds", source_files=("a.SGY", "b.SGY"))
    result = backfill_dataset("ds", apply=True)
    assert result.status == "written" and result.frame_count == 2
    assert result.source_files == ["a.SGY", "b.SGY"]
    frames = load_frames("ds")
    assert len(frames) == 2
    assert all(f.assumption("frame_reconstructed") is not None for f in frames)


def test_written_frames_are_marked_as_reconstructed(store):
    """Nothing may mistake an inference for something the source declared."""
    _write_records(store, "ds")
    backfill_dataset("ds", apply=True)
    marker = load_frames("ds")[0].assumption("frame_reconstructed")
    assert marker.value is True and marker.verified is False


# --- idempotency and protecting ingest-time frames ---

def test_rerunning_skips_an_already_covered_dataset(store):
    _write_records(store, "ds")
    assert backfill_dataset("ds", apply=True).status == "written"
    again = backfill_dataset("ds", apply=True)
    assert again.status == "skipped" and "already has frames" in again.detail


def test_an_ingest_time_frame_is_not_downgraded(store):
    """
    A frame written at ingest knows the real source format and CRS; a
    reconstruction does not. Backfill must never silently replace one.
    """
    _write_records(store, "ds")
    real = SurveyFrame(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy", source_file="line.SGY",
        spatial_ref=SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:32633",
                               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="time-zero", positive_down=True),
    )
    save_frames("ds", [real])
    assert backfill_dataset("ds", apply=True).status == "skipped"
    kept = load_frames("ds")[0]
    assert kept.source_format == "segy"
    assert kept.spatial_ref.code == "EPSG:32633"
    assert kept.assumption("frame_reconstructed") is None


def test_overwrite_replaces_existing_frames_when_asked(store):
    _write_records(store, "ds")
    backfill_dataset("ds", apply=True)
    result = backfill_dataset("ds", apply=True, overwrite=True)
    assert result.status == "written"


# --- records are never modified ---

def test_records_are_left_untouched(store):
    _write_records(store, "ds")
    before = (store / "ds.jsonl").read_bytes()
    backfill_dataset("ds", apply=True)
    assert (store / "ds.jsonl").read_bytes() == before


# --- batch behaviour ---

def test_backfill_covers_every_dataset_by_default(store):
    _write_records(store, "ds_a")
    _write_records(store, "ds_b")
    results = backfill(apply=True)
    assert {r.dataset_id for r in results} == {"ds_a", "ds_b"}
    assert all(r.status == "written" for r in results)


def test_backfill_can_be_limited_to_one_dataset(store):
    _write_records(store, "ds_a")
    _write_records(store, "ds_b")
    results = backfill(["ds_a"], apply=True)
    assert [r.dataset_id for r in results] == ["ds_a"]
    assert load_frames("ds_b") == []


def test_an_empty_record_file_reports_empty(store):
    (store / "ds.jsonl").write_text("")
    r = backfill_dataset("ds", apply=True)
    assert r.status == "empty"


def test_a_corrupt_record_file_is_reported_not_raised(store):
    (store / "ds.jsonl").write_text("{not json}\n")
    r = backfill_dataset("ds", apply=True)
    assert r.status == "error" and "could not read records" in r.detail


def test_result_lines_are_human_readable(store):
    _write_records(store, "ds")
    assert "would_write" in backfill_dataset("ds").line()
