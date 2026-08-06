"""
M3: Position is the single source of spatial truth, and no component
depends on placeholder latitude/longitude.

The placeholder was not cosmetic. `latitude=0.0, longitude=0.0` made "at
0N 0E" and "position unknown" the same value, which produced a fabricated
0.0 m lateral extent in the evidence tier and clustered every unpositioned
dataset together off the coast of Africa during fusion. Two separate bugs
in one session traced back to code trying to tell the two apart after the
fact.

These tests assert the four position kinds coexist correctly and that no
converter needs a fake coordinate to satisfy the schema.
"""
import pytest

from schemas.spatial import (
    GeographicPosition, LocalCartesianPosition, NoPosition, OdometryPosition,
    PositionKind, ProjectedPosition, has_geographic_coordinates,
)
from schemas.subterra_record import SensorType, SubterraRecord


def _rec(**kw):
    return SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, **kw)


# --- no kind requires fake coordinates ---

@pytest.mark.parametrize("position", [
    ProjectedPosition(easting=501134.03, northing=4544705.58),
    OdometryPosition(along_track_m=12.5, path_id="run1"),
    LocalCartesianPosition(x=3.0, y=4.0),
    NoPosition(reason="instrument provides no horizontal position"),
])
def test_non_geographic_positions_need_no_latitude_longitude(position):
    r = _rec(position=position)
    assert (r.latitude, r.longitude) == (None, None)
    assert r.position == position
    assert has_geographic_coordinates(r) is False


def test_a_record_can_be_constructed_with_no_spatial_information_at_all():
    """Absence is a declaration, not an unset field."""
    r = _rec()
    assert r.position.kind == PositionKind.NONE
    assert r.position.reason
    assert (r.latitude, r.longitude) == (None, None)


# --- geographic records are unchanged, in both construction directions ---

def test_geographic_records_behave_exactly_as_before():
    r = _rec(latitude=41.05, longitude=15.01)
    assert (r.latitude, r.longitude) == (41.05, 15.01)
    assert r.position.kind == PositionKind.GEOGRAPHIC
    assert has_geographic_coordinates(r) is True


def test_a_geographic_position_populates_the_legacy_fields():
    """The bridge that keeps every existing lat/lon consumer working."""
    r = _rec(position=GeographicPosition(lat=41.05, lon=15.01))
    assert (r.latitude, r.longitude) == (41.05, 15.01)


def test_the_bridge_round_trips_through_serialization():
    for position in (GeographicPosition(lat=41.0, lon=15.0),
                     ProjectedPosition(easting=5e5, northing=4.5e6),
                     OdometryPosition(along_track_m=1.0),
                     NoPosition(reason="none")):
        r = _rec(position=position)
        back = SubterraRecord.model_validate_json(r.model_dump_json())
        assert back.position == position
        assert (back.latitude, back.longitude) == (r.latitude, r.longitude)


# --- mixed position kinds coexist ---

def test_mixed_position_kinds_survive_together():
    records = [
        _rec(latitude=41.0, longitude=15.0),
        _rec(position=ProjectedPosition(easting=5e5, northing=4.5e6)),
        _rec(position=OdometryPosition(along_track_m=2.0)),
        _rec(position=NoPosition(reason="none")),
    ]
    assert [r.position.kind for r in records] == [
        PositionKind.GEOGRAPHIC, PositionKind.PROJECTED,
        PositionKind.ODOMETRY, PositionKind.NONE,
    ]
    assert [has_geographic_coordinates(r) for r in records] == [True, False, False, False]


def test_fusion_keeps_mixed_kinds_apart():
    from fusion.sensor_fusion import fuse_datasets, multimodal_only, partition_by_spatial_ref

    records = [
        SubterraRecord(dataset_id="a", sensor_type=SensorType.GPR,
                       latitude=41.0, longitude=15.0),
        SubterraRecord(dataset_id="b", sensor_type=SensorType.SEISMIC,
                       latitude=41.0, longitude=15.0),
        SubterraRecord(dataset_id="c", sensor_type=SensorType.ERT,
                       position=OdometryPosition(along_track_m=1.0)),
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GRAVITY,
                       position=NoPosition(reason="none")),
    ]
    kinds = {p.kind for p in partition_by_spatial_ref(records)}
    assert kinds == {"geographic", "odometry", "none"}
    multi = multimodal_only(fuse_datasets(records, radius_m=50.0))
    assert len(multi) == 1
    assert set(multi[0].sensor_types) == {"gpr", "seismic"}


def test_validation_does_not_penalise_a_positionless_dataset():
    from validators.dataset_validator import validate_dataset

    positionless = [_rec(position=NoPosition(reason="format provides none"),
                         signal=[1.0], depth=0.5, timestamp="2024-01-01T00:00:00")
                    for _ in range(5)]
    geographic = [_rec(latitude=41.0, longitude=15.0, signal=[1.0], depth=0.5,
                       timestamp="2024-01-01T00:00:00") for _ in range(5)]
    a = validate_dataset(positionless, dataset_id="a")
    b = validate_dataset(geographic, dataset_id="b")
    assert a.missing_coordinates == 0
    assert a.quality_score == pytest.approx(b.quality_score)


# --- converters no longer invent coordinates ---

def test_every_converter_declares_rather_than_fabricates():
    """
    A survey of the four converters' position handling. Each must be able to
    say what it does NOT know; none may fall back to (0, 0).
    """
    import inspect

    from converters import (csv_converter, geotiff_converter, ids_dt_converter,
                            las_converter, segy_converter)

    for module in (csv_converter, geotiff_converter, ids_dt_converter,
                   las_converter, segy_converter):
        source = inspect.getsource(module)
        assert "latitude=0.0, longitude=0.0" not in source, (
            f"{module.__name__} still fabricates placeholder coordinates"
        )
