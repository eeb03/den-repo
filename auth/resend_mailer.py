"""
Delivering a reset link through Resend.

NO SDK, AND NO NEW DEPENDENCY. Resend's send endpoint is one HTTPS POST with a
bearer token and a JSON body, and `requests` is already a direct dependency of
this project -- `ingestion/sources.py` and `ingestion/downloader.py` both use
it. Adding a provider SDK to save writing that one call would buy convenience
with a supply-chain surface, a release cadence and a second HTTP stack, for a
request that fits on a screen. If the provider is ever swapped, what changes is
this file; the seam is already the mailer interface.

WHAT THIS CLASS IS NOT ALLOWED TO KNOW. It receives an address and a URL. It
does not read the database, does not see the user, does not mint or hash
anything, and has no idea what a reset token is -- to it the URL is an opaque
string. `PasswordResetService` therefore stays identical whichever provider is
installed, which is the point of the seam.

FAILING IS NORMAL AND MUST BE LOUD -- INTERNALLY. Mail providers reject, rate
limit, time out and go down. Every one of those raises `EmailDeliveryError`
here, because the alternative -- returning quietly and letting the caller assume
an inbox will fill -- produces a system that looks healthy while nobody can get
back into their account. The route above catches it, logs it, and still answers
the caller with the same generic acknowledgement, so loud internally and silent
externally are not in tension: the anti-enumeration property lives in the route,
the truthfulness lives here.

NO RETRIES. Not "bounded retries" -- none. This runs synchronously inside an
HTTP request, so a retry does not make delivery more likely so much as it makes
the request twice as slow before failing, and a 429 answered by immediately
asking again is the one response guaranteed not to help. The user's retry is
requesting another link, which costs them one click and is rate-limited
already. A queue would change this calculus, and there is a job runner in this
repository -- but introducing background delivery for one email would mean
persisting a live credential into a job record, which is a worse trade than a
synchronous failure.

SECRETS NEVER TRAVEL WITH ERRORS. The API key and the reset URL are scrubbed
from any provider text before it reaches an exception message, because that
message ends up in a log file. See `_scrub`.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

import requests

from auth.email_content import password_reset_content
from utils.logger import get_logger

logger = get_logger(__name__)

#: https://resend.com/docs/api-reference/emails/send-email
RESEND_ENDPOINT = "https://api.resend.com/emails"

#: Bounded, and short. This is spent inside a request a person is waiting on,
#: and a provider that has not answered in ten seconds is not about to.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: How much provider text may survive into a log line. Applied AFTER scrubbing,
#: never before -- truncating first could cut a secret in half and leave the
#: front of it in place.
_MAX_REASON_CHARS = 200


class EmailConfigurationError(RuntimeError):
    """
    The deployment asked for a provider it did not finish configuring.

    Raised at startup rather than at send time. A reset request answers with the
    same generic acknowledgement whether or not the mail went out, so a
    misconfiguration discovered at send time is invisible to the user and shows
    up only as a support ticket weeks later. Startup is the one moment where
    this can be loud.
    """


class EmailDeliveryError(RuntimeError):
    """The provider was reached, or was not, and the message did not go."""


class ResendMailer:
    """
    A `PasswordResetMailer` backed by Resend's HTTP API.

    The transport is injectable purely so tests can drive every failure branch
    -- 4xx, 5xx, timeout, connection refused, malformed body -- without a
    network, a key, or a mock of a global. Production passes nothing and gets
    `requests.post`.
    """

    def __init__(
        self,
        *,
        api_key: str,
        sender: str,
        reply_to: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Optional[Callable[..., Any]] = None,
    ) -> None:
        # Validated in the constructor, so a half-configured instance cannot
        # exist at all -- there is no object to hand to `set_mailer` and
        # discover is broken later.
        missing = [
            name
            for name, value in (("RESEND_API_KEY", api_key), ("SUBTERRA_EMAIL_FROM", sender))
            if not (value or "").strip()
        ]
        if missing:
            raise EmailConfigurationError(
                "SUBTERRA_EMAIL_PROVIDER=resend requires " + " and ".join(missing)
            )

        self._api_key = api_key.strip()
        self._sender = sender.strip()
        self._reply_to = (reply_to or "").strip() or None
        self._timeout = float(timeout)
        self._transport = transport or requests.post

    # -- construction from the environment ---------------------------------

    @classmethod
    def from_environment(cls) -> "ResendMailer":
        """
        Read the deployment's configuration. Never falls back to a default
        sender or a default key: both are deployment-specific, and a hard-coded
        one would either fail obscurely or send from somebody else's domain.
        """
        return cls(
            api_key=os.environ.get("RESEND_API_KEY", ""),
            sender=os.environ.get("SUBTERRA_EMAIL_FROM", ""),
            reply_to=os.environ.get("SUBTERRA_EMAIL_REPLY_TO"),
            timeout=_timeout_from_environment(),
        )

    # -- the interface -----------------------------------------------------

    def send_password_reset(self, email: str, reset_url: str) -> None:
        content = password_reset_content(reset_url, _ttl_minutes())

        payload: dict[str, Any] = {
            "from": self._sender,
            "to": [email],
            "subject": content.subject,
            "html": content.html,
            "text": content.text,
        }
        if self._reply_to:
            payload["reply_to"] = self._reply_to

        try:
            response = self._transport(
                RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001 -- timeouts, DNS, TLS, refused
            # `from None` deliberately breaks the chain: the original exception
            # is not needed to act on this, and suppressing it guarantees no
            # future handler can render an unscrubbed traceback into a log.
            raise EmailDeliveryError(
                f"could not reach the email provider for {email}: "
                f"{self._scrub(f'{type(exc).__name__}: {exc}', reset_url)}"
            ) from None

        status = getattr(response, "status_code", None)
        if status is None or not 200 <= int(status) < 300:
            raise EmailDeliveryError(
                f"the email provider refused the message for {email} "
                f"(HTTP {status}): {self._provider_reason(response, reset_url)}"
            )

        message_id = self._message_id(response)
        if not message_id:
            # A 2xx whose body we cannot read is NOT a success. Treating it as
            # one would be the misleading "sent" this whole module exists to
            # avoid; the provider may well have accepted it, but we do not know
            # that and must not record that we do.
            raise EmailDeliveryError(
                f"the email provider returned an unreadable response for {email} "
                f"(HTTP {status}); the message cannot be confirmed as accepted"
            )

        # ACCEPTED, NOT DELIVERED. Resend has taken the message; the recipient's
        # server has not. Nothing here can promise an inbox, so nothing here
        # says so. The id is Resend's own, carries no account information, and
        # is what support will ask for.
        logger.info("password reset email accepted by provider for %s (id %s)", email, message_id)

    # -- response reading --------------------------------------------------

    @staticmethod
    def _message_id(response: Any) -> str:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 -- not JSON, empty, truncated
            return ""
        if not isinstance(body, dict):
            return ""
        value = body.get("id")
        return value.strip() if isinstance(value, str) else ""

    def _provider_reason(self, response: Any, reset_url: str) -> str:
        """
        A short, scrubbed summary of why the provider said no.

        The full body is never used: it is the provider's to shape, may echo
        parts of the request, and belongs in neither a log nor an exception.
        Only the fields Resend documents as human-readable are taken, and only
        after scrubbing.
        """
        reason = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                parts = [
                    str(body[key])
                    for key in ("name", "message", "error")
                    if isinstance(body.get(key), (str, int))
                ]
                reason = " / ".join(parts)
        except Exception:  # noqa: BLE001
            reason = ""

        reason = self._scrub(reason, reset_url).strip()
        if not reason:
            return "no readable reason given"
        return reason[:_MAX_REASON_CHARS]

    def _scrub(self, blob: str, reset_url: str) -> str:
        """
        Remove the two credentials that could plausibly appear in provider text
        before it becomes a log line: the API key, and the reset URL (with its
        token, which is the more damaging of the two because it is live and
        belongs to a specific person).

        Scrubbing happens before truncation everywhere it is used, so a secret
        cannot survive by being cut in half.
        """
        token = reset_url.rsplit("token=", 1)[-1] if "token=" in reset_url else ""
        for secret in (self._api_key, reset_url, token):
            if secret and len(secret) > 3:
                blob = blob.replace(secret, "[redacted]")
        return blob


def _timeout_from_environment() -> float:
    raw = os.environ.get("SUBTERRA_EMAIL_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise EmailConfigurationError(
            "SUBTERRA_EMAIL_TIMEOUT_SECONDS must be a number of seconds"
        ) from None
    if not 0 < value <= 60:
        raise EmailConfigurationError(
            "SUBTERRA_EMAIL_TIMEOUT_SECONDS must be between 0 and 60 seconds"
        )
    return value


def _ttl_minutes() -> int:
    """Read from the reset module so the email's stated expiry and the token's
    real one cannot disagree. Imported locally to keep the dependency one-way:
    reset knows nothing about mail."""
    from auth.reset import TTL_SECONDS

    return max(1, round(TTL_SECONDS / 60))
