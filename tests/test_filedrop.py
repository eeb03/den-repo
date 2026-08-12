"""
FileDrop: the acquisition boundary.

WHAT THESE DEFEND. An acquisition is evidence arriving from outside Subterra,
and the invariant is that receiving it must never make it less trustworthy. So
the tests are about preservation and honesty at the boundary: the bytes are kept
exactly as sent, the checksum is of those bytes, a filename cannot become a
path, an unreadable file is refused without leaving anything behind, and nothing
about modality, spatial reference or time is inferred from an extension.

The acquisition record is `ImportJob` -- extended, not replaced -- so several of
these also check that the existing pipeline still runs the ingestion.
"""
import hashlib
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import acquisition
from api.main import app
from database.models import Dataset, ImportJob
from database.session import Base, get_db
from jobs import runner, storage

pytestmark = pytest.mark.real_auth

PASSWORD = "filedrop-test-password"

CSV = (b"latitude,longitude,signal,depth\n"
       b"52.0,4.3,18.4,0.15\n"
       b"52.0001,4.3001,21.0,0.15\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "data_root", tmp_path)
    for name in ("processed", "raw", "metadata"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'filedrop.db'}",
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

    # The worker opens its OWN session rather than the request's, so it has to
    # be pointed at the same database or it reaches for the real one.
    @contextmanager
    def _worker_session():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(runner, "get_session", _worker_session)
    # The endpoint really does hand off to a background thread; recording the
    # hand-off instead lets each test drive `_execute` deterministically.
    monkeypatch.setattr(runner, "submit", lambda job_id: None)
    try:
        yield Session, tmp_path
    finally:
        app.dependency_overrides.clear()


def signed_in(email="owner@example.test") -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/register",
                       json={"email": email, "password": PASSWORD}).status_code == 201
    return client


def drop(client, content=CSV, filename="survey.csv", sensor="gpr", review=True):
    return client.post("/api/imports", files={"file": (filename, content, "text/csv")},
                       data={"sensor_type": sensor, "review": str(review).lower()})


# ---------------------------------------------------------------------------
# receipt and preservation
# ---------------------------------------------------------------------------

def test_a_supported_file_is_received_and_identified(env):
    Session, _ = env
    client = signed_in()
    body = drop(client).json()["job"]

    # `.csv` is ambiguous, so it rests at NEEDS_INPUT rather than IDENTIFIED --
    # both are held states awaiting a decision.
    assert body["state"] in acquisition.HELD_STATES
    assert body["identification"]["parser_available"] is True
    assert body["identification"]["detected_format"] == "csv"


def test_the_original_bytes_are_preserved_exactly(env):
    """The acquisition is evidence. Receiving it must not alter it."""
    Session, root = env
    client = signed_in()
    body = drop(client).json()["job"]

    stored = [p for p in (root / "raw").rglob("*") if p.is_file()]
    assert len(stored) == 1
    assert stored[0].read_bytes() == CSV


def test_the_checksum_is_of_the_bytes_that_arrived(env):
    Session, root = env
    client = signed_in()
    body = drop(client).json()["job"]

    assert body["checksum"] == hashlib.sha256(CSV).hexdigest()
    stored = next(p for p in (root / "raw").rglob("*") if p.is_file())
    assert body["checksum"] == hashlib.sha256(stored.read_bytes()).hexdigest()


def test_the_original_filename_is_preserved_alongside_the_safe_one(env):
    Session, _ = env
    client = signed_in()
    body = drop(client, filename="Site 01 survey.csv").json()["job"]

    assert body["original_filename"] == "Site 01 survey.csv"
    assert body["stored_filename"] != body["original_filename"]
    assert "/" not in body["stored_filename"]


def test_the_receipt_time_is_recorded(env):
    Session, _ = env
    client = signed_in()
    assert drop(client).json()["job"]["created_at"]


