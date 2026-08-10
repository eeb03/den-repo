"""
Dataset lifecycle: naming, status, duplicate awareness, and deletion.

WHAT THESE DEFEND. Deletion is irreversible and operates on scientific data, so
most of what follows is about what it must NOT destroy -- the raw source at the
bottom of the evidence chain, the record that an import happened -- and about
what it must not LEAVE, which is the failure this stage exists to fix: the
corpus on this machine carries 15 orphaned artifact sets totalling 167 MB
because the previous implementation deleted one database row and nothing else.

Rename is the opposite risk: it must change exactly one thing. The test that
matters is that provenance is byte-identical across it.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import dataset_lifecycle as lifecycle
from api.main import app
from database.models import Dataset, DatasetVersion, FusionSample, ImportJob, User
from database.session import Base, get_db
from schemas.spatial import GeographicPosition
from schemas.subterra_record import SensorType, SubterraRecord

pytestmark = pytest.mark.real_auth

PASSWORD = "lifecycle-test-password"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "data_root", tmp_path)
    for name in ("processed", "raw", "metadata"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'lifecycle.db'}",
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


def signed_in(email="owner@example.test") -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return client


def record(i, dataset_id="d"):
    return SubterraRecord(
        dataset_id=dataset_id, sensor_type=SensorType.GPR,
        position=GeographicPosition(lat=52.0 + i * 1e-4, lon=4.3),
        latitude=52.0 + i * 1e-4, longitude=4.3,
        frame_id=f"{dataset_id}:line1", signal=[0.1, 0.2, 0.3],
        metadata={"source_file": "line1.sgy", "trace_index": i},
    )


def seed_dataset(Session, root, dataset_id="d", *, owner_id=None, name="Site 01",
                 records=4, checksum="abc123", raw_name="line1.sgy"):
    """A dataset with a full set of on-disk artifacts, as a real ingest leaves."""
    from database.frames_store import save_frames, synthesize_frames_from_records
    from database.records_store import save_records

    rows = [record(i, dataset_id) for i in range(records)]
    save_records(dataset_id, rows)
    save_frames(dataset_id, synthesize_frames_from_records(rows))
    # The stores that only write when something uses them.
    (root / "processed" / f"{dataset_id}.labels.json").write_text('{"dataset_id": "d", "labels": []}')
    (root / "processed" / f"{dataset_id}.objects.json").write_text("[]")
    (root / "processed" / f"{dataset_id}.associations.json").write_text('{"dataset_id": "d"}')
    raw = root / "raw" / raw_name
    raw.write_text("raw bytes")

    session = Session()
    session.add(Dataset(
        id=dataset_id, name=name, sensor_type="gpr", original_format="segy",
        record_count=records, quality_score=0.8, owner_id=owner_id,
        checksum=checksum, raw_path=str(raw), created_at=datetime(2026, 1, 1)))
    session.commit()
    session.close()
    return raw


def own_dataset(client, Session, root, dataset_id="d", **kw):
    """A dataset owned by the signed-in user of `client`."""
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    return seed_dataset(Session, root, dataset_id, owner_id=user_id, **kw)


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------

def test_a_name_is_trimmed_and_kept():
    assert lifecycle.clean_dataset_name("  Site 01 GPR  ") == "Site 01 GPR"


@pytest.mark.parametrize("bad", ["", "   ", None, "x" * 201, "with\x00null", "line\nbreak"])
def test_unusable_names_are_refused(bad):
    with pytest.raises(lifecycle.InvalidDatasetName):
        lifecycle.clean_dataset_name(bad)


def test_names_are_not_required_to_be_unique():
    """
    Two datasets in the corpus are already both "INGV-UNISA Site 1 GPR v3" and
    are genuinely different ingestion events. Enforcing uniqueness would either
    reject that or mangle it.
    """
    assert lifecycle.clean_dataset_name("same") == lifecycle.clean_dataset_name("same")


def test_renaming_changes_the_name_and_nothing_else(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root, name="Original name")

    before = client.get("/api/datasets/d").json()
    response = client.patch("/api/datasets/d", json={"name": "Renamed survey"})
    assert response.status_code == 200
    after = response.json()

    assert after["name"] == "Renamed survey"
    # The id, the source file and the checksum are what everything downstream
    # is keyed on; a rename must not move any of them.
    for field in ("id", "source_file", "checksum", "record_count", "original_format"):
        assert after[field] == before[field], f"rename changed {field}"


def test_renaming_leaves_provenance_byte_identical(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root, name="Original name")

    before = client.get("/api/datasets/d/report").json()
    client.patch("/api/datasets/d", json={"name": "Renamed survey"})
    after = client.get("/api/datasets/d/report").json()

    assert before["provenance"] == after["provenance"]
    assert before["spatial"] == after["spatial"]
    assert before["identity"]["source_files"] == after["identity"]["source_files"]
    assert after["identity"]["name"] == "Renamed survey"


def test_an_invalid_name_is_refused_without_changing_anything(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root, name="Original name")

    assert client.patch("/api/datasets/d", json={"name": "   "}).status_code == 422
    assert client.get("/api/datasets/d").json()["name"] == "Original name"


def test_renaming_does_not_touch_the_records(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)

    from database.records_store import _path_for

    before = _path_for("d").read_bytes()
    client.patch("/api/datasets/d", json={"name": "Something else"})
    assert _path_for("d").read_bytes() == before


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def make_job(state, dataset_id="d", error=None):
    return ImportJob(id=f"job-{state}", state=state, dataset_id=dataset_id,
                     error_message=error, created_at=datetime(2026, 1, 1))


def test_a_dataset_with_records_and_no_job_is_ready():
    status = lifecycle.status_for(Dataset(id="d", record_count=10), None)
    assert status.value == "ready"


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING"])
def test_an_in_flight_import_wins_over_record_count(state):
    """
    A dataset being written to is not "ready" merely because an earlier import
    left rows behind.
    """
    status = lifecycle.status_for(Dataset(id="d", record_count=10), make_job(state))
    assert status.value == "importing"
    assert status.is_busy


def test_a_failed_import_with_no_records_is_failed():
    status = lifecycle.status_for(
        Dataset(id="d", record_count=0), make_job("FAILED", error="conversion failed"))
    assert status.value == "failed"
    assert "conversion failed" in status.reason


def test_a_dataset_with_no_records_and_no_job_is_empty():
    assert lifecycle.status_for(Dataset(id="d", record_count=0), None).value == "empty"


def test_the_job_state_is_carried_through_unrenamed():
    """One status vocabulary, not two: the job's own state is never reinterpreted."""
    status = lifecycle.status_for(Dataset(id="d", record_count=5), make_job("SUCCEEDED"))
    assert status.job_state == "SUCCEEDED"


