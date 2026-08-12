"""
Server-side sessions in an HTTP-only cookie.

WHY SESSIONS AND NOT JWT.

  - LOGOUT HAS TO MEAN SOMETHING. A JWT is valid until it expires; revoking one
    needs a server-side denylist, which is a session table wearing a disguise.
    Here logout deletes a row and the credential is dead immediately.
  - No dependency. A JWT needs pyjwt or python-jose; this needs `secrets` and a
    table the database already knows how to create.
  - Nothing sensitive is in the browser. The cookie holds an opaque random
    token, not a claim set, so there is nothing in it for a client to read,
    tamper with, or misinterpret as authority.

ONLY A HASH OF THE TOKEN IS STORED. The database keeps SHA-256 of the token,
never the token itself, so a leaked database dump cannot be replayed as a set of
live sessions. (SHA-256 without a KDF is right here and wrong for passwords: the
token is 256 bits of `secrets` output, so there is no dictionary to attack --
the reason passwords need PBKDF2 is that humans choose them.)

COOKIE FLAGS. httponly so script cannot read it; samesite=lax so it is not sent
on cross-site POSTs; secure taken from SUBTERRA_COOKIE_SECURE, defaulting to
false because local development is plain http and a secure cookie would simply
never be stored. Set it to 1 in any deployment served over https.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import Response

#: The cookie the browser carries. Nothing else authenticates a browser request.
COOKIE_NAME = "subterra_session"

SESSION_TTL_HOURS = int(os.environ.get("SUBTERRA_SESSION_TTL_HOURS", "72"))
COOKIE_SECURE = os.environ.get("SUBTERRA_COOKIE_SECURE", "0") not in ("0", "", "false", "False")
COOKIE_SAMESITE = os.environ.get("SUBTERRA_COOKIE_SAMESITE", "lax")


def new_token() -> str:
    """256 bits from the OS CSPRNG. Never stored; only its hash is."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def expiry_from(now: datetime | None = None) -> datetime:
    return (now or datetime.utcnow()) + timedelta(hours=SESSION_TTL_HOURS)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=SESSION_TTL_HOURS * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")
