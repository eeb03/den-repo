"""
The one place identity is established, and the one place dataset access is
decided.

IDENTITY COMES FROM THE SESSION COOKIE, NEVER FROM THE REQUEST BODY. No route
accepts `user_id` or `owner_id` as an authority field. If a client sends one it
is ignored; ownership is read from the authenticated session and nowhere else.
`test_client_cannot_spoof_ownership` holds that line.

THE VISIBILITY RULE, stated once:

    a dataset is visible to an authenticated user when
        owner_id IS NULL          (system/public reference data)
     OR owner_id  = user.id       (their own)

    it is WRITABLE only when owner_id = user.id

System datasets are the six published corpora the platform was built on -- BAM,
4TU, INGV, Lazaresti. They belong to nobody because nobody uploaded them here,
and inventing an owner for them would be the same fabrication this codebase
refuses everywhere else. They are readable by any signed-in user and mutable by
none, which is what "reference data" actually means.

A dataset the caller may not see returns 404, not 403. 403 confirms the id
exists, which is a disclosure the caller has not earned.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Query, Session

from auth import sessions
from database.models import Dataset, ImportJob, User, UserSession
from database.session import get_db

UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="authentication required",
)


def _session_user(db: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    row = (
        db.query(UserSession)
        .filter(UserSession.token_hash == sessions.token_hash(token))
        .first()
    )
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at <= datetime.utcnow():
        return None
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None or not user.is_active:
        return None
    return user


def get_optional_user(
    subterra_session: Optional[str] = Cookie(default=None, alias=sessions.COOKIE_NAME),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """The signed-in user, or None. For routes that are legitimately public."""
    return _session_user(db, subterra_session)


def get_current_user(
    subterra_session: Optional[str] = Cookie(default=None, alias=sessions.COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    """
    The signed-in user, or 401. THE canonical dependency -- every protected
    route derives identity from this and from nothing else.
    """
    user = _session_user(db, subterra_session)
    if user is None:
        raise UNAUTHENTICATED
    return user


# --------------------------------------------------------------------------
# dataset access
# --------------------------------------------------------------------------

def visible_datasets(db: Session, user: User) -> Query:
    """
    Datasets this user may read, scoped IN THE QUERY rather than fetched and
    filtered afterwards -- a listing that loads every row and drops some in
    Python is one forgotten filter away from leaking them.
    """
    return db.query(Dataset).filter(
        (Dataset.owner_id.is_(None)) | (Dataset.owner_id == user.id)
    )


def visible_dataset_ids(db: Session, user: User) -> set[str]:
    return {row.id for row in visible_datasets(db, user).with_entities(Dataset.id)}


def dataset_or_404(db: Session, user: User, dataset_id: str) -> Dataset:
    dataset = (
        visible_datasets(db, user).filter(Dataset.id == dataset_id).first()
    )
    if dataset is None:
        # 404 whether it is absent or someone else's: the difference is not
        # this caller's business.
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


def require_dataset_access(
    dataset_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dataset:
    """
    Route dependency for any path carrying `{dataset_id}`. Authenticates, then
    authorises, then hands back the row so the handler need not re-query.
    """
    return dataset_or_404(db, user, dataset_id)


def require_owned_dataset(
    dataset_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dataset:
    """
    As above, but for routes that MUTATE. System datasets are readable by
    everyone and writable by no one, so a reference corpus cannot be reprocessed
    or deleted out from under every other user.
    """
    dataset = dataset_or_404(db, user, dataset_id)
    if dataset.owner_id != user.id:
        raise HTTPException(
            status_code=403,
            detail=(
                "this is system reference data and cannot be modified; "
                "import your own copy to work on it"
            ),
        )
    return dataset


def job_or_404(db: Session, user: User, job_id: str) -> ImportJob:
    """
    An import job belongs to whoever started it. Unlike datasets there is no
    system-owned case: a job with no owner predates authentication and is
    nobody's to read.
    """
    job = (
        db.query(ImportJob)
        .filter(ImportJob.id == job_id, ImportJob.owner_id == user.id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail=f"no import job {job_id!r}")
    return job
