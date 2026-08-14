"""
Device abstraction: devices, acquisition sessions, and the convergence with
FileDrop.

WHAT THESE DEFEND. Stage 10 adds a way for a person to assert that hardware
produced some evidence. That is a provenance claim, and the failure mode is a
claim quietly becoming a fact: a capability read as an observation, a typed
serial number read as a device-reported one, a simulated device read as
physical. So most of what follows is about categories staying apart.

There is NO hardware integration behind any of this, and a test says so.
"""
import hashlib
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import app
from database.models import AcquisitionSession, Device, ImportJob
from database.session import Base, get_db
from jobs import runner
from schemas.devices import (
    ALLOWED_TRANSITIONS,
    FAILURE_STAGES,
    DeviceCapabilities,
    InvalidTransition,
    SessionEvidence,
    SessionState,
    transition,
)
from schemas.subterra_record import SensorType

pytestmark = pytest.mark.real_auth

PASSWORD = "device-test-password"
CSV = (b"latitude,longitude,signal,depth\n"
       b"52.0,4.3,18.4,0.15\n"
       b"52.0001,4.3001,21.0,0.15\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "data_root", tmp_path)
    for name in ("processed", "raw", "metadata"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'devices.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

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

    app.dependency_overrides[get_db] = _get_db
    monkeypatch.setattr(runner, "get_session", _worker_session)
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


def register(client, **overrides):
    body = {
        "device_type": "gpr",
        "manufacturer": "IDS",
        "model": "Stream C",
        "capabilities": {"modalities": ["gpr"], "reports_position": True,
                         "reports_orientation": False, "reports_absolute_time": True},
    }
    body.update(overrides)
    return client.post("/api/devices", json=body)


def new_session(client, device_id, **overrides):
    body = {"label": "Line 1", "operator": "field team"}
    body.update(overrides)
    return client.post(f"/api/devices/{device_id}/sessions", json=body)


def move(client, session_id, to):
    return client.post(f"/api/sessions/{session_id}/state", params={"to": to})


def acquire(client, session_id, filename="line1.csv", content=CSV):
    """A session produces an acquisition through the SAME endpoint FileDrop uses."""
    return client.post("/api/imports",
                       files={"file": (filename, content, "text/csv")},
                       data={"sensor_type": "gpr", "review": "true",
                             "session_id": session_id})


# ---------------------------------------------------------------------------
# the device record
# ---------------------------------------------------------------------------

def test_a_device_can_be_registered(env):
    client = signed_in()
    body = register(client).json()["device"]

    assert body["manufacturer"] == "IDS"
    assert body["device_type"] == "gpr"
    assert body["is_simulated"] is False


def test_user_typed_metadata_stays_user_declared(env):
    """
    A serial number somebody remembered is not one an instrument reported, and
    no request field can say otherwise.
    """
    client = signed_in()
    body = register(client, serial_number="SN-12345").json()["device"]

    assert body["serial_number"] == "SN-12345"
    assert body["identity_source"] == "user_declared"


def test_a_client_cannot_claim_a_device_reported_its_own_identity(env):
    """`identity_source` is not a request field. Setting it would be a forgery."""
    client = signed_in()
    body = register(client, identity_source="device_reported").json()["device"]
    assert body["identity_source"] == "user_declared"


def test_a_serial_number_is_optional(env):
    """Neither FileDrop nor a simulated device can supply one; requiring it
    would invite an invented value."""
    client = signed_in()
    assert register(client, serial_number=None).status_code == 201


def test_a_simulated_device_is_marked_permanently(env):
    client = signed_in()
    body = register(client, kind="simulated", label="TEST simulator").json()["device"]

    assert body["kind"] == "simulated"
    assert body["is_simulated"] is True


def test_capabilities_use_the_existing_modality_vocabulary(env):
    """Not a second enum: a capability and a dataset's modality are one word."""
    capabilities = DeviceCapabilities(modalities=[SensorType.GPR, SensorType.GPS])
    assert capabilities.describes(SensorType.GPR)
    assert not capabilities.describes(SensorType.LIDAR)


def test_an_unknown_modality_is_refused(env):
    client = signed_in()
    assert register(client, device_type="teleporter").status_code == 422


# ---------------------------------------------------------------------------
# DeviceProfile: declared facts about the instrument, still not a measurement
# ---------------------------------------------------------------------------

def test_the_profile_fields_are_declared_and_stored(env):
    client = signed_in()
    body = register(client, capabilities={
        "modalities": ["gpr"], "reports_position": True,
        "reports_orientation": False, "reports_absolute_time": True,
        "frequency_mhz": 400.0, "channels": 2,
        "sampling_configuration": {"sample_interval_ns": 0.4, "samples_per_trace": 512},
        "supported_export_formats": [".sgy", ".dzt"],
    }).json()["device"]

    assert body["capabilities"]["frequency_mhz"] == 400.0
    assert body["capabilities"]["channels"] == 2
    assert body["capabilities"]["sampling_configuration"] == {
        "sample_interval_ns": 0.4, "samples_per_trace": 512,
    }
    assert body["capabilities"]["supported_export_formats"] == [".sgy", ".dzt"]


def test_the_profile_fields_default_to_absent_not_invented(env):
    """A device with no declared frequency, channels or export formats reports
    that absence -- it is not filled in with a typical or zero value."""
    body = register(client := signed_in()).json()["device"]

    assert body["capabilities"]["frequency_mhz"] is None
    assert body["capabilities"]["channels"] is None
    assert body["capabilities"]["sampling_configuration"] == {}
    assert body["capabilities"]["supported_export_formats"] == []


def test_supported_export_formats_must_be_readable_by_the_platform(env):
    """
    Not a second hardcoded list: a declared export format must be one
    `converters/registry.py` actually dispatches on, so a device profile can
    never promise a format Subterra cannot ingest.
    """
    client = signed_in()
    response = register(client, capabilities={
        "modalities": ["gpr"],
        "supported_export_formats": [".not_a_real_format"],
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DeviceAdapter: HOW evidence is meant to arrive -- neither capability nor
# evidence
# ---------------------------------------------------------------------------

def test_a_file_drop_adapter_round_trips(env):
    client = signed_in()
    body = register(client, adapter={"transport": "file_drop"}).json()["device"]
    assert body["adapter"] == {"transport": "file_drop"}


def test_a_device_with_no_declared_adapter_reports_absence_not_file_drop(env):
    """A device with no adapter is valid, and the absence must not be
    quietly filled in with the one implemented transport."""
    body = register(client := signed_in()).json()["device"]
    assert body["adapter"] is None


@pytest.mark.parametrize("transport", ["network", "serial"])
def test_an_unimplemented_transport_is_refused(env, transport):
    client = signed_in()
    response = register(client, adapter={"transport": transport})
    assert response.status_code == 422
    detail = str(response.json()["detail"]).lower()
    assert "could not connect" not in detail
    assert "device unavailable" not in detail
    assert "timeout" not in detail
    assert transport in detail


def test_an_unknown_transport_is_refused(env):
    client = signed_in()
    assert register(client, adapter={"transport": "bluetooth"}).status_code == 422


def test_the_adapter_travels_into_the_session_payload(env):
    client = signed_in()
    device_id = register(client, adapter={"transport": "file_drop"}).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]

    payload = client.get(f"/api/sessions/{session_id}").json()
    assert payload["device"]["adapter"] == {"transport": "file_drop"}


def test_declaring_an_adapter_does_not_touch_capabilities_or_evidence(env):
    """The three objects stay three objects: an adapter is not folded into
    what the device can produce, and it creates no session evidence."""
    client = signed_in()
    device = register(client, adapter={"transport": "file_drop"}).json()["device"]
    assert "adapter" not in device["capabilities"]

    session_id = new_session(client, device["id"]).json()["session"]["id"]
    evidence = client.get(f"/api/sessions/{session_id}").json()["session"]["evidence"]
    assert "transport" not in evidence
    assert "adapter" not in evidence


# ---------------------------------------------------------------------------
# capability is not evidence
# ---------------------------------------------------------------------------

def test_a_capability_creates_no_measurement():
    """
    A device that CAN report a position has said nothing about whether a
    particular session got one.
    """
    capabilities = DeviceCapabilities(reports_position=True, reports_orientation=True,
                                      reports_absolute_time=True)
    evidence = SessionEvidence()

    assert evidence.position_provided is False
    assert evidence.orientation_provided is False
    assert len(evidence.missing(capabilities)) == 3


def test_the_gap_between_capability_and_evidence_is_reported(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]

    payload = client.get(f"/api/sessions/{session_id}").json()
    gap = payload["capability_gap"]
    assert any("position" in g for g in gap)
    assert any("absolute acquisition time" in g for g in gap)
    # Orientation is NOT in the gap: this device does not claim to report one.
    assert not any("orientation" in g for g in gap)


def test_recording_evidence_closes_only_what_was_actually_provided(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]

    client.post(f"/api/sessions/{session_id}/evidence", json={
        "evidence": {"position_provided": True, "position_source": "device_reported"}})

    payload = client.get(f"/api/sessions/{session_id}").json()
    assert not any("position" in g for g in payload["capability_gap"])
    assert any("absolute acquisition time" in g for g in payload["capability_gap"])


def test_evidence_records_no_coordinate_orientation_or_time(env):
    """
    It records WHETHER a kind of information arrived. The values live on
    records, frames and spatial declarations, where they already have
    provenance.
    """
    fields = set(SessionEvidence.model_fields)
    for forbidden in ("latitude", "longitude", "easting", "heading", "elevation",
                      "timestamp", "crs", "datum", "depth", "velocity"):
        assert forbidden not in fields


# ---------------------------------------------------------------------------
# session lifecycle
# ---------------------------------------------------------------------------

def test_a_session_starts_created_with_no_evidence(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    body = new_session(client, device_id).json()["session"]

    assert body["state"] == "CREATED"
    assert body["started_at"] is None
    assert body["evidence"]["position_provided"] is False


def test_the_lifecycle_runs_created_ready_acquiring_completed(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]

    for state in ("READY", "ACQUIRING", "COMPLETED"):
        response = move(client, session_id, state)
        assert response.status_code == 200, response.text
        assert response.json()["session"]["state"] == state

    body = client.get(f"/api/sessions/{session_id}").json()["session"]
    assert body["started_at"] and body["ended_at"]


@pytest.mark.parametrize("bad", ["ACQUIRING", "COMPLETED"])
def test_a_session_cannot_skip_its_lifecycle(env, bad):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]

    response = move(client, session_id, bad)
    assert response.status_code == 409
    assert "cannot go from CREATED" in response.json()["detail"]


def test_a_terminal_session_never_reopens(env):
    """A second acquisition event is a second session."""
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "CANCELLED")

    assert move(client, session_id, "READY").status_code == 409
    assert move(client, session_id, "ACQUIRING").status_code == 409


def test_the_transition_table_has_no_route_out_of_a_terminal_state():
    for terminal in (SessionState.COMPLETED, SessionState.CANCELLED, SessionState.FAILED):
        assert ALLOWED_TRANSITIONS[terminal] == ()
        with pytest.raises(InvalidTransition):
            transition(terminal, SessionState.READY)


def test_session_state_is_not_import_job_state():
    """
    They answer different questions: one is the acquisition event, the other is
    the ingestion of what it produced.
    """
    from api import acquisition

    session_states = {s.value for s in SessionState}
    job_states = {acquisition.RECEIVED, acquisition.IDENTIFIED,
                  acquisition.NEEDS_INPUT, acquisition.REJECTED,
                  runner.QUEUED, runner.RUNNING, runner.SUCCEEDED, runner.FAILED}
    # FAILED is deliberately shared as a word; nothing else overlaps.
    assert session_states & job_states == {"FAILED"}


# ---------------------------------------------------------------------------
# failure states stay distinguishable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stage", FAILURE_STAGES)
def test_each_failure_category_is_preserved(env, stage):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]

    response = client.post(f"/api/sessions/{session_id}/fail",
                           json={"stage": stage, "message": "it did not work"})
    assert response.status_code == 200
    body = response.json()["session"]
    assert body["state"] == "FAILED"
    assert body["failure_stage"] == stage
    assert body["failure_message"] == "it did not work"


def test_an_unknown_failure_stage_is_refused(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]

    assert client.post(f"/api/sessions/{session_id}/fail",
                       json={"stage": "device error", "message": "x"}).status_code == 422


def test_ingestion_failure_is_not_a_session_failure_stage():
    """A session does not fail because a parser did; the import job owns that."""
    assert "ingestion" not in FAILURE_STAGES


# ---------------------------------------------------------------------------
# convergence with FileDrop
# ---------------------------------------------------------------------------

def test_a_session_produces_an_acquisition_through_the_same_endpoint(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "READY")

    response = acquire(client, session_id)
    assert response.status_code == 202
    job = response.json()["job"]

    assert job["session_id"] == session_id
    # The SAME identification FileDrop performs, on the same record.
    assert job["identification"]["detected_format"] == "csv"
    assert job["checksum"] == hashlib.sha256(CSV).hexdigest()


def test_a_filedrop_acquisition_has_no_session(env):
    """A file is a source in its own right, not a session with a missing device."""
    client = signed_in()
    response = client.post("/api/imports",
                           files={"file": ("a.csv", CSV, "text/csv")},
                           data={"sensor_type": "gpr", "review": "true"})
    assert response.json()["job"]["session_id"] is None


def test_a_device_acquisition_reaches_a_dataset_through_the_existing_pipeline(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "READY")
    job_id = acquire(client, session_id).json()["job"]["id"]

    client.post(f"/api/imports/jobs/{job_id}/accept")
    runner._execute(job_id)

    job = client.get(f"/api/imports/jobs/{job_id}").json()["job"]
    assert job["state"] == runner.SUCCEEDED, job.get("error_message")
    assert job["dataset_id"]

    # And the dataset is the ordinary one, with the ordinary report.
    report = client.get(f"/api/datasets/{job['dataset_id']}/report").json()
    assert len(report["readiness"]) == 8
    assert report["candidates"]["classified_object_count"] == 0


def test_the_session_lists_what_it_produced(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "READY")
    job_id = acquire(client, session_id).json()["job"]["id"]
    client.post(f"/api/imports/jobs/{job_id}/accept")
    runner._execute(job_id)

    payload = client.get(f"/api/sessions/{session_id}").json()
    assert [a["acquisition_id"] for a in payload["acquisitions"]] == [job_id]
    assert len(payload["datasets"]) == 1


def test_one_session_may_produce_several_acquisitions(env):
    """A device session is not one dataset."""
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "READY")

    acquire(client, session_id, filename="line1.csv")
    acquire(client, session_id, filename="line2.csv")

    assert len(client.get(f"/api/sessions/{session_id}").json()["acquisitions"]) == 2


