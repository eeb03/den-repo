"""
A fusion sample must be persistable without inventing coordinates.

`fusion_samples.center_lat/center_lon` were NOT NULL. Any sample clustered
in a non-geographic frame therefore either could not be stored at all or
had to be given placeholder coordinates -- the exact failure the Position
abstraction exists to prevent, reintroduced at the storage layer. It was
latent only because fusion currently returns geographic samples alone.
"""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from database.models import FusionSample as FusionSampleModel
from database.session import Base
from fusion.sensor_fusion import FusionSample, fuse_datasets, multimodal_only
from schemas.subterra_record import SensorType, SubterraRecord


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)(), engine


# --- the schema no longer forces coordinates ---

def test_centre_columns_are_nullable(session):
    _s, engine = session
    columns = {c["name"]: c for c in inspect(engine).get_columns("fusion_samples")}
    assert columns["center_lat"]["nullable"] is True
    assert columns["center_lon"]["nullable"] is True
    assert {"spatial_ref_kind", "center_x", "center_y"} <= set(columns)


def test_a_non_geographic_sample_persists_without_fake_coordinates(session):
    """The blocker: this used to be impossible without a placeholder."""
    s, _e = session
    s.add(FusionSampleModel(
        id="a", spatial_ref_kind="odometry", radius_m=5.0,
        center_x=12.5, center_y=0.0, dataset_ids=["ds"], sensor_types=["gpr"],
    ))
    s.commit()
    row = s.query(FusionSampleModel).one()
    assert (row.center_lat, row.center_lon) == (None, None)
    assert (row.center_x, row.spatial_ref_kind) == (12.5, "odometry")


def test_a_geographic_sample_still_persists_as_before(session):
    s, _e = session
    s.add(FusionSampleModel(
        id="b", spatial_ref_kind="geographic", center_lat=41.0, center_lon=15.0,
        radius_m=25.0, dataset_ids=["ds"], sensor_types=["gpr"],
    ))
    s.commit()
    row = s.query(FusionSampleModel).one()
    assert (row.center_lat, row.center_lon) == (41.0, 15.0)
    assert (row.center_x, row.center_y) == (None, None)


def test_spatial_ref_kind_defaults_to_geographic(session):
    s, _e = session
    s.add(FusionSampleModel(id="c", center_lat=1.0, center_lon=2.0, radius_m=1.0))
    s.commit()
    assert s.query(FusionSampleModel).one().spatial_ref_kind == "geographic"


# --- the in-memory sample mirrors it ---

def test_the_dataclass_centre_is_optional():
    sample = FusionSample(radius_m=5.0, spatial_ref_kind="odometry", center_x=3.0, center_y=0.0)
    assert (sample.center_lat, sample.center_lon) == (None, None)
    assert sample.has_geographic_centre is False


def test_geographic_fusion_output_is_unchanged():
    records = [
        SubterraRecord(dataset_id="a", sensor_type=SensorType.GPR,
                       latitude=40.0, longitude=-105.0),
        SubterraRecord(dataset_id="b", sensor_type=SensorType.SEISMIC,
                       latitude=40.0, longitude=-105.0),
    ]
    multi = multimodal_only(fuse_datasets(records, radius_m=25.0))
    assert len(multi) == 1
    sample = multi[0]
    assert sample.spatial_ref_kind == "geographic"
    assert (sample.center_lat, sample.center_lon) == (40.0, -105.0)
    assert sample.has_geographic_centre is True
    assert (sample.center_x, sample.center_y) == (None, None)


def test_a_geographic_sample_round_trips_into_the_table(session):
    s, _e = session
    records = [
        SubterraRecord(dataset_id="a", sensor_type=SensorType.GPR,
                       latitude=41.0, longitude=15.0),
        SubterraRecord(dataset_id="b", sensor_type=SensorType.ERT,
                       latitude=41.0, longitude=15.0),
    ]
    for sample in multimodal_only(fuse_datasets(records, radius_m=25.0)):
        s.add(FusionSampleModel(
            id="x", spatial_ref_kind=sample.spatial_ref_kind,
            center_lat=sample.center_lat, center_lon=sample.center_lon,
            center_x=sample.center_x, center_y=sample.center_y,
            radius_m=sample.radius_m, dataset_ids=sample.dataset_ids,
            sensor_types=sample.sensor_types,
        ))
    s.commit()
    assert s.query(FusionSampleModel).one().center_lat == 41.0


# --- the migration reports honestly on an old database ---

def test_migration_detects_an_outdated_table(tmp_path, monkeypatch):
    """A database created before this change keeps the old constraint."""
    from sqlalchemy import Column, Float, MetaData, String, Table

    old = MetaData()
    Table("fusion_samples", old,
          Column("id", String, primary_key=True),
          Column("center_lat", Float, nullable=False),
          Column("center_lon", Float, nullable=False),
          Column("radius_m", Float, nullable=False))
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    old.create_all(bind=engine)

    import scripts.migrate_fusion_sample_centre as mig
    monkeypatch.setattr(mig, "engine", engine)

    state = mig.inspect_table()
    assert state["missing_columns"] == ["spatial_ref_kind", "center_x", "center_y"]
    assert state["still_not_null"] == ["center_lat", "center_lon"]
    # SQLite cannot drop NOT NULL, so that is reported rather than emitted
    assert all("DROP NOT NULL" not in sql for sql in mig.plan(state))


def test_migration_is_a_noop_on_a_current_table(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/new.db")
    Base.metadata.create_all(bind=engine)

    import scripts.migrate_fusion_sample_centre as mig
    monkeypatch.setattr(mig, "engine", engine)

    result = mig.migrate(apply=True)
    assert result["statements"] == []
    assert result["still_not_null"] == []
    assert result["blocked_by_sqlite"] is False


def test_migration_reports_a_missing_table_rather_than_failing(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/empty.db")
    import scripts.migrate_fusion_sample_centre as mig
    monkeypatch.setattr(mig, "engine", engine)
    assert mig.migrate()["exists"] is False
