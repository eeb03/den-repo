import numpy as np
import pytest

from preprocessing.spatial_grid import preprocess_trace_local_anomaly, build_trace_depth_grid_for_records
from preprocessing.pipeline import run_pipeline
from schemas.subterra_record import SubterraRecord, SensorType


def _make_trace_depth_records(n_traces=30, n_depths=30, source_file="line.SGY", seed=0, lat0=41.0, lon0=15.0, depth_step=0.05):
    """
    Mirrors the real radargram structure: n_traces positions along a survey
    line, each carrying n_depths real depth samples -- what SEGYConverter +
    georeference_records_by_trace produce.
    """
    rng = np.random.default_rng(seed)
    records = []
    for t in range(n_traces):
        for d in range(n_depths):
            val = rng.normal(20, 2)
            records.append(
                SubterraRecord(
                    dataset_id="trace-anomaly-test", sensor_type=SensorType.GPR,
                    latitude=lat0 + t * 0.00001, longitude=lon0 + t * 0.00002,
                    depth=round(d * depth_step, 6), signal=[float(val)],
                    metadata={"trace_index": t, "source_file": source_file, "sample_index": d},
                )
            )
    return records


# Real C1T_7,5_0001 depth spacing: ~7.05m max depth over 482 samples.
REAL_DEPTH_STEP = 7.04665 / 481


def _inject_spike(records, trace_index, depth, magnitude=25.0):
    for r in records:
        if r.metadata["trace_index"] == trace_index and abs(r.depth - depth) < 1e-9:
            r.signal = [r.signal[0] + magnitude]
    return records


def test_preprocess_trace_local_anomaly_flags_injected_spike():
    records = _make_trace_depth_records(n_traces=30, n_depths=30, seed=3)
    records = _inject_spike(records, trace_index=15, depth=round(15 * 0.05, 6))

    processed = preprocess_trace_local_anomaly(records)  # default axis-aware windows

    spike_rec = next(
        r for r in processed
        if r.metadata["trace_index"] == 15 and abs(r.depth - round(15 * 0.05, 6)) < 1e-9
    )
    assert spike_rec.signal[0] > 5.0
    assert spike_rec.metadata["anomaly_reliable"] is True
    assert "pre_anomaly_signal" in spike_rec.metadata


def test_preprocess_trace_local_anomaly_preserves_record_count_and_depth():
    records = _make_trace_depth_records(n_traces=10, n_depths=15)
    before_depths = sorted({r.depth for r in records})

    processed = preprocess_trace_local_anomaly(records)

    assert len(processed) == 10 * 15
    assert sorted({r.depth for r in processed}) == before_depths


def test_preprocess_trace_local_anomaly_keeps_multiple_survey_lines_independent():
    line_a = _make_trace_depth_records(n_traces=20, n_depths=20, source_file="A.SGY", seed=1)
    line_b = _make_trace_depth_records(n_traces=20, n_depths=20, source_file="B.SGY", seed=2)
    line_b = _inject_spike(line_b, trace_index=10, depth=round(10 * 0.05, 6), magnitude=30.0)
    combined = line_a + line_b

    processed = preprocess_trace_local_anomaly(combined)

    a_records = [r for r in processed if r.metadata["source_file"] == "A.SGY"]
    b_spike = next(
        r for r in processed
        if r.metadata["source_file"] == "B.SGY"
        and r.metadata["trace_index"] == 10
        and abs(r.depth - round(10 * 0.05, 6)) < 1e-9
    )

    assert b_spike.signal[0] > 5.0
    # line A had no injected spike -- its statistics must not be polluted by line B's
    reliable_a = [r.signal[0] for r in a_records if r.metadata["anomaly_reliable"]]
    assert max(abs(v) for v in reliable_a) < 5.0


def test_preprocess_trace_local_anomaly_real_aspect_ratio_lateral_edges_unreliable():
    """
    Regression test for C2, using the REAL C1T_7,5_0001 grid shape (482
    depth samples x 72 traces), not a square synthetic grid. Confirmed
    empirically before this fix: on random noise of this exact shape, NO
    min_ring_count up to 200+ ever flagged the true leftmost/rightmost
    trace columns unreliable, because the abundant depth axis backfills
    the joint ring count regardless of trace-direction truncation. The
    axis-aware min_trace_ring_count must catch this independently of depth.

    Derived defaults (trace_inner=2, trace_outer=6, min_trace_ring_count=4)
    plateau to the interior marginal count of 4 near either end of the
    line -- verified directly via `_axis_ring_counts(72, 2, 6)`: counts are
    [2, 2, 3, 4, ...] from the left (traces 0-2 unreliable, trace 3+
    reliable) and [..., 4, 3, 2] from the right (traces 70-71 unreliable,
    trace 69 reliable). The two-cell difference in how many traces are
    flagged on each side is an even-window-size box-filter artifact (a
    window of 6 pads 3 cells one side / 2 the other; `_box_filter_1d`'s
    `pad = window // 2`) -- not a directional bug, and the SAME artifact
    already exists in the pre-existing isotropic lat/lon case, just not
    usually visible since typical area-survey windows are far smaller
    relative to the grid than this line's trace axis is.
    """
    records = _make_trace_depth_records(n_traces=72, n_depths=482, seed=7, depth_step=REAL_DEPTH_STEP)
    processed = preprocess_trace_local_anomaly(records)  # real defaults, no override

    def reliability_at_trace(trace_idx):
        return [r.metadata["anomaly_reliable"] for r in processed if r.metadata["trace_index"] == trace_idx]

    for edge_trace in (0, 1, 2):
        assert all(rel is False for rel in reliability_at_trace(edge_trace)), \
            f"trace {edge_trace} (near line start) should be unreliable -- too few lateral neighbors"
    for edge_trace in (70, 71):
        assert all(rel is False for rel in reliability_at_trace(edge_trace)), \
            f"trace {edge_trace} (near line end) should be unreliable -- too few lateral neighbors"

    # trace 3 / trace 69 are exactly where the marginal count reaches the
    # interior plateau -- should NOT be flagged purely for trace-proximity
    # (may still be flagged if also near a depth edge, excluded below)
    interior_check = sorted(
        (r for r in processed if r.metadata["trace_index"] in (3, 36, 69)), key=lambda r: r.depth
    )
    away_from_depth_edges = [r for r in interior_check if 10 <= r.metadata["sample_index"] <= 471]
    assert all(r.metadata["anomaly_reliable"] is True for r in away_from_depth_edges)