def test_a_session_may_produce_no_dataset_at_all(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "READY")
    move(client, session_id, "ACQUIRING")
    client.post(f"/api/sessions/{session_id}/fail",
                json={"stage": "acquisition", "message": "the survey was abandoned"})

    payload = client.get(f"/api/sessions/{session_id}").json()
    assert payload["datasets"] == []
    assert payload["session"]["state"] == "FAILED"


def test_a_completed_session_cannot_receive_a_new_acquisition(env):
    """Attaching to a closed event would rewrite history rather than record it."""
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "READY")
    move(client, session_id, "ACQUIRING")
    move(client, session_id, "COMPLETED")

    response = acquire(client, session_id)
    assert response.status_code == 409
    assert "cannot receive an acquisition" in response.json()["detail"]


def test_an_acquisition_for_an_unknown_session_is_refused_before_any_bytes(env):
    Session, root = env
    client = signed_in()

    assert acquire(client, "no-such-session").status_code == 404
    assert [p for p in (root / "raw").rglob("*") if p.is_file()] == []


def test_there_is_no_device_specific_ingestion_path():
    """
    One pipeline. A hardware endpoint of its own would be a second one, and the
    two would drift.
    """
    from fastapi.routing import APIRoute

    upload_routes = [
        r.path for r in app.routes
        if isinstance(r, APIRoute) and "POST" in r.methods
        and ("/devices" in r.path or "/sessions" in r.path)
        and ("upload" in r.path or "ingest" in r.path or "acquisition" in r.path)
    ]
    assert upload_routes == []


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def test_a_dataset_traces_back_to_its_session_and_device(env):
    client = signed_in()
    device_id = register(client, serial_number="SN-9").json()["device"]["id"]
    session_id = new_session(client, device_id, operator="field team").json()["session"]["id"]
    move(client, session_id, "READY")
    job_id = acquire(client, session_id).json()["job"]["id"]
    client.post(f"/api/imports/jobs/{job_id}/accept")
    runner._execute(job_id)
    dataset_id = client.get(f"/api/imports/jobs/{job_id}").json()["job"]["dataset_id"]

    provenance = client.get(f"/api/datasets/{dataset_id}/acquisition").json()
    assert provenance["acquisition"]["id"] == job_id
    assert provenance["session"]["id"] == session_id
    assert provenance["session"]["operator"] == "field team"
    assert provenance["device"]["serial_number"] == "SN-9"
    assert provenance["device"]["identity_source"] == "user_declared"


