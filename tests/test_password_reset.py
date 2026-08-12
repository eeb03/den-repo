"""
Password reset.

The reset flow hands out a credential by email, so the tests that matter are
about what it must NOT do: reveal which addresses have accounts, keep a usable
token in the database, let one link be spent twice, or leave old sessions alive
through a reset that was probably prompted by a compromise.

Nothing sleeps. Both clocks -- the token clock and the rate-limit clock -- are
injected, so expiry is tested by moving time rather than waiting for it.
"""
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import app
from auth import mailer, passwords, rate_limit, reset
from database.models import PasswordResetToken, User, UserSession
from database.session import Base, get_db

pytestmark = pytest.mark.real_auth

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "a-completely-different-passphrase"


@pytest.fixture
def env(tmp_path):
    from datetime import datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        f"sqlite:///{tmp_path / 'reset.db'}", connect_args={"check_same_thread": False}
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

    outbox = mailer.CapturingMailer()
    mailer.set_mailer(outbox)

    # Token clock and limiter clock, both driven by the test.
    now = [datetime(2026, 1, 1, 12, 0, 0)]
    reset.set_clock(lambda: now[0])
    rate_limit.set_clock(lambda: now[0].timestamp())

    try:
        yield Session, outbox, now, timedelta
    finally:
        reset.reset_clock()
        rate_limit.reset_clock()
        mailer.set_mailer(mailer.UnconfiguredMailer())
        app.dependency_overrides.clear()


def client() -> TestClient:
    return TestClient(app)


def register(c, email=None):
    return c.post(
        "/api/auth/register",
        json={"email": email or "a@example.test", "password": PASSWORD},
    )


def forgot(c, email):
    return c.post("/api/auth/forgot-password", json={"email": email})


def do_reset(c, token, password=NEW_PASSWORD, confirmation=None):
    return c.post(
        "/api/auth/reset-password",
        json={
            "token": token,
            "password": password,
            "password_confirmation": confirmation if confirmation is not None else password,
        },
    )


def token_from(outbox) -> str:
    return outbox.last.reset_url.split("token=")[1]


# --------------------------------------------------------------------------
# enumeration
# --------------------------------------------------------------------------

def test_a_real_and_an_unknown_address_get_identical_answers(env):
    _, outbox, _, _ = env
    register(client(), "a@example.test")

    real = forgot(client(), "a@example.test")
    unknown = forgot(client(), "nobody@example.test")

    assert real.status_code == unknown.status_code == 200
    assert real.json() == unknown.json()
    assert "if an account exists" in real.json()["message"].lower()
    # only the real address produced an email, which the CALLER cannot observe
    assert len(outbox.messages) == 1
    assert outbox.last.email == "a@example.test"


def test_a_malformed_address_is_answered_the_same_way(env):
    _, outbox, _, _ = env
    r = forgot(client(), "not-an-email")
    assert r.status_code == 200
    assert "if an account exists" in r.json()["message"].lower()
    assert outbox.messages == []


def test_the_response_carries_no_identifier_token_or_url(env):
    _, outbox, _, _ = env
    register(client(), "a@example.test")
    body = forgot(client(), "a@example.test").text

    assert "token" not in body.lower()
    assert "http" not in body.lower()
    assert "reset-password" not in body
    with_user = client().get("/api/auth/me")  # unauthenticated
    assert with_user.status_code == 401
    # nothing from the mail leaked into the response
    assert token_from(outbox) not in body


# --------------------------------------------------------------------------
# token security
# --------------------------------------------------------------------------

def test_only_the_hash_is_stored_never_the_token(env):
    Session, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    token = token_from(outbox)

    with Session() as s:
        rows = s.query(PasswordResetToken).all()
        assert len(rows) == 1
        assert rows[0].token_hash == reset.token_hash(token)
        assert rows[0].token_hash != token
        # and the raw value appears nowhere in the table at all
        dump = s.execute(text("SELECT * FROM password_reset_tokens")).all()
    assert token not in str(dump)


def test_the_token_is_long_and_unpredictable(env):
    tokens = {reset.new_token() for _ in range(200)}
    assert len(tokens) == 200                      # no collisions
    assert all(len(t) >= 40 for t in tokens)       # 256 bits, url-safe


