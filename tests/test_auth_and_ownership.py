"""
Authentication, and the isolation boundary it exists to create.

The tests that matter most here are the CROSS-USER ones. Authentication that
works is easy; the failure that ships is a route somebody forgot to scope, so
this file builds two real users with real datasets and then tries, from each
side, to reach the other's data by every route that takes an id.

`test_every_dataset_route_is_authorised` is the one that keeps working after
this commit: it enumerates the live app's routes and fails if a NEW one appears
without authorisation, which no hand-written list of endpoints could do.
"""
import io

import pytest

#: Every test in this file runs against the REAL authentication stack --
#: conftest's default identity override is skipped for `real_auth`. Without
#: this the suite would be testing a bypass.
pytestmark = pytest.mark.real_auth
from fastapi.testclient import TestClient

from api.main import app
from auth import passwords
from database.models import Dataset, ImportJob, User, UserSession
from database.session import Base, get_db

CSV = b"latitude,longitude,depth,signal\n41.0,15.0,0.5,1.0\n41.001,15.001,0.5,2.0\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from configs import settings as settings_mod
    from jobs import runner

    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(settings_mod.settings, "data_root", tmp_path)
    for sub in ("raw", "processed"):
        (tmp_path / sub).mkdir(exist_ok=True)

    def _get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    from contextlib import contextmanager

    @contextmanager
    def _get_session():
        s = Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(runner, "get_session", _get_session)
    # Drive the worker explicitly so assertions never race a thread.
    submitted: list[str] = []
    import api.routes.imports as imports_mod

    monkeypatch.setattr(imports_mod.runner, "submit", submitted.append)

    app.dependency_overrides[get_db] = _get_db
    try:
        yield Session, submitted
    finally:
        app.dependency_overrides.clear()


def _client() -> TestClient:
    """A separate client per user: each keeps its own cookie jar."""
    return TestClient(app)


def _register(client, email, password="correct-horse-battery"):
    return client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )


def _seed_dataset(Session, owner_id, name="ds"):
    from database.models import gen_uuid

    did = gen_uuid()
    with Session() as s:
        s.add(
            Dataset(
                id=did, name=name, sensor_type="gpr",
                original_format="csv", owner_id=owner_id,
            )
        )
        s.commit()
    return did


# --------------------------------------------------------------------------
# authentication
# --------------------------------------------------------------------------

def test_register_creates_an_account_and_signs_it_in(env):
    c = _client()
    r = _register(c, "a@example.test")
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "a@example.test"
    assert "password" not in r.text and "hash" not in r.text
    # the session cookie was set, so /me works immediately
    assert c.get("/api/auth/me").json()["user"]["email"] == "a@example.test"


def test_the_password_is_never_stored_in_the_clear(env):
    Session, _ = env
    c = _client()
    _register(c, "a@example.test", "correct-horse-battery")
    with Session() as s:
        user = s.query(User).one()
    assert user.password_hash and "correct-horse-battery" not in user.password_hash
    assert user.password_hash.startswith("pbkdf2_sha256$")
    assert passwords.verify_password("correct-horse-battery", user.password_hash)


def test_duplicate_registration_is_refused(env):
    c = _client()
    assert _register(c, "a@example.test").status_code == 201
    again = _register(_client(), "a@example.test")
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


@pytest.mark.parametrize("email", ["", "not-an-email", "a@b", "@example.test"])
def test_malformed_identity_is_refused(env, email):
    assert _register(_client(), email).status_code == 422


def test_a_short_password_is_refused(env):
    r = _client().post("/api/auth/register", json={"email": "a@example.test", "password": "short"})
    assert r.status_code == 422
    assert "at least" in r.json()["detail"]


def test_login_succeeds_and_issues_a_session(env):
    _register(_client(), "a@example.test")
    c = _client()
    r = c.post("/api/auth/login", json={"email": "a@example.test", "password": "correct-horse-battery"})
    assert r.status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_login_failure_does_not_reveal_whether_the_account_exists(env):
    _register(_client(), "a@example.test")

    wrong_password = _client().post(
        "/api/auth/login", json={"email": "a@example.test", "password": "wrong-password-here"}
    )
    no_account = _client().post(
        "/api/auth/login", json={"email": "nobody@example.test", "password": "wrong-password-here"}
    )

    assert wrong_password.status_code == no_account.status_code == 401
    assert wrong_password.json()["detail"] == no_account.json()["detail"]
    assert "invalid email or password" in wrong_password.json()["detail"]