def test_a_filedrop_dataset_reports_no_device(env):
    client = signed_in()
    response = client.post("/api/imports",
                           files={"file": ("a.csv", CSV, "text/csv")},
                           data={"sensor_type": "gpr"})
    job_id = response.json()["job"]["id"]
    runner._execute(job_id)
    dataset_id = client.get(f"/api/imports/jobs/{job_id}").json()["job"]["dataset_id"]

    provenance = client.get(f"/api/datasets/{dataset_id}/acquisition").json()
    assert provenance["acquisition"]["id"] == job_id
    assert provenance["session"] is None
    assert provenance["device"] is None


def test_a_simulated_device_is_visible_in_the_datasets_provenance(env):
    """
    Test data that cannot be told from measurement is the worst thing an
    acquisition layer can leak.
    """
    client = signed_in()
    device_id = register(client, kind="simulated").json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "READY")
    job_id = acquire(client, session_id).json()["job"]["id"]
    client.post(f"/api/imports/jobs/{job_id}/accept")
    runner._execute(job_id)
    dataset_id = client.get(f"/api/imports/jobs/{job_id}").json()["job"]["dataset_id"]

    provenance = client.get(f"/api/datasets/{dataset_id}/acquisition").json()
    assert provenance["device"]["is_simulated"] is True


