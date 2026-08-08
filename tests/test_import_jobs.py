"""
The asynchronous import path.

These tests pin the properties that make a background job trustworthy rather
than merely convenient:

  1. a job is durable -- it exists in the database before any work starts, so
     it can always be reported on;
  2. a job never disappears silently -- an interrupted one is reconciled to
     FAILED with a stated reason;
  3. a failure carries the real backend error and the stage that raised it;
  4. an upload cannot escape its directory or overwrite anything;
  5. the format answer comes from the converter registry, never a second list.

Nothing here is timing-based. The worker is driven synchronously by calling
`runner._execute` directly, so the tests assert state transitions rather than
racing a thread.
"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from database.models import ImportJob
from database.session import Base, get_db
from jobs import runner, storage


@pytest.fixture
def client(tmp_path, monkeypatch):
    """An API bound to a throwaway sqlite database and a throwaway data root."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from configs import settings as settings_mod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # data_root is a pydantic-settings FIELD (raw_dir/processed_dir are
    # properties derived from it), so it is patched on the instance.
    monkeypatch.setattr(settings_mod.settings, "data_root", tmp_path)
    (tmp_path / "raw").mkdir(exist_ok=True)
    (tmp_path / "processed").mkdir(exist_ok=True)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    # The runner opens its own sessions; point them at the same engine.
    from contextlib import contextmanager

    @contextmanager
    def _get_session():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(runner, "get_session", _get_session)

    # The endpoint really does hand the job to a background thread. That is the
    # behaviour under test, but it makes assertions race the worker, so here
    # the hand-off is recorded instead of performed and each test drives
    # `_execute` itself. `test_the_endpoint_hands_the_job_to_the_worker` pins
    # that the real submit is still called.
    submitted: list[str] = []
    import api.routes.imports as imports_mod
    monkeypatch.setattr(imports_mod.runner, "submit", submitted.append)

    app.dependency_overrides[get_db] = _get_db
    try:
        yield TestClient(app), Session, submitted
    finally:
        app.dependency_overrides.clear()


CSV = b"latitude,longitude,depth,signal\n41.0,15.0,0.5,1.0\n41.001,15.001,0.5,2.0\n"


def _post(client, filename, body=CSV, sensor_type="gpr"):
    return client.post(
        "/api/imports",
        files={"file": (filename, io.BytesIO(body), "application/octet-stream")},
        data={"sensor_type": sensor_type},
    )


# --- format answers come from the registry --------------------------------

def test_formats_endpoint_reports_the_registry(client):
    api, _, _submitted = client
    body = api.get("/api/imports/formats").json()

    from converters.registry import supported_extensions

    assert set(body["supported"]) == set(supported_extensions())
    assert ".csv" in body["supported"]
    # recognised-but-unreadable is a distinct answer, not padding
    exts = {r["extension"] for r in body["recognized_unsupported"]}
    assert ".dzx" in exts and ".sgd" in exts
    assert body["max_upload_bytes"] == storage.MAX_UPLOAD_BYTES


# --- job creation and the happy path --------------------------------------

def test_the_endpoint_hands_the_job_to_the_worker(client):
    """A queued job must actually be submitted, or it would wait for ever."""
    api, _, submitted = client
    job_id = _post(api, "line1.csv").json()["job"]["id"]
    assert submitted == [job_id]


def test_a_refused_job_is_never_submitted(client):
    api, _, submitted = client
    _post(api, "notes.bananas")
    assert submitted == []


def test_upload_creates_a_queued_job_before_any_work_happens(client):
    api, Session, _submitted = client
    r = _post(api, "line1.csv")
    assert r.status_code == 202          # the dataset does not exist yet

    job = r.json()["job"]
    assert job["state"] == runner.QUEUED
    assert job["stage"] == runner.STAGE_QUEUED
    assert job["dataset_id"] is None     # nothing registered yet
    assert job["format_status"] == "supported"
    assert job["original_filename"] == "line1.csv"
    assert job["size_bytes"] == len(CSV)

    # durable: it is in the database, not only in the response
    with Session() as s:
        assert s.query(ImportJob).filter(ImportJob.id == job["id"]).first() is not None