def test_logout_revokes_the_session_server_side(env):
    Session, _ = env
    c = _client()
    _register(c, "a@example.test")
    assert c.get("/api/auth/me").status_code == 200

    assert c.post("/api/auth/logout").status_code == 200

    with Session() as s:
        assert s.query(UserSession).one().revoked_at is not None
    assert c.get("/api/auth/me").status_code == 401


def test_a_revoked_session_cannot_be_replayed(env):
    """Clearing the cookie is not enough; the token itself must die."""
    Session, _ = env
    c = _client()
    _register(c, "a@example.test")
    token = c.cookies.get("subterra_session")
    c.post("/api/auth/logout")

    replay = _client()
    replay.cookies.set("subterra_session", token)
    assert replay.get("/api/auth/me").status_code == 401


def test_an_expired_session_is_rejected(env):
    from datetime import datetime, timedelta

    Session, _ = env
    c = _client()
    _register(c, "a@example.test")
    with Session() as s:
        row = s.query(UserSession).one()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        s.commit()
    assert c.get("/api/auth/me").status_code == 401


def test_an_invalid_or_missing_cookie_is_rejected(env):
    assert _client().get("/api/auth/me").status_code == 401
    forged = _client()
    forged.cookies.set("subterra_session", "not-a-real-token")
    assert forged.get("/api/auth/me").status_code == 401


def test_only_a_hash_of_the_token_is_stored(env):
    Session, _ = env
    c = _client()
    _register(c, "a@example.test")
    token = c.cookies.get("subterra_session")
    with Session() as s:
        stored = s.query(UserSession).one().token_hash
    assert token not in stored
    assert len(stored) == 64  # sha256 hex


# --------------------------------------------------------------------------
# the isolation boundary
# --------------------------------------------------------------------------

@pytest.fixture
def two_users(env):
    Session, _ = env
    a, b = _client(), _client()
    _register(a, "a@example.test")
    _register(b, "b@example.test")
    with Session() as s:
        ids = {u.email: u.id for u in s.query(User).all()}
    ds_a = _seed_dataset(Session, ids["a@example.test"], "A's survey")
    ds_b = _seed_dataset(Session, ids["b@example.test"], "B's survey")
    system = _seed_dataset(Session, None, "system reference corpus")
    return a, b, ds_a, ds_b, system


def test_each_user_lists_only_their_own_datasets_plus_system_data(two_users):
    a, b, ds_a, ds_b, system = two_users

    a_ids = {d["id"] for d in a.get("/api/datasets/").json()}
    b_ids = {d["id"] for d in b.get("/api/datasets/").json()}

    assert ds_a in a_ids and ds_b not in a_ids
    assert ds_b in b_ids and ds_a not in b_ids
    # unowned reference data is visible to both, by design
    assert system in a_ids and system in b_ids


ID_ROUTES = [
    "/api/datasets/{id}",
    "/api/datasets/{id}/info",
    "/api/datasets/{id}/report",
    "/api/datasets/{id}/acquisition",
    "/api/datasets/{id}/points",
    "/api/datasets/{id}/depths",
    "/api/datasets/{id}/grid",
    "/api/datasets/{id}/trace_grid",
    "/api/spatial/{id}",
    "/api/spatial/{id}/declarations",
    "/api/provenance/{id}/frames",
    "/api/provenance/{id}/records",
    "/api/overlays/{id}/layers",
    "/api/labels/{id}",
    "/api/objects/{id}",
    "/api/objects/{id}/associations",
    "/api/exports/{id}/objects",
    "/api/training/{id}/detect_objects",
]


@pytest.mark.parametrize("route", ID_ROUTES)
def test_a_user_cannot_reach_another_users_dataset_by_id(two_users, route):
    a, b, ds_a, ds_b, _ = two_users
    # A asking for B's dataset must look exactly like asking for one that does
    # not exist: 404, never 403, so ids cannot be probed for existence.
    assert a.get(route.format(id=ds_b)).status_code == 404
    assert b.get(route.format(id=ds_a)).status_code == 404