def test_raw_device_evidence_is_preserved_unchanged(env):
    Session, root = env
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    move(client, session_id, "READY")
    acquire(client, session_id)

    stored = [p for p in (root / "raw").rglob("*") if p.is_file()]
    assert len(stored) == 1
    assert stored[0].read_bytes() == CSV


# ---------------------------------------------------------------------------
# security
# ---------------------------------------------------------------------------

def test_another_user_cannot_see_or_use_a_device_or_session(env):
    client = signed_in("owner@example.test")
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]
    intruder = signed_in("intruder@example.test")

    assert intruder.get(f"/api/devices/{device_id}").status_code == 404
    assert intruder.post(f"/api/devices/{device_id}/sessions", json={}).status_code == 404
    assert intruder.get(f"/api/sessions/{session_id}").status_code == 404
    assert move(intruder, session_id, "READY").status_code == 404
    assert intruder.post(f"/api/sessions/{session_id}/fail",
                         json={"stage": "acquisition", "message": "x"}).status_code == 404


def test_an_unauthenticated_caller_cannot_reach_devices_or_sessions(env):
    client = signed_in()
    device_id = register(client).json()["device"]["id"]
    session_id = new_session(client, device_id).json()["session"]["id"]

    anonymous = TestClient(app)
    assert anonymous.get("/api/devices").status_code == 401
    assert anonymous.post("/api/devices", json={"device_type": "gpr"}).status_code == 401
    assert anonymous.get(f"/api/sessions/{session_id}").status_code == 401


