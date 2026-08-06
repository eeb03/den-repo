from schemas.subterra_record import SubterraRecord, SensorType
from fusion.sensor_fusion import fuse_datasets, multimodal_only, haversine_m


def _rec(dataset_id, sensor_type, lat, lon):
    return SubterraRecord(
        dataset_id=dataset_id, sensor_type=sensor_type, latitude=lat, longitude=lon
    )


def test_haversine_zero_distance():
    assert haversine_m(40.0, -105.0, 40.0, -105.0) == 0.0


def test_haversine_known_distance_approx():
    # ~111km per degree of latitude
    d = haversine_m(0.0, 0.0, 1.0, 0.0)
    assert 110_000 < d < 112_000


def test_fusion_groups_colocated_multimodal_records():
    records = [
        _rec("ds_gpr", SensorType.GPR, 40.0000, -105.0000),
        _rec("ds_seismic", SensorType.SEISMIC, 40.0000, -105.0000),
        _rec("ds_mag", SensorType.MAGNETOMETER, 40.5000, -105.5000),  # far away, own cluster
    ]
    samples = fuse_datasets(records, radius_m=25.0)
    multi = multimodal_only(samples)
    assert len(multi) == 1
    assert set(multi[0].sensor_types) == {"gpr", "seismic"}


def test_fusion_empty_input():
    assert fuse_datasets([]) == []


# --- spatial partitioning ----------------------------------------------------
#
# Fusion measures distance, and a distance between two different kinds of
# position is meaningless. Before partitioning, every record carrying the
# legacy (0.0, 0.0) placeholder -- odometry runs, un-georeferenced lines,
# projected surveys -- bucketed into one cell off the coast of Africa and
# fused as if collected at one spot.

from fusion.sensor_fusion import (           # noqa: E402
    SpatialPartition, non_fusable_partitions, partition_by_spatial_ref,
)
from schemas.spatial import (                # noqa: E402
    LocalCartesianPosition, NoPosition, OdometryPosition, ProjectedPosition,
)


def _positioned(dataset_id, sensor_type, position):
    """A record whose legacy lat/lon are the placeholder, as real ones are."""
    return SubterraRecord(
        dataset_id=dataset_id, sensor_type=sensor_type,
        latitude=0.0, longitude=0.0, position=position,
    )


def test_partitions_are_grouped_by_position_kind():
    records = [
        _rec("a", SensorType.GPR, 40.0, -105.0),
        _positioned("b", SensorType.SEISMIC, OdometryPosition(along_track_m=1.0)),
        _positioned("c", SensorType.MAGNETOMETER, NoPosition(reason="no GNSS")),
    ]
    kinds = {p.kind: len(p.records) for p in partition_by_spatial_ref(records)}
    assert kinds == {"geographic": 1, "odometry": 1, "none": 1}


def test_only_geographic_partitions_are_fusable():
    records = [
        _rec("a", SensorType.GPR, 40.0, -105.0),
        _positioned("b", SensorType.SEISMIC, OdometryPosition(along_track_m=1.0)),
        _positioned("c", SensorType.ERT, ProjectedPosition(easting=5e5, northing=4.5e6)),
        _positioned("d", SensorType.GRAVITY, LocalCartesianPosition(x=1.0, y=2.0)),
        _positioned("e", SensorType.MAGNETOMETER, NoPosition(reason="none")),
    ]
    fusable = {p.kind for p in partition_by_spatial_ref(records) if p.fusable}
    assert fusable == {"geographic"}
    assert all(p.reason for p in partition_by_spatial_ref(records) if not p.fusable)


def test_placeholder_coordinates_no_longer_fuse_at_null_island():
    """
    THE BUG: three sensors with no comparable position each carry lat/lon
    (0.0, 0.0), so they used to cluster into one multimodal sample at 0N 0E.
    """
    records = [
        _positioned("gpr", SensorType.GPR, OdometryPosition(along_track_m=0.0)),
        _positioned("seis", SensorType.SEISMIC, NoPosition(reason="none")),
        _positioned("mag", SensorType.MAGNETOMETER,
                    ProjectedPosition(easting=5e5, northing=4.5e6)),
    ]
    assert fuse_datasets(records, radius_m=25.0) == []
    assert multimodal_only(fuse_datasets(records, radius_m=25.0)) == []