def test_the_token_generator_uses_secrets_not_random(env):
    import inspect

    source = inspect.getsource(reset)
    assert "secrets.token_urlsafe" in source
    assert "random.choice" not in source and "random.random" not in source


def test_the_token_carries_an_expiry(env):
    Session, outbox, now, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    with Session() as s:
        row = s.query(PasswordResetToken).one()
    assert row.expires_at > now[0]
    assert (row.expires_at - now[0]).total_seconds() == reset.TTL_SECONDS


@pytest.mark.parametrize(
    "bad_token",
    ["", "not-a-real-token", "x" * 400, "../../etc/passwd", "null"],
)
def test_a_malformed_or_unknown_token_is_refused(env, bad_token):
    register(client(), "a@example.test")
    r = do_reset(client(), bad_token)
    assert r.status_code == 400
    assert "invalid or has expired" in r.json()["detail"]


def test_an_expired_token_is_refused_and_reads_the_same_as_an_invalid_one(env):
    _, outbox, now, timedelta = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    token = token_from(outbox)

    now[0] += timedelta(seconds=reset.TTL_SECONDS + 1)

    expired = do_reset(client(), token)
    invalid = do_reset(client(), "never-existed")
    assert expired.status_code == invalid.status_code == 400
    assert expired.json() == invalid.json()


def test_a_used_token_never_works_again(env):
    _, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    token = token_from(outbox)

    assert do_reset(client(), token).status_code == 200
    second = do_reset(client(), token, "yet-another-passphrase-here")
    assert second.status_code == 400
    assert "invalid or has expired" in second.json()["detail"]


def test_requesting_again_invalidates_the_previous_link(env):
    """Two live links to one account would be one more than necessary."""
    _, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    first = token_from(outbox)
    forgot(client(), "a@example.test")
    second = token_from(outbox)

    assert first != second
    assert do_reset(client(), first).status_code == 400
    assert do_reset(client(), second).status_code == 200


def test_there_is_no_get_endpoint_that_consumes_a_token():
    """A GET would be spent by a link scanner or a prefetch before the user
    ever saw the page."""
    from fastapi.routing import APIRoute

    for route in app.routes:
        if isinstance(route, APIRoute) and "reset" in route.path:
            assert "GET" not in route.methods, route.path


# --------------------------------------------------------------------------
# consumption is atomic
# --------------------------------------------------------------------------

def test_two_simultaneous_resets_with_one_token_yield_exactly_one_success(env):
    """
    Catches the three-step version -- check, update, mark used -- which has a
    window in which a second request reads the same unused token.
    """
    Session, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    token = token_from(outbox)

    results: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(6)

    def attempt(i):
        barrier.wait()
        r = do_reset(client(), token, f"passphrase-number-{i}-here")
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(200) == 1, results
    assert results.count(400) == 5, results

    with Session() as s:
        assert s.query(PasswordResetToken).one().used_at is not None


# --------------------------------------------------------------------------
# the password actually changes, using the existing implementation
# --------------------------------------------------------------------------

def test_the_old_password_stops_working_and_the_new_one_works(env):
    _, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    do_reset(client(), token_from(outbox))

    c = client()
    assert c.post(
        "/api/auth/login", json={"email": "a@example.test", "password": PASSWORD}
    ).status_code == 401
    assert c.post(
        "/api/auth/login", json={"email": "a@example.test", "password": NEW_PASSWORD}
    ).status_code == 200


def test_the_existing_hashing_implementation_is_reused(env):
    Session, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    do_reset(client(), token_from(outbox))

    with Session() as s:
        stored = s.query(User).one().password_hash

    assert stored.startswith("pbkdf2_sha256$")          # not bcrypt, not a second scheme
    assert NEW_PASSWORD not in stored
    assert passwords.verify_password(NEW_PASSWORD, stored)


def test_the_existing_password_policy_is_reused(env):
    _, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    token = token_from(outbox)

    weak = do_reset(client(), token, "short")
    assert weak.status_code == 422
    assert "at least" in weak.json()["detail"]
    # and the link is NOT burned by a rejected password
    assert do_reset(client(), token).status_code == 200