@pytest.mark.parametrize("route", ID_ROUTES)
def test_the_owner_is_not_locked_out_of_their_own_dataset(two_users, route):
    a, _, ds_a, _, _ = two_users
    response = a.get(route.format(id=ds_a))

    # A 200 is not required: a seeded row has no records, so several of these
    # legitimately answer "this dataset has no trace grid". What must never
    # happen is the AUTHORISATION refusal -- 401, 403, or the "Dataset not
    # found" 404 that means "not yours".
    assert response.status_code not in (401, 403)
    if response.status_code == 404:
        assert "Dataset not found" not in str(response.json().get("detail", "")), (
            f"{route} refused the owner their own dataset"
        )


def test_body_supplied_dataset_ids_are_authorised_too(two_users):
    """views/resolve and overlays/compose take ids in the BODY, where a route
    dependency cannot see them. They are the easiest place to leave a hole."""
    a, _, _, ds_b, _ = two_users

    resolve = a.post(
        "/api/views/resolve",
        json={
            "selection": {
                "kind": "frame",
                "dataset_id": ds_b,
                "selection_id": f"{ds_b}:line",
                "frame_id": f"{ds_b}:line",
            }
        },
    )
    assert resolve.status_code == 404, resolve.text

    compose = a.post("/api/overlays/compose", json={"datasets": [ds_b]})
    assert compose.status_code == 404


def test_unauthenticated_requests_are_refused(env):
    anon = _client()
    for path in ("/api/datasets/", "/api/imports/jobs", "/api/auth/me"):
        assert anon.get(path).status_code == 401, path


def test_system_datasets_are_readable_but_not_writable(two_users):
    a, _, _, _, system = two_users

    # Readable: a seeded row has no records, so /info answers "no stored
    # records" -- what matters is that it is not the authorisation refusal.
    info = a.get(f"/api/datasets/{system}/info")
    assert info.status_code not in (401, 403)
    if info.status_code == 404:
        assert "Dataset not found" not in str(info.json().get("detail", ""))

    # Not writable: a reference corpus must not be deletable or reprocessable
    # out from under every other user who can see it.
    assert a.delete(f"/api/datasets/{system}").status_code == 403


# --------------------------------------------------------------------------
# ownership propagation and spoofing
# --------------------------------------------------------------------------

def test_an_import_is_owned_by_the_uploader_end_to_end(env):
    Session, _ = env
    from jobs import runner

    c = _client()
    _register(c, "a@example.test")
    with Session() as s:
        uid = s.query(User).one().id

    job = c.post(
        "/api/imports",
        files={"file": ("line1.csv", io.BytesIO(CSV), "text/csv")},
        data={"sensor_type": "gpr"},
    ).json()["job"]
    assert job["owner_id"] == uid

    runner._execute(job["id"])

    finished = c.get(f"/api/imports/jobs/{job['id']}").json()["job"]
    assert finished["state"] == "SUCCEEDED"
    with Session() as s:
        dataset = s.query(Dataset).filter(Dataset.id == finished["dataset_id"]).one()
    # ownership survived job -> worker -> pipeline -> dataset
    assert dataset.owner_id == uid
    assert finished["dataset_id"] in {d["id"] for d in c.get("/api/datasets/").json()}


def test_client_cannot_spoof_ownership(env):
    """
    The decisive one. A client that could name the owner could give its upload
    away, or take someone else's.
    """
    Session, _ = env
    a, b = _client(), _client()
    _register(a, "a@example.test")
    _register(b, "b@example.test")
    with Session() as s:
        ids = {u.email: u.id for u in s.query(User).all()}

    job = a.post(
        "/api/imports",
        files={"file": ("line1.csv", io.BytesIO(CSV), "text/csv")},
        # A tries to hand the upload to B.
        data={"sensor_type": "gpr", "owner_id": ids["b@example.test"]},
    ).json()["job"]

    assert job["owner_id"] == ids["a@example.test"], "owner_id came from the body"

    from jobs import runner

    runner._execute(job["id"])
    with Session() as s:
        dataset = s.query(Dataset).filter(Dataset.owner_id.isnot(None)).one()
    assert dataset.owner_id == ids["a@example.test"]
    # and B still cannot see it
    assert b.get(f"/api/datasets/{dataset.id}/info").status_code == 404


