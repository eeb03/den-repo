"""
`POST /api/datasets/ingest` cannot be made to write outside its directory.

This endpoint predates the async import path and had a real traversal bug: it
wrote to `settings.raw_dir / file.filename` with the client's filename
unmodified, so `../../../etc/evil.csv` escaped the raw directory and a repeated
name silently overwrote an earlier upload. It had no test coverage at all, which
is how it survived.

These tests are the coverage it lacked. They assert the property rather than the
implementation: whatever the client calls its file, the bytes must land inside
the raw directory and must not displace anything already there.
"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from database.session import Base, get_db

CSV = b"latitude,longitude,depth,signal\n41.0,15.0,0.5,1.0\n41.001,15.001,0.5,2.0\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from configs import settings as settings_mod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(settings_mod.settings, "data_root", tmp_path)
    for sub in ("raw", "processed"):
        (tmp_path / sub).mkdir(exist_ok=True)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    try:
        yield TestClient(app), tmp_path, Session
    finally:
        app.dependency_overrides.clear()


def _ingest(api, filename, body=CSV):
    return api.post(
        "/api/datasets/ingest",
        files={"file": (filename, io.BytesIO(body), "application/octet-stream")},
        data={"sensor_type": "gpr"},
    )


def _raw_path_of(Session, dataset_id) -> Path:
    from database.models import Dataset

    with Session() as s:
        row = s.query(Dataset).filter(Dataset.id == dataset_id).first()
        return Path(row.raw_path)


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../etc/evil.csv",
        "../../evil.csv",
        "/etc/evil.csv",                      # absolute
        "/absolute/nested/path/line.csv",     # absolute, nested
        "nested/dir/line.csv",                # nested relative
        "..\\..\\windows\\system32\\evil.csv",  # windows separators
        "....//....//evil.csv",               # doubled-up traversal
    ],
)
def test_a_hostile_filename_cannot_escape_the_raw_directory(client, hostile):
    api, tmp_path, Session = client
    response = _ingest(api, hostile)
    assert response.status_code == 200, response.text

    stored = _raw_path_of(Session, response.json()["dataset_id"]).resolve()
    raw_root = (tmp_path / "raw").resolve()

    assert raw_root in stored.parents, f"{stored} escaped {raw_root}"
    assert ".." not in stored.parts
    assert stored.is_file()
    # and nothing was written outside the data root at all
    assert tmp_path.resolve() in stored.parents


def test_a_normal_filename_still_works_and_keeps_its_extension(client):
    api, _, Session = client
    response = _ingest(api, "line1.csv")
    assert response.status_code == 200

    stored = _raw_path_of(Session, response.json()["dataset_id"])
    # the extension must survive: the converter registry dispatches on it
    assert stored.suffix == ".csv"
    assert stored.name == "line1.csv"


def test_the_original_filename_survives_as_the_dataset_name_not_as_a_path(client):
    """A hostile name is safe to DISPLAY; it is only unsafe as a path."""
    api, _, Session = client
    from database.models import Dataset

    response = _ingest(api, "../../../etc/evil.csv")
    dataset_id = response.json()["dataset_id"]

    with Session() as s:
        row = s.query(Dataset).filter(Dataset.id == dataset_id).first()
        assert row.name == "../../../etc/evil.csv"      # metadata, verbatim
    assert ".." not in _raw_path_of(Session, dataset_id).parts  # path, sanitised


def test_two_uploads_of_the_same_name_do_not_overwrite_each_other(client):
    api, _, Session = client
    first = _ingest(api, "line1.csv", CSV).json()["dataset_id"]
    second = _ingest(
        api, "line1.csv", CSV + b"41.002,15.002,0.5,3.0\n"
    ).json()["dataset_id"]

    a, b = _raw_path_of(Session, first), _raw_path_of(Session, second)
    assert a != b
    assert a.read_bytes() != b.read_bytes()
    assert a.is_file() and b.is_file()          # neither was displaced


def test_an_empty_upload_is_refused_rather_than_stored(client):
    api, tmp_path, _ = client
    response = _ingest(api, "empty.csv", b"")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_nothing_is_written_above_the_raw_directory(client):
    """A belt-and-braces sweep: no stray file anywhere outside raw/."""
    api, tmp_path, _ = client
    for name in ("../../../etc/evil.csv", "/etc/passwd.csv", "line1.csv"):
        _ingest(api, name)

    strays = [
        p
        for p in tmp_path.rglob("*.csv")
        if (tmp_path / "raw").resolve() not in p.resolve().parents
    ]
    assert strays == [], f"files written outside raw/: {strays}"


def test_the_endpoint_still_produces_a_usable_dataset(client):
    """The security fix must not change what ingestion produces."""
    api, _, _ = client
    body = _ingest(api, "line1.csv").json()

    assert body["record_count"] == 2
    assert body["preprocessing_applied"] is True
    assert isinstance(body["quality_score"], float)
    assert body["dataset_id"]