def test_a_mismatched_confirmation_is_refused(env):
    _, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    token = token_from(outbox)

    r = do_reset(client(), token, NEW_PASSWORD, "a-different-passphrase-here")
    assert r.status_code == 422
    assert "do not match" in r.json()["detail"]
    assert do_reset(client(), token).status_code == 200   # still usable


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------

def test_every_existing_session_is_revoked_by_a_reset(env):
    """
    A reset usually means the password was lost or is believed compromised. If
    sessions survived it, an attacker already holding one would keep exactly the
    access the reset was meant to remove.
    """
    Session, outbox, _, _ = env

    # two signed-in browsers
    a, b = client(), client()
    register(a, "a@example.test")
    b.post("/api/auth/login", json={"email": "a@example.test", "password": PASSWORD})
    assert a.get("/api/auth/me").status_code == 200
    assert b.get("/api/auth/me").status_code == 200

    forgot(client(), "a@example.test")
    assert do_reset(client(), token_from(outbox)).status_code == 200

    assert a.get("/api/auth/me").status_code == 401
    assert b.get("/api/auth/me").status_code == 401

    with Session() as s:
        assert all(row.revoked_at is not None for row in s.query(UserSession).all())


def test_a_new_login_after_reset_establishes_a_working_session(env):
    _, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")
    do_reset(client(), token_from(outbox))

    c = client()
    assert c.post(
        "/api/auth/login", json={"email": "a@example.test", "password": NEW_PASSWORD}
    ).status_code == 200
    assert c.get("/api/auth/me").json()["user"]["email"] == "a@example.test"


def test_a_reset_clears_the_account_failed_login_counter(env):
    """
    Somebody who just proved control of the address should not then be locked
    out by their own earlier attempts to remember the old password.

    Only the ACCOUNT counter is cleared. The per-address counter is left alone
    on purpose -- clearing it would let an attacker refill the budget they had
    spent guessing at other accounts by resetting a password on one they own --
    so this test asserts the account bucket specifically rather than going
    through a login, which the untouched address counter also governs.
    """
    Session, outbox, _, _ = env
    register(client(), "a@example.test")

    failures = 3  # deliberately below the per-address budget
    for _ in range(failures):
        client().post(
            "/api/auth/login",
            json={"email": "a@example.test", "password": "wrong-password-here"},
        )

    def bucket(name):
        with Session() as s:
            row = s.execute(
                text("SELECT attempts FROM login_attempts WHERE bucket = :b"),
                {"b": name},
            ).first()
            return row[0] if row else 0

    assert bucket("email:a@example.test") == failures

    forgot(client(), "a@example.test")
    assert do_reset(client(), token_from(outbox)).status_code == 200

    assert bucket("email:a@example.test") == 0        # cleared
    assert bucket("ip:testclient") == failures        # deliberately NOT cleared

    assert client().post(
        "/api/auth/login", json={"email": "a@example.test", "password": NEW_PASSWORD}
    ).status_code == 200


# --------------------------------------------------------------------------
# the mailer
# --------------------------------------------------------------------------

def test_the_test_mailer_captures_the_link(env):
    _, outbox, _, _ = env
    register(client(), "a@example.test")
    forgot(client(), "a@example.test")

    assert outbox.last is not None
    assert outbox.last.email == "a@example.test"
    assert outbox.last.reset_url.startswith(reset.APP_BASE_URL)
    assert "/reset-password?token=" in outbox.last.reset_url


def test_the_token_is_never_written_to_a_log(env, caplog):
    import logging

    _, outbox, _, _ = env
    register(client(), "a@example.test")
    with caplog.at_level(logging.DEBUG):
        forgot(client(), "a@example.test")
    token = token_from(outbox)

    assert token not in caplog.text
    assert token not in str(caplog.records)


def test_a_delivery_failure_is_not_an_existence_oracle(env):
    """
    The production default REFUSES to send. That must not make a registered
    address answer differently from an unregistered one.
    """
    _, _, _, _ = env
    register(client(), "a@example.test")
    mailer.set_mailer(mailer.UnconfiguredMailer())

    real = forgot(client(), "a@example.test")
    unknown = forgot(client(), "nobody@example.test")

    assert real.status_code == unknown.status_code == 200
    assert real.json() == unknown.json()


def test_the_production_default_refuses_rather_than_pretending():
    """A silent no-op would look like a working system until a user was locked
    out of their own account."""
    with pytest.raises(RuntimeError):
        mailer.UnconfiguredMailer().send_password_reset("a@example.test", "http://x")


