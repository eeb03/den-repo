"""
`POST /api/datasets/{dataset_id}/apply_time_zero` -- the live HTTP route
wiring `preprocessing.time_zero.apply_time_zero_for_dataset` into the
platform for the first time. `tests/test_time_zero.py` covers the
algorithms and the orchestration function in isolation; this file covers
the route itself: auth, persistence, and the honest-failure responses.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import app
from database.models import Dataset
from database.session import Base, get_db
from schemas.spatial import AxisKind, CRSKind, SpatialRef, VerticalAxis
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame

pytestmark = pytest.mark.real_auth

PASSWORD = "apply-time-zero-test-password"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "data_root", tmp_path)
    for name in ("processed", "raw", "metadata"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'apply_time_zero.db'}",
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
    try:
        yield Session, tmp_path
    finally:
        app.dependency_overrides.clear()


def signed_in(email="tz-owner@example.test") -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return client


def _pulse(n=200, onset=60, amp=5000.0, noise=1.0, seed=0):
    import random
    rng = random.Random(seed)
    trace = [rng.gauss(0, noise) for _ in range(n)]
    for i in range(onset, min(onset + 15, n)):
        trace[i] += amp * (1 - abs(i - onset - 7) / 8.0)
    return trace


def _gpr_records(dataset_id, frame_id, n_traces=20, sample_interval_ns=0.5,
                 velocity_m_per_ns=0.1, onset=60):
    """The per-sample shape a real SEGYConverter ingest leaves, with a
    genuine coherent direct-wave pulse Method C can actually pick."""
    records = []
    for trace_index in range(n_traces):
        trace = _pulse(onset=onset, seed=trace_index)
        for sample_index, value in enumerate(trace):
            two_way_time_ns = sample_index * sample_interval_ns
            depth = (two_way_time_ns * velocity_m_per_ns) / 2.0
            records.append(SubterraRecord(
                dataset_id=dataset_id, sensor_type=SensorType.GPR,
                position={"kind": "none", "reason": "not surveyed"},
                frame_id=frame_id, signal=[float(value)], depth=depth,
                metadata={
                    "source_file": "line1.sgy", "trace_index": trace_index,
                    "two_way_time_ns": two_way_time_ns,
                    "velocity_m_per_ns": velocity_m_per_ns,
                },
            ))
    return records


def _gpr_frame(frame_id, dataset_id):
    return SurveyFrame(
        frame_id=frame_id, dataset_id=dataset_id, modality=SensorType.GPR,
        source_format="segy", source_file="line1.sgy",
        spatial_ref=SpatialRef(kind=CRSKind.UNKNOWN, name="none"),
        vertical_axis=VerticalAxis(
            kind=AxisKind.TWO_WAY_TIME_NS, units="ns", origin="instrument time zero",
            positive_down=True),
        n_positions=20, position_index_name="trace_index",
    )


def seed_gpr_dataset(Session, root, dataset_id="d", *, owner_id=None,
                     n_traces=20, onset=60):
    from database.frames_store import save_frames
    from database.records_store import save_records

    frame_id = f"{dataset_id}:line1"
    records = _gpr_records(dataset_id, frame_id, n_traces=n_traces, onset=onset)
    save_records(dataset_id, records)
    save_frames(dataset_id, [_gpr_frame(frame_id, dataset_id)])

    raw = root / "raw" / "line1.sgy"
    raw.write_text("raw bytes")

    session = Session()
    session.add(Dataset(
        id=dataset_id, name="Site 01", sensor_type="gpr", original_format="segy",
        record_count=len(records), quality_score=0.8, owner_id=owner_id,
        checksum="abc123", raw_path=str(raw), created_at=datetime(2026, 1, 1)))
    session.commit()
    session.close()


def own_gpr_dataset(client, Session, root, dataset_id="d", **kw):
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    seed_gpr_dataset(Session, root, dataset_id, owner_id=user_id, **kw)


# ---------------------------------------------------------------------------

def test_a_real_pulse_resolves_derived_and_is_persisted(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)

    resp = client.post("/api/datasets/d/apply_time_zero")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["frame_count"] == 1
    assert body["resolved_frame_count"] == 1
    result = body["frames"]["d:line1"]
    assert result["status"] == "derived"
    assert result["method"] == "direct_wave_consensus"
    assert result["correction_ns"] == pytest.approx(30.0, abs=1.0)  # onset=60 * 0.5ns
    assert result["applied"] is True

    from database.records_store import load_records
    records = load_records("d", use_cache=False)
    corrected = {r.metadata["corrected_time_ns"] for r in records}
    assert None not in corrected  # always set once resolved, even where excluded

    # A sample well before the pulse onset: corrected time goes negative and
    # is excluded, not clamped -- depth is None, not a fabricated shallow value.
    early = next(r for r in records if r.metadata["trace_index"] == 0
                and r.metadata["two_way_time_ns"] == pytest.approx(1.0))
    assert early.metadata["time_zero_excluded"] is True
    assert early.depth is None

    # A sample well after the onset: depth was recomputed from the CORRECTED
    # axis using the record's own existing velocity, not left at the
    # raw-time value.
    late = next(r for r in records if r.metadata["trace_index"] == 0
               and r.metadata["two_way_time_ns"] == pytest.approx(75.0))
    assert late.metadata["time_zero_excluded"] is False
    assert late.depth == pytest.approx(
        (75.0 - result["correction_ns"]) * 0.1 / 2.0, abs=1e-6)


def test_flat_traces_are_reported_inconclusive_not_a_guessed_number(env):
    Session, root = env
    client = signed_in()
    from database.frames_store import save_frames
    from database.records_store import save_records

    frame_id = "d:line1"
    records = []
    for trace_index in range(6):
        for sample_index in range(30):
            records.append(SubterraRecord(
                dataset_id="d", sensor_type=SensorType.GPR,
                position={"kind": "none", "reason": "not surveyed"},
                frame_id=frame_id, signal=[0.0], depth=sample_index * 0.05,
                metadata={
                    "source_file": "line1.sgy", "trace_index": trace_index,
                    "two_way_time_ns": sample_index * 1.0, "velocity_m_per_ns": 0.1,
                },
            ))
    save_records("d", records)
    save_frames("d", [_gpr_frame(frame_id, "d")])
    from database.models import Dataset as DatasetModel
    session = Session()
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    session.add(DatasetModel(
        id="d", name="Flat", sensor_type="gpr", original_format="segy",
        record_count=len(records), quality_score=0.8, owner_id=user_id,
        checksum="flat123", raw_path=str(root / "raw" / "line1.sgy"),
        created_at=datetime(2026, 1, 1)))
    session.commit()
    session.close()

    resp = client.post("/api/datasets/d/apply_time_zero")
    assert resp.status_code == 200, resp.text
    result = resp.json()["frames"]["d:line1"]
    assert result["status"] == "inconclusive"
    assert result["correction_ns"] is None
    assert result["applied"] is False


def test_an_explicit_velocity_override_is_honoured(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)

    resp = client.post("/api/datasets/d/apply_time_zero", params={"velocity_m_per_ns": 0.2})
    assert resp.status_code == 200, resp.text
    from database.records_store import load_records
    records = load_records("d", use_cache=False)
    with_depth = [r for r in records if r.depth is not None]
    assert with_depth  # the pulse resolved, so at least the post-onset samples got a depth
    assert all(r.metadata.get("velocity_source") == "supplied_by_caller" for r in with_depth)


def test_no_stored_records_is_a_404(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root, n_traces=0)
    resp = client.post("/api/datasets/d/apply_time_zero")
    assert resp.status_code == 404


def test_missing_dataset_is_a_404(env):
    Session, root = env
    client = signed_in()
    resp = client.post("/api/datasets/does-not-exist/apply_time_zero")
    assert resp.status_code == 404


def test_a_dataset_you_do_not_own_is_refused(env):
    Session, root = env
    seed_gpr_dataset(Session, root, dataset_id="not-mine", owner_id="someone-else")
    client = signed_in()
    resp = client.post("/api/datasets/not-mine/apply_time_zero")
    assert resp.status_code in (403, 404)
