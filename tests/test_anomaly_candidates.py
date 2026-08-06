import numpy as np
import pytest

from schemas.subterra_record import SubterraRecord, SensorType
from interpretation.anomaly_candidates import (
    find_anomaly_candidates,
    find_anomaly_candidates_all_lines,
    encode_candidate_id,
    decode_candidate_id,
    AnomalyCandidate,
)

FORBIDDEN_PHYSICAL_TERMS = [
    # Specific physical material/object identities the interpretation layer
    # must never assert. Deliberately excludes generic words like "object"
    # itself, since the required disclaimer text legitimately says "not a
    # physical ... object identification" -- negating the claim, not making it.
    "pipe", "cable", "void", "rock", "concrete", "utility",
    "archaeolog", "tunnel", "cavity", "mineral", "ore", "rebar", "mine",
    "ordnance", "foundation",
]


def _make_records_from_grid(
    zscore_grid, depths, trace_ids, source_file="line.SGY", dataset_id="anomaly-candidate-test",
    lat0=41.0, lon0=15.0, reliable_grid=None, elevation=None,
):
    """
    Builds SubterraRecord objects directly from a given (depth x trace)
    z-score array, already tagged as if trace-local anomaly preprocessing
    had run -- gives full control over exact grid values for deterministic
    assertions, same convention as other tests in this suite
    (e.g. tests/test_trace_local_anomaly.py's _make_trace_depth_records).
    """
    n_depths, n_traces = zscore_grid.shape
    assert len(depths) == n_depths and len(trace_ids) == n_traces
    records = []
    for ti, trace_idx in enumerate(trace_ids):
        lat = lat0 + ti * 0.00002
        lon = lon0 + ti * 0.00002
        for di, depth in enumerate(depths):
            reliable = True if reliable_grid is None else bool(reliable_grid[di, ti])
            records.append(
                SubterraRecord(
                    dataset_id=dataset_id, sensor_type=SensorType.GPR,
                    latitude=lat, longitude=lon, depth=float(depth),
                    signal=[float(zscore_grid[di, ti])],
                    elevation=elevation,
                    metadata={
                        "trace_index": trace_idx,
                        "source_file": source_file,
                        "anomaly_reliable": reliable,
                        "pre_anomaly_signal": 0.0,
                        "velocity_m_per_ns": 0.1,
                        "kmz_direction_verified": False,
                    },
                )
            )
    return records


def _flat_grid(n_depths=20, n_traces=20, noise=0.1, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(0, noise, size=(n_depths, n_traces))


def test_find_anomaly_candidates_detects_injected_cluster():
    grid = _flat_grid()
    grid[8:11, 8:11] = 5.0  # 3x3 compact spike, depth rows 8-10, trace cols 8-10
    depths = [round(i * 0.05, 6) for i in range(20)]
    trace_ids = list(range(20))
    records = _make_records_from_grid(grid, depths, trace_ids)

    candidates = find_anomaly_candidates(records, source_file="line.SGY", threshold=3.0, min_cells=3)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.evidence.trace_range == (8, 10)
    assert c.evidence.depth_range == (depths[8], depths[10])
    assert c.evidence.n_supporting_cells == 9
    assert c.evidence.peak_value == pytest.approx(5.0, abs=0.2)


def test_find_anomaly_candidates_empty_when_no_signal_exceeds_threshold():
    grid = _flat_grid(noise=0.2)
    depths = [round(i * 0.05, 6) for i in range(20)]
    trace_ids = list(range(20))
    records = _make_records_from_grid(grid, depths, trace_ids)

    candidates = find_anomaly_candidates(records, source_file="line.SGY", threshold=3.0, min_cells=3)
    assert candidates == []


def test_find_anomaly_candidates_requires_anomaly_processed_metadata():
    """Rule: must not silently interpret raw amplitude as z-score evidence."""
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR, latitude=41.0, longitude=15.0,
            depth=float(d), signal=[10.0],
            metadata={"trace_index": t, "source_file": "line.SGY"},  # no anomaly_reliable key
        )
        for t in range(5) for d in range(5)
    ]
    with pytest.raises(ValueError, match="anomaly_reliable"):
        find_anomaly_candidates(records, source_file="line.SGY")


def test_find_anomaly_candidates_missing_source_file_raises():
    grid = _flat_grid()
    depths = [round(i * 0.05, 6) for i in range(20)]
    trace_ids = list(range(20))
    records = _make_records_from_grid(grid, depths, trace_ids, source_file="A.SGY")

    with pytest.raises(ValueError, match="No records found"):
        find_anomaly_candidates(records, source_file="NONEXISTENT.SGY")