# ---------------------------------------------------------------------------
# security
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hostile", [
    "../../../etc/passwd.csv",
    "..\\..\\windows\\evil.csv",
    "....//....//escape.csv",
    "/absolute/path.csv",
    ".hidden.csv",
])
def test_a_hostile_filename_never_becomes_a_path(env, hostile):
    Session, root = env
    client = signed_in()
    body = drop(client, filename=hostile).json()["job"]

    stored = [p for p in (root / "raw").rglob("*") if p.is_file()]
    assert len(stored) == 1
    # Everything written stays under the raw directory, whatever was claimed.
    assert root / "raw" in stored[0].parents
    assert ".." not in body["stored_filename"]
    assert not body["stored_filename"].startswith(".")


def test_an_empty_upload_is_refused_and_leaves_nothing_behind(env):
    Session, root = env
    client = signed_in()
    body = drop(client, content=b"").json()["job"]

    assert body["state"] == runner.FAILED
    assert body["error_stage"] == acquisition.STAGE_UPLOAD
    assert [p for p in (root / "raw").rglob("*") if p.is_file()] == []


def test_an_oversized_upload_is_refused(env, monkeypatch):
    Session, root = env
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 16)
    client = signed_in()
    body = drop(client, content=b"x" * 4096).json()["job"]

    assert body["state"] == runner.FAILED
    assert body["error_stage"] == acquisition.STAGE_UPLOAD
    assert [p for p in (root / "raw").rglob("*") if p.is_file()] == []


def test_another_user_cannot_read_or_accept_an_acquisition(env):
    Session, _ = env
    owner = signed_in("owner@example.test")
    job_id = drop(owner).json()["job"]["id"]
    intruder = signed_in("intruder@example.test")

    assert intruder.get(f"/api/imports/jobs/{job_id}").status_code == 404
    assert intruder.post(f"/api/imports/jobs/{job_id}/accept").status_code == 404


def test_an_unauthenticated_caller_cannot_drop_a_file(env):
    Session, _ = env
    anonymous = TestClient(app)
    assert anonymous.post(
        "/api/imports", files={"file": ("a.csv", CSV, "text/csv")},
        data={"sensor_type": "gpr"}).status_code == 401


def test_the_claimed_content_type_is_recorded_but_not_trusted(env):
    """Dispatch is by what a converter can read, never by what a client says."""
    Session, _ = env
    client = signed_in()
    response = client.post(
        "/api/imports",
        files={"file": ("survey.csv", CSV, "application/x-executable")},
        data={"sensor_type": "gpr", "review": "true"})
    body = response.json()["job"]

    assert body["content_type"] == "application/x-executable"
    assert body["identification"]["detected_format"] == "csv"
    assert body["state"] in acquisition.HELD_STATES


# ---------------------------------------------------------------------------
# identification
# ---------------------------------------------------------------------------

def test_an_unsupported_file_is_rejected_with_a_usable_answer(env):
    Session, root = env
    client = signed_in()
    body = drop(client, content=b"nope", filename="notes.docx").json()["job"]

    assert body["state"] == runner.FAILED
    assert body["error_stage"] == acquisition.STAGE_FORMAT
    assert "docx" in body["error_message"] or "Unrecognised" in body["error_message"]
    # Nothing unreadable is left on disk.
    assert [p for p in (root / "raw").rglob("*") if p.is_file()] == []


def test_an_ambiguous_format_needs_input_rather_than_a_guess(env):
    """A .csv may be GPR traces, a point cloud or a DEM. Subterra does not know."""
    Session, _ = env
    client = signed_in()
    body = drop(client).json()["job"]

    assert body["state"] == acquisition.NEEDS_INPUT
    assert body["identification"]["ambiguous_format"] is True
    assert "cannot tell which" in body["identification"]["ambiguity_note"]


