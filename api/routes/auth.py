"""
Register, log in, log out, and say who you are.

WHAT THE CLIENT NEVER SENDS. There is no `user_id` or `owner_id` field on any
request here or anywhere else. Identity comes from the session cookie and from
nothing the caller can type.

WHY LOGIN FAILURES ARE UNIFORM. `POST /login` answers "invalid email or
password" whether the account is absent, the password is wrong, or the account
is disabled. Distinguishing them turns the endpoint into an account-existence
oracle, which is how credential-stuffing lists get validated. The verification
also runs against a dummy hash when no user is found, so a missing account and a
wrong password take comparable time and the timing does not leak the answer the
message withholds.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import mailer, passwords, rate_limit, reset, sessions
from auth.dependencies import get_current_user, get_optional_user
from database.models import User, UserSession, gen_uuid
from database.session import get_db
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

#: Deliberately permissive: this checks the address is well-formed enough to be
#: a login identifier, not that it can receive mail. Rejecting valid-but-unusual
#: addresses is a worse failure than accepting one that never gets used.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

#: Verified against when no account matches, so the timing of a failed login
#: does not reveal whether the address exists. Computed once at import.
_DUMMY_HASH = passwords.hash_password("not-a-real-password-placeholder")

GENERIC_LOGIN_FAILURE = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid email or password",
)


def _too_many(retry_after: int) -> HTTPException:
    """
    429 with Retry-After.

    The message says nothing about the account, and is identical for a
    registered address and an invented one -- a 429 that appeared only for real
    accounts would be exactly the existence oracle the uniform 401 prevents. It
    also names no storage: an error mentioning a table or a backend tells an
    attacker about the deployment and the user nothing.
    """
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="too many sign-in attempts. Please wait and try again.",
        headers={"Retry-After": str(retry_after)},
    )


#: Fail closed. Refusing the attempt costs nothing that was working: the counter
#: shares its database with the credential store, so there is no state in which
#: this is unreachable and the sign-in could otherwise have succeeded.
_LIMITER_DOWN = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="sign-in is temporarily unavailable. Please try again shortly.",
    headers={"Retry-After": "30"},
)


class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=320)
    password: str = Field(..., max_length=passwords.MAX_PASSWORD_LENGTH)
    display_name: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=320)
    password: str = Field(..., max_length=passwords.MAX_PASSWORD_LENGTH)


def _public(user: User) -> dict:
    """What the browser is allowed to know about an account. Never the hash."""
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _start_session(db: Session, user: User, request: Request, response: Response) -> None:
    token = sessions.new_token()
    db.add(
        UserSession(
            id=gen_uuid(),
            user_id=user.id,
            token_hash=sessions.token_hash(token),
            expires_at=sessions.expiry_from(),
            user_agent=(request.headers.get("user-agent") or "")[:300],
        )
    )
    db.commit()
    sessions.set_session_cookie(response, token)


@router.post("/register", status_code=201)
def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    email = (body.email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="a valid email address is required")

    try:
        passwords.validate_password(body.password)
    except passwords.WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if db.query(User).filter(User.email == email).first() is not None:
        # Registration cannot hide that an address is taken -- the account
        # could not be created either way -- so this one says so plainly
        # rather than failing in a way the user cannot act on.
        raise HTTPException(status_code=409, detail="an account with this email already exists")

    user = User(
        id=gen_uuid(),
        email=email,
        display_name=(body.display_name or "").strip() or None,
        password_hash=passwords.hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _start_session(db, user, request, response)
    logger.info("registered user %s", user.id)
    return {"user": _public(user)}


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    email = (body.email or "").strip().lower()
    ip = rate_limit.client_key(request)

    # Checked BEFORE the password is verified: the point is to stop spending
    # 600k PBKDF2 iterations on an attacker's behalf, not merely to withhold
    # the answer afterwards. Both dimensions are consulted -- see
    # auth/rate_limit.py for why either alone is the wrong key.
    try:
        for scope, key, limit in (
            ("ip", ip, rate_limit.IP_MAX_FAILURES),
            ("email", email, rate_limit.EMAIL_MAX_FAILURES),
        ):
            retry_after = rate_limit.check(db, scope, key, limit)
            if retry_after is not None:
                raise _too_many(retry_after)
    except rate_limit.RateLimitUnavailable:
        raise _LIMITER_DOWN

    user = db.query(User).filter(User.email == email).first()

    # Always verify something, so a missing account is not faster than a wrong
    # password.
    encoded = user.password_hash if user is not None else _DUMMY_HASH
    ok = passwords.verify_password(body.password, encoded)

    if user is None or not ok or not user.is_active:
        # Only FAILURES are counted, so a correct sign-in is never throttled by
        # the user's own earlier typos. Counted for the submitted address
        # whether or not it exists, so the counter is not an oracle either.
        try:
            rate_limit.record_failure(db, "ip", ip)
            rate_limit.record_failure(db, "email", email)
        except rate_limit.RateLimitUnavailable:
            raise _LIMITER_DOWN
        raise GENERIC_LOGIN_FAILURE

    rate_limit.clear(db, "ip", ip)
    rate_limit.clear(db, "email", email)
    _start_session(db, user, request, response)
    return {"user": _public(user)}


@router.post("/logout")
def logout(
    response: Response,
    subterra_session: Optional[str] = None,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
    request: Request = None,  # type: ignore[assignment]
):
    """
    Revoke this session server-side and clear the cookie.

    Revoking the row is the part that matters: clearing the cookie alone would
    leave a token that still authenticates if it was captured, which is the
    failure mode that makes stateless tokens awkward to log out of.
    """
    token = request.cookies.get(sessions.COOKIE_NAME) if request else None
    if token:
        row = (
            db.query(UserSession)
            .filter(UserSession.token_hash == sessions.token_hash(token))
            .first()
        )
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.utcnow()
            db.commit()

    sessions.clear_session_cookie(response)
    # 200 whether or not there was a session: logging out of nothing is not an
    # error, and saying so would report whether the token was valid.
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """The signed-in account. 401 when there is none."""
    return {"user": _public(user)}


# ---------------------------------------------------------------------------
# password reset
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., max_length=512)
    password: str = Field(..., max_length=passwords.MAX_PASSWORD_LENGTH)
    password_confirmation: str = Field(..., max_length=passwords.MAX_PASSWORD_LENGTH)


#: The one answer `forgot-password` ever gives. Identical for a registered
#: address, an unregistered one, a malformed one, and one whose email failed to
#: send -- because any difference between them is an account-existence oracle,
#: and this endpoint is unauthenticated so anyone may ask it anything.
_RESET_ACKNOWLEDGEMENT = {
    "message": (
        "If an account exists for that address, a password reset link has been sent."
    )
}

#: Deliberately the same message for a token that never existed, one that
#: expired, one already used, and one that is malformed. Distinguishing them
#: tells an attacker which guesses were close.
_INVALID_RESET_TOKEN = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="This password reset link is invalid or has expired. Please request a new one.",
)


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Begin a password reset. Always answers the same thing.

    The work happens only if the account exists, but the RESPONSE does not
    depend on that: same status, same body, same shape. Nothing about the user,
    the token or the link is returned -- the token reaches the person through
    the mailer and by no other route.
    """
    email = (body.email or "").strip().lower()
    ip = rate_limit.client_key(request)

    # Abuse control, separate from the login limiter: this is a ceiling on how
    # many emails a stranger can cause, not a count of failed credentials. A
    # throttled caller still gets the generic acknowledgement, because a 429
    # here would say "this address is worth throttling" -- which is the oracle
    # the generic response exists to prevent.
    throttled = False
    try:
        for scope, key, limit in (
            ("reset_ip", ip, rate_limit.RESET_IP_MAX),
            ("reset_email", email, rate_limit.RESET_EMAIL_MAX),
        ):
            if rate_limit.check(db, scope, key, limit, rate_limit.RESET_WINDOW_SECONDS) is not None:
                throttled = True
        rate_limit.record_failure(db, "reset_ip", ip, rate_limit.RESET_WINDOW_SECONDS)
        rate_limit.record_failure(db, "reset_email", email, rate_limit.RESET_WINDOW_SECONDS)
    except rate_limit.RateLimitUnavailable:
        # Fail closed on the SIDE EFFECT, not on the response: no email is sent,
        # and the caller still cannot tell whether the address exists.
        throttled = True

    if throttled or not EMAIL_RE.match(email):
        return _RESET_ACKNOWLEDGEMENT

    user = db.query(User).filter(User.email == email).first()
    if user is not None and user.is_active:
        token = reset.issue(db, user.id)
        try:
            mailer.get_mailer().send_password_reset(user.email, reset.reset_url(token))
        except Exception as exc:  # noqa: BLE001
            # Logged WITHOUT the token or the link, and swallowed: a delivery
            # failure must not become a way to detect that the account exists.
            logger.error("password reset email could not be sent: %s", exc)

    return _RESET_ACKNOWLEDGEMENT


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Consume a reset token and set a new password.

    Order matters. The password is validated BEFORE the token is consumed, so a
    weak password does not burn the link and strand the user; the token is then
    claimed atomically, so two simultaneous submissions cannot both succeed.
    """
    if body.password != body.password_confirmation:
        raise HTTPException(status_code=422, detail="the two passwords do not match")

    # The existing policy, reused rather than restated -- a second copy would
    # drift and one endpoint would quietly accept what the other refuses.
    try:
        passwords.validate_password(body.password)
    except passwords.WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user_id = reset.consume(db, body.token)
    if user_id is None:
        raise _INVALID_RESET_TOKEN

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise _INVALID_RESET_TOKEN

    user.password_hash = passwords.hash_password(body.password)
    db.commit()

    # Every signed-in browser ends here. A reset usually means the password was
    # lost or is believed compromised; sessions surviving it would preserve
    # exactly the access it is meant to remove.
    reset.revoke_all_sessions(db, user.id)

    # The ACCOUNT-level failed-login counter is cleared: somebody who just
    # proved control of the address should not then be locked out by their own
    # earlier attempts to remember the old password.
    #
    # The per-ADDRESS counter is deliberately left alone. Clearing it would let
    # an attacker wipe the budget they had spent guessing at other accounts,
    # simply by resetting a password on an account they control -- turning the
    # recovery flow into a way to refill an attack.
    rate_limit.clear(db, "email", user.email)

    logger.info("password reset completed for user %s", user.id)
    return {"message": "Your password has been changed. Please sign in."}
