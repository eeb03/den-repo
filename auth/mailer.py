"""
Getting a reset link to a person.

NO PROVIDER IS ADDED HERE. This repository has no email infrastructure --
no SMTP settings, no SendGrid, no SES -- and choosing one is a deployment
decision with credentials, deliverability and privacy consequences that a
password-reset feature should not make on its behalf. What this module adds is
the seam: one small interface, two implementations, and a documented way to
plug a real provider in.

THE THREE IMPLEMENTATIONS, and why each exists.

  ConsoleMailer (default in development)
      Writes the link to the log so a developer can follow the flow without any
      provider. It logs the URL -- which contains the token -- and is therefore
      REFUSED IN PRODUCTION by `configure_from_environment`, because a token in
      a log file is a credential in a log file.

  CapturingMailer (tests)
      Keeps messages in memory so a test can assert what was sent. Never used
      outside tests.

  UnconfiguredMailer (default in production)
      RAISES. This is the important one. The alternative -- quietly doing
      nothing and returning success -- would leave users waiting for an email
      that was never going to arrive, with nothing in the logs to say so. A
      deployment that has not chosen a provider should find out immediately,
      not from a support ticket.

THE API RESPONSE IS GENERIC EITHER WAY. A delivery failure must not become an
account-existence oracle: if sending raises, the route logs it and still returns
the same generic acknowledgement, because "we could not send mail" and "no such
account" must be indistinguishable from outside.

TO ADD A REAL PROVIDER: implement `PasswordResetMailer.send_password_reset`,
and set it with `set_mailer()` at startup. Nothing else changes; the route
depends only on the interface.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from utils.logger import get_logger

logger = get_logger(__name__)


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
            "set one with auth.mailer.set_mailer() at startup"
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
    Pick a default at startup.

    Development gets ConsoleMailer so the flow works out of the box. Anything
    else gets UnconfiguredMailer, so a real deployment must choose a provider
    rather than inheriting one that writes tokens to a log.
    """
    environment = os.environ.get("SUBTERRA_ENV", "development").strip().lower()
    if environment in ("development", "dev", "test", "local"):
        set_mailer(ConsoleMailer())
        return
    set_mailer(UnconfiguredMailer())
    logger.warning(
        "SUBTERRA_ENV=%s and no password-reset mail provider is configured; "
        "reset requests will be accepted and will fail to deliver until one is set",
        environment,
    )