def test_non_geographic_records_do_not_contaminate_a_real_cluster():
    """A genuine geographic pair must not absorb unpositioned records."""
    records = [
        _rec("ds_gpr", SensorType.GPR, 40.0, -105.0),
        _rec("ds_seismic", SensorType.SEISMIC, 40.0, -105.0),
        _positioned("ds_ids", SensorType.GPR, OdometryPosition(along_track_m=5.0)),
        _positioned("ds_none", SensorType.ERT, NoPosition(reason="none")),
    ]
    multi = multimodal_only(fuse_datasets(records, radius_m=25.0))
    assert len(multi) == 1
    assert set(multi[0].sensor_types) == {"gpr", "seismic"}
    assert set(multi[0].dataset_ids) == {"ds_gpr", "ds_seismic"}


def test_excluded_records_are_reported_not_silently_dropped():
    records = [
        _rec("a", SensorType.GPR, 40.0, -105.0),
        _positioned("b", SensorType.SEISMIC, OdometryPosition(along_track_m=1.0)),
        _positioned("c", SensorType.ERT, NoPosition(reason="none")),
    ]
    excluded = non_fusable_partitions(records)
    assert {p.kind for p in excluded} == {"odometry", "none"}
    assert sum(len(p.records) for p in excluded) == 2
    for p in excluded:
        assert p.reason and p.dataset_ids and p.sensor_types


def test_a_wholly_non_geographic_input_fuses_to_nothing():
    records = [_positioned("a", SensorType.GPR, OdometryPosition(along_track_m=float(i)))
               for i in range(5)]
    assert fuse_datasets(records) == []


def test_geographic_fusion_behaviour_is_unchanged():
    """The existing path must produce exactly what it always did."""
    records = [
        _rec("ds_gpr", SensorType.GPR, 40.0000, -105.0000),
        _rec("ds_seismic", SensorType.SEISMIC, 40.0000, -105.0000),
        _rec("ds_mag", SensorType.MAGNETOMETER, 40.5000, -105.5000),
    ]
    samples = fuse_datasets(records, radius_m=25.0)
    multi = multimodal_only(samples)
    assert len(multi) == 1
    assert set(multi[0].sensor_types) == {"gpr", "seismic"}
    assert multi[0].center_lat == 40.0 and multi[0].center_lon == -105.0


def test_partition_helpers_expose_dataset_and_sensor_summaries():
    p = SpatialPartition(kind="odometry", records=[
        _positioned("d1", SensorType.GPR, OdometryPosition(along_track_m=0.0)),
        _positioned("d2", SensorType.SEISMIC, OdometryPosition(along_track_m=1.0)),
    ])
    assert p.dataset_ids == ["d1", "d2"]
    assert p.sensor_types == ["gpr", "seismic"]


def test_kmz_georeferenced_records_are_fusable():
    """
    REGRESSION: KMZ georeferencing writes real lat/lon while `position` keeps
    what the file itself reported. Keying partitioning on `position.kind`
    alone excluded these records from fusion despite their coordinates being
    perfectly usable -- caught by the end-to-end interpretation test.
    """
    from schemas.spatial import has_geographic_coordinates

    gpr = SubterraRecord(
        dataset_id="ds_gpr", sensor_type=SensorType.GPR,
        latitude=41.05, longitude=15.01, signal=[1.0],
        position=ProjectedPosition(easting=501134.0, northing=4544705.0),
        metadata={"georeferenced_from_kmz": True},
    )
    seismic = _rec("ds_seismic", SensorType.SEISMIC, 41.05, 15.01)

    assert has_geographic_coordinates(gpr) is True
    kinds = {p.kind: len(p.records) for p in partition_by_spatial_ref([gpr, seismic])}
    assert kinds == {"geographic": 2}
    multi = multimodal_only(fuse_datasets([gpr, seismic], radius_m=50.0))
    assert len(multi) == 1
    assert set(multi[0].sensor_types) == {"gpr", "seismic"}


def test_a_projected_record_without_a_track_is_still_excluded():
    """The KMZ flag is what makes coordinates real -- not the projected position."""
    from schemas.spatial import has_geographic_coordinates

    r = _positioned("ds", SensorType.GPR, ProjectedPosition(easting=5e5, northing=4.5e6))
    assert has_geographic_coordinates(r) is False
    assert [p.kind for p in partition_by_spatial_ref([r])] == ["projected"]
