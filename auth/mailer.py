"""
Getting a reset link to a person.

THE SEAM, AND WHAT PLUGS INTO IT. One interface with a single method, and four
implementations chosen explicitly by configuration. The password-reset route
holds only the interface, so it cannot tell -- and must never be able to tell --
which provider is installed.

  ResendMailer (production)
      An HTTPS POST to Resend, in `auth/resend_mailer.py`. No SDK and no new
      dependency: `requests` is already used elsewhere in this repository.

  ConsoleMailer (development)
      Writes the link to the log so a developer can follow the flow without a
      provider or a key. It logs the URL -- which contains the token -- and is
      therefore REFUSED OUTSIDE DEVELOPMENT, because a token in a log file is a
      credential in a log file.

  CapturingMailer (tests)
      Keeps messages in memory so a test can assert what was sent, without a
      network. Never selectable from the environment.

  UnconfiguredMailer (the default when nothing is chosen)
      RAISES. The alternative -- quietly doing nothing and returning success --
      would leave users waiting for mail that was never going to be sent, with
      nothing in the logs to say so.

SELECTION IS EXPLICIT, AND NEVER FALLS BACK. `SUBTERRA_EMAIL_PROVIDER` is
`console` or `resend`, and asking for `resend` without a key or a sender is a
startup error, not a quiet demotion to console. That rule is the whole point of
this function: a deployment that silently downgraded to writing reset links into
its own log would still appear to work, and every token it ever issued would be
sitting in a log file.

WHY STARTUP AND NOT SEND TIME. Because of anti-enumeration, `forgot-password`
returns the same acknowledgement whether or not the mail went out. A
misconfiguration discovered at send time is therefore invisible to the user and
to the caller; it surfaces weeks later as "I never got the email". Startup is
the one moment where it can be loud, so it is raised there. `ResendMailer` also
validates in its constructor, so a half-configured instance cannot exist.

THE API RESPONSE IS GENERIC EITHER WAY. A delivery failure must not become an
account-existence oracle: if sending raises, the route logs it and still returns
the same generic acknowledgement, because "we could not send mail" and "no such
account" must be indistinguishable from outside. Loud internally, silent
externally -- the two live in different places and do not conflict.

TO ADD ANOTHER PROVIDER: implement `send_password_reset`, and give it a name in
`configure_from_environment`. Nothing else changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from auth.resend_mailer import (
    EmailConfigurationError,
    EmailDeliveryError,
    ResendMailer,
)
from utils.logger import get_logger

logger = get_logger(__name__)

#: Which provider to use. No default that sends anything: see
#: `configure_from_environment`.
PROVIDER_ENV = "SUBTERRA_EMAIL_PROVIDER"

#: Environments in which writing a live reset link to the log is acceptable.
_DEVELOPMENT_ENVIRONMENTS = ("development", "dev", "test", "local")

__all__ = [
    "PasswordResetMailer",
    "UnconfiguredMailer",
    "ConsoleMailer",
    "CapturingMailer",
    "CapturedMessage",
    "ResendMailer",
    "EmailConfigurationError",
    "EmailDeliveryError",
    "set_mailer",
    "get_mailer",
    "configure_from_environment",
]


class PasswordResetMailer(Protocol):
    """The whole interface. One method, because that is all this needs."""

    def send_password_reset(self, email: str, reset_url: str) -> None:
        ...


class UnconfiguredMailer:
    """
    Refuses to send, loudly.

    The production default. Failing here is a deliberate choice over returning
    success for mail nobody sent: a silent no-op is indistinguishable from a
    working system until a user cannot get back into their account.
    """

    def send_password_reset(self, email: str, reset_url: str) -> None:
        raise RuntimeError(
            "no password-reset mail provider is configured; "
            f"set {PROVIDER_ENV}=resend (with RESEND_API_KEY and "
            "SUBTERRA_EMAIL_FROM), or install one with auth.mailer.set_mailer()"
        )


class ConsoleMailer:
    """
    Development only. Logs the link so the flow can be followed locally.

    This writes a live credential to the log, which is exactly why
    `configure_from_environment` refuses to select it when SUBTERRA_ENV says
    production.
    """

    def send_password_reset(self, email: str, reset_url: str) -> None:
        logger.info(
            "[dev mailer] password reset for %s -> %s\n"
            "  (development only: this link contains a live token)",
            email,
            reset_url,
        )


@dataclass
class CapturedMessage:
    email: str
    reset_url: str


@dataclass
class CapturingMailer:
    """Tests only. Keeps what was 'sent' so it can be asserted on."""

    messages: list[CapturedMessage] = field(default_factory=list)

    def send_password_reset(self, email: str, reset_url: str) -> None:
        self.messages.append(CapturedMessage(email=email, reset_url=reset_url))

    @property
    def last(self) -> CapturedMessage | None:
        return self.messages[-1] if self.messages else None

    def clear(self) -> None:
        self.messages.clear()


_mailer: PasswordResetMailer = UnconfiguredMailer()


def set_mailer(mailer: PasswordResetMailer) -> None:
    global _mailer
    _mailer = mailer


def get_mailer() -> PasswordResetMailer:
    return _mailer


def configure_from_environment() -> None:
    """
    Install the configured provider at startup, or refuse to start.

    Raises `EmailConfigurationError` for a provider that was asked for and
    cannot be built. That is deliberate: the caller is the application lifespan,
    so a deployment that names a provider it did not finish configuring fails at
    deploy time, when somebody is watching, rather than at 3am when a user
    cannot sign in and the API cheerfully answers "if an account exists...".

    NOTHING HERE EVER FALLS BACK TO ConsoleMailer. Not when the key is missing,
    not when the provider name is wrong, not when the environment is unset.
    Console delivery writes live tokens into the log, and a silent demotion to
    it is the one failure that would look exactly like success.
    """
    provider = os.environ.get(PROVIDER_ENV, "").strip().lower()
    environment = os.environ.get("SUBTERRA_ENV", "development").strip().lower()
    development = environment in _DEVELOPMENT_ENVIRONMENTS

    if not provider:
        # Unset: the pre-existing behaviour, kept so a developer who has never
        # heard of this variable still gets a working local flow. It selects
        # console ONLY in development, and never sends anything anywhere else.
        if development:
            set_mailer(ConsoleMailer())
            logger.info(
                "%s is unset and SUBTERRA_ENV=%s: using the development console "
                "mailer (reset links are written to the log)",
                PROVIDER_ENV,
                environment,
            )
            return
        set_mailer(UnconfiguredMailer())
        logger.warning(
            "SUBTERRA_ENV=%s and %s is unset; password reset requests will be "
            "accepted and will fail to deliver until a provider is configured",
            environment,
            PROVIDER_ENV,
        )
        return

    if provider == "console":
        if not development:
            raise EmailConfigurationError(
                f"{PROVIDER_ENV}=console is refused when SUBTERRA_ENV={environment}: "
                "the console mailer writes live reset links to the log. "
                f"Set {PROVIDER_ENV}=resend."
            )
        set_mailer(ConsoleMailer())
        logger.info("using the development console mailer for password reset")
        return

    if provider == "resend":
        # Raises EmailConfigurationError, naming the variables that are missing
        # and never their values.
        mailer = ResendMailer.from_environment()
        set_mailer(mailer)
        logger.info("password reset email will be sent through Resend")
        return

    raise EmailConfigurationError(
        f"unknown {PROVIDER_ENV}={provider!r}; expected 'console' or 'resend'"
    )