def test_the_modality_is_the_uploaders_declaration_not_an_inference(env):
    Session, _ = env
    client = signed_in()
    body = drop(client, sensor="lidar").json()["job"]

    assert body["identification"]["declared_modality"] == "lidar"
    assert body["identification"]["modality_source"] == "declared_by_uploader"


def test_identification_reports_what_the_format_can_carry_not_what_it_declares(env):
    Session, _ = env
    client = signed_in()
    identification = drop(client).json()["job"]["identification"]

    assert "spatial_expectation" in identification
    assert "not what this file declares" in identification["spatial_expectation_note"]


def test_identification_reads_no_payload():
    """
    It reads the registry, the extension and the size. Parsing here would
    duplicate the converter and could disagree with it.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(acquisition.identify))
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    assert not called & {"open", "read_bytes", "read_text", "load", "get_converter"}


# ---------------------------------------------------------------------------
# duplicates
# ---------------------------------------------------------------------------

def test_identical_bytes_are_reported_never_merged(env):
    Session, _ = env
    client = signed_in()
    first = drop(client).json()["job"]
    second = drop(client).json()["job"]

    duplicates = second["identification"]["duplicates"]
    assert duplicates["is_duplicate"] is True
    assert first["id"] in [a["acquisition_id"] for a in duplicates["acquisitions"]]
    assert second["state"] == acquisition.NEEDS_INPUT
    # Both acquisitions survive: arrival is a fact, not a mistake.
    assert first["id"] != second["id"]


def test_a_duplicate_can_still_be_accepted(env):
    """The user decides what identical bytes mean."""
    Session, _ = env
    client = signed_in()
    drop(client)
    second = drop(client).json()["job"]

    accepted = client.post(f"/api/imports/jobs/{second['id']}/accept")
    assert accepted.status_code == 202
    assert accepted.json()["job"]["state"] == runner.QUEUED


def test_duplicate_detection_does_not_leak_another_users_holdings(env):
    Session, _ = env
    other = signed_in("other@example.test")
    drop(other)
    client = signed_in("me@example.test")
    duplicates = drop(client).json()["job"]["identification"]["duplicates"]

    assert duplicates["acquisitions"] == []
    assert duplicates["is_duplicate"] is False


def test_a_checksum_matching_an_existing_dataset_is_reported(env):
    Session, _ = env
    client = signed_in()
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    session = Session()
    session.add(Dataset(id="existing", name="Earlier survey", sensor_type="gpr",
                        original_format="csv", owner_id=user_id,
                        checksum=hashlib.sha256(CSV).hexdigest()))
    session.commit()
    session.close()

    duplicates = drop(client).json()["job"]["identification"]["duplicates"]
    assert duplicates["is_duplicate"] is True
    assert duplicates["datasets"][0]["dataset_id"] == "existing"


# ---------------------------------------------------------------------------
# the hold, and the handoff
# ---------------------------------------------------------------------------

def test_review_holds_the_acquisition_without_ingesting(env):
    Session, _ = env
    client = signed_in()
    body = drop(client, review=True).json()["job"]

    assert body["state"] in acquisition.HELD_STATES
    assert body["dataset_id"] is None


def test_without_review_the_original_immediate_behaviour_is_unchanged(env):
    """Every existing caller keeps working; the new flow is opt-in."""
    Session, _ = env
    client = signed_in()
    body = drop(client, review=False).json()["job"]

    assert body["state"] == runner.QUEUED


def test_accepting_hands_off_to_the_existing_pipeline(env):
    Session, root = env
    client = signed_in()
    job_id = drop(client).json()["job"]["id"]

    assert client.post(f"/api/imports/jobs/{job_id}/accept").json()["job"]["state"] == \
        runner.QUEUED

    runner._execute(job_id)

    job = client.get(f"/api/imports/jobs/{job_id}").json()["job"]
    assert job["state"] == runner.SUCCEEDED, job.get("error_message")
    assert job["dataset_id"]


def test_the_dataset_is_traceable_back_to_the_acquisition(env):
    Session, _ = env
    client = signed_in()
    job_id = drop(client).json()["job"]["id"]
    client.post(f"/api/imports/jobs/{job_id}/accept")
    runner._execute(job_id)

    job = client.get(f"/api/imports/jobs/{job_id}").json()["job"]
    provenance = client.get(f"/api/datasets/{job['dataset_id']}/acquisition").json()

    assert provenance["acquisition"]["id"] == job_id
    assert provenance["acquisition"]["original_filename"] == "survey.csv"
    assert provenance["acquisition"]["checksum"] == hashlib.sha256(CSV).hexdigest()


def test_a_rejected_acquisition_cannot_be_accepted(env):
    Session, _ = env
    client = signed_in()
    job_id = drop(client, content=b"nope", filename="notes.docx").json()["job"]["id"]

    response = client.post(f"/api/imports/jobs/{job_id}/accept")
    assert response.status_code == 409
    assert "cannot be accepted" in response.json()["detail"]


def test_the_same_acquisition_cannot_be_accepted_twice(env):
    Session, _ = env
    client = signed_in()
    job_id = drop(client).json()["job"]["id"]

    assert client.post(f"/api/imports/jobs/{job_id}/accept").status_code == 202
    assert client.post(f"/api/imports/jobs/{job_id}/accept").status_code == 409


# ---------------------------------------------------------------------------
# failure categories stay distinguishable
# ---------------------------------------------------------------------------

def test_a_malformed_supported_file_fails_at_ingestion_not_at_receipt(env):
    """
    Receipt, identification and ingestion are different failures with different
    answers. Collapsing them into "upload failed" destroys the diagnosis.
    """
    Session, _ = env
    client = signed_in()
    job_id = drop(client, content=b"not,a,valid\x00\x00csv\n").json()["job"]["id"]
    client.post(f"/api/imports/jobs/{job_id}/accept")
    runner._execute(job_id)

    job = client.get(f"/api/imports/jobs/{job_id}").json()["job"]
    if job["state"] == runner.FAILED:
        assert job["error_stage"] not in (acquisition.STAGE_UPLOAD,
                                          acquisition.STAGE_FORMAT)
        assert job["error_message"]


def test_the_failure_stages_are_distinct_values():
    stages = {acquisition.STAGE_UPLOAD, acquisition.STAGE_FORMAT,
              acquisition.STAGE_IDENTIFICATION, acquisition.STAGE_VALIDATION,
              acquisition.STAGE_INGESTION}
    assert len(stages) == 5


# ---------------------------------------------------------------------------
# no fabrication
# ---------------------------------------------------------------------------

def test_identification_declares_no_crs_datum_depth_or_time_window(env):
    Session, _ = env
    client = signed_in()
    identification = drop(client).json()["job"]["identification"]

    blob = str(identification).lower()
    for fabricated in ("epsg:", "nap", "velocity_m_per_ns", "time_window_ns"):
        assert fabricated not in blob


def test_the_dt_time_window_is_read_from_the_file_not_supplied(env):
    """
    The acquisition time window IS carried by a .dt, in the H record's ASCII
    field 2. FileDrop must not offer to supply one: a window nobody measured
    would rescale every sample in the file.
    """
    import inspect

    from converters import ids_dt_converter

    assert "time_window_ns" in inspect.getsource(ids_dt_converter)
    # The acquisition layer knows nothing about time windows and cannot set one.
    assert "time_window" not in inspect.getsource(acquisition)


def test_the_spatial_expectation_for_dt_names_the_geo_tie_requirement():
    """An IDS .dt carries along-track distance, not a position on Earth."""
    expectation = acquisition._FORMAT_SPATIAL_EXPECTATION["ids_dt"]
    assert "not a position on Earth" in expectation["horizontal"]
    assert any("GeoTie" in m for m in expectation["missing"])
