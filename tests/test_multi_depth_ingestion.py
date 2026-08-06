import numpy as np

from schemas.subterra_record import SubterraRecord, SensorType
from preprocessing.spatial_grid import list_available_depths


def _make_records(depth, n=20, seed=0):
    rng = np.random.default_rng(seed)
    return [
        SubterraRecord(
            dataset_id="multi-depth-test", sensor_type=SensorType.GPR,
            latitude=45.0 + i * 0.0001, longitude=25.0, depth=depth,
            signal=[float(rng.normal(20, 2))],
        )
        for i in range(n)
    ]


def test_merging_records_from_multiple_depths_preserves_all():
    """Mirrors what _run_depth_slice_pipeline does: existing_records + new_records, saved as one dataset."""
    layer1 = _make_records(depth=0.5, n=20, seed=1)
    layer2 = _make_records(depth=1.0, n=25, seed=2)
    combined = layer1 + layer2

    assert len(combined) == 45
    depths = list_available_depths(combined)
    assert {"depth": 0.5, "count": 20} in depths
    assert {"depth": 1.0, "count": 25} in depths


def test_duplicate_depth_detection_logic():
    """Mirrors the 409-conflict guard: same rounding used to detect an existing depth."""
    existing = _make_records(depth=0.5, n=10)
    existing_depths = {round(r.depth, 4) for r in existing if r.depth is not None}

    assert round(0.5, 4) in existing_depths
    assert round(0.50001, 4) in existing_depths  # rounds to the same 4dp value -- correctly flagged as duplicate
    assert round(1.0, 4) not in existing_depths


def test_three_depth_layers_all_distinct_and_countable():
    layers = [_make_records(depth=d, n=10 + i, seed=i) for i, d in enumerate([0.1, 0.5, 1.0])]
    combined = [r for layer in layers for r in layer]
    depths = list_available_depths(combined)
    assert len(depths) == 3
    assert sum(d["count"] for d in depths) == len(combined)
