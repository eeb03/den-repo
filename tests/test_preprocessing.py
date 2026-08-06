from schemas.subterra_record import SubterraRecord, SensorType
from preprocessing.pipeline import normalize_signal, remove_outliers, run_pipeline, interpolate_missing_depth


def test_normalize_signal_zero_mean_unit_std():
    signal = [1.0, 2.0, 3.0, 4.0, 5.0]
    normalized = normalize_signal(signal)
    mean = sum(normalized) / len(normalized)
    assert abs(mean) < 1e-9


def test_normalize_handles_zero_variance():
    signal = [5.0, 5.0, 5.0]
    assert normalize_signal(signal) == signal


def test_remove_outliers_clips_extremes():
    signal = [1.0, 2.0, 1.5, 2.5, 1000.0]
    cleaned = remove_outliers(signal, z_thresh=1.0)
    assert max(cleaned) < 1000.0


def test_interpolate_missing_depth_fills_gaps():
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, latitude=0, longitude=0, depth=1.0),
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, latitude=0, longitude=0, depth=None),
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, latitude=0, longitude=0, depth=3.0),
    ]
    filled = interpolate_missing_depth(records)
    assert filled[1].depth == 2.0


def test_run_pipeline_end_to_end():
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR, latitude=0, longitude=0,
            signal=[1.0, 2.0, 3.0, 4.0, 5.0, 100.0],
        )
    ]
    result = run_pipeline(records)
    assert len(result[0].signal) == 6