def test_find_anomaly_candidates_boundary_touching_flags():
    n_depths, n_traces = 20, 20
    depths = [round(i * 0.05, 6) for i in range(n_depths)]
    trace_ids = list(range(n_traces))

    # cluster at the trace-axis edge (cols 0-1) and away from depth edges
    grid_edge = _flat_grid(n_depths, n_traces, seed=1)
    grid_edge[9:12, 0:2] = 6.0
    edge_candidates = find_anomaly_candidates(
        _make_records_from_grid(grid_edge, depths, trace_ids, source_file="edge.SGY"),
        source_file="edge.SGY", threshold=3.0, min_cells=3,
    )
    assert len(edge_candidates) == 1
    assert edge_candidates[0].confidence.touches_trace_boundary is True
    assert edge_candidates[0].confidence.touches_depth_boundary is False

    # interior cluster, away from all edges
    grid_interior = _flat_grid(n_depths, n_traces, seed=2)
    grid_interior[9:12, 9:12] = 6.0
    interior_candidates = find_anomaly_candidates(
        _make_records_from_grid(grid_interior, depths, trace_ids, source_file="interior.SGY"),
        source_file="interior.SGY", threshold=3.0, min_cells=3,
    )
    assert len(interior_candidates) == 1
    assert interior_candidates[0].confidence.touches_trace_boundary is False
    assert interior_candidates[0].confidence.touches_depth_boundary is False

    # cluster at the depth-axis edge (rows 0-1)
    grid_depth_edge = _flat_grid(n_depths, n_traces, seed=3)
    grid_depth_edge[0:2, 9:12] = 6.0
    depth_edge_candidates = find_anomaly_candidates(
        _make_records_from_grid(grid_depth_edge, depths, trace_ids, source_file="depth_edge.SGY"),
        source_file="depth_edge.SGY", threshold=3.0, min_cells=3,
    )
    assert len(depth_edge_candidates) == 1
    assert depth_edge_candidates[0].confidence.touches_depth_boundary is True


def test_find_anomaly_candidates_reliability_fraction_not_collapsed_to_boolean():
    """Confidence must preserve the actual fraction, not just a pass/fail flag."""
    n_depths, n_traces = 20, 20
    depths = [round(i * 0.05, 6) for i in range(n_depths)]
    trace_ids = list(range(n_traces))
    grid = _flat_grid(n_depths, n_traces, seed=4)
    grid[8:11, 8:11] = 5.0

    reliable_grid = np.ones((n_depths, n_traces), dtype=bool)
    # mark exactly 3 of the 9 supporting cells as unreliable
    reliable_grid[8, 8] = False
    reliable_grid[9, 9] = False
    reliable_grid[10, 10] = False

    records = _make_records_from_grid(grid, depths, trace_ids, source_file="rel.SGY", reliable_grid=reliable_grid)
    candidates = find_anomaly_candidates(records, source_file="rel.SGY", threshold=3.0, min_cells=3)

    assert len(candidates) == 1
    assert candidates[0].confidence.reliable_fraction == pytest.approx(6 / 9)


def test_anomaly_confidence_has_no_single_combined_score_field():
    """
    Regression guard for the explicit requirement: uncertainty must stay as
    separate, named signals -- never fused into one misleading scalar.
    """
    fields = set(AnomalyCandidate.model_fields["confidence"].annotation.model_fields.keys())
    forbidden = {"confidence", "confidence_score", "score", "overall_confidence", "overall_reliable", "quality_score"}
    assert fields.isdisjoint(forbidden), f"found a collapsed confidence field: {fields & forbidden}"


def test_anomaly_class_is_always_neutral_never_physical():
    """No candidate output may ever contain a physical-object/material name."""
    n_depths, n_traces = 20, 30
    depths = [round(i * 0.05, 6) for i in range(n_depths)]
    trace_ids = list(range(n_traces))

    shapes = []
    compact = _flat_grid(n_depths, n_traces, seed=10)
    compact[9:12, 14:17] = 6.0
    shapes.append(("compact_case.SGY", compact))

    trace_elongated = _flat_grid(n_depths, n_traces, seed=11)
    trace_elongated[9:11, 5:25] = 6.0
    shapes.append(("trace_elongated_case.SGY", trace_elongated))

    depth_elongated = _flat_grid(n_depths, n_traces, seed=12)
    depth_elongated[2:18, 14:16] = 6.0
    shapes.append(("depth_elongated_case.SGY", depth_elongated))

    all_candidates = []
    for source_file, grid in shapes:
        records = _make_records_from_grid(grid, depths, trace_ids, source_file=source_file)
        all_candidates.extend(find_anomaly_candidates(records, source_file=source_file, threshold=3.0, min_cells=3))

    assert len(all_candidates) == 3
    allowed = {"compact", "trace-elongated", "depth-elongated", "diffuse", "unclassified"}
    for c in all_candidates:
        assert c.interpretation.anomaly_class in allowed
        blob = c.model_dump_json().lower()
        for term in FORBIDDEN_PHYSICAL_TERMS:
            assert term not in blob, f"forbidden physical-object term {term!r} found in candidate output: {blob}"