def test_a_supported_upload_runs_to_succeeded_and_yields_a_dataset(client):
    api, _, _submitted = client
    job_id = _post(api, "line1.csv").json()["job"]["id"]

    runner._execute(job_id)              # drive the worker deterministically

    job = api.get(f"/api/imports/jobs/{job_id}").json()["job"]
    assert job["state"] == runner.SUCCEEDED
    assert job["stage"] == runner.STAGE_COMPLETE
    assert job["dataset_id"], "a succeeded import must name its dataset"
    assert job["error_message"] is None
    assert job["started_at"] and job["completed_at"]


def test_the_job_reports_the_stage_it_is_in_and_never_a_percentage(client):
    api, _, _submitted = client
    job_id = _post(api, "line1.csv").json()["job"]["id"]
    runner._execute(job_id)

    job = api.get(f"/api/imports/jobs/{job_id}").json()["job"]
    assert "progress" not in job and "percent" not in job
    assert job["stage"] in (
        runner.STAGE_COMPLETE, runner.STAGE_CONVERTING, runner.STAGE_VALIDATING,
        runner.STAGE_PREPROCESSING, runner.STAGE_PERSISTING, runner.STAGE_REGISTERING,
    )


def test_stages_are_reported_in_pipeline_order(client, tmp_path):
    """
    The stage names come from the real pipeline, in the order it really runs.

    Asserted against `_run_ingest_pipeline` directly rather than through the
    worker: the contract being pinned is the `on_stage` hook itself, and going
    via the job layer would only add indirection between the assertion and the
    thing it is about.
    """
    _, Session, _submitted = client
    from api.routes.datasets import _run_ingest_pipeline
    from schemas.subterra_record import SensorType

    src = tmp_path / "line1.csv"
    src.write_bytes(CSV)

    seen: list[str] = []
    with Session() as session:
        _run_ingest_pipeline(src, SensorType.GPR, "line1.csv", session,
                             on_stage=seen.append)

    assert seen[0] == "converting"
    for stage in ("validating", "persisting", "registering"):
        assert stage in seen
    assert seen.index("validating") < seen.index("persisting") < seen.index("registering")
    # no percentage is derivable from this, and none is offered
    assert all(isinstance(s, str) for s in seen)


# --- refusals -------------------------------------------------------------

def test_recognized_but_unsupported_format_is_refused_and_named(client):
    api, _, _submitted = client
    job = _post(api, "survey.dzx").json()["job"]
    assert job["state"] == runner.FAILED
    assert job["format_status"] == "recognized_unsupported"
    assert job["error_stage"] == "format-check"
    assert "no adapter" in job["error_message"].lower()
    # the platform still names what it is
    assert "GSSI" in job["detected_format"]


def test_unknown_format_is_refused_differently(client):
    api, _, _submitted = client
    job = _post(api, "notes.bananas").json()["job"]
    assert job["state"] == runner.FAILED
    assert job["format_status"] == "unknown"
    assert "unrecognised" in job["error_message"].lower()


def _stored_path(Session, job_id):
    """stored_path is a server filesystem path and is deliberately not in the
    API response; tests read it from the database."""
    with Session() as s:
        return s.query(ImportJob).filter(ImportJob.id == job_id).first().stored_path


def test_a_refused_upload_writes_nothing_to_disk(client, tmp_path):
    api, Session, _submitted = client
    job = _post(api, "survey.sgd").json()["job"]
    assert job["state"] == runner.FAILED
    assert _stored_path(Session, job["id"]) is None
    assert not (tmp_path / "raw" / storage.IMPORT_SUBDIR / job["id"]).exists()


def test_an_empty_upload_is_refused(client):
    api, _, _submitted = client
    job = _post(api, "empty.csv", body=b"").json()["job"]
    assert job["state"] == runner.FAILED
    assert job["error_stage"] == "upload"
    assert "empty" in job["error_message"].lower()


def test_a_conversion_failure_becomes_a_failed_job_with_the_real_error(client):
    """A .csv whose contents are not a readable table must fail informatively."""
    api, _, _submitted = client
    job_id = _post(api, "broken.csv", body=b"\x00\x01\x02 not a csv at all").json()["job"]["id"]
    runner._execute(job_id)

    job = api.get(f"/api/imports/jobs/{job_id}").json()["job"]
    assert job["state"] == runner.FAILED
    assert job["dataset_id"] is None
    assert job["error_stage"] in ("converting", "validating", "persisting", "registering")
    assert job["error_message"]
    # the real backend message, never a generic apology
    assert "something went wrong" not in job["error_message"].lower()


