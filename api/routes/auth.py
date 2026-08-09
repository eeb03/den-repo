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

from auth import passwords, sessions
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
    user = db.query(User).filter(User.email == email).first()

    # Always verify something, so a missing account is not faster than a wrong
    # password.
    encoded = user.password_hash if user is not None else _DUMMY_HASH
    ok = passwords.verify_password(body.password, encoded)

    if user is None or not ok or not user.is_active:
        raise GENERIC_LOGIN_FAILURE

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
