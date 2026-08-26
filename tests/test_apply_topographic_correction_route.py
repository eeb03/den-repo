"""
`POST /api/datasets/{dataset_id}/apply_topographic_correction` -- the live
HTTP route wiring `preprocessing.topographic_correction.
apply_topographic_correction_for_dataset` into the platform for the first
time. `tests/test_topographic_correction.py` covers the algorithm and the
orchestration function in isolation; this file covers the route itself:
auth, persistence, and the honest-failure responses. Mirrors
`tests/test_apply_time_zero_route.py`'s own structure and fixtures.
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

PASSWORD = "apply-topo-correction-test-password"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "data_root", tmp_path)
    for name in ("processed", "raw", "metadata"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'apply_topo.db'}",
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


def signed_in(email="topo-owner@example.test") -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return client


def _dem_aligned_records(dataset_id, frame_id, ground_elevation_m, pre_dem_elevation_m,
                         n_samples=10, sample_interval_ns=0.5):
    """
    The per-sample shape a real ingest + `/align_dem` leaves: `elevation`
    holds the DEM's ground elevation, `metadata["pre_dem_elevation_m"]`
    holds the antenna's own reading from before that overwrite -- exactly
    what the DEM-alignment fix in `preprocessing.dem_alignment` preserves.
    """
    records = []
    for trace_index, ground_elev in ground_elevation_m.items():
        for sample_index in range(n_samples):
            two_way_time_ns = sample_index * sample_interval_ns
            records.append(SubterraRecord(
                dataset_id=dataset_id, sensor_type=SensorType.GPR,
                position={"kind": "none", "reason": "not surveyed"},
                frame_id=frame_id, elevation=ground_elev, signal=[0.0],
                depth=sample_index * 0.05,
                metadata={
                    "source_file": "line1.sgy", "trace_index": trace_index,
                    "two_way_time_ns": two_way_time_ns,
                    "corrected_time_ns": two_way_time_ns,  # as if time-zero already ran
                    "pre_dem_elevation_m": pre_dem_elevation_m[trace_index],
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
        n_positions=1, position_index_name="trace_index",
    )


def seed_dataset(Session, root, dataset_id, records, *, owner_id=None):
    from database.frames_store import save_frames
    from database.records_store import save_records

    frame_id = f"{dataset_id}:line1"
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


def own_dem_aligned_dataset(client, Session, root, dataset_id="d",
                            ground_elevation_m=None, pre_dem_elevation_m=None):
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    frame_id = f"{dataset_id}:line1"
    records = _dem_aligned_records(dataset_id, frame_id, ground_elevation_m, pre_dem_elevation_m)
    seed_dataset(Session, root, dataset_id, records, owner_id=user_id)


# ---------------------------------------------------------------------------

def test_a_material_topographic_variation_resolves_derived_and_is_persisted(env):
    Session, root = env
    client = signed_in()
    own_dem_aligned_dataset(
        client, Session, root,
        ground_elevation_m={0: 10.0, 1: 10.0, 2: 10.0},
        pre_dem_elevation_m={0: 20.0, 1: 20.5, 2: 19.5},  # +-0.5 m deviation
    )

    resp = client.post("/api/datasets/d/apply_topographic_correction")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["frame_count"] == 1
    assert body["material_frame_count"] == 1
    result = body["frames"]["d:line1"]
    assert result["status"] == "derived"
    assert result["method"] == "dem_antenna_differential"
    assert result["applied"] is True

    from database.records_store import load_records
    records = load_records("d", use_cache=False)
    by_trace = {r.metadata["trace_index"]: r for r in records
               if r.metadata["two_way_time_ns"] == 0.0}
    assert by_trace[0].metadata["topographic_corrected_time_ns"] is not None
    assert (by_trace[1].metadata["topographic_corrected_time_ns"]
           != by_trace[2].metadata["topographic_corrected_time_ns"])
    # the time-zero-corrected axis this refines is never overwritten
    assert by_trace[0].metadata["corrected_time_ns"] == 0.0


def test_a_terrain_following_line_is_not_material_and_persists_no_correction(env):
    Session, root = env
    client = signed_in()
    own_dem_aligned_dataset(
        client, Session, root,
        ground_elevation_m={0: 10.0, 1: 11.0, 2: 12.0},
        pre_dem_elevation_m={0: 20.0, 1: 21.0, 2: 22.0},  # constant height-above-ground
    )

    resp = client.post("/api/datasets/d/apply_topographic_correction")
    assert resp.status_code == 200, resp.text
    result = resp.json()["frames"]["d:line1"]
    assert result["status"] == "not_material"
    assert result["applied"] is False

    from database.records_store import load_records
    records = load_records("d", use_cache=False)
    assert all(r.metadata["topographic_corrected_time_ns"] is None for r in records)


def test_a_dataset_never_dem_aligned_reports_unavailable_not_a_500(env):
    Session, root = env
    client = signed_in()
    frame_id = "d:line1"
    records = []
    for trace_index in range(3):
        for sample_index in range(10):
            records.append(SubterraRecord(
                dataset_id="d", sensor_type=SensorType.GPR,
                position={"kind": "none", "reason": "not surveyed"},
                frame_id=frame_id, elevation=None, signal=[0.0],
                depth=sample_index * 0.05,
                metadata={
                    "source_file": "line1.sgy", "trace_index": trace_index,
                    "two_way_time_ns": sample_index * 0.5,
                },
            ))
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    seed_dataset(Session, root, "d", records, owner_id=user_id)

    resp = client.post("/api/datasets/d/apply_topographic_correction")
    assert resp.status_code == 200, resp.text
    result = resp.json()["frames"]["d:line1"]
    assert result["status"] == "unavailable"


def test_no_stored_records_is_a_404(env):
    Session, root = env
    client = signed_in()
    own_dem_aligned_dataset(client, Session, root, ground_elevation_m={}, pre_dem_elevation_m={})
    resp = client.post("/api/datasets/d/apply_topographic_correction")
    assert resp.status_code == 404


def test_missing_dataset_is_a_404(env):
    Session, root = env
    client = signed_in()
    resp = client.post("/api/datasets/does-not-exist/apply_topographic_correction")
    assert resp.status_code == 404


def test_a_dataset_you_do_not_own_is_refused(env):
    Session, root = env
    frame_id = "not-mine:line1"
    records = _dem_aligned_records(
        "not-mine", frame_id, {0: 10.0, 1: 10.0}, {0: 20.0, 1: 20.5})
    seed_dataset(Session, root, "not-mine", records, owner_id="someone-else")
    client = signed_in()
    resp = client.post("/api/datasets/not-mine/apply_topographic_correction")
    assert resp.status_code in (403, 404)