def test_no_email_provider_dependency_was_added():
    from pathlib import Path

    requirements = Path("requirements.txt").read_text().lower()
    for provider in ("sendgrid", "resend", "boto3", "mailgun", "aiosmtplib", "postmark"):
        assert provider not in requirements


# --------------------------------------------------------------------------
# abuse control
# --------------------------------------------------------------------------

def test_repeated_requests_for_one_address_are_capped(env):
    """The endpoint must not be an unlimited way to fill somebody's inbox."""
    _, outbox, _, _ = env
    register(client(), "a@example.test")

    for _ in range(rate_limit.RESET_EMAIL_MAX + 4):
        assert forgot(client(), "a@example.test").status_code == 200

    assert len(outbox.messages) == rate_limit.RESET_EMAIL_MAX


def test_a_throttled_request_is_indistinguishable_from_an_unthrottled_one(env):
    _, _, _, _ = env
    register(client(), "a@example.test")

    first = forgot(client(), "a@example.test")
    for _ in range(rate_limit.RESET_EMAIL_MAX + 3):
        forgot(client(), "a@example.test")
    throttled = forgot(client(), "a@example.test")
    unknown = forgot(client(), "nobody-else@example.test")

    assert first.status_code == throttled.status_code == unknown.status_code == 200
    assert first.json() == throttled.json() == unknown.json()


def test_the_cap_lifts_after_its_window(env):
    _, outbox, now, timedelta = env
    register(client(), "a@example.test")
    for _ in range(rate_limit.RESET_EMAIL_MAX + 2):
        forgot(client(), "a@example.test")
    sent = len(outbox.messages)

    now[0] += timedelta(seconds=rate_limit.RESET_WINDOW_SECONDS + 1)
    forgot(client(), "a@example.test")

    assert len(outbox.messages) == sent + 1


def test_reset_throttling_does_not_disturb_the_login_limiter(env):
    """The two policies share a mechanism but must not share a budget."""
    Session, _, _, _ = env
    register(client(), "a@example.test")
    for _ in range(rate_limit.RESET_EMAIL_MAX + 2):
        forgot(client(), "a@example.test")

    # login still works: reset requests are not failed credentials
    assert client().post(
        "/api/auth/login", json={"email": "a@example.test", "password": PASSWORD}
    ).status_code == 200

    with Session() as s:
        buckets = {row[0] for row in s.execute(text("SELECT bucket FROM login_attempts"))}
    assert any(b.startswith("reset_email:") for b in buckets)
    assert not any(b == "email:a@example.test" for b in buckets)


# --------------------------------------------------------------------------
# migration
# --------------------------------------------------------------------------

def test_the_migration_creates_the_table_on_a_pre_reset_database(tmp_path):
    from sqlalchemy import create_engine, inspect

    from database.migrations import MIGRATIONS, applied_migrations, run_migrations

    engine = create_engine(f"sqlite:///{tmp_path / 'pre.db'}")

    # a database that predates password reset: every table EXCEPT this one
    from database.models import PasswordResetToken

    tables = [t for t in Base.metadata.sorted_tables if t.name != "password_reset_tokens"]
    Base.metadata.create_all(bind=engine, tables=tables)
    assert not inspect(engine).has_table("password_reset_tokens")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, is_active) VALUES ('u1', 'a@x.test', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO datasets (id, name, sensor_type, original_format) "
                "VALUES ('d1', 'existing', 'gpr', 'segy')"
            )
        )

    ran = run_migrations(engine)

    assert "003_password_reset_tokens" in ran
    assert inspect(engine).has_table("password_reset_tokens")
    assert applied_migrations(engine) == {m.id for m in MIGRATIONS}

    # and the data that was already there is untouched
    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM datasets")).scalar() == 1


def test_the_migration_is_idempotent(tmp_path):
    from sqlalchemy import create_engine

    from database.migrations import run_migrations

    engine = create_engine(f"sqlite:///{tmp_path / 'idem.db'}")
    Base.metadata.create_all(bind=engine)

    assert "003_password_reset_tokens" in run_migrations(engine)
    assert run_migrations(engine) == []
    assert run_migrations(engine) == []