def test_a_user_only_lists_their_own_devices(env):
    other = signed_in("other@example.test")
    register(other)
    client = signed_in("me@example.test")
    register(client, manufacturer="Mine")

    listed = client.get("/api/devices").json()
    assert len(listed) == 1
    assert listed[0]["manufacturer"] == "Mine"


def test_a_session_cannot_be_created_against_another_users_device(env):
    owner = signed_in("owner@example.test")
    device_id = register(owner).json()["device"]["id"]
    intruder = signed_in("intruder@example.test")

    assert new_session(intruder, device_id).status_code == 404


# ---------------------------------------------------------------------------
# no hardware
# ---------------------------------------------------------------------------

def test_no_hardware_transport_is_implemented():
    """
    Stage 10 is an abstraction. Nothing here opens a port, speaks a protocol or
    commands an instrument.
    """
    import inspect

    from api.routes import devices as module

    source = inspect.getsource(module) + inspect.getsource(
        __import__("schemas.devices", fromlist=["x"]))
    for forbidden in ("serial.", "pyusb", "usb.core", "socket.", "bluetooth",
                      "pyserial", "/dev/tty", "COM3"):
        assert forbidden not in source


def test_no_route_claims_a_device_is_connected():
    import inspect

    from api.routes import devices as module

    source = inspect.getsource(module).lower()
    for claim in ("connected", "streaming", "live telemetry", "disconnect"):
        assert claim not in source
