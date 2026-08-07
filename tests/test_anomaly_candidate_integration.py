"""
Integration test for the anomaly-candidate detector at REAL survey
dimensions: 482 depth samples x 72 traces (C1T_7,5_0001) and 482 x 66
(C1T_7,5_0002), run through the actual existing pipeline stages
(georeference -> trace preprocessing -> trace-local anomaly detection)
before candidate grouping/characterization -- not just small synthetic
grids built by hand.
"""
import numpy as np
import pytest

from schemas.subterra_record import SubterraRecord, SensorType
from ingestion.kmz_georeference import georeference_records_by_trace
from preprocessing.trace_processing import process_gpr_traces
from preprocessing.spatial_grid import preprocess_trace_local_anomaly
from interpretation.anomaly_candidates import find_anomaly_candidates, find_anomaly_candidates_all_lines

N_DEPTHS = 482
MAX_DEPTH_M = 7.04665  # matches the real C1T_7,5_0001/0002 depth range
N_TRACES_LINE_A = 72   # matches real C1T_7,5_0001
N_TRACES_LINE_B = 66   # matches real C1T_7,5_0002


def _make_line_records(source_file, n_traces, seed, dataset_id="multiline-integration-test"):
    """Mirrors SEGYConverter's exact pre-georeferencing output shape."""
    records = []
    depths = np.linspace(0, MAX_DEPTH_M, N_DEPTHS)
    for t in range(n_traces):
        rng = np.random.default_rng(seed + t)
        waveform = rng.normal(0, 1, N_DEPTHS)
        for s, depth in enumerate(depths):
            records.append(
                SubterraRecord(
                    dataset_id=dataset_id, sensor_type=SensorType.GPR,
                    latitude=0.0, longitude=0.0, depth=float(depth),
                    signal=[float(waveform[s])],
                    metadata={"source_file": source_file, "trace_index": t, "sample_index": s},
                )
            )
    return records


def _inject_anomaly(records, source_file, center_trace, center_sample_idx, magnitude, half_width=3):
    for r in records:
        if (
            r.metadata["source_file"] == source_file
            and center_trace - half_width <= r.metadata["trace_index"] <= center_trace + half_width
            and r.metadata["sample_index"] == center_sample_idx
        ):
            r.signal = [r.signal[0] + magnitude]
    return records


def _synthetic_kmz_path(offset=0.0):
    return [(15.0133 + offset, 41.0535 + offset), (15.0134 + offset, 41.0536 + offset), (15.0135 + offset, 41.0537 + offset)]


def test_candidate_detection_at_real_dimensions_across_two_independent_lines():
    line_a = _make_line_records("C1T_7,5_0001.SGY", N_TRACES_LINE_A, seed=100)
    line_b = _make_line_records("C1T_7,5_0002.SGY", N_TRACES_LINE_B, seed=200)

    # inject one clear anomaly into line A only, well away from any edge
    line_a = _inject_anomaly(line_a, "C1T_7,5_0001.SGY", center_trace=36, center_sample_idx=241, magnitude=20.0)

    combined = line_a + line_b
    assert len(combined) == (N_TRACES_LINE_A + N_TRACES_LINE_B) * N_DEPTHS

    # 1. georeferencing, exactly as ingest_zip_from_url does it -- per file
    georeference_records_by_trace(line_a, _synthetic_kmz_path(offset=0.0))
    georeference_records_by_trace(line_b, _synthetic_kmz_path(offset=0.01))
    combined = line_a + line_b

    # 2. trace preprocessing (dewow / background removal / gain), across both colliding-trace_index lines at once
    combined = process_gpr_traces(combined)

    # 3. trace-local anomaly detection, default axis-aware windows
    combined = preprocess_trace_local_anomaly(combined)

    # 4. candidate detection must never cross source_file boundaries
    result = find_anomaly_candidates_all_lines(combined, threshold=3.0, min_cells=3)
    assert set(result.keys()) == {"C1T_7,5_0001.SGY", "C1T_7,5_0002.SGY"}

    line_a_candidates = result["C1T_7,5_0001.SGY"]
    line_b_candidates = result["C1T_7,5_0002.SGY"]

    assert len(line_a_candidates) >= 1
    injected = next(
        (c for c in line_a_candidates if c.evidence.trace_range[0] <= 36 <= c.evidence.trace_range[1]), None
    )
    assert injected is not None, "the injected line-A anomaly should surface as a candidate"
    assert injected.evidence.source_file == "C1T_7,5_0001.SGY"
    assert 0 <= injected.evidence.trace_range[0] and injected.evidence.trace_range[1] < N_TRACES_LINE_A
    assert 0.0 <= injected.evidence.depth_range[0] and injected.evidence.depth_range[1] <= MAX_DEPTH_M
    assert injected.interpretation.anomaly_class in {"compact", "trace-elongated", "depth-elongated", "diffuse", "unclassified"}
    assert 0.0 <= injected.confidence.reliable_fraction <= 1.0

    # no candidate from line A may report line B's source_file or vice versa
    for c in line_a_candidates:
        assert c.evidence.source_file == "C1T_7,5_0001.SGY"
    for c in line_b_candidates:
        assert c.evidence.source_file == "C1T_7,5_0002.SGY"

    # calling per-line directly must match the all-lines wrapper
    direct_a = find_anomaly_candidates(combined, source_file="C1T_7,5_0001.SGY", threshold=3.0, min_cells=3)
    assert len(direct_a) == len(line_a_candidates)


def test_candidate_detection_real_dimensions_grid_shape_matches_survey():
    """Sanity check that the underlying grid this test exercises really is 482x72 / 482x66, not a stand-in size."""
    line_a = _make_line_records("C1T_7,5_0001.SGY", N_TRACES_LINE_A, seed=300)
    georeference_records_by_trace(line_a, _synthetic_kmz_path())
    line_a = preprocess_trace_local_anomaly(line_a)

    from preprocessing.spatial_grid import build_trace_depth_grid_for_records
    grid_result = build_trace_depth_grid_for_records(line_a)
    assert grid_result["grid"].shape == (482, 72)
