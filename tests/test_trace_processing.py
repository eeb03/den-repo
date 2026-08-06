import numpy as np

from preprocessing.trace_processing import dewow, apply_gain, background_removal, process_gpr_traces, _reconstruct_traces_by_index
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


def _make_persample_trace_records(n_traces=6, n_samples=40, source_file="line.SGY", seed=0):
    """Mirrors SEGYConverter's real output shape: one record per (trace, depth) sample."""
    records = []
    for t in range(n_traces):
        rng = np.random.default_rng(seed + t)
        waveform = rng.normal(0, 1, n_samples)
        for s in range(n_samples):
            records.append(
                SubterraRecord(
                    dataset_id="trace-persample-test", sensor_type=SensorType.GPR,
                    latitude=45.0, longitude=25.0 + t * 0.001, depth=round(s * 0.01, 6),
                    signal=[float(waveform[s])],
                    metadata={"trace_index": t, "source_file": source_file, "sample_index": s},
                )
            )
    return records


def test_process_gpr_traces_reconstructs_and_processes_persample_records():
    records = _make_persample_trace_records(n_traces=8, n_samples=50)
    processed = process_gpr_traces(records)
    assert len(processed) == 8 * 50
    assert all("processing_applied" in r.metadata for r in processed)
    assert processed[0].metadata["processing_applied"]["dewow"] is True
    assert all(len(r.signal) == 1 for r in processed)  # per-sample shape preserved


def test_process_gpr_traces_persample_preserves_depth_and_position():
    records = _make_persample_trace_records(n_traces=4, n_samples=20)
    depths_before = [r.depth for r in records]
    positions_before = [(r.latitude, r.longitude) for r in records]

    processed = process_gpr_traces(records)

    assert [r.depth for r in processed] == depths_before
    assert [(r.latitude, r.longitude) for r in processed] == positions_before


def test_process_gpr_traces_persample_background_removal_reduces_common_banding():
    n_traces, n_samples = 20, 30
    banding = [3 * np.sin(2 * np.pi * i / 10) for i in range(n_samples)]
    records = []
    for t in range(n_traces):
        rng = np.random.default_rng(t)
        noise = rng.normal(0, 0.2, n_samples)
        for s in range(n_samples):
            records.append(
                SubterraRecord(
                    dataset_id="d", sensor_type=SensorType.GPR,
                    latitude=45.0, longitude=25.0 + t * 0.001, depth=round(s * 0.01, 6),
                    signal=[float(banding[s] + noise[s])],
                    metadata={"trace_index": t, "source_file": "line.SGY"},
                )
            )

    processed = process_gpr_traces(records, dewow_enabled=False, gain_enabled=False)

    import collections
    by_depth = collections.defaultdict(list)
    for r in processed:
        by_depth[round(r.depth, 6)].append(r.signal[0])
    mean_std_after = np.mean([np.std(v) for v in by_depth.values()])
    assert mean_std_after < 1.0  # banding (amplitude 3) removed, only small noise (0.2) left


def test_reconstruct_traces_by_index_keeps_colliding_trace_indices_from_different_files_separate():
    """
    Regression test for a real bug: SEGYConverter numbers traces 0..N-1
    independently PER FILE, so a dataset combining multiple SEG-Y lines
    (exactly what ingest_zip_from_url produces for a multi-file zip, and
    exactly the shape of the real INGV-UNISA dataset) has colliding
    trace_index values across files. Grouping by trace_index alone (the
    original bug) silently interleaved unrelated lines' samples -- e.g.
    two independent 2-trace, 4-sample lines reconstructed into 2 fake
    8-sample "traces" instead of 4 real 4-sample ones. Verified by direct
    reproduction before this fix existed.
    """
    def make_records(source_file, n_traces, n_samples):
        recs = []
        for t in range(n_traces):
            for s in range(n_samples):
                recs.append(
                    SubterraRecord(
                        dataset_id="multi-line-test", sensor_type=SensorType.GPR,
                        latitude=41.0, longitude=15.0, depth=float(s), signal=[float(s)],
                        metadata={"trace_index": t, "source_file": source_file},
                    )
                )
        return recs

    line_a = make_records("LINE_A.SGY", n_traces=2, n_samples=4)  # trace_index 0, 1
    line_b = make_records("LINE_B.SGY", n_traces=2, n_samples=4)  # trace_index 0, 1 -- COLLIDES with line_a
    combined = line_a + line_b

    by_trace = _reconstruct_traces_by_index(combined)

    assert len(by_trace) == 4, f"expected 4 independent traces (2 per file), got {len(by_trace)}"
    for key, recs in by_trace.items():
        source_files_in_trace = {r.metadata["source_file"] for r in recs}
        assert len(source_files_in_trace) == 1, f"trace {key} mixes source files: {source_files_in_trace}"
        assert len(recs) == 4, f"trace {key} has {len(recs)} samples, expected 4 (8 would mean two lines got merged)"


def test_process_gpr_traces_processes_colliding_trace_indices_from_different_files_independently():
    """
    Full end-to-end version of the regression above: two lines with
    colliding trace_index 0/1 and large, OPPOSITE-sign per-file offsets
    (+1000ish vs -1000ish) so any cross-file contamination in background
    removal produces a result far outside floating-point tolerance of the
    correct, independently-computed-per-file answer.
    """
    rng = np.random.default_rng(42)
    n_samples = 6
    line_a_traces = [rng.normal(1000, 5, n_samples) for _ in range(2)]
    line_b_traces = [rng.normal(-1000, 5, n_samples) for _ in range(2)]

    def make_records(source_file, traces):
        recs = []
        for t, trace in enumerate(traces):
            for s, val in enumerate(trace):
                recs.append(
                    SubterraRecord(
                        dataset_id="multi-line-test", sensor_type=SensorType.GPR,
                        latitude=41.0, longitude=15.0, depth=float(s), signal=[float(val)],
                        metadata={"trace_index": t, "source_file": source_file},
                    )
                )
        return recs

    line_a_records = make_records("LINE_A.SGY", line_a_traces)
    line_b_records = make_records("LINE_B.SGY", line_b_traces)
    combined = line_a_records + line_b_records

    # Ground truth computed independently (plain numpy per-file mean subtraction),
    # NOT by calling the function under test.
    expected_a = np.array(line_a_traces) - np.array(line_a_traces).mean(axis=0)
    expected_b = np.array(line_b_traces) - np.array(line_b_traces).mean(axis=0)

    processed = process_gpr_traces(combined, dewow_enabled=False, gain_enabled=False)

    def _actual(source_file, trace_idx):
        recs = sorted(
            (r for r in processed if r.metadata["source_file"] == source_file and r.metadata["trace_index"] == trace_idx),
            key=lambda r: r.depth,
        )
        return np.array([r.signal[0] for r in recs])

    for t in range(2):
        assert np.allclose(_actual("LINE_A.SGY", t), expected_a[t], atol=1e-9)
        assert np.allclose(_actual("LINE_B.SGY", t), expected_b[t], atol=1e-9)
    assert all("processing_applied" in r.metadata for r in processed)
