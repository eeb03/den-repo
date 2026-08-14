"""
Schema changes that `create_all` cannot make.

WHY THIS EXISTS. `Base.metadata.create_all` creates tables that are MISSING. It
never alters a table that already exists. So a new table (users, import_jobs) is
free, but a new COLUMN on a populated table is invisible to it: the model would
declare `datasets.owner_id`, SQLAlchemy would emit `SELECT datasets.owner_id`,
and the live database would answer "no such column" -- taking down the entire
datasets API and the workspace with it. That failure is silent until the first
query, which is what makes it dangerous.

WHY NOT ALEMBIC. Alembic is the right answer for a schema with real churn, and
it may well be the right answer here later. It is not the right answer for one
nullable column: it brings a migrations directory, an env.py, a version graph
and an autogenerate step whose diffs still need reading by hand. This module is
~100 lines, does one thing, and can be replaced by Alembic without any of the
data or the models changing.

WHAT IT GUARANTEES.

  - Idempotent. Every migration checks the live schema before acting, so
    running it twice, or against a database that already has the column, is a
    no-op. It is safe to call on every startup.
  - Recorded. Applied ids are written to `schema_migrations`, so the history is
    inspectable rather than inferred.
  - Additive only. Nothing here drops a column, drops a table, or rewrites a
    row. A migration that could destroy data does not belong in a function that
    runs automatically at startup.

DIALECT NOTE. PostgreSQL and SQLite both support `ALTER TABLE ... ADD COLUMN`.
Only PostgreSQL supports adding a foreign-key constraint to an existing table;
SQLite cannot, and rebuilding the table to fake it would be exactly the kind of
destructive operation this module refuses to do automatically. So a SQLite
database migrated in place gets the column and its index but not the constraint,
while a freshly created one gets all three from `create_all`. That divergence is
recorded here rather than hidden: the column is nullable and unread until
authentication exists, so nothing depends on the constraint yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    apply: Callable[[Engine], None]


def _has_table(engine: Engine, table: str) -> bool:
    return inspect(engine).has_table(table)


def _has_column(engine: Engine, table: str, column: str) -> bool:
    if not _has_table(engine, table):
        return False
    return any(c["name"] == column for c in inspect(engine).get_columns(table))


def _has_index(engine: Engine, table: str, index: str) -> bool:
    if not _has_table(engine, table):
        return False
    return any(i["name"] == index for i in inspect(engine).get_indexes(table))


def _add_dataset_owner(engine: Engine) -> None:
    """
    001 — give `datasets` the ownership column the model now declares.

    Nullable, because every existing row was uploaded before ownership existed
    and by an unauthenticated caller. A NOT NULL column would require inventing
    an owner for that data, which is precisely the fabrication this platform
    exists to avoid.
    """
    table, column, index = "datasets", "owner_id", "ix_datasets_owner_id"

    if not _has_table(engine, table):
        return  # a fresh database: create_all already built it correctly

    with engine.begin() as conn:
        if not _has_column(engine, table, column):
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR"))
            logger.info("migration 001: added %s.%s", table, column)

        if not _has_index(engine, table, index):
            conn.execute(text(f"CREATE INDEX {index} ON {table} ({column})"))
            logger.info("migration 001: created %s", index)

        # The foreign key, where the dialect can add one to an existing table.
        if engine.dialect.name == "postgresql":
            existing = {
                fk.get("name") for fk in inspect(engine).get_foreign_keys(table)
            }
            if "fk_datasets_owner_id_users" not in existing:
                conn.execute(
                    text(
                        f"ALTER TABLE {table} "
                        "ADD CONSTRAINT fk_datasets_owner_id_users "
                        f"FOREIGN KEY ({column}) REFERENCES users (id)"
                    )
                )
                logger.info("migration 001: added fk_datasets_owner_id_users")
        else:
            logger.info(
                "migration 001: %s cannot add a foreign key to an existing "
                "table; %s.%s carries the index but not the constraint",
                engine.dialect.name, table, column,
            )


def _add_user_password_hash(engine: Engine) -> None:
    """
    002 — give `users` the credential column.

    `users` was created empty by 001, deliberately without a credential because
    the choice belonged to the authentication task. That table now EXISTS, so
    `create_all` will not add the column to it: same problem as 001, one table
    along. Nullable, because a row without a hash simply cannot log in --
    `verify_password` refuses an absent hash -- which is the correct behaviour
    for any account created by some future non-password route (an invite, an
    OIDC link) that has no password to store.
    """
    table, column = "users", "password_hash"
    if not _has_table(engine, table):
        return  # fresh database: create_all built it correctly

    if not _has_column(engine, table, column):
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR"))
        logger.info("migration 002: added %s.%s", table, column)


def _password_reset_tokens(engine: Engine) -> None:
    """
    003 — the password-reset token table.

    A NEW table, so `create_all` builds it on a fresh database and this
    migration is a no-op there. It exists for databases that already have the
    other tables: create_all adds missing tables too, so strictly this is
    belt-and-braces -- but recording it in the ledger keeps the schema history
    complete and readable, which is the point of having a ledger at all.

    Additive like every migration here: it creates, and never drops or rewrites.
    """
    if _has_table(engine, "password_reset_tokens"):
        return

    from database.models import PasswordResetToken

    PasswordResetToken.__table__.create(bind=engine, checkfirst=True)
    logger.info("migration 003: created password_reset_tokens")


def _spatial_declarations(engine: Engine) -> None:
    """
    004 — the spatial declaration log.

    A NEW table, additive like every migration here. It records CLAIMS about how
    a dataset relates to the physical world; nothing in it rewrites a
    measurement, and an existing database that never receives a declaration
    behaves exactly as before.
    """
    if _has_table(engine, "spatial_declarations"):
        return

    from database.models import SpatialDeclaration

    SpatialDeclaration.__table__.create(bind=engine, checkfirst=True)
    logger.info("migration 004: created spatial_declarations")


def _acquisition_fields(engine: Engine) -> None:
    """
    005 — the acquisition fields on import_jobs.

    ADDITIVE COLUMNS ON AN EXISTING TABLE, which is the case `create_all`
    cannot handle: it creates missing tables and never alters one that exists.
    Every column is nullable, so rows written before FileDrop stay valid and
    simply report that they carry no checksum -- which is true of them.

    `ImportJob` is the acquisition record. A separate table would have been a
    second upload pipeline with its own ownership, its own failure vocabulary
    and its own drift; these four columns are what it was missing.
    """
    # `create_all` builds the whole table on a fresh database, so there is
    # nothing to alter there. On a database that predates import jobs entirely
    # there is no table either -- and ALTERing one that does not exist would
    # fail the whole migration run for a column nobody needs yet.
    if not _has_table(engine, "import_jobs"):
        return

    for column, ddl in (
        ("checksum", "VARCHAR"),
        ("content_type", "VARCHAR"),
        ("identification", "JSON"),
    ):
        if not _has_column(engine, "import_jobs", column):
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE import_jobs ADD COLUMN {column} {ddl}"))
            logger.info("migration 005: added import_jobs.%s", column)


def _devices_and_sessions(engine: Engine) -> None:
    """
    006 — devices, acquisition sessions, and the link from an acquisition.

    Two new tables (which `create_all` builds on a fresh database anyway) plus
    one additive column on `import_jobs`, which is the part `create_all` cannot
    do. `session_id` is nullable because FileDrop acquisitions have no session
    and never will: a file is a source in its own right, not a session with a
    missing device.
    """
    from database.models import AcquisitionSession, Device

    for model in (Device, AcquisitionSession):
        if not _has_table(engine, model.__tablename__):
            model.__table__.create(bind=engine, checkfirst=True)
            logger.info("migration 006: created %s", model.__tablename__)

    if _has_table(engine, "import_jobs") and not _has_column(engine, "import_jobs", "session_id"):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE import_jobs ADD COLUMN session_id VARCHAR"))
        logger.info("migration 006: added import_jobs.session_id")


def _ingest_options(engine: Engine) -> None:
    """
    007 — what the user declared about how to read the file.

    One additive nullable column, which `create_all` cannot add to an existing
    table. Persisted because it is a CLAIM that changed what the converter
    produced -- whether a raster band is elevation -- and no later inspection
    of the records could recover whether somebody said so or the modality
    inference guessed it.
    """
    if _has_table(engine, "import_jobs") and not _has_column(
            engine, "import_jobs", "ingest_options"):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE import_jobs ADD COLUMN ingest_options JSON"))
        logger.info("migration 007: added import_jobs.ingest_options")


def _device_adapter(engine: Engine) -> None:
    """
    008 — how a device's evidence is meant to arrive.

    One additive nullable column on `devices`, which `create_all` cannot add
    to a table that already exists (created by 006, before `adapter` was a
    field on the model). Nullable and never defaulted: a device migrated in
    place has an undeclared adapter, exactly as a device recorded before this
    column existed actually is. Filling it in with `file_drop` would assert a
    transport nobody declared.
    """
    if _has_table(engine, "devices") and not _has_column(engine, "devices", "adapter"):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE devices ADD COLUMN adapter JSON"))
        logger.info("migration 008: added devices.adapter")


MIGRATIONS: list[Migration] = [
    Migration(
        id="001_dataset_owner_id",
        description="add nullable datasets.owner_id, indexed, FK to users where supported",
        apply=_add_dataset_owner,
    ),
    Migration(
        id="002_user_password_hash",
        description="add nullable users.password_hash for PBKDF2 credentials",
        apply=_add_user_password_hash,
    ),
    Migration(
        id="003_password_reset_tokens",
        description="create password_reset_tokens (hashed, expiring, single-use)",
        apply=_password_reset_tokens,
    ),
    Migration(
        id="004_spatial_declarations",
        description="create spatial_declarations (append-only spatial reference claims)",
        apply=_spatial_declarations,
    ),
    Migration(
        id="005_acquisition_fields",
        description="add checksum, content_type and identification to import_jobs",
        apply=_acquisition_fields,
    ),
    Migration(
        id="006_devices_and_sessions",
        description="create devices and acquisition_sessions; link acquisitions to a session",
        apply=_devices_and_sessions,
    ),
    Migration(
        id="007_ingest_options",
        description="add ingest_options to import_jobs (user declarations about how to read a file)",
        apply=_ingest_options,
    ),
    Migration(
        id="008_device_adapter",
        description="add nullable devices.adapter (how a device's evidence is meant to arrive)",
        apply=_device_adapter,
    ),
]


def _ensure_ledger(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "  id VARCHAR PRIMARY KEY,"
                "  applied_at VARCHAR NOT NULL"
                ")"
            )
        )


def applied_migrations(engine: Engine) -> set[str]:
    if not _has_table(engine, "schema_migrations"):
        return set()
    with engine.begin() as conn:
        return {row[0] for row in conn.execute(text("SELECT id FROM schema_migrations"))}


def run_migrations(engine: Engine) -> list[str]:
    """
    Apply every pending migration. Returns the ids applied this call.

    Called from `init_db()` AFTER `create_all`, so new tables exist before a
    migration tries to reference them. Safe to call repeatedly.
    """
    _ensure_ledger(engine)
    already = applied_migrations(engine)
    ran: list[str] = []

    for migration in MIGRATIONS:
        if migration.id in already:
            continue
        migration.apply(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (id, applied_at) "
                    "VALUES (:id, :at)"
                ),
                {"id": migration.id, "at": datetime.utcnow().isoformat()},
            )
        ran.append(migration.id)
        logger.info("applied migration %s (%s)", migration.id, migration.description)

    return ran