def test_the_listing_reports_status_without_loading_records(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)

    rows = client.get("/api/datasets/").json()
    assert len(rows) == 1
    assert rows[0]["status"] == "ready"
    assert rows[0]["status_reason"]
    # Readiness is deliberately absent from the list: assessing it means loading
    # every record, and the list must not cost more than opening a dataset.
    assert "readiness" not in rows[0]


# ---------------------------------------------------------------------------
# duplicate awareness
# ---------------------------------------------------------------------------

def test_datasets_sharing_a_checksum_are_grouped():
    groups = lifecycle.duplicate_groups([
        Dataset(id="a", checksum="same"), Dataset(id="b", checksum="same"),
        Dataset(id="c", checksum="other"),
    ])
    assert groups == {"same": ["a", "b"]}


def test_a_dataset_with_no_checksum_is_not_grouped_with_others():
    """Two unknowns are not the same thing."""
    assert lifecycle.duplicate_groups(
        [Dataset(id="a", checksum=None), Dataset(id="b", checksum=None)]) == {}


def test_duplicate_detection_never_deletes_or_merges(env):
    """
    Identical bytes are not the same dataset. The four INGV rows share one
    checksum and are four different ingestion events under different converter
    behaviour -- one read 100 files, three read 50 -- which is provenance, not
    clutter.
    """
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root, "d1", checksum="same", name="First ingest")
    own_dataset(client, Session, root, "d2", checksum="same", name="Second ingest")

    rows = {r["id"]: r for r in client.get("/api/datasets/").json()}
    assert len(rows) == 2, "detection must not remove anything"
    assert rows["d1"]["shares_source_with"] == ["d2"]
    assert rows["d2"]["shares_source_with"] == ["d1"]
    assert rows["d1"]["name"] != rows["d2"]["name"]


def test_a_dataset_with_a_unique_source_shares_with_nothing(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root, "d1", checksum="one")
    own_dataset(client, Session, root, "d2", checksum="two")
    for row in client.get("/api/datasets/").json():
        assert row["shares_source_with"] == []


# ---------------------------------------------------------------------------
# deletion
# ---------------------------------------------------------------------------

def test_the_artifact_list_covers_every_store_that_writes_per_dataset():
    """
    The existing orphans accumulated because a store was added and nothing
    cleaned up after it. This reads the stores' own path builders rather than
    trusting a hand-written list to stay complete.
    """
    import inspect

    from database import frames_store, labels_store, objects_store, records_store

    suffixes = set()
    for module in (records_store, frames_store, labels_store, objects_store):
        source = inspect.getsource(module)
        for line in source.splitlines():
            if "processed_dir /" in line and "dataset_id" in line:
                # f"{dataset_id}.frames.json" -> ".frames.json"
                tail = line.split("dataset_id}")[1].split('"')[0]
                suffixes.add(tail)

    missing = suffixes - set(lifecycle.ARTIFACT_SUFFIXES)
    assert not missing, f"stores write artifacts that deletion does not remove: {missing}"