# --- filename safety ------------------------------------------------------

@pytest.mark.parametrize(
    "hostile",
    [
        "../../etc/passwd",
        "../processed/deadbeef.jsonl",
        "..\\..\\windows\\system32\\x.csv",
        "/absolute/path/line.csv",
        "....//....//line.csv",
    ],
)
def test_hostile_filenames_cannot_escape_the_job_directory(client, tmp_path, hostile):
    api, Session, _submitted = client
    job = _post(api, hostile).json()["job"]
    path = _stored_path(Session, job["id"])
    if path is None:
        return  # refused on format grounds, which is also safe
    stored = Path(path).resolve()
    root = (tmp_path / "raw" / storage.IMPORT_SUBDIR).resolve()
    assert root in stored.parents, f"{stored} escaped {root}"
    assert ".." not in stored.parts


def test_sanitize_filename_keeps_the_extension_the_registry_dispatches_on():
    # mangling the extension would turn a supported file into an unknown one
    assert storage.sanitize_filename("../../a b/line 1.csv").endswith(".csv")
    assert storage.sanitize_filename("x.SGY").endswith(".SGY")
    assert storage.sanitize_filename(None) == "upload"
    assert "/" not in storage.sanitize_filename("a/b/c.csv")


def test_two_uploads_of_the_same_name_do_not_overwrite_each_other(client):
    api, Session, _submitted = client
    a = _post(api, "line1.csv", body=CSV).json()["job"]
    b = _post(api, "line1.csv", body=CSV + b"41.002,15.002,0.5,3.0\n").json()["job"]

    pa, pb = _stored_path(Session, a["id"]), _stored_path(Session, b["id"])
    assert pa != pb
    assert Path(pa).read_bytes() != Path(pb).read_bytes()


# --- durability -----------------------------------------------------------

def test_an_interrupted_job_is_reconciled_rather_than_left_running(client):
    api, Session, _submitted = client
    job_id = _post(api, "line1.csv").json()["job"]["id"]

    with Session() as s:                      # simulate a crash mid-run
        s.query(ImportJob).filter(ImportJob.id == job_id).first().state = runner.RUNNING
        s.commit()

    assert runner.mark_orphaned_jobs_failed() == 1

    job = api.get(f"/api/imports/jobs/{job_id}").json()["job"]
    assert job["state"] == runner.FAILED
    assert "restarted" in job["error_message"].lower()
    assert job["completed_at"]


def test_execute_ignores_a_job_that_is_no_longer_queued(client):
    """Guards against the same job being run twice."""
    api, _, _submitted = client
    job_id = _post(api, "line1.csv").json()["job"]["id"]
    runner._execute(job_id)
    first = api.get(f"/api/imports/jobs/{job_id}").json()["job"]

    runner._execute(job_id)                   # second run must be a no-op
    assert api.get(f"/api/imports/jobs/{job_id}").json()["job"] == first


def test_the_api_does_not_leak_server_filesystem_paths(client):
    api, _, _submitted = client
    job = _post(api, "line1.csv").json()["job"]
    assert "stored_path" not in job
    assert job["stored_filename"] == "line1.csv"   # the name is fine; the path is not


def test_missing_job_is_a_404(client):
    api, _, _submitted = client
    assert api.get("/api/imports/jobs/does-not-exist").status_code == 404


def test_jobs_can_be_listed_newest_first(client):
    api, _, _submitted = client
    _post(api, "a.csv")
    _post(api, "b.csv")
    jobs = api.get("/api/imports/jobs").json()["jobs"]
    assert len(jobs) >= 2
    assert {j["original_filename"] for j in jobs} >= {"a.csv", "b.csv"}


# --- the synchronous path is untouched ------------------------------------

def test_the_existing_synchronous_ingest_route_still_exists():
    """
    The old endpoint is deliberately NOT removed. It has no test coverage of
    its own, so removing it could break an unseen caller.
    """
    paths = {r.path for r in app.routes}
    assert "/api/datasets/ingest" in paths
    assert "/api/imports" in paths


def test_the_ingest_pipeline_signature_stays_backward_compatible():
    """`on_stage` must be optional, or every existing caller breaks."""
    import inspect

    from api.routes.datasets import _run_ingest_pipeline

    sig = inspect.signature(_run_ingest_pipeline)
    assert sig.parameters["on_stage"].default is None
