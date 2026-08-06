import numpy as np
import pytest

from schemas.subterra_record import SubterraRecord, SensorType
from preprocessing.pipeline import run_pipeline
from preprocessing.spatial_grid import preprocess_spatial_grid, _infer_decimals, _smooth_2d_nanaware


def _make_grid_records(n_lat=10, n_lon=10, depth=0.15, seed=0):
    rng = np.random.default_rng(seed)
    records = []
    lat0, lon0 = 45.0, 25.0
    step = 0.00001
    for i in range(n_lat):
        for j in range(n_lon):
            val = 20.0 + rng.normal(0, 3)
            records.append(
                SubterraRecord(
                    dataset_id="grid-test", sensor_type=SensorType.GPR,
                    latitude=lat0 + i * step, longitude=lon0 + j * step,
                    depth=depth, signal=[val],
                )
            )
    return records


def test_spatial_grid_changes_signal_using_neighbors():
    records = _make_grid_records()
    before = [r.signal[0] for r in records]
    processed = preprocess_spatial_grid(records, smoothing_window=3)
    after = [r.signal[0] for r in processed]
    assert len(after) == len(before)
    # with real neighbor-based smoothing, at least some values must change
    assert any(abs(a - b) > 1e-9 for a, b in zip(before, after))


def test_spatial_grid_record_count_preserved():
    records = _make_grid_records(n_lat=15, n_lon=20)
    processed = preprocess_spatial_grid(records)
    assert len(processed) == 15 * 20


def test_spatial_grid_groups_by_depth_layer():
    layer1 = _make_grid_records(n_lat=5, n_lon=5, depth=0.1, seed=1)
    layer2 = _make_grid_records(n_lat=5, n_lon=5, depth=0.5, seed=2)
    combined = layer1 + layer2
    processed = preprocess_spatial_grid(combined)
    assert len(processed) == 50
    depths = {round(r.depth, 2) for r in processed}
    assert depths == {0.1, 0.5}


def test_run_pipeline_dispatches_to_spatial_grid_mode():
    records = _make_grid_records()
    before = [r.signal[0] for r in records]
    result = run_pipeline(records, mode="spatial_grid")
    after = [r.signal[0] for r in result]
    assert any(abs(a - b) > 1e-9 for a, b in zip(before, after))


def test_run_pipeline_trace_mode_is_default_and_unchanged_behavior():
    # single-value signal under trace mode should be left alone by denoise/normalize
    # (z-score normalize on a length-1 array falls back to unchanged per normalize_signal)
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, latitude=0, longitude=0, signal=[42.0])
    ]
    result = run_pipeline(records)  # default mode="trace"
    assert result[0].signal == [42.0]


def test_spatial_grid_handles_irregular_gps_track_without_blowup():
    """
    Regression test: GPS-tracked survey data has near-continuous, mostly
    non-repeating lat/lon (points along scan lines, not a clean raster).
    The old decimal-rounding approach tried to preserve enough precision to
    keep points distinct, producing a pivot table with as many rows as
    points -> billions of cells for a 157k-point dataset -> OOM. This
    confirms the density-based binning fix keeps total cells proportional
    to point count instead.
    """
    rng = np.random.default_rng(7)
    n_points = 5000  # scaled down from the real 157k case for test speed
    lines = 50
    pts_per_line = n_points // lines
    records = []
    for line in range(lines):
        base_lat = 45.965665 + line * 0.0000012
        xs = np.linspace(25.871818, 25.872206, pts_per_line) + rng.normal(0, 1e-8, pts_per_line)
        ys = base_lat + rng.normal(0, 1e-9, pts_per_line)
        for x, y in zip(xs, ys):
            records.append(
                SubterraRecord(
                    dataset_id="irregular-test", sensor_type=SensorType.GPR,
                    latitude=float(y), longitude=float(x), depth=0.15,
                    signal=[float(rng.normal(20, 3))],
                )
            )

    unique_lats = len({r.latitude for r in records})
    assert unique_lats > n_points * 0.8, "test setup should produce near-continuous (irregular) coordinates"

    processed = preprocess_spatial_grid(records, smoothing_window=3)
    assert len(processed) == n_points
    # every record should have gotten a value back (no widescale data loss to empty bins)
    assert sum(1 for r in processed if r.signal) >= n_points * 0.95


def test_infer_decimals_reasonable_for_fine_grid():
    values = [45.0, 45.00001, 45.00002, 45.00003]
    decimals = _infer_decimals(np.array(values))
    assert decimals >= 5


def test_smooth_2d_nanaware_reduces_noise_variance():
    rng = np.random.default_rng(42)
    grid = np.ones((20, 20)) * 10 + rng.normal(0, 2, size=(20, 20))
    smoothed = _smooth_2d_nanaware(grid, window=5)
    assert np.nanstd(smoothed) < np.nanstd(grid)
