"""
The Resend email provider.

NOTHING HERE TOUCHES THE NETWORK. Every test drives an injected transport, so
the suite cannot reach api.resend.com even if a real key happened to be in the
environment -- and `test_the_default_transport_is_never_called_in_tests` proves
the injection is real rather than decorative.

The properties worth defending are not "the JSON has the right keys" (though
that is checked). They are: a misconfigured deployment fails loudly instead of
quietly logging tokens; every provider failure raises rather than pretending;
and neither the API key nor the reset token can ride out on an error message
into a log file.
"""
import logging
import re

import pytest

from auth import email_content, mailer, reset
from auth.resend_mailer import (
    RESEND_ENDPOINT,
    EmailConfigurationError,
    EmailDeliveryError,
    ResendMailer,
)

API_KEY = "re_test_0123456789abcdefghijklmnop"
SENDER = "Subterra AI <no-reply@mail.example.test>"
RECIPIENT = "person@example.test"
RESET_URL = "https://app.example.test/reset-password?token=TOKEN-abcdef0123456789"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raises=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"id": "msg_abc123"}
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._payload


class FakeTransport:
    """Records the one call it is given and returns whatever it was told to."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response if response is not None else FakeResponse()
        self._error = error

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self._error is not None:
            raise self._error
        return self._response

    @property
    def last(self):
        return self.calls[-1]

    @property
    def payload(self):
        return self.last["json"]


def build(transport=None, **overrides):
    options = {"api_key": API_KEY, "sender": SENDER, "transport": transport or FakeTransport()}
    options.update(overrides)
    return ResendMailer(**options)


@pytest.fixture
def restore_mailer():
    """Provider selection mutates module state; put it back."""
    try:
        yield
    finally:
        mailer.set_mailer(mailer.UnconfiguredMailer())


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        "SUBTERRA_EMAIL_PROVIDER",
        "SUBTERRA_ENV",
        "RESEND_API_KEY",
        "SUBTERRA_EMAIL_FROM",
        "SUBTERRA_EMAIL_REPLY_TO",
        "SUBTERRA_EMAIL_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --------------------------------------------------------------------------
# provider selection
# --------------------------------------------------------------------------

def test_console_selects_the_console_mailer(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "console")
    clean_env.setenv("SUBTERRA_ENV", "development")
    mailer.configure_from_environment()
    assert isinstance(mailer.get_mailer(), mailer.ConsoleMailer)


def test_resend_selects_the_resend_mailer(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "resend")
    clean_env.setenv("RESEND_API_KEY", API_KEY)
    clean_env.setenv("SUBTERRA_EMAIL_FROM", SENDER)
    mailer.configure_from_environment()
    assert isinstance(mailer.get_mailer(), ResendMailer)


def test_an_unknown_provider_is_rejected(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "sendgrid")
    with pytest.raises(EmailConfigurationError) as exc:
        mailer.configure_from_environment()
    assert "sendgrid" in str(exc.value)


def test_resend_without_an_api_key_is_rejected(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "resend")
    clean_env.setenv("SUBTERRA_EMAIL_FROM", SENDER)
    with pytest.raises(EmailConfigurationError) as exc:
        mailer.configure_from_environment()
    assert "RESEND_API_KEY" in str(exc.value)


def test_resend_without_a_sender_is_rejected(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "resend")
    clean_env.setenv("RESEND_API_KEY", API_KEY)
    with pytest.raises(EmailConfigurationError) as exc:
        mailer.configure_from_environment()
    assert "SUBTERRA_EMAIL_FROM" in str(exc.value)


def test_a_broken_resend_configuration_never_falls_back_to_console(clean_env, restore_mailer):
    """
    THE POINT OF THE WHOLE MODULE. A deployment that asked for Resend and got
    the console mailer instead would look healthy while writing every live reset
    token into its log.
    """
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "resend")
    mailer.set_mailer(mailer.UnconfiguredMailer())

    with pytest.raises(EmailConfigurationError):
        mailer.configure_from_environment()
    assert not isinstance(mailer.get_mailer(), mailer.ConsoleMailer)


def test_console_is_refused_outside_development(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "console")
    clean_env.setenv("SUBTERRA_ENV", "production")
    with pytest.raises(EmailConfigurationError):
        mailer.configure_from_environment()


def test_an_unset_provider_still_works_in_development(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_ENV", "development")
    mailer.configure_from_environment()
    assert isinstance(mailer.get_mailer(), mailer.ConsoleMailer)


def test_an_unset_provider_sends_nothing_in_production(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_ENV", "production")
    mailer.configure_from_environment()
    assert isinstance(mailer.get_mailer(), mailer.UnconfiguredMailer)


def test_a_missing_key_is_reported_by_name_and_never_by_value(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "resend")
    clean_env.setenv("RESEND_API_KEY", "   ")  # present but blank
    clean_env.setenv("SUBTERRA_EMAIL_FROM", SENDER)
    with pytest.raises(EmailConfigurationError) as exc:
        mailer.configure_from_environment()
    assert "RESEND_API_KEY" in str(exc.value)
    assert API_KEY not in str(exc.value)


def test_an_out_of_range_timeout_is_rejected(clean_env, restore_mailer):
    clean_env.setenv("SUBTERRA_EMAIL_PROVIDER", "resend")
    clean_env.setenv("RESEND_API_KEY", API_KEY)
    clean_env.setenv("SUBTERRA_EMAIL_FROM", SENDER)
    for bad in ("0", "-1", "600", "soon"):
        clean_env.setenv("SUBTERRA_EMAIL_TIMEOUT_SECONDS", bad)
        with pytest.raises(EmailConfigurationError):
            mailer.configure_from_environment()


# --------------------------------------------------------------------------
# the request
# --------------------------------------------------------------------------

def test_the_request_goes_to_the_documented_endpoint():
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert transport.last["url"] == RESEND_ENDPOINT
    assert transport.last["url"].startswith("https://")


def test_the_request_carries_a_bearer_authorization_header():
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert transport.last["headers"]["Authorization"] == f"Bearer {API_KEY}"


def test_the_request_carries_the_configured_sender_and_recipient():
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert transport.payload["from"] == SENDER
    assert transport.payload["to"] == [RECIPIENT]


def test_the_subject_says_what_the_message_is():
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert transport.payload["subject"] == "Reset your Subterra AI password"


def test_both_bodies_are_sent():
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert "<html" in transport.payload["html"].lower()
    assert transport.payload["text"].strip()
    assert "<" not in transport.payload["text"]


def test_a_reply_to_is_sent_only_when_configured():
    plain = FakeTransport()
    build(plain).send_password_reset(RECIPIENT, RESET_URL)
    assert "reply_to" not in plain.payload

    with_reply = FakeTransport()
    build(with_reply, reply_to="support@example.test").send_password_reset(RECIPIENT, RESET_URL)
    assert with_reply.payload["reply_to"] == "support@example.test"


def test_the_request_is_given_a_bounded_timeout():
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    timeout = transport.last["timeout"]
    assert 0 < timeout <= 60


def test_exactly_one_request_is_made_per_message():
    """No retries: this runs inside a request somebody is waiting on."""
    transport = FakeTransport(FakeResponse(status_code=500, payload={"message": "boom"}))
    with pytest.raises(EmailDeliveryError):
        build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert len(transport.calls) == 1


def test_the_default_transport_is_never_called_in_tests(monkeypatch):
    """Proves the injection is real: with `requests.post` sabotaged, an injected
    transport still works, so nothing in this file can reach the internet."""
    import requests

    def explode(*args, **kwargs):
        raise AssertionError("a test attempted a real HTTP request")

    monkeypatch.setattr(requests, "post", explode)
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert len(transport.calls) == 1


# --------------------------------------------------------------------------
# the reset URL in the email
# --------------------------------------------------------------------------

def test_the_link_uses_the_configured_application_url(monkeypatch):
    monkeypatch.setattr(reset, "APP_BASE_URL", "https://app.example.test")
    assert reset.reset_url("abc").startswith("https://app.example.test/reset-password?token=")


def test_the_configured_url_must_be_absolute(monkeypatch):
    monkeypatch.setenv("SUBTERRA_APP_URL", "app.example.test")
    with pytest.raises(ValueError):
        reset._configured_app_url()


def test_the_documented_variable_wins_over_the_legacy_one(monkeypatch):
    monkeypatch.setenv("SUBTERRA_APP_URL", "https://new.example.test")
    monkeypatch.setenv("SUBTERRA_APP_BASE_URL", "https://old.example.test")
    assert reset._configured_app_url() == "https://new.example.test"


def test_reset_urls_are_built_without_access_to_any_request():
    """
    Host-header poisoning is the classic way a reset link is stolen: the
    attacker's host arrives in a header, is baked into an email we send, and the
    victim clicks it. The structural defence is that the module which builds the
    link cannot see a request at all -- so there is no header to trust or
    distrust. (The behavioural proof, with a spoofed Host, is in the integration
    test below.)
    """
    import ast
    import inspect

    assert list(inspect.signature(reset.reset_url).parameters) == ["token"]

    # Read the imports, not the prose: a substring search over source would
    # trip over the word "Requesting" in a docstring and prove nothing.
    tree = ast.parse(inspect.getsource(reset))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not imported & {"fastapi", "starlette", "flask", "django"}


def test_the_email_contains_the_token_and_not_its_hash():
    token = "a-token-value-that-is-clearly-distinct"
    url = f"https://app.example.test/reset-password?token={token}"
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, url)

    assert token in transport.payload["html"]
    assert token in transport.payload["text"]
    assert reset.token_hash(token) not in transport.payload["html"]
    assert reset.token_hash(token) not in transport.payload["text"]


def test_the_email_carries_no_database_identifier():
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    body = transport.payload["html"] + transport.payload["text"]
    # A uuid anywhere in the message would be a user id or a row id.
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", body)


def test_the_email_states_the_configured_expiry(monkeypatch):
    content = email_content.password_reset_content(RESET_URL, 30)
    assert "30 minutes" in content.text and "30 minutes" in content.html
    hourly = email_content.password_reset_content(RESET_URL, 60)
    assert "1 hour" in hourly.text


def test_the_email_does_not_claim_the_owner_asked():
    content = email_content.password_reset_content(RESET_URL, 30)
    for body in (content.text, content.html):
        lowered = body.lower()
        assert "someone asked" in lowered
        assert "you requested" not in lowered
        assert "you asked" not in lowered
        assert "did not ask" in lowered  # ignoring it is offered as normal


def test_the_email_loads_nothing_from_the_network():
    """No images, no fonts, no tracking pixel -- so opening it leaks nothing and
    a blocked resource cannot break the message."""
    content = email_content.password_reset_content(RESET_URL, 30)
    assert "<img" not in content.html.lower()
    for scheme in ("src=", "@import", "<script"):
        assert scheme not in content.html.lower()


def test_a_hostile_url_cannot_inject_markup():
    content = email_content.password_reset_content(
        'https://app.example.test/reset-password?token="><script>alert(1)</script>', 30
    )
    assert "<script>" not in content.html


# --------------------------------------------------------------------------
# provider failures
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", [400, 401, 403, 422, 429, 500, 502, 503])
def test_every_provider_error_status_raises(status):
    transport = FakeTransport(FakeResponse(status_code=status, payload={"message": "nope"}))
    with pytest.raises(EmailDeliveryError) as exc:
        build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert str(status) in str(exc.value)


def test_a_timeout_raises_rather_than_reporting_success():
    import requests

    transport = FakeTransport(error=requests.exceptions.Timeout("timed out"))
    with pytest.raises(EmailDeliveryError):
        build(transport).send_password_reset(RECIPIENT, RESET_URL)


def test_a_connection_failure_raises():
    import requests

    transport = FakeTransport(error=requests.exceptions.ConnectionError("refused"))
    with pytest.raises(EmailDeliveryError):
        build(transport).send_password_reset(RECIPIENT, RESET_URL)


def test_a_response_that_is_not_json_is_a_failure():
    transport = FakeTransport(FakeResponse(status_code=200, raises=True))
    with pytest.raises(EmailDeliveryError) as exc:
        build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert "cannot be confirmed" in str(exc.value)


@pytest.mark.parametrize("payload", [{}, {"id": ""}, {"id": None}, [], "ok", {"other": "x"}])
def test_a_2xx_without_a_message_id_is_not_treated_as_sent(payload):
    """
    "Probably accepted" is not accepted. Recording a send we cannot confirm is
    the misleading success this module exists to avoid.
    """
    transport = FakeTransport(FakeResponse(status_code=200, payload=payload))
    with pytest.raises(EmailDeliveryError):
        build(transport).send_password_reset(RECIPIENT, RESET_URL)


def test_a_successful_send_is_silent():
    transport = FakeTransport(FakeResponse(status_code=200, payload={"id": "msg_1"}))
    assert build(transport).send_password_reset(RECIPIENT, RESET_URL) is None


# --------------------------------------------------------------------------
# secrets never leave
# --------------------------------------------------------------------------

def test_the_api_key_never_appears_in_an_error():
    transport = FakeTransport(
        FakeResponse(status_code=401, payload={"message": f"invalid key {API_KEY}"})
    )
    with pytest.raises(EmailDeliveryError) as exc:
        build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert API_KEY not in str(exc.value)
    assert "[redacted]" in str(exc.value)


def test_the_reset_url_never_appears_in_an_error():
    transport = FakeTransport(
        FakeResponse(status_code=400, payload={"message": f"bad body {RESET_URL}"})
    )
    with pytest.raises(EmailDeliveryError) as exc:
        build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert RESET_URL not in str(exc.value)
    assert "TOKEN-abcdef0123456789" not in str(exc.value)


def test_a_transport_exception_carrying_a_secret_is_scrubbed():
    transport = FakeTransport(error=RuntimeError(f"POST failed with {API_KEY}"))
    with pytest.raises(EmailDeliveryError) as exc:
        build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert API_KEY not in str(exc.value)


def test_a_scrubbed_reason_is_truncated_after_scrubbing_not_before():
    """
    Ordering, isolated. The key is positioned so that it STRADDLES the
    truncation point: truncate-then-scrub would cut it in half, leaving the
    front of it in the log with nothing left for the replacement to match.
    Scrub-then-truncate removes it whole.
    """
    from auth.resend_mailer import _MAX_REASON_CHARS

    straddling = "x" * (_MAX_REASON_CHARS - 10) + API_KEY
    transport = FakeTransport(
        FakeResponse(status_code=400, payload={"message": straddling})
    )
    with pytest.raises(EmailDeliveryError) as exc:
        build(transport).send_password_reset(RECIPIENT, RESET_URL)

    assert API_KEY not in str(exc.value)
    assert API_KEY[:10] not in str(exc.value)  # not even the first characters


def test_the_provider_response_body_is_not_reproduced_wholesale():
    transport = FakeTransport(
        FakeResponse(
            status_code=422,
            payload={"message": "domain not verified", "request_id": "req_secret_internal"},
        )
    )
    with pytest.raises(EmailDeliveryError) as exc:
        build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert "domain not verified" in str(exc.value)   # actionable
    assert "req_secret_internal" not in str(exc.value)  # not ours to echo


def test_a_successful_send_logs_no_credential(caplog):
    transport = FakeTransport()
    with caplog.at_level(logging.DEBUG):
        build(transport).send_password_reset(RECIPIENT, RESET_URL)
    assert API_KEY not in caplog.text
    assert RESET_URL not in caplog.text
    assert "TOKEN-abcdef0123456789" not in caplog.text


def test_a_failed_send_logs_no_credential(caplog):
    transport = FakeTransport(
        FakeResponse(status_code=500, payload={"message": f"{API_KEY} {RESET_URL}"})
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(EmailDeliveryError) as exc:
            build(transport).send_password_reset(RECIPIENT, RESET_URL)
        logging.getLogger(__name__).error("relayed: %s", exc.value)
    assert API_KEY not in caplog.text
    assert "TOKEN-abcdef0123456789" not in caplog.text


def test_no_password_or_session_material_is_in_the_email():
    transport = FakeTransport()
    build(transport).send_password_reset(RECIPIENT, RESET_URL)
    body = (transport.payload["html"] + transport.payload["text"]).lower()
    for forbidden in ("password_hash", "pbkdf2", "session", "cookie", "sha256", "token_hash"):
        assert forbidden not in body


def test_the_provider_never_learns_anything_but_an_address_and_a_url():
    """
    The seam holds only if the provider cannot reach past it. `ResendMailer`
    takes no database session, no user, and no request.
    """
    import inspect

    signature = inspect.signature(ResendMailer.send_password_reset)
    assert list(signature.parameters) == ["self", "email", "reset_url"]

    # It reaches neither the database nor the request, so there is nothing for a
    # provider to be handed by accident.
    source = inspect.getsource(ResendMailer)
    for forbidden in ("sqlalchemy", "database", "query(", "password_hash", "token_hash"):
        assert forbidden not in source


def test_the_resend_sdk_was_not_added():
    """The integration is one HTTPS POST with `requests`, which this project
    already depends on."""
    from pathlib import Path

    requirements = Path("requirements.txt").read_text().lower()
    assert "resend" not in requirements
    assert "requests" in requirements


# --------------------------------------------------------------------------
# end to end, through the real routes, with a fake transport
# --------------------------------------------------------------------------
#
# The unit tests above check the provider in isolation. This one checks the
# thing that actually has to work: that a person who has forgotten their
# password ends up signed in with a new one, and that the link which got them
# there came out of an outgoing Resend request and nowhere else.

@pytest.fixture
def api(tmp_path, monkeypatch):
    from datetime import datetime

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from api.main import app
    from auth import rate_limit
    from database.session import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'email.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    monkeypatch.setattr(reset, "APP_BASE_URL", "https://app.example.test")

    now = [datetime(2026, 1, 1, 12, 0, 0)]
    reset.set_clock(lambda: now[0])
    rate_limit.set_clock(lambda: now[0].timestamp())

    transport = FakeTransport()
    mailer.set_mailer(build(transport))

    try:
        yield TestClient(app), transport
    finally:
        reset.reset_clock()
        rate_limit.reset_clock()
        mailer.set_mailer(mailer.UnconfiguredMailer())
        app.dependency_overrides.clear()


def _link_from(transport) -> str:
    """The reset link as the recipient would find it: pulled out of the HTML
    body of the request that went to the provider."""
    html_body = transport.payload["html"]
    match = re.search(r'href="(https://app\.example\.test/reset-password\?token=[^"]+)"', html_body)
    assert match, "no reset link in the outgoing email"
    return match.group(1)


@pytest.mark.real_auth
def test_a_forgotten_password_is_recovered_entirely_through_the_email(api):
    client, transport = api
    email, old_password, new_password = "person@example.test", "old-password-here", "new-password-here"

    signed_in = client.post(
        "/api/auth/register", json={"email": email, "password": old_password}
    )
    assert signed_in.status_code == 201
    session_cookie = signed_in.cookies.get("subterra_session")
    assert client.get("/api/auth/me", cookies={"subterra_session": session_cookie}).status_code == 200

    # Ask for a reset. The API says nothing; the email carries everything.
    acknowledgement = client.post("/api/auth/forgot-password", json={"email": email})
    assert acknowledgement.status_code == 200
    assert "token" not in acknowledgement.text.lower()

    # Exactly one outgoing provider request, addressed to the person who asked.
    assert len(transport.calls) == 1
    assert transport.last["url"] == RESEND_ENDPOINT
    assert transport.payload["to"] == [email]

    link = _link_from(transport)
    token = link.split("token=")[1]
    assert token in transport.payload["text"]  # both bodies carry the same link

    changed = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": new_password, "password_confirmation": new_password},
    )
    assert changed.status_code == 200

    # The old password no longer works, the new one does.
    assert client.post(
        "/api/auth/login", json={"email": email, "password": old_password}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": email, "password": new_password}
    ).status_code == 200

    # And the session that existed before the reset is gone.
    assert client.get(
        "/api/auth/me", cookies={"subterra_session": session_cookie}
    ).status_code == 401

    # The link is spent.
    assert client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": new_password, "password_confirmation": new_password},
    ).status_code == 400


@pytest.mark.real_auth
def test_a_spoofed_host_header_does_not_reach_the_emailed_link(api):
    """
    The behavioural half of the host-poisoning defence: an attacker controls the
    Host and X-Forwarded-Host of their own request, and the link we send still
    points at the configured application.
    """
    client, transport = api
    client.post("/api/auth/register", json={"email": "h@example.test", "password": "old-password-here"})

    client.post(
        "/api/auth/forgot-password",
        json={"email": "h@example.test"},
        headers={"Host": "evil.example.net", "X-Forwarded-Host": "evil.example.net"},
    )

    body = transport.payload["html"] + transport.payload["text"]
    assert "evil.example.net" not in body
    assert _link_from(transport).startswith("https://app.example.test/reset-password?token=")


@pytest.mark.real_auth
def test_a_provider_failure_stays_invisible_to_the_caller(api):
    """
    A Resend outage must not become an account-existence oracle, and must not
    put provider detail in front of the caller.
    """
    client, _ = api
    client.post("/api/auth/register", json={"email": "p@example.test", "password": "old-password-here"})

    failing = FakeTransport(
        FakeResponse(status_code=503, payload={"message": "resend is unavailable"})
    )
    mailer.set_mailer(build(failing))

    real = client.post("/api/auth/forgot-password", json={"email": "p@example.test"})
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.test"})

    assert real.status_code == unknown.status_code == 200
    assert real.json() == unknown.json()
    for text in (real.text.lower(), unknown.text.lower()):
        for leak in ("resend", "503", "provider", "unavailable"):
            assert leak not in text


@pytest.mark.real_auth
def test_no_credential_reaches_the_log_on_the_whole_journey(api, caplog):
    client, transport = api
    client.post("/api/auth/register", json={"email": "l@example.test", "password": "old-password-here"})

    with caplog.at_level(logging.DEBUG):
        client.post("/api/auth/forgot-password", json={"email": "l@example.test"})
        token = _link_from(transport).split("token=")[1]
        client.post(
            "/api/auth/reset-password",
            json={
                "token": token,
                "password": "new-password-here",
                "password_confirmation": "new-password-here",
            },
        )

    assert token not in caplog.text
    assert API_KEY not in caplog.text
    assert "reset-password?token=" not in caplog.text
