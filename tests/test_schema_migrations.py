"""
The migration mechanism, and the specific failure it exists to prevent.

`create_all` creates missing TABLES and never alters an existing one. So the
moment `Dataset` declared `owner_id`, every database created before that change
became one query away from `no such column: datasets.owner_id` -- which would
take out the dataset listing, the workspace and the import report together.

The decisive test here is `test_a_pre_ownership_database_is_repaired`: it builds
a database with the OLD schema, proves the new model cannot query it, runs the
migration, and proves it can. Without that test the migration could quietly stop
working and nothing would notice until a deployment broke.
"""
from datetime import datetime

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from database.migrations import MIGRATIONS, applied_migrations, run_migrations
from database.models import AcquisitionSession, Dataset, Device, ImportJob, User
from database.session import Base


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'm.db'}")


def _legacy_datasets_table(engine):
    """
    The `datasets` table exactly as it existed BEFORE ownership.

    Derived from the current model minus `owner_id`, rather than hand-listing
    columns: a hand-written copy drifts as the model grows, and then the query
    below fails on some OTHER missing column and the test passes for the wrong
    reason. That is precisely what happened on the first attempt here -- it
    tripped on `datasets.source` and proved nothing about ownership.
    """
    meta = MetaData()
    Table(
        "datasets",
        meta,
        *[
            Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
            for c in Dataset.__table__.columns
            if c.name != "owner_id"
        ],
    )
    meta.create_all(bind=engine)


# --- the failure this prevents --------------------------------------------

def test_a_pre_ownership_database_is_repaired(engine):
    _legacy_datasets_table(engine)
    assert not _has_column(engine, "datasets", "owner_id")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO datasets (id, name, sensor_type, original_format) "
                "VALUES ('d1', 'existing survey', 'gpr', 'segy')"
            )
        )

    Session = sessionmaker(bind=engine)

    # Before the migration the new model cannot read the old table at all.
    with Session() as s, pytest.raises(Exception) as excinfo:
        s.query(Dataset).all()
    assert "owner_id" in str(excinfo.value)

    Base.metadata.create_all(bind=engine)     # brings in users, import_jobs
    run_migrations(engine)

    # After it, the existing row is intact and readable, and unowned.
    with Session() as s:
        rows = s.query(Dataset).all()
        assert len(rows) == 1
        assert rows[0].name == "existing survey"
        assert rows[0].owner_id is None


def _legacy_devices_table(engine):
    """The `devices` table exactly as migration 006 created it, before
    `adapter` was a field on the model."""
    meta = MetaData()
    Table(
        "devices",
        meta,
        *[
            Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
            for c in Device.__table__.columns
            if c.name != "adapter"
        ],
    )
    meta.create_all(bind=engine)


def test_a_pre_adapter_device_database_is_repaired(engine):
    _legacy_devices_table(engine)
    assert not _has_column(engine, "devices", "adapter")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO devices (id, device_type, capabilities, identity_source, kind) "
                "VALUES ('dev1', 'gpr', '{}', 'user_declared', 'physical')"
            )
        )

    Session = sessionmaker(bind=engine)

    # Before the migration the new model cannot read the old table at all.
    with Session() as s, pytest.raises(Exception) as excinfo:
        s.query(Device).all()
    assert "adapter" in str(excinfo.value)

    Base.metadata.create_all(bind=engine)     # brings in the other tables
    run_migrations(engine)

    # After it, the existing row is intact, readable, and its adapter is
    # undeclared -- never filled in with file_drop.
    with Session() as s:
        rows = s.query(Device).all()
        assert len(rows) == 1
        assert rows[0].device_type == "gpr"
        assert rows[0].adapter is None


def _legacy_sessions_table(engine):
    """The `acquisition_sessions` table exactly as migration 006 created it,
    before `survey_area` was a field on the model."""
    meta = MetaData()
    Table(
        "acquisition_sessions",
        meta,
        *[
            Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
            for c in AcquisitionSession.__table__.columns
            if c.name != "survey_area"
        ],
    )
    meta.create_all(bind=engine)


def test_a_pre_survey_area_session_database_is_repaired(engine):
    _legacy_sessions_table(engine)
    assert not _has_column(engine, "acquisition_sessions", "survey_area")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO acquisition_sessions "
                "(id, device_id, state, evidence) "
                "VALUES ('s1', 'dev1', 'CREATED', '{}')"
            )
        )

    Session = sessionmaker(bind=engine)

    with Session() as s, pytest.raises(Exception) as excinfo:
        s.query(AcquisitionSession).all()
    assert "survey_area" in str(excinfo.value)

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    # After it, the existing session is intact, readable, and its survey
    # area is undeclared -- never backfilled with a site name.
    with Session() as s:
        rows = s.query(AcquisitionSession).all()
        assert len(rows) == 1
        assert rows[0].state == "CREATED"
        assert rows[0].survey_area is None


def _legacy_sessions_table_without_coordinate_system(engine):
    """The `acquisition_sessions` table with `survey_area` (009) already
    applied, but before `coordinate_system` (010) was a field."""
    meta = MetaData()
    Table(
        "acquisition_sessions",
        meta,
        *[
            Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
            for c in AcquisitionSession.__table__.columns
            if c.name != "coordinate_system"
        ],
    )
    meta.create_all(bind=engine)