def test_ground_truth_never_written_by_candidate_detection():
    n_depths, n_traces = 10, 10
    depths = [round(i * 0.05, 6) for i in range(n_depths)]
    trace_ids = list(range(n_traces))
    grid = _flat_grid(n_depths, n_traces, seed=5)
    grid[4:7, 4:7] = 6.0
    records = _make_records_from_grid(grid, depths, trace_ids, source_file="gt.SGY")

    before = [r.ground_truth for r in records]
    find_anomaly_candidates(records, source_file="gt.SGY", threshold=3.0, min_cells=3)
    after = [r.ground_truth for r in records]

    assert before == after
    assert all(gt.value == "none" for gt in after)


def test_source_file_separation_between_two_independent_lines():
    """Rule: a connected component must NEVER cross from one source_file into another."""
    n_depths, n_traces = 20, 20
    depths = [round(i * 0.05, 6) for i in range(n_depths)]
    trace_ids = list(range(n_traces))  # deliberately identical, colliding trace_index range in both files

    grid_a = _flat_grid(n_depths, n_traces, seed=20)
    grid_a[5:8, 5:8] = 6.0  # line A's own anomaly

    grid_b = _flat_grid(n_depths, n_traces, seed=21)
    grid_b[12:15, 12:15] = 7.0  # line B's own anomaly, different location

    records_a = _make_records_from_grid(grid_a, depths, trace_ids, source_file="A.SGY", dataset_id="multi-line-ds")
    records_b = _make_records_from_grid(grid_b, depths, trace_ids, source_file="B.SGY", dataset_id="multi-line-ds")
    combined = records_a + records_b

    result = find_anomaly_candidates_all_lines(combined, threshold=3.0, min_cells=3)

    assert set(result.keys()) == {"A.SGY", "B.SGY"}
    assert len(result["A.SGY"]) == 1
    assert len(result["B.SGY"]) == 1
    assert result["A.SGY"][0].evidence.trace_range == (5, 7)
    assert result["B.SGY"][0].evidence.trace_range == (12, 14)
    assert result["A.SGY"][0].evidence.source_file == "A.SGY"
    assert result["B.SGY"][0].evidence.source_file == "B.SGY"

    # also verify calling find_anomaly_candidates directly per file gives the same isolated result
    direct_a = find_anomaly_candidates(combined, source_file="A.SGY", threshold=3.0, min_cells=3)
    assert len(direct_a) == 1
    assert direct_a[0].evidence.trace_range == (5, 7)


def test_candidate_serialization_round_trip():
    n_depths, n_traces = 10, 10
    depths = [round(i * 0.05, 6) for i in range(n_depths)]
    trace_ids = list(range(n_traces))
    grid = _flat_grid(n_depths, n_traces, seed=6)
    grid[4:7, 4:7] = 5.0
    records = _make_records_from_grid(grid, depths, trace_ids, source_file="ser.SGY")

    candidates = find_anomaly_candidates(records, source_file="ser.SGY", threshold=3.0, min_cells=3)
    assert len(candidates) == 1

    dumped = candidates[0].model_dump()
    assert isinstance(dumped, dict)
    json_str = candidates[0].model_dump_json()
    assert "NaN" not in json_str and "Infinity" not in json_str

    reloaded = AnomalyCandidate.model_validate_json(json_str)
    assert reloaded == candidates[0]


def test_encode_decode_candidate_id_round_trip():
    cid = encode_candidate_id("ds-123", "C1T_7,5_0001.SGY", label_id=3, threshold=3.0, min_cells=3)
    decoded = decode_candidate_id(cid)
    assert decoded == {
        "dataset_id": "ds-123",
        "source_file": "C1T_7,5_0001.SGY",
        "label_id": 3,
        "threshold": 3.0,
        "min_cells": 3,
    }


def test_candidate_ids_are_unique_per_cluster_within_one_call():
    n_depths, n_traces = 20, 30
    depths = [round(i * 0.05, 6) for i in range(n_depths)]
    trace_ids = list(range(n_traces))
    grid = _flat_grid(n_depths, n_traces, seed=7)
    grid[2:5, 2:5] = 6.0
    grid[14:17, 20:23] = 6.0
    records = _make_records_from_grid(grid, depths, trace_ids, source_file="two_clusters.SGY")

    candidates = find_anomaly_candidates(records, source_file="two_clusters.SGY", threshold=3.0, min_cells=3)
    assert len(candidates) == 2
    assert candidates[0].id != candidates[1].id


def test_no_dem_alignment_yields_none_elevation_not_error():
    n_depths, n_traces = 10, 10
    depths = [round(i * 0.05, 6) for i in range(n_depths)]
    trace_ids = list(range(n_traces))
    grid = _flat_grid(n_depths, n_traces, seed=8)
    grid[4:7, 4:7] = 6.0
    records = _make_records_from_grid(grid, depths, trace_ids, source_file="no_dem.SGY", elevation=None)

    candidates = find_anomaly_candidates(records, source_file="no_dem.SGY", threshold=3.0, min_cells=3)
    assert len(candidates) == 1
    assert candidates[0].characteristics.centroid_elevation_m is None
    assert candidates[0].confidence.dem_vertical_datum_verified is None
