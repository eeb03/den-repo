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