def test_a_user_cannot_read_another_users_import_job(env):
    Session, _ = env
    a, b = _client(), _client()
    _register(a, "a@example.test")
    _register(b, "b@example.test")

    job = a.post(
        "/api/imports",
        files={"file": ("line1.csv", io.BytesIO(CSV), "text/csv")},
        data={"sensor_type": "gpr"},
    ).json()["job"]

    assert b.get(f"/api/imports/jobs/{job['id']}").status_code == 404
    assert a.get(f"/api/imports/jobs/{job['id']}").status_code == 200
    assert b.get("/api/imports/jobs").json()["jobs"] == []


def test_the_legacy_ingest_endpoint_also_assigns_ownership(env):
    Session, _ = env
    c = _client()
    _register(c, "a@example.test")
    with Session() as s:
        uid = s.query(User).one().id

    body = c.post(
        "/api/datasets/ingest",
        files={"file": ("line1.csv", io.BytesIO(CSV), "text/csv")},
        data={"sensor_type": "gpr"},
    ).json()

    with Session() as s:
        assert s.query(Dataset).filter(Dataset.id == body["dataset_id"]).one().owner_id == uid


# --------------------------------------------------------------------------
# the guard that outlives this commit
# --------------------------------------------------------------------------

def test_every_dataset_route_is_authorised():
    """
    Enumerates the LIVE app rather than a hand-written list, so a route added
    later without authorisation fails here instead of in production.
    """
    from fastapi.routing import APIRoute

    unprotected = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or "{dataset_id}" not in route.path:
            continue
        names = {
            d.call.__name__
            for d in route.dependant.dependencies
            if hasattr(d.call, "__name__")
        }
        if not names & {"require_dataset_access", "require_owned_dataset"}:
            unprotected.append(f"{sorted(route.methods)[0]} {route.path}")

    assert unprotected == [], f"dataset routes without authorisation: {unprotected}"


def test_the_public_surface_is_exactly_what_we_intend():
    """
    Every route that does NOT require authentication, pinned. Adding one is
    then a deliberate act with a test to update, not an oversight.
    """
    from fastapi.routing import APIRoute

    public = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue
        names = {
            d.call.__name__
            for d in route.dependant.dependencies
            if hasattr(d.call, "__name__")
        }
        if not names & {"get_current_user", "require_dataset_access", "require_owned_dataset"}:
            public.add(route.path)

    assert public == {
        "/api/health",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/logout",
        # Password reset is unauthenticated by definition: somebody who cannot
        # sign in is exactly who needs it.
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        # published scientific results: the landing page links to them and a
        # signed-out reader is meant to be able to check our claims
        "/api/benchmark/artifacts",
        "/api/benchmark/artifacts/{name:path}",
        # static capability vocabularies; no user data of any kind
        "/api/candidates/vocabulary",
        "/api/exports/formats",
        "/api/imports/formats",
        "/api/labels/vocabulary",
        "/api/objects/vocabulary",
        "/api/overlays/vocabulary",
        "/api/provenance/vocabulary",
        "/api/spatial/vocabulary",
        "/api/views/vocabulary",
    }, sorted(public)


def test_no_route_accepts_a_user_or_owner_id_as_authority():
    """Identity must come from the session and nowhere a client can type."""
    import pathlib
    import re

    import ast

    offenders = []
    for path in pathlib.Path("api/routes").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            # Only PYDANTIC REQUEST MODELS matter: an internal function
            # parameter named owner_id is fine -- the worker passes one -- but
            # a field on a request body is something a client can set.
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {getattr(b, "id", getattr(b, "attr", "")) for b in node.bases}
            if "BaseModel" not in bases:
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.target.id in ("owner_id", "user_id"):
                        offenders.append(f"{path}:{stmt.lineno} {node.name}.{stmt.target.id}")

    assert offenders == [], f"client-supplied identity fields: {offenders}"
