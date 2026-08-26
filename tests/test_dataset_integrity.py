"""
Dataset integrity signing: `security.dataset_integrity` (the crypto),
`database.integrity_store` (the file-per-dataset store, mirroring
`reviews_store.py`), and the live routes --
`POST /{id}/sign_integrity`, `GET /{id}/verify_integrity`,
`GET /api/integrity/public_key`.

WHAT THIS PROVES AND DOES NOT. A verified signature means these exact
stored bytes are what this deployment's own key last signed -- it is
never treated here as evidence the underlying measurement is correct,
independently verified, or Grade A/B (tests explicitly check the module
never conflates the two).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import app
from database.models import Dataset
from database.session import Base, get_db
from schemas.subterra_record import SensorType, SubterraRecord
from security.dataset_integrity import (
    IntegritySignature,
    SigningUnavailable,
    dataset_digest,
    generate_signing_key,
    public_key_b64,
    sign_dataset,
    verify_dataset,
)

pytestmark = pytest.mark.real_auth

PASSWORD = "dataset-integrity-test-password"


# ---------------------------------------------------------------------------
# 1. security.dataset_integrity -- the crypto, in isolation
# ---------------------------------------------------------------------------

class TestSigningUnavailable:
    def test_signing_with_no_key_configured_raises_a_named_error(self, tmp_path):
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')
        with pytest.raises(SigningUnavailable):
            sign_dataset("d", records_path, None, "")


class TestDigest:
    def test_the_same_bytes_always_produce_the_same_digest(self, tmp_path):
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')
        assert dataset_digest(records_path, None) == dataset_digest(records_path, None)

    def test_different_bytes_produce_a_different_digest(self, tmp_path):
        a = tmp_path / "a.jsonl"
        b = tmp_path / "b.jsonl"
        a.write_text('{"a": 1}\n')
        b.write_text('{"a": 2}\n')
        assert dataset_digest(a, None) != dataset_digest(b, None)

    def test_a_missing_frames_file_is_a_distinct_stable_case(self, tmp_path):
        """A dataset with no frames file (predates frame coverage) must not collide with one that has an empty/different frames file."""
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')
        no_frames = dataset_digest(records_path, tmp_path / "does_not_exist.frames.json")
        again = dataset_digest(records_path, tmp_path / "does_not_exist.frames.json")
        assert no_frames == again

        frames_path = tmp_path / "d.frames.json"
        frames_path.write_text("[]")
        with_frames = dataset_digest(records_path, frames_path)
        assert with_frames != no_frames

    def test_changing_the_frames_file_changes_the_digest_even_if_records_are_unchanged(self, tmp_path):
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')
        frames_path = tmp_path / "d.frames.json"
        frames_path.write_text("[]")
        before = dataset_digest(records_path, frames_path)
        frames_path.write_text('[{"frame_id": "x"}]')
        after = dataset_digest(records_path, frames_path)
        assert before != after


class TestSignAndVerifyRoundTrip:
    def test_a_fresh_signature_verifies_against_the_records_it_was_signed_over(self, tmp_path):
        key = generate_signing_key()
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')

        signature = sign_dataset("d", records_path, None, key)
        verified, reason = verify_dataset(records_path, None, signature)

        assert verified is True
        assert "verifies" in reason

    def test_a_record_change_after_signing_fails_verification_with_a_digest_mismatch_reason(self, tmp_path):
        key = generate_signing_key()
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')
        signature = sign_dataset("d", records_path, None, key)

        records_path.write_text('{"a": 999}\n')  # tampered / reprocessed / corrupted -- indistinguishable, by design
        verified, reason = verify_dataset(records_path, None, signature)

        assert verified is False
        assert "no longer match what was signed" in reason

    def test_a_forged_signature_fails_verification_with_a_different_reason(self, tmp_path):
        """Digest matches (nobody touched the data) but the signature bytes themselves are wrong -- a distinct failure mode from a digest mismatch."""
        key = generate_signing_key()
        other_key = generate_signing_key()
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')

        real = sign_dataset("d", records_path, None, key)
        forged = IntegritySignature(
            dataset_id="d", digest_sha256=real.digest_sha256,
            signature_b64=real.signature_b64,  # a real signature, but from the WRONG key
            public_key_b64=public_key_b64(other_key),
            algorithm=real.algorithm, signed_at=real.signed_at,
        )
        verified, reason = verify_dataset(records_path, None, forged)

        assert verified is False
        assert "does not verify against it" in reason

    def test_two_different_datasets_signed_with_the_same_key_produce_different_signatures(self, tmp_path):
        key = generate_signing_key()
        a = tmp_path / "a.jsonl"
        b = tmp_path / "b.jsonl"
        a.write_text('{"a": 1}\n')
        b.write_text('{"b": 2}\n')

        sig_a = sign_dataset("a", a, None, key)
        sig_b = sign_dataset("b", b, None, key)

        assert sig_a.digest_sha256 != sig_b.digest_sha256
        assert sig_a.signature_b64 != sig_b.signature_b64


class TestSerialization:
    def test_round_trips_through_dict(self, tmp_path):
        key = generate_signing_key()
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')
        signature = sign_dataset("d", records_path, None, key)

        restored = IntegritySignature.from_dict(signature.to_dict())

        assert restored == signature


# ---------------------------------------------------------------------------
# 2. database.integrity_store -- the file-per-dataset store
# ---------------------------------------------------------------------------

class TestIntegrityStore:
    def test_an_unsigned_dataset_loads_as_none_not_a_fabricated_signature(self, tmp_path, monkeypatch):
        from configs.settings import settings
        from database.integrity_store import load_integrity

        monkeypatch.setattr(settings, "data_root", tmp_path)
        (tmp_path / "processed").mkdir()

        assert load_integrity("never-signed") is None

    def test_save_then_load_round_trips(self, tmp_path, monkeypatch):
        from configs.settings import settings
        from database.integrity_store import load_integrity, save_integrity

        monkeypatch.setattr(settings, "data_root", tmp_path)
        (tmp_path / "processed").mkdir()

        key = generate_signing_key()
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')
        signature = sign_dataset("d", records_path, None, key)

        save_integrity(signature)
        loaded = load_integrity("d")

        assert loaded == signature

    def test_delete_removes_the_file(self, tmp_path, monkeypatch):
        from configs.settings import settings
        from database.integrity_store import delete_integrity, load_integrity, save_integrity

        monkeypatch.setattr(settings, "data_root", tmp_path)
        (tmp_path / "processed").mkdir()

        key = generate_signing_key()
        records_path = tmp_path / "d.jsonl"
        records_path.write_text('{"a": 1}\n')
        save_integrity(sign_dataset("d", records_path, None, key))

        assert delete_integrity("d") is True
        assert load_integrity("d") is None
        assert delete_integrity("d") is False  # already gone


# ---------------------------------------------------------------------------
# shared HTTP fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "data_root", tmp_path)
    monkeypatch.setattr(settings, "integrity_signing_private_key", generate_signing_key())
    for name in ("processed", "raw", "metadata"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'integrity.db'}",
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


def signed_in(email="integrity-owner@example.test") -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return client


def seed_dataset(Session, root, dataset_id="d", *, owner_id=None):
    from database.frames_store import save_frames
    from database.records_store import save_records
    from datetime import datetime

    records = [SubterraRecord(
        dataset_id=dataset_id, sensor_type=SensorType.GPR,
        position={"kind": "none", "reason": "not surveyed"},
        signal=[1.0, 2.0], depth=0.5, metadata={"trace_index": 0},
    )]
    save_records(dataset_id, records)
    save_frames(dataset_id, [])

    raw = root / "raw" / "line.sgy"
    raw.write_text("raw bytes")

    session = Session()
    session.add(Dataset(
        id=dataset_id, name="Test", sensor_type="gpr", original_format="segy",
        record_count=len(records), quality_score=0.8, owner_id=owner_id,
        checksum="abc123", raw_path=str(raw), created_at=datetime(2026, 1, 1)))
    session.commit()
    session.close()


def own_dataset(client, Session, root, dataset_id="d"):
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    seed_dataset(Session, root, dataset_id, owner_id=user_id)


# ---------------------------------------------------------------------------
# 3. POST /{id}/sign_integrity
# ---------------------------------------------------------------------------

class TestSignIntegrityRoute:
    def test_signs_a_real_dataset_and_returns_the_signature(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)

        resp = client.post("/api/datasets/d/sign_integrity")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dataset_id"] == "d"
        assert body["algorithm"] == "ed25519"
        assert body["digest_sha256"]
        assert body["signature_b64"]
        assert body["public_key_b64"]

        from database.integrity_store import load_integrity
        assert load_integrity("d") is not None

    def test_no_stored_records_is_a_404(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)
        from database.records_store import _path_for
        _path_for("d").unlink()

        resp = client.post("/api/datasets/d/sign_integrity")
        assert resp.status_code == 404

    def test_missing_dataset_is_a_404(self, env):
        client = signed_in()
        resp = client.post("/api/datasets/does-not-exist/sign_integrity")
        assert resp.status_code == 404

    def test_a_dataset_you_do_not_own_is_refused(self, env):
        Session, root = env
        seed_dataset(Session, root, "not-mine", owner_id="someone-else")
        client = signed_in()
        resp = client.post("/api/datasets/not-mine/sign_integrity")
        assert resp.status_code in (403, 404)

    def test_signing_is_unavailable_when_no_key_is_configured(self, env, monkeypatch):
        from configs.settings import settings

        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)
        monkeypatch.setattr(settings, "integrity_signing_private_key", "")

        resp = client.post("/api/datasets/d/sign_integrity")
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]

    def test_resigning_after_a_real_change_produces_a_different_digest(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)

        first = client.post("/api/datasets/d/sign_integrity").json()

        from database.records_store import load_records, save_records
        records = load_records("d", use_cache=False)
        records[0].metadata["reprocessed"] = True
        save_records("d", records)

        second = client.post("/api/datasets/d/sign_integrity").json()
        assert second["digest_sha256"] != first["digest_sha256"]


# ---------------------------------------------------------------------------
# 4. GET /{id}/verify_integrity
# ---------------------------------------------------------------------------

class TestVerifyIntegrityRoute:
    def test_an_unsigned_dataset_reports_signed_false_not_an_error(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)

        resp = client.get("/api/datasets/d/verify_integrity")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["signed"] is False
        assert body["verified"] is None
        assert "never been signed" in body["reason"]

    def test_a_signed_unchanged_dataset_verifies(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)
        client.post("/api/datasets/d/sign_integrity")

        resp = client.get("/api/datasets/d/verify_integrity")
        body = resp.json()
        assert body["signed"] is True
        assert body["verified"] is True

    def test_a_signed_then_modified_dataset_fails_verification_honestly(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)
        client.post("/api/datasets/d/sign_integrity")

        from database.records_store import load_records, save_records
        records = load_records("d", use_cache=False)
        records[0].metadata["tampered"] = True
        save_records("d", records)

        resp = client.get("/api/datasets/d/verify_integrity")
        body = resp.json()
        assert body["signed"] is True
        assert body["verified"] is False
        assert "no longer match" in body["reason"]

    def test_missing_dataset_records_after_signing_is_a_404(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)
        client.post("/api/datasets/d/sign_integrity")

        from database.records_store import _path_for
        _path_for("d").unlink()

        resp = client.get("/api/datasets/d/verify_integrity")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. GET /api/integrity/public_key
# ---------------------------------------------------------------------------

class TestPublicKeyRoute:
    def test_reports_available_with_a_real_public_key_when_configured(self, env):
        client = signed_in()  # no special auth needed, but a client is convenient
        resp = client.get("/api/integrity/public_key")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["available"] is True
        assert body["algorithm"] == "ed25519"
        assert body["public_key_b64"]

    def test_reports_unavailable_honestly_when_not_configured(self, env, monkeypatch):
        from configs.settings import settings
        monkeypatch.setattr(settings, "integrity_signing_private_key", "")
        client = TestClient(app)
        resp = client.get("/api/integrity/public_key")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert "not configured" in body["reason"]

    def test_needs_no_authentication(self, env):
        client = TestClient(app)  # never registered/signed in
        resp = client.get("/api/integrity/public_key")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6. Signature does not become validation -- honesty checks
# ---------------------------------------------------------------------------

class TestSignatureNeverImpliesPhysicalValidation:
    def test_verified_response_never_claims_ground_truth_or_grade(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)
        client.post("/api/datasets/d/sign_integrity")

        body = client.get("/api/datasets/d/verify_integrity").json()
        blob = str(body).lower()
        for forbidden in ("ground truth", "grade a", "grade b", "independently validated"):
            assert forbidden not in blob


# ---------------------------------------------------------------------------
# 7. Cleanup on dataset deletion
# ---------------------------------------------------------------------------

class TestPathHelpersMatchTheRealStores:
    """
    api.routes.datasets._records_path/_frames_path duplicate
    records_store/frames_store's own path convention rather than
    importing their private `_path_for` -- this pins that duplication so
    a change to either store's real path is caught here, not discovered
    live via a digest that silently hashes the wrong (nonexistent) file.
    """

    def test_records_path_matches_the_real_store(self):
        from api.routes.datasets import _records_path
        from database.records_store import _path_for

        assert _records_path("some-id") == _path_for("some-id")

    def test_frames_path_matches_the_real_store(self):
        from api.routes.datasets import _frames_path
        from database.frames_store import _path_for

        assert _frames_path("some-id") == _path_for("some-id")


class TestDeletionCleanup:
    def test_deleting_a_dataset_removes_its_integrity_signature(self, env):
        Session, root = env
        client = signed_in()
        own_dataset(client, Session, root)
        client.post("/api/datasets/d/sign_integrity")

        integrity_path = root / "processed" / "d.integrity.json"
        assert integrity_path.exists()

        resp = client.delete("/api/datasets/d")
        assert resp.status_code == 200, resp.text
        assert not integrity_path.exists()
