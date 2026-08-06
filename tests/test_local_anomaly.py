import numpy as np
import pytest

from preprocessing.spatial_grid import _local_anomaly_grid, preprocess_spatial_grid_anomaly
from preprocessing.pipeline import run_pipeline
from schemas.subterra_record import SubterraRecord, SensorType


def test_local_anomaly_flags_injected_spike_strongly():
    rng = np.random.default_rng(3)
    grid = rng.normal(20, 2, size=(30, 30))
    grid[14:17, 14:17] += 25  # small, strong localized anomaly

    z, unreliable = _local_anomaly_grid(grid, inner_window=5, outer_window=15, min_ring_count=20)
    assert z[15, 15] > 5.0  # spike should be a strong outlier
    assert not unreliable[15, 15]


def test_local_anomaly_background_false_positive_rate_is_reasonable():
    """Statistical sanity check: pure background should not systematically trigger anomalies."""
    rng = np.random.default_rng(3)
    grid = rng.normal(20, 2, size=(60, 60))
    z, unreliable = _local_anomaly_grid(grid, inner_window=5, outer_window=15, min_ring_count=20)
    valid = ~unreliable
    frac_exceeding_3 = np.mean(np.abs(z[valid]) > 3)
    assert frac_exceeding_3 < 0.02  # well above the ~0.27% expected under normality, but bounded


def test_local_anomaly_flags_edge_cells_as_unreliable():
    grid = np.ones((10, 10)) * 5.0
    z, unreliable = _local_anomaly_grid(grid, inner_window=3, outer_window=9, min_ring_count=20)
    # corner cells have far fewer ring neighbors than interior cells
    assert unreliable[0, 0] or unreliable[9, 9]


def _make_grid_records(n_lat=20, n_lon=20, seed=0):
    rng = np.random.default_rng(seed)
    records = []
    lat0, lon0 = 45.0, 25.0
    step = 0.00001
    for i in range(n_lat):
        for j in range(n_lon):
            val = 20.0 + rng.normal(0, 2)
            records.append(
                SubterraRecord(
                    dataset_id="anomaly-test", sensor_type=SensorType.GPR,
                    latitude=lat0 + i * step, longitude=lon0 + j * step,
                    depth=0.15, signal=[val],
                )
            )
    # inject a real anomaly in the middle
    mid_idx = (10 * n_lon) + 10
    records[mid_idx].signal = [20.0 + 25.0]
    return records


def test_preprocess_spatial_grid_anomaly_end_to_end():
    records = preprocess_spatial_grid_anomaly(_make_grid_records())
    assert len(records) == 400
    # every record should have raw_signal preserved and a reliability flag
    assert all("raw_signal" in r.metadata for r in records)
    assert all("anomaly_reliable" in r.metadata for r in records)
    # the injected anomaly should end up with a distinctly high |signal| (z-score)
    max_abs_signal = max(abs(r.signal[0]) for r in records)
    assert max_abs_signal > 3.0


def test_run_pipeline_dispatches_to_local_anomaly_mode():
    records = _make_grid_records()
    result = run_pipeline(records, mode="local_anomaly")
    assert len(result) == 400
    assert all("raw_signal" in r.metadata for r in result)
