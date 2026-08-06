import numpy as np

from preprocessing.spatial_grid import build_grid_for_records, list_available_depths
from schemas.subterra_record import SubterraRecord, SensorType


def _make_grid_records(n_lat=10, n_lon=15, depth=0.15, elevation_base=500.0, seed=0):
    rng = np.random.default_rng(seed)
    records = []
    lat0, lon0 = 45.0, 25.0
    step = 0.00001
    for i in range(n_lat):
        for j in range(n_lon):
            records.append(
                SubterraRecord(
                    dataset_id="grid-display-test", sensor_type=SensorType.GPR,
                    latitude=lat0 + i * step, longitude=lon0 + j * step,
                    depth=depth, elevation=elevation_base + i * 0.1,
                    signal=[float(rng.normal(20, 2))],
                    metadata={"absolute_elevation_m": elevation_base + i * 0.1 - depth},
                )
            )
    return records


def test_build_grid_for_records_signal_field():
    records = _make_grid_records(n_lat=10, n_lon=15)
    grid, lat_centers, lon_centers, depth = build_grid_for_records(records, field="signal")
    assert grid.shape == (10, 15)
    assert len(lat_centers) == 10
    assert len(lon_centers) == 15
    assert depth == 0.15


def test_build_grid_for_records_elevation_field_matches_shape():
    records = _make_grid_records(n_lat=8, n_lon=12)
    signal_grid, _, _, _ = build_grid_for_records(records, field="signal")
    elev_grid, _, _, _ = build_grid_for_records(records, field="elevation")
    assert signal_grid.shape == elev_grid.shape
    # elevation should increase along the lat axis as constructed
    assert np.nanmean(elev_grid[-1]) > np.nanmean(elev_grid[0])


def test_build_grid_for_records_absolute_elevation_field():
    records = _make_grid_records(n_lat=5, n_lon=5, elevation_base=600.0)
    grid, _, _, _ = build_grid_for_records(records, field="absolute_elevation_m")
    assert not np.isnan(grid).all()
    assert np.nanmean(grid) > 590  # roughly elevation_base minus small depth


def test_build_grid_picks_nearest_depth_when_multiple_present():
    layer1 = _make_grid_records(n_lat=5, n_lon=5, depth=0.1, seed=1)
    layer2 = _make_grid_records(n_lat=5, n_lon=5, depth=1.5, seed=2)
    combined = layer1 + layer2
    _, _, _, chosen_depth = build_grid_for_records(combined, depth=0.2)
    assert chosen_depth == 0.1  # nearest to 0.2 is 0.1, not 1.5


def test_build_grid_defaults_to_densest_layer_when_no_depth_given():
    layer1 = _make_grid_records(n_lat=5, n_lon=5, depth=0.1, seed=1)
    layer2 = _make_grid_records(n_lat=8, n_lon=8, depth=1.5, seed=2)  # more records
    combined = layer1 + layer2
    _, _, _, chosen_depth = build_grid_for_records(combined)
    assert chosen_depth == 1.5


def test_list_available_depths():
    layer1 = _make_grid_records(n_lat=3, n_lon=3, depth=0.1, seed=1)
    layer2 = _make_grid_records(n_lat=4, n_lon=4, depth=0.5, seed=2)
    combined = layer1 + layer2
    depths = list_available_depths(combined)
    assert {"depth": 0.1, "count": 9} in depths
    assert {"depth": 0.5, "count": 16} in depths