def test_deleting_removes_every_derived_artifact(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)

    processed = root / "processed"
    assert len(list(processed.glob("d.*"))) == 5

    response = client.delete("/api/datasets/d")
    assert response.status_code == 200
    assert list(processed.glob("d.*")) == [], "artifacts were left behind"
    assert len(response.json()["removed"]["artifacts"]) == 5


def test_deleting_never_removes_the_raw_source(env):
    """
    The bottom of the evidence chain. It cannot be regenerated, and in this
    corpus it is shared: four datasets point at one download.
    """
    Session, root = env
    client = signed_in()
    raw = own_dataset(client, Session, root)

    body = client.delete("/api/datasets/d").json()
    assert raw.exists(), "the original measurement was deleted"
    assert body["retained"]["raw_source"] == str(raw)


def test_a_shared_raw_source_survives_deleting_one_of_its_datasets(env):
    Session, root = env
    client = signed_in()
    raw = own_dataset(client, Session, root, "d1", raw_name="shared.sgy")
    own_dataset(client, Session, root, "d2", raw_name="shared.sgy")

    client.delete("/api/datasets/d1")
    assert raw.exists()
    assert client.get("/api/datasets/d2").status_code == 200


def test_deleting_keeps_the_import_job_as_a_record_of_what_happened(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)
    session = Session()
    session.add(ImportJob(id="j1", state="SUCCEEDED", dataset_id="d",
                          original_filename="line1.sgy"))
    session.commit()
    session.close()

    body = client.delete("/api/datasets/d").json()
    assert body["retained"]["import_jobs"] == 1

    session = Session()
    assert session.query(ImportJob).filter(ImportJob.id == "j1").count() == 1
    session.close()


def test_deleting_removes_fusion_samples_that_included_the_dataset(env):
    """
    Derived data, recomputable from what remains. A sample that silently
    references a dataset nobody can open is worse than no sample.
    """
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root, "d1")
    own_dataset(client, Session, root, "d2")
    session = Session()
    session.add(FusionSample(id="f1", radius_m=10.0, dataset_ids=["d1", "d2"]))
    session.add(FusionSample(id="f2", radius_m=10.0, dataset_ids=["d2"]))
    session.commit()
    session.close()

    body = client.delete("/api/datasets/d1").json()
    assert body["removed"]["fusion_samples"] == 1

    session = Session()
    remaining = {s.id for s in session.query(FusionSample).all()}
    session.close()
    assert remaining == {"f2"}, "an unrelated fusion sample was destroyed"


def test_deleting_leaves_no_reference_to_a_dataset_that_is_gone(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)
    session = Session()
    session.add(DatasetVersion(id="v1", dataset_id="d", version=1))
    session.add(FusionSample(id="f1", radius_m=10.0, dataset_ids=["d"]))
    session.commit()
    session.close()

    client.delete("/api/datasets/d")

    session = Session()
    live = {row.id for row in session.query(Dataset).all()}
    dangling = [
        s.id for s in session.query(FusionSample).all()
        if any(i not in live for i in (s.dataset_ids or []))
    ]
    versions = session.query(DatasetVersion).filter(DatasetVersion.dataset_id == "d").count()
    session.close()

    assert dangling == []
    assert versions == 0


def test_a_dataset_being_imported_cannot_be_deleted(env):
    """Removing artifacts a running job is writing would race it."""
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)
    session = Session()
    session.add(ImportJob(id="j1", state="RUNNING", dataset_id="d"))
    session.commit()
    session.close()

    response = client.delete("/api/datasets/d")
    assert response.status_code == 409
    assert "running" in response.json()["detail"]
    assert client.get("/api/datasets/d").status_code == 200


def test_a_finished_import_does_not_block_deletion(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)
    session = Session()
    session.add(ImportJob(id="j1", state="SUCCEEDED", dataset_id="d"))
    session.commit()
    session.close()

    assert client.delete("/api/datasets/d").status_code == 200


def test_deleting_twice_is_a_404_the_second_time(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)

    assert client.delete("/api/datasets/d").status_code == 200
    assert client.delete("/api/datasets/d").status_code == 404


def test_deleting_a_nonexistent_dataset_is_a_404(env):
    Session, _ = env
    client = signed_in()
    assert client.delete("/api/datasets/no-such-dataset").status_code == 404


