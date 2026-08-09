"""
Throttling credential guessing.

WHAT THIS DEFENDS AGAINST, and what it does not. Login is the one endpoint an
unauthenticated stranger can call repeatedly with attacker-chosen input, so it
is where a weak password is eventually found. PBKDF2 at 600k iterations already
makes each guess expensive, but expensive is not limited: given time, an
attacker still gets unlimited attempts. This caps them. It is NOT a defence
against a large distributed attack, and it is not a substitute for a strong
password.

STORAGE: THE APPLICATION DATABASE.

  - Not a Python dict. That resets on restart -- handing an attacker a fresh
    budget every deploy -- and is per-process, so N workers would silently
    multiply the limit by N.
  - Not Redis. There is none. The deployment is `db` and `api`; the only
    mention of Redis in this repository is the comment explaining why the job
    runner does not use one. Adding a broker for a single counter would be a
    new operational dependency to buy what PostgreSQL already provides.

COUNTING IS ATOMIC IN SQL. A single `INSERT ... ON CONFLICT DO UPDATE ...
RETURNING` both rolls the window and increments, and hands back the new value.
There is no read-then-write in Python, so two simultaneous failures cannot both
read "4", both write "5", and let a fifth attempt through.

TWO KEYS, BECAUSE EITHER ALONE IS WRONG.

  - Per IP alone: one host cannot grind, but a botnet trying one password
    against every account walks straight through.
  - Per account alone: an attacker can lock a victim out of their own account
    by deliberately failing their login -- turning a defence into a weapon.

Both are counted; the per-account budget is the more generous, because that is
the key an attacker could aim at somebody else. NEITHER EVER LOCKS: a window
expires on its own, there is no admin unlock and no flag that outlives it. The
worst that can be done to a victim is delay, and only while the attacker keeps
spending their own attempts.

ONLY FAILURES COUNT, and a success clears both counters. Somebody who signs in
correctly is never throttled by their own earlier typos, and a shared office
address is not punished for having many legitimate users.

THE RESPONSE CANNOT LEAK. Counters are keyed on the SUBMITTED address, whether
or not an account exists, so a throttled response is identical for a real
address and an invented one. A 429 that appeared only for real accounts would
be exactly the account-existence oracle the uniform 401 exists to prevent.

FAILURE POLICY: FAIL CLOSED, and it costs nothing. If the counter cannot be
read or written, login is refused rather than allowed unlimited attempts. That
is normally a hard trade -- an outage becomes an authentication outage -- but
here the limiter shares its store with the credential store, so there is no
state of the world in which this table is unreachable and login could otherwise
have succeeded. Failing closed gives up nothing that was working.

A NOTE ON THE WINDOW. This is a fixed window, not sliding: the counter resets
when the window elapses. An attacker can therefore spend a full budget at the
end of one window and another at the start of the next, briefly doubling the
rate. That is a known and acceptable cost for a counter that is one row and one
statement; a sliding window needs per-attempt timestamps and a much heavier
table.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from utils.logger import get_logger

logger = get_logger(__name__)

# --- policy ---------------------------------------------------------------
# Explicit, and overridable per deployment. Environment variables rather than
# configs/settings.py because that is how auth/sessions.py already reads its
# cookie and TTL settings -- one mechanism, not two.

#: Failed sign-ins allowed per window from one client address.
IP_MAX_FAILURES = int(os.environ.get("SUBTERRA_LOGIN_IP_MAX", "10"))

#: Failed sign-ins allowed per window against one email address. Deliberately
#: the larger budget: this is the key an attacker could point at a victim, so it
#: must not be the binding constraint in ordinary use.
EMAIL_MAX_FAILURES = int(os.environ.get("SUBTERRA_LOGIN_EMAIL_MAX", "20"))

#: 15 minutes. Long enough to make grinding useless, short enough that somebody
#: who genuinely forgot their password is not locked out of their evening.
WINDOW_SECONDS = int(os.environ.get("SUBTERRA_LOGIN_WINDOW_SECONDS", "900"))

#: `request.client.host` is the peer -- behind a reverse proxy, the proxy. The
#: forwarded header is honoured ONLY when a deployment says it sits behind one,
#: because trusting it unconditionally lets any caller choose their own bucket
#: by sending a header, which does not weaken the limit so much as delete it.
#: There is no trusted-proxy configuration in this application today, so this
#: defaults off.
TRUST_PROXY_HEADERS = os.environ.get("SUBTERRA_TRUST_PROXY_HEADERS", "0") not in (
    "0", "", "false", "False",
)

#: Injectable so tests can advance time deterministically. A rate limiter tested
#: with `sleep` is a slow test that fails on a loaded machine.
_clock = time.time


def set_clock(clock) -> None:
    """Replace the time source. Tests only."""
    global _clock
    _clock = clock


def reset_clock() -> None:
    global _clock
    _clock = time.time


class RateLimitUnavailable(RuntimeError):
    """The counter could not be consulted, so the attempt must be refused."""


def client_key(request) -> str:
    """The address an attempt is charged to. See TRUST_PROXY_HEADERS."""
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the original client, by convention.
            return forwarded.split(",")[0].strip()[:200]
    client = getattr(request, "client", None)
    return (getattr(client, "host", None) or "unknown").strip()[:200]


def _bucket(scope: str, key: str) -> str:
    return f"{scope}:{key}"[:300]


#: One statement: roll the window if it has elapsed, otherwise increment, and
#: return the resulting count either way. Portable across PostgreSQL and SQLite
#: -- both support ON CONFLICT DO UPDATE and RETURNING.
_INCREMENT = text(
    """
    INSERT INTO login_attempts (bucket, window_started_at, attempts)
    VALUES (:bucket, :now, 1)
    ON CONFLICT (bucket) DO UPDATE SET
        attempts = CASE
            WHEN login_attempts.window_started_at <= :cutoff THEN 1
            ELSE login_attempts.attempts + 1
        END,
        window_started_at = CASE
            WHEN login_attempts.window_started_at <= :cutoff THEN :now
            ELSE login_attempts.window_started_at
        END
    RETURNING attempts, window_started_at
    """
)

_READ = text(
    "SELECT attempts, window_started_at FROM login_attempts WHERE bucket = :bucket"
)


def _retry_after(window_started_at: float, now: float) -> int:
    return max(1, int(window_started_at + WINDOW_SECONDS - now) + 1)


def check(db: Session, scope: str, key: str, limit: int) -> Optional[int]:
    """
    Seconds until this bucket may try again, or None if it may try now.

    Raises RateLimitUnavailable if the counter cannot be read -- the caller
    refuses the attempt rather than proceeding uncounted.
    """
    now = _clock()
    try:
        row = db.execute(_READ, {"bucket": _bucket(scope, key)}).first()
    except Exception as exc:  # noqa: BLE001 - deliberately fail closed
        logger.error("login rate-limit read failed: %s", exc)
        raise RateLimitUnavailable(str(exc)) from exc

    if row is None:
        return None
    attempts, window_started_at = row[0], float(row[1])
    if window_started_at <= now - WINDOW_SECONDS:
        return None  # the window has elapsed; the row is stale
    if attempts < limit:
        return None
    return _retry_after(window_started_at, now)


def record_failure(db: Session, scope: str, key: str) -> int:
    """Atomically count one failed attempt and return the new total."""
    now = _clock()
    try:
        row = db.execute(
            _INCREMENT,
            {"bucket": _bucket(scope, key), "now": now, "cutoff": now - WINDOW_SECONDS},
        ).first()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("login rate-limit write failed: %s", exc)
        raise RateLimitUnavailable(str(exc)) from exc
    return int(row[0]) if row else 0


def clear(db: Session, scope: str, key: str) -> None:
    """Forget a bucket. Called on a successful sign-in."""
    try:
        db.execute(
            text("DELETE FROM login_attempts WHERE bucket = :bucket"),
            {"bucket": _bucket(scope, key)},
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        # A failure here can only leave a counter that expires on its own, so
        # it is logged rather than raised: it cannot grant access.
        db.rollback()
        logger.warning("could not clear login rate-limit bucket: %s", exc)
