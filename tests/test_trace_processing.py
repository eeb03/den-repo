import numpy as np

from preprocessing.trace_processing import dewow, apply_gain, background_removal, process_gpr_traces
from schemas.subterra_record import SubterraRecord, SensorType


def test_dewow_removes_slow_drift_preserves_fast_signal():
    n = 200
    t = np.arange(n)
    drift = 5 * np.sin(2 * np.pi * t / 150)
    signal = 0.5 * np.sin(2 * np.pi * t / 8)
    trace = (drift + signal).tolist()

    dewowed = np.array(dewow(trace, window=15))
    corr = np.corrcoef(dewowed[20:-20], signal[20:-20])[0, 1]
    assert corr > 0.9


def test_dewow_noop_on_short_trace():
    trace = [1.0, 2.0, 3.0]
    assert dewow(trace, window=15) == trace


def test_background_removal_eliminates_common_banding():
    n_traces, n_samples = 30, 50
    rng = np.random.default_rng(1)
    banding = 3 * np.sin(2 * np.pi * np.arange(n_samples) / 20)
    traces = [(banding + rng.normal(0, 0.3, n_samples)).tolist() for _ in range(n_traces)]

    cleaned = np.array(background_removal(traces))
    original_mean_std = np.array(traces).mean(axis=0).std()
    cleaned_mean_std = cleaned.mean(axis=0).std()
    assert cleaned_mean_std < original_mean_std * 0.2


def test_background_removal_preserves_localized_anomaly():
    n_traces, n_samples = 30, 50
    traces = [[1.0] * n_samples for _ in range(n_traces)]
    for i in range(10, 15):
        for j in range(20, 25):
            traces[i][j] = 10.0

    cleaned = np.array(background_removal(traces))
    assert cleaned[10:15, 20:25].max() > 5


def test_gain_compensates_depth_attenuation():
    n = 100
    reflectivity = np.array([1.0 if i % 15 == 0 else 0.1 for i in range(n)])
    attenuation = np.exp(-3 * np.arange(n) / n)
    attenuated = (reflectivity * attenuation).tolist()

    gained = apply_gain(attenuated, gain_type="exponential", power=3.0)
    reflector_vals = [gained[i] for i in range(n) if i % 15 == 0]
    spread = max(reflector_vals) / min(reflector_vals)
    assert spread < 1.5


def test_gain_invalid_type_raises():
    import pytest
    with pytest.raises(ValueError):
        apply_gain([1.0, 2.0, 3.0], gain_type="not_a_real_type")


def _make_trace_records(n_traces=10, n_samples=20):
    records = []
    for i in range(n_traces):
        records.append(
            SubterraRecord(
                dataset_id="trace-test", sensor_type=SensorType.GPR,
                latitude=45.0 + i * 0.0001, longitude=25.0,
                signal=[float(x) for x in np.random.default_rng(i).normal(0, 1, n_samples)],
            )
        )
    return records


def test_process_gpr_traces_end_to_end():
    records = _make_trace_records()
    processed = process_gpr_traces(records)
    assert len(processed) == 10
    assert all("processing_applied" in r.metadata for r in processed)
    assert processed[0].metadata["processing_applied"]["dewow"] is True


def test_process_gpr_traces_noop_on_single_value_records():
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, latitude=0, longitude=0, signal=[5.0])
        for _ in range(5)
    ]
    processed = process_gpr_traces(records)
    assert all(r.signal == [5.0] for r in processed)