def test_preprocess_trace_local_anomaly_real_aspect_ratio_interior_traces_reliable():
    """Interior traces (away from BOTH the trace-line edges and the depth-window edges) must remain reliable -- the fix must not over-flag the whole grid."""
    records = _make_trace_depth_records(n_traces=72, n_depths=482, seed=9, depth_step=REAL_DEPTH_STEP)
    processed = preprocess_trace_local_anomaly(records)

    interior_trace = 36  # far from both trace-line edges (0/71)
    interior_recs = [r for r in processed if r.metadata["trace_index"] == interior_trace]
    away_from_depth_edges = [r for r in interior_recs if 10 <= r.metadata["sample_index"] <= 471]

    assert len(away_from_depth_edges) > 0
    assert all(r.metadata["anomaly_reliable"] is True for r in away_from_depth_edges)


def test_preprocess_trace_local_anomaly_real_aspect_ratio_depth_edges_unreliable():
    """Shallowest/deepest few depth samples get flagged too (depth-axis marginal count plateaus by sample ~7), independent of trace position -- verified on the real 482x72 shape."""
    records = _make_trace_depth_records(n_traces=72, n_depths=482, seed=7, depth_step=REAL_DEPTH_STEP)
    processed = preprocess_trace_local_anomaly(records)

    interior_trace_recs = sorted(
        (r for r in processed if r.metadata["trace_index"] == 36), key=lambda r: r.depth
    )
    shallowest = interior_trace_recs[:6]
    deepest = interior_trace_recs[-6:]
    assert all(r.metadata["anomaly_reliable"] is False for r in shallowest)
    assert all(r.metadata["anomaly_reliable"] is False for r in deepest)


def test_preprocess_trace_local_anomaly_real_aspect_ratio_still_detects_interior_spike():
    """The fix must not break real anomaly detection away from edges -- verified on the real 482x72 shape, not just a square grid."""
    records = _make_trace_depth_records(n_traces=72, n_depths=482, seed=11, depth_step=REAL_DEPTH_STEP)
    records = _inject_spike(records, trace_index=36, depth=round(241 * REAL_DEPTH_STEP, 6), magnitude=25.0)

    processed = preprocess_trace_local_anomaly(records)

    spike_rec = next(
        r for r in processed
        if r.metadata["trace_index"] == 36 and abs(r.depth - round(241 * REAL_DEPTH_STEP, 6)) < 1e-9
    )
    assert spike_rec.signal[0] > 5.0
    assert spike_rec.metadata["anomaly_reliable"] is True


def test_preprocess_trace_local_anomaly_skips_records_missing_trace_metadata():
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, latitude=0, longitude=0, signal=[5.0])
        for _ in range(5)
    ]
    processed = preprocess_trace_local_anomaly(records)
    assert all(r.signal == [5.0] for r in processed)  # left untouched, not crashed


def test_build_trace_depth_grid_for_records_shape_and_positions():
    records = _make_trace_depth_records(n_traces=12, n_depths=8)
    result = build_trace_depth_grid_for_records(records)
    assert result["grid"].shape == (8, 12)
    assert len(result["trace_indices"]) == 12
    assert len(result["depths"]) == 8
    assert len(result["trace_lat"]) == 12
    assert len(result["trace_lon"]) == 12
    assert np.isfinite(result["grid"]).all()  # dense: no missing cells, unlike a lat/lon area grid


def test_build_trace_depth_grid_for_records_selects_by_source_file():
    line_a = _make_trace_depth_records(n_traces=5, n_depths=5, source_file="A.SGY", seed=1)
    line_b = _make_trace_depth_records(n_traces=9, n_depths=9, source_file="B.SGY", seed=2)
    combined = line_a + line_b

    default_result = build_trace_depth_grid_for_records(combined)  # defaults to densest -> B
    assert default_result["source_file"] == "B.SGY"

    a_result = build_trace_depth_grid_for_records(combined, source_file="A.SGY")
    assert a_result["source_file"] == "A.SGY"
    assert a_result["grid"].shape == (5, 5)

    # Item 8 fix: the full list of available lines must always be surfaced,
    # not just whichever one was auto-selected -- so a caller (the viewer)
    # never has to silently guess at a multi-line dataset's other lines.
    assert default_result["available_source_files"] == ["A.SGY", "B.SGY"]
    assert a_result["available_source_files"] == ["A.SGY", "B.SGY"]


def test_build_trace_depth_grid_for_records_raises_on_missing_metadata():
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, latitude=0, longitude=0, signal=[5.0])
    ]
    with pytest.raises(ValueError):
        build_trace_depth_grid_for_records(records)


def test_run_pipeline_dispatches_to_gpr_local_anomaly_mode():
    records = _make_trace_depth_records(n_traces=10, n_depths=10)
    result = run_pipeline(records, mode="gpr_local_anomaly")
    assert len(result) == 100
    assert all("pre_anomaly_signal" in r.metadata for r in result)
