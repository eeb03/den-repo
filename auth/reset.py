"""
Password-reset tokens: minting, and consuming exactly once.

THE TOKEN IS A CREDENTIAL, so it is handled like one. 256 bits from
`secrets.token_urlsafe` -- never `random`, which is a Mersenne Twister whose
future output is predictable from a few hundred observed values. Only its
SHA-256 hash reaches the database; the raw token exists in the emailed link and
nowhere else.

(SHA-256 with no KDF is right here for the same reason it is right for session
tokens and wrong for passwords: the input is 256 bits of CSPRNG output, so there
is no dictionary to attack. Passwords need PBKDF2 because humans choose them.)

CONSUMPTION IS A SINGLE ATOMIC UPDATE:

    UPDATE ... SET used_at = :now
    WHERE token_hash = :h AND used_at IS NULL AND expires_at > :now
    RETURNING user_id

The WHERE clause is the check and the SET is the consumption, in one statement,
so the row is claimed by exactly one caller. The obvious three-step version --
read the token, change the password, mark it used -- has a window between the
read and the mark in which a second request can read the same unused token and
also succeed. That is not theoretical: two clicks on a slow connection are
enough.

EXPIRY AND INVALIDITY ARE THE SAME OUTCOME. An expired token, a consumed token,
a malformed token and a token that never existed all produce the same failure,
because telling them apart tells an attacker which guesses were close.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models import PasswordResetToken, UserSession, gen_uuid

#: 30 minutes. Long enough to find the email and choose a password, short enough
#: that a link left in an inbox or a proxy log stops working the same hour.
TTL_SECONDS = int(os.environ.get("SUBTERRA_PASSWORD_RESET_TTL_SECONDS", "1800"))

def _configured_app_url() -> str:
    """
    Where the emailed link points, taken from configuration and from nothing
    else.

    NEVER FROM THE REQUEST. A reset link built from the incoming `Host` header
    would let anyone who can reach the API mint an email, sent by us, carrying a
    real token, pointing at a host they chose -- the standard host-header
    poisoning route to a stolen reset. `reset_url` is not given the request at
    all, so there is nothing to get wrong later.

    `SUBTERRA_APP_URL` is the documented name; `SUBTERRA_APP_BASE_URL` is still
    read so an existing deployment does not break silently on upgrade.
    """
    raw = (
        os.environ.get("SUBTERRA_APP_URL")
        or os.environ.get("SUBTERRA_APP_BASE_URL")
        or "http://localhost:3000"
    ).strip().rstrip("/")

    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        # Refused at import, so a deployment cannot start and then email links
        # nobody can open.
        raise ValueError(
            "SUBTERRA_APP_URL must be an absolute http(s) URL such as "
            "https://app.example.com"
        )
    return raw


APP_BASE_URL = _configured_app_url()

#: Injectable so tests can expire a token by moving time rather than sleeping.
_clock = datetime.utcnow


def set_clock(clock) -> None:
    """Tests only."""
    global _clock
    _clock = clock


def reset_clock() -> None:
    global _clock
    _clock = datetime.utcnow


def new_token() -> str:
    """256 bits from the OS CSPRNG. Returned once, never stored."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def reset_url(token: str) -> str:
    """
    The link that goes in the email. Takes a token and nothing else -- no
    request, no headers, no host.

    The token is percent-encoded even though `token_urlsafe` cannot produce a
    character that needs it: the encoding is what makes that stay true if the
    generator is ever changed.
    """
    return f"{APP_BASE_URL}/reset-password?token={quote(token, safe='')}"


def issue(db: Session, user_id: str) -> str:
    """
    Mint a token for this account and return the RAW value, for the email only.

    Any of the user's earlier unused tokens are consumed first. Requesting a
    reset twice should not leave two working links: the newest email is the one
    the user is looking at, and the older link becoming inert is what they would
    expect.
    """
    now = _clock()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)

    token = new_token()
    db.add(
        PasswordResetToken(
            id=gen_uuid(),
            user_id=user_id,
            token_hash=token_hash(token),
            expires_at=now + timedelta(seconds=TTL_SECONDS),
            created_at=now,
        )
    )
    db.commit()
    return token


#: Check and consume in one statement. Returns the owner only if the token was
#: unused and unexpired at the moment it was claimed.
_CONSUME = text(
    """
    UPDATE password_reset_tokens
       SET used_at = :now
     WHERE token_hash = :token_hash
       AND used_at IS NULL
       AND expires_at > :now
    RETURNING user_id
    """
)


def consume(db: Session, token: str) -> Optional[str]:
    """
    Claim the token. Returns the user id, or None if it was invalid, expired or
    already used -- the caller must not be told which.
    """
    if not token or not isinstance(token, str):
        return None
    row = db.execute(
        _CONSUME, {"token_hash": token_hash(token), "now": _clock()}
    ).first()
    db.commit()
    return row[0] if row else None


def revoke_all_sessions(db: Session, user_id: str) -> int:
    """
    End every signed-in browser for this account.

    A reset usually means the password was lost or is believed compromised. If
    the sessions survived it, an attacker already holding one would keep their
    access through the very act meant to remove it.
    """
    now = _clock()
    count = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .update({UserSession.revoked_at: now}, synchronize_session=False)
    )
    db.commit()
    return int(count or 0)