def test_a_pre_coordinate_system_session_database_is_repaired(engine):
    _legacy_sessions_table_without_coordinate_system(engine)
    assert not _has_column(engine, "acquisition_sessions", "coordinate_system")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO acquisition_sessions "
                "(id, device_id, state, evidence) "
                "VALUES ('s1', 'dev1', 'CREATED', '{}')"
            )
        )

    Session = sessionmaker(bind=engine)

    with Session() as s, pytest.raises(Exception) as excinfo:
        s.query(AcquisitionSession).all()
    assert "coordinate_system" in str(excinfo.value)

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    # After it, the existing session is intact, readable, and its
    # coordinate system is undeclared -- never backfilled with EPSG:4326 or
    # anything else.
    with Session() as s:
        rows = s.query(AcquisitionSession).all()
        assert len(rows) == 1
        assert rows[0].state == "CREATED"
        assert rows[0].coordinate_system is None


def _has_column(engine, table, column) -> bool:
    if not inspect(engine).has_table(table):
        return False
    return any(c["name"] == column for c in inspect(engine).get_columns(table))


# --- properties of the mechanism ------------------------------------------

def test_migrations_are_idempotent(engine):
    Base.metadata.create_all(bind=engine)

    first = run_migrations(engine)
    second = run_migrations(engine)
    third = run_migrations(engine)

    assert first == [m.id for m in MIGRATIONS]
    assert second == [] and third == []
    assert applied_migrations(engine) == {m.id for m in MIGRATIONS}


def test_the_ledger_records_what_ran(engine):
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    with engine.begin() as conn:
        rows = list(conn.execute(text("SELECT id, applied_at FROM schema_migrations")))
    assert {r[0] for r in rows} == {m.id for m in MIGRATIONS}
    assert all(r[1] for r in rows), "every applied migration records a timestamp"


def test_a_fresh_database_gets_ownership_from_create_all(engine):
    """A new deployment needs no migration to be correct."""
    Base.metadata.create_all(bind=engine)
    assert _has_column(engine, "datasets", "owner_id")
    assert _has_column(engine, "import_jobs", "owner_id")
    assert inspect(engine).has_table("users")


def test_the_owner_column_is_indexed(engine):
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    names = {i["name"] for i in inspect(engine).get_indexes("datasets")}
    assert any("owner_id" in (n or "") for n in names), names


def test_migrations_are_additive_only(engine):
    """
    Nothing in this module may drop a column, drop a table or rewrite rows: it
    runs automatically at startup, where a destructive statement would be
    catastrophic and unreviewed.
    """
    import inspect as pyinspect

    from database import migrations

    source = pyinspect.getsource(migrations).lower()
    for destructive in ("drop table", "drop column", "delete from", "truncate", "update "):
        assert destructive not in source, f"migrations contain {destructive!r}"


# --- ownership schema is prepared, not enforced ---------------------------

def test_ownership_is_nullable_and_unset(engine):
    """
    The platform has no authentication, so nothing may claim an owner. A
    default of "default-user" here would make every dataset look owned by
    somebody who does not exist.
    """
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    Session = sessionmaker(bind=engine)

    with Session() as s:
        s.add(Dataset(id="d1", name="n", sensor_type="gpr", original_format="csv"))
        s.add(ImportJob(id="j1"))
        s.commit()

    with Session() as s:
        assert s.query(Dataset).one().owner_id is None
        assert s.query(ImportJob).one().owner_id is None

    assert Dataset.__table__.c.owner_id.nullable
    assert ImportJob.__table__.c.owner_id.nullable
    assert Dataset.__table__.c.owner_id.default is None
    assert ImportJob.__table__.c.owner_id.default is None


def test_no_code_invents_a_placeholder_owner():
    """Guards against a 'default-user' creeping in to populate the column."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for rel in ("api", "database", "jobs"):
        for path in (root / rel).rglob("*.py"):
            source = path.read_text().lower()
            for placeholder in ('owner_id="default', "owner_id='default",
                                'owner_id="anonymous', "owner_id='anonymous",
                                'owner_id="system', "owner_id='system"):
                assert placeholder not in source, f"{path} fabricates an owner"


def test_the_user_table_carries_exactly_one_credential_column(engine):
    """
    Superseded assertion, updated rather than deleted.

    When this table was introduced it deliberately had NO credential column,
    because the choice belonged to the authentication task, and a test held
    that line. Authentication has since landed and chosen: a single
    `password_hash` holding a PBKDF2 digest. The test now pins the new truth --
    that one credential column exists and that no OTHER secret has crept in
    beside it, which is the failure worth catching from here on.
    """
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("users")}

    assert {"id", "email", "is_active", "password_hash"} <= columns
    for other_secret in ("password", "hashed_password", "token", "secret", "api_key"):
        assert other_secret not in columns


def test_ownership_links_to_a_real_user_when_one_exists(engine):
    """The relationship works; nothing populates it automatically."""
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    Session = sessionmaker(bind=engine)

    with Session() as s:
        s.add(User(id="u1", email="a@example.test", display_name="A"))
        s.add(Dataset(id="d1", name="n", sensor_type="gpr",
                      original_format="csv", owner_id="u1"))
        s.commit()

    with Session() as s:
        dataset = s.query(Dataset).one()
        assert dataset.owner_id == "u1"
        assert dataset.owner.email == "a@example.test"
        assert [d.id for d in s.query(User).one().datasets] == ["d1"]
