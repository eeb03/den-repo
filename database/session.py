from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from configs.settings import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db():
    """
    Create all tables, then apply pending schema migrations. Idempotent.

    `create_all` only ever creates MISSING tables -- it cannot add a column to
    one that already exists. Anything of that kind lives in
    database/migrations.py and runs here, after the tables exist so a migration
    can reference them.
    """
    from database import models  # noqa: F401 - register models on Base
    from database.migrations import run_migrations

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