def test_a_deleted_dataset_disappears_from_the_listing(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root, "d1")
    own_dataset(client, Session, root, "d2")

    client.delete("/api/datasets/d1")
    assert {r["id"] for r in client.get("/api/datasets/").json()} == {"d2"}


def test_a_dataset_recreated_under_the_same_id_does_not_read_the_old_records(env):
    """The parse cache is keyed on file identity; the file is gone."""
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root, records=4)
    assert client.get("/api/datasets/d/report").json()["volume"]["record_count"] == 4

    client.delete("/api/datasets/d")
    own_dataset(client, Session, root, records=7)
    assert client.get("/api/datasets/d/report").json()["volume"]["record_count"] == 7


# ---------------------------------------------------------------------------
# ownership and access control
# ---------------------------------------------------------------------------

def test_another_user_cannot_rename_or_delete_your_dataset(env):
    Session, root = env
    owner = signed_in("owner@example.test")
    own_dataset(owner, Session, root)
    intruder = signed_in("intruder@example.test")

    # 404, never 403: an id must not be probeable for existence.
    assert intruder.patch("/api/datasets/d", json={"name": "mine now"}).status_code == 404
    assert intruder.delete("/api/datasets/d").status_code == 404
    assert intruder.post("/api/datasets/d/rescore").status_code == 404

    assert owner.get("/api/datasets/d").json()["name"] == "Site 01"


def test_an_unauthenticated_caller_cannot_manage_datasets(env):
    Session, root = env
    owner = signed_in()
    own_dataset(owner, Session, root)

    anonymous = TestClient(app)
    for call in (
        lambda: anonymous.patch("/api/datasets/d", json={"name": "x"}),
        lambda: anonymous.delete("/api/datasets/d"),
        lambda: anonymous.post("/api/datasets/d/rescore"),
    ):
        assert call().status_code == 401


def test_system_reference_data_cannot_be_renamed_or_deleted(env):
    """
    Readable by everyone, writable by nobody -- a published corpus must not be
    renamed or deleted out from under every other user.
    """
    Session, root = env
    seed_dataset(Session, root, owner_id=None, name="Published corpus")
    client = signed_in()

    assert client.get("/api/datasets/d").status_code == 200
    assert client.patch("/api/datasets/d", json={"name": "mine"}).status_code == 403
    assert client.delete("/api/datasets/d").status_code == 403
    assert client.get("/api/datasets/d").json()["name"] == "Published corpus"


def test_the_listing_marks_system_datasets_so_the_ui_knows(env):
    Session, root = env
    seed_dataset(Session, root, "sys", owner_id=None, checksum="s")
    client = signed_in()
    own_dataset(client, Session, root, "mine", checksum="m")

    rows = {r["id"]: r for r in client.get("/api/datasets/").json()}
    assert rows["sys"]["is_system_dataset"] is True
    assert rows["mine"]["is_system_dataset"] is False


# ---------------------------------------------------------------------------
# rescore: the safe half of "stale"
# ---------------------------------------------------------------------------

def test_rescore_corrects_a_stale_score_without_touching_the_records(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)

    session = Session()
    session.query(Dataset).filter(Dataset.id == "d").update({"quality_score": 0.30})
    session.commit()
    session.close()

    assert client.get("/api/datasets/d/report").json()["quality"]["score_is_stale"] is True

    from database.records_store import _path_for

    before = _path_for("d").read_bytes()
    response = client.post("/api/datasets/d/rescore")
    assert response.status_code == 200
    assert response.json()["previous_quality_score"] == 0.30
    assert _path_for("d").read_bytes() == before, "rescore modified the records"

    assert client.get("/api/datasets/d/report").json()["quality"]["score_is_stale"] is False


def test_rescore_is_idempotent(env):
    Session, root = env
    client = signed_in()
    own_dataset(client, Session, root)

    first = client.post("/api/datasets/d/rescore").json()["quality_score"]
    second = client.post("/api/datasets/d/rescore").json()["quality_score"]
    assert first == second


def test_rescore_is_not_reprocess(env):
    """
    `reprocess` runs the preprocessing pipeline and saves the result back --
    dewow, gain, normalisation. Using it to fix a number ABOUT the data would
    change the data. This endpoint must not.
    """
    import inspect

    from api.routes import datasets as module

    source = inspect.getsource(module.rescore_dataset)
    for forbidden in ("run_pipeline", "save_records", "save_frames"):
        assert forbidden not in source


def test_rescore_refuses_a_dataset_with_no_records(env):
    Session, root = env
    client = signed_in()
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    session = Session()
    session.add(Dataset(id="empty", name="Empty", sensor_type="gpr",
                        original_format="segy", record_count=0, owner_id=user_id))
    session.commit()
    session.close()

    assert client.post("/api/datasets/empty/rescore").status_code == 400
