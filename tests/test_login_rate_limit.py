"""
Login throttling.

The tests that matter are the ones that would catch a limiter which LOOKS right:
one that counts successes and locks out honest users, one that leaks account
existence through a status code, one that loses increments under concurrency,
and one that lives in a process dictionary and evaporates on restart.

Nothing here sleeps. The clock is injected, so a window is advanced by moving
time rather than by waiting for it -- a rate limiter tested with `sleep` is a
slow test that fails on a loaded machine.
"""
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import app
from auth import rate_limit
from database.models import LoginAttempt, User
from database.session import Base, get_db

pytestmark = pytest.mark.real_auth

PASSWORD = "correct-horse-battery"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        f"sqlite:///{tmp_path / 'rl.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db

    # A clock the test drives. `now` is a one-element list so a test can
    # advance it without rebinding anything the limiter captured.
    now = [1_000_000.0]
    rate_limit.set_clock(lambda: now[0])
    try:
        yield Session, now
    finally:
        rate_limit.reset_clock()
        app.dependency_overrides.clear()


class _WithPeerAddress:
    """
    Test-only ASGI shim that sets the connection's peer address from a header.

    This Starlette's TestClient has no `client=` argument, and every request
    would otherwise arrive from the same fixed peer -- making the per-IP
    dimension untestable. Rewriting the ASGI scope keeps `client_key` itself
    under test (it still reads `request.client.host`) rather than stubbing the
    very function whose behaviour matters.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            peer = headers.get(b"x-test-peer")
            if peer:
                scope = dict(scope)
                scope["client"] = (peer.decode(), 12345)
        await self.app(scope, receive, send)


def client(host="10.0.0.1") -> TestClient:
    """A client with a stated peer address, so the IP key is controllable."""
    c = TestClient(_WithPeerAddress(app))
    c.headers.update({"x-test-peer": host})
    return c


def register(c, email):
    return c.post("/api/auth/register", json={"email": email, "password": PASSWORD})


def login(c, email, password=PASSWORD):
    return c.post("/api/auth/login", json={"email": email, "password": password})


def attempts(Session, bucket):
    with Session() as s:
        row = s.query(LoginAttempt).filter(LoginAttempt.bucket == bucket).first()
        return row.attempts if row else 0


# --------------------------------------------------------------------------
# the limiter does not get in the way of ordinary use
# --------------------------------------------------------------------------

def test_a_correct_password_works_and_keeps_working(env):
    c = client()
    register(c, "a@example.test")

    for _ in range(rate_limit.IP_MAX_FAILURES + 5):
        assert login(c, "a@example.test").status_code == 200


def test_a_success_clears_the_counters(env):
    """Yesterday's typos must not throttle today's correct password."""
    Session, _ = env
    c = client()
    register(c, "a@example.test")

    for _ in range(rate_limit.IP_MAX_FAILURES - 1):
        assert login(c, "a@example.test", "wrong-password-here").status_code == 401
    assert attempts(Session, "ip:10.0.0.1") == rate_limit.IP_MAX_FAILURES - 1

    assert login(c, "a@example.test").status_code == 200

    assert attempts(Session, "ip:10.0.0.1") == 0
    assert attempts(Session, "email:a@example.test") == 0


# --------------------------------------------------------------------------
# the threshold
# --------------------------------------------------------------------------

def test_failed_attempts_are_counted_and_the_threshold_is_enforced(env):
    Session, _ = env
    c = client()
    register(c, "a@example.test")

    for i in range(rate_limit.IP_MAX_FAILURES):
        assert login(c, "a@example.test", "wrong-password-here").status_code == 401, i

    blocked = login(c, "a@example.test", "wrong-password-here")
    assert blocked.status_code == 429
    assert attempts(Session, "ip:10.0.0.1") == rate_limit.IP_MAX_FAILURES


def test_the_block_carries_retry_after_and_a_generic_message(env):
    c = client()
    register(c, "a@example.test")
    for _ in range(rate_limit.IP_MAX_FAILURES):
        login(c, "a@example.test", "wrong-password-here")

    blocked = login(c, "a@example.test", "wrong-password-here")
    assert blocked.status_code == 429

    retry_after = blocked.headers.get("Retry-After")
    assert retry_after is not None and int(retry_after) > 0
    assert int(retry_after) <= rate_limit.WINDOW_SECONDS + 1

    detail = blocked.json()["detail"]
    assert "too many sign-in attempts" in detail.lower()
    # no storage internals, no stack trace, no account information
    for leak in ("sqlite", "postgres", "redis", "login_attempts", "traceback", "@"):
        assert leak not in detail.lower()


def test_even_the_correct_password_is_refused_while_blocked(env):
    """Otherwise the 429 is a free oracle: it would answer only wrong guesses."""
    c = client()
    register(c, "a@example.test")
    for _ in range(rate_limit.IP_MAX_FAILURES):
        login(c, "a@example.test", "wrong-password-here")

    assert login(c, "a@example.test").status_code == 429


# --------------------------------------------------------------------------
# no new enumeration channel
# --------------------------------------------------------------------------

def test_a_nonexistent_account_is_throttled_identically_to_a_real_one(env):
    """
    The decisive anti-enumeration test. If only real addresses were counted, an
    attacker could tell registered from unregistered by which one starts
    answering 429.
    """
    real, fake = client("10.0.0.1"), client("10.0.0.2")
    register(client("10.0.0.9"), "a@example.test")

    for _ in range(rate_limit.IP_MAX_FAILURES):
        assert login(real, "a@example.test", "wrong-password-here").status_code == 401
        assert login(fake, "nobody@example.test", "wrong-password-here").status_code == 401

    blocked_real = login(real, "a@example.test", "wrong-password-here")
    blocked_fake = login(fake, "nobody@example.test", "wrong-password-here")

    assert blocked_real.status_code == blocked_fake.status_code == 429
    assert blocked_real.json()["detail"] == blocked_fake.json()["detail"]


def test_a_malformed_credential_is_still_a_generic_failure(env):
    c = client()
    for body in ({"email": "", "password": ""}, {"email": "not-an-email", "password": "x"}):
        r = c.post("/api/auth/login", json=body)
        assert r.status_code in (401, 429)
        if r.status_code == 401:
            assert r.json()["detail"] == "invalid email or password"


# --------------------------------------------------------------------------
# recovery -- never a permanent lockout
# --------------------------------------------------------------------------

def test_the_window_expires_and_login_works_again(env):
    _, now = env
    c = client()
    register(c, "a@example.test")

    for _ in range(rate_limit.IP_MAX_FAILURES):
        login(c, "a@example.test", "wrong-password-here")
    assert login(c, "a@example.test").status_code == 429

    now[0] += rate_limit.WINDOW_SECONDS + 1  # the window elapses

    assert login(c, "a@example.test").status_code == 200


def test_nothing_creates_a_permanent_lockout(env):
    """No flag, no disabled column, no admin unlock -- only an expiring window."""
    Session, now = env
    c = client()
    register(c, "a@example.test")
    for _ in range(rate_limit.IP_MAX_FAILURES + 3):
        login(c, "a@example.test", "wrong-password-here")

    with Session() as s:
        assert s.query(User).one().is_active is True

    now[0] += rate_limit.WINDOW_SECONDS + 1
    assert login(c, "a@example.test").status_code == 200


# --------------------------------------------------------------------------
# isolation between users and addresses
# --------------------------------------------------------------------------

def test_one_users_failures_do_not_block_another_user(env):
    """A shared office address must not lock everyone out because one person
    mistyped -- so the per-IP budget is checked, but exhausting the EMAIL budget
    for one account leaves another account reachable."""
    a, b = client("10.0.0.1"), client("10.0.0.2")
    register(client("10.0.0.9"), "a@example.test")
    register(client("10.0.0.8"), "b@example.test")

    for _ in range(rate_limit.IP_MAX_FAILURES):
        login(a, "a@example.test", "wrong-password-here")
    assert login(a, "a@example.test").status_code == 429

    # B, from a different address, is unaffected
    assert login(b, "b@example.test").status_code == 200


def test_an_attacker_cannot_evade_the_account_budget_by_rotating_addresses(env):
    """
    The reason the email dimension exists. Each address stays under the per-IP
    budget, but they are all guessing at one account.
    """
    Session, _ = env
    register(client("10.0.0.99"), "victim@example.test")

    per_host = rate_limit.IP_MAX_FAILURES - 1  # never trips the IP limit
    hosts = (rate_limit.EMAIL_MAX_FAILURES // per_host) + 1

    blocked = False
    for h in range(hosts):
        c = client(f"10.1.0.{h}")
        for _ in range(per_host):
            if login(c, "victim@example.test", "wrong-password-here").status_code == 429:
                blocked = True
                break
        if blocked:
            break

    assert blocked, "rotating client addresses evaded the per-account budget"
    assert attempts(Session, "email:victim@example.test") >= rate_limit.EMAIL_MAX_FAILURES


def test_the_two_dimensions_are_counted_separately(env):
    Session, _ = env
    c = client("10.0.0.5")
    register(client("10.0.0.9"), "a@example.test")

    login(c, "a@example.test", "wrong-password-here")
    login(c, "other@example.test", "wrong-password-here")

    assert attempts(Session, "ip:10.0.0.5") == 2          # both charged to the IP
    assert attempts(Session, "email:a@example.test") == 1  # one each to the accounts
    assert attempts(Session, "email:other@example.test") == 1


# --------------------------------------------------------------------------
# the properties an in-memory dict would not have
# --------------------------------------------------------------------------

def test_the_counter_lives_in_the_database_not_in_the_process(env):
    """
    Durability and cross-worker coordination in one assertion: the count is a
    row another process could read, not a dict that dies with this one.
    """
    Session, _ = env
    c = client()
    register(c, "a@example.test")
    login(c, "a@example.test", "wrong-password-here")

    with Session() as s:
        rows = s.execute(text("SELECT bucket, attempts FROM login_attempts")).all()
    assert ("ip:10.0.0.1", 1) in [(r[0], r[1]) for r in rows]


def test_simultaneous_failures_do_not_lose_an_increment(env):
    """
    Catches read-modify-write. Twelve threads each record a failure; if the
    counter were incremented in Python the total would come out short and an
    attacker would get free attempts.
    """
    Session, _ = env
    threads, per_thread = 12, 5

    def worker():
        s = Session()
        try:
            for _ in range(per_thread):
                rate_limit.record_failure(s, "ip", "concurrent")
        finally:
            s.close()

    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    assert attempts(Session, "ip:concurrent") == threads * per_thread


def test_concurrent_login_requests_are_all_counted(env):
    """The same property through the actual endpoint."""
    Session, _ = env
    register(client("10.0.0.9"), "a@example.test")

    results: list[int] = []
    lock = threading.Lock()

    def worker():
        c = client("10.0.0.7")
        r = login(c, "a@example.test", "wrong-password-here")
        with lock:
            results.append(r.status_code)

    workers = [threading.Thread(target=worker) for _ in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    assert all(code in (401, 429) for code in results)
    assert attempts(Session, "ip:10.0.0.7") == 8


# --------------------------------------------------------------------------
# failure policy
# --------------------------------------------------------------------------

def test_the_limiter_fails_closed(env, monkeypatch):
    """
    If the counter cannot be consulted, the attempt is REFUSED rather than
    allowed through uncounted. This costs nothing that was working: the counter
    shares its database with the credential store.
    """
    c = client()
    register(c, "a@example.test")

    def explode(*args, **kwargs):
        raise rate_limit.RateLimitUnavailable("counter unavailable")

    monkeypatch.setattr(rate_limit, "check", explode)

    blocked = login(c, "a@example.test")
    assert blocked.status_code == 503
    detail = blocked.json()["detail"]
    assert "temporarily unavailable" in detail.lower()
    # the outage is not described to the caller
    for leak in ("sqlite", "postgres", "counter unavailable", "traceback"):
        assert leak not in detail.lower()


# --------------------------------------------------------------------------
# scope
# --------------------------------------------------------------------------

def test_only_the_login_endpoint_is_throttled(env):
    """
    Registration, /me and logout are deliberately NOT rate limited in this
    change. Credential guessing is the threat being addressed; throttling the
    rest would be scope this task did not ask for.
    """
    c = client()
    register(c, "a@example.test")
    for _ in range(rate_limit.IP_MAX_FAILURES + 5):
        assert c.get("/api/auth/me").status_code == 200
        assert c.post("/api/auth/logout").status_code == 200
        assert login(c, "a@example.test").status_code == 200


def test_every_credential_accepting_route_is_throttled():
    """
    Guards against a second login path appearing later without the limiter --
    a bypass that would make all of the above decorative.
    """
    import ast
    import pathlib

    src = pathlib.Path("api/routes/auth.py").read_text()
    tree = ast.parse(src)
    lines = src.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        decorated = any("@router." in lines[d.lineno - 1] for d in node.decorator_list)
        if not decorated:
            continue
        body = ast.get_source_segment(src, node) or ""
        # a route that verifies a password must also consult the limiter
        if "verify_password" in body:
            assert "rate_limit." in body, (
                f"{node.name} verifies a password without consulting the limiter"
            )


def test_the_proxy_header_is_not_trusted_by_default(env):
    """
    Honouring X-Forwarded-For unconditionally would let any caller pick their
    own bucket, which deletes the limit rather than weakening it. There is no
    trusted-proxy configuration in this application, so it defaults off.
    """
    Session, _ = env
    assert rate_limit.TRUST_PROXY_HEADERS is False

    c = client("10.0.0.1")
    register(client("10.0.0.9"), "a@example.test")
    for i in range(3):
        c.post(
            "/api/auth/login",
            json={"email": "a@example.test", "password": "wrong-password-here"},
            headers={"X-Forwarded-For": f"9.9.9.{i}"},
        )

    # all three landed in the real peer's bucket, not three forged ones
    assert attempts(Session, "ip:10.0.0.1") == 3
    for i in range(3):
        assert attempts(Session, f"ip:9.9.9.{i}") == 0
