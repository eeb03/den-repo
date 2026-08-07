"""
The BAM benchmark ingestion, association, detection scoring and evidence gate.

Structure of this module, and why:

  * Everything that can be tested WITHOUT the 1.7 GB archives is, using a
    synthetic grid of the documented shape and deterministic fixture
    detections. That is most of the contract -- footprints, association,
    TP/FP/FN, precision/recall/F1, false alarms, the gate -- and it runs in CI
    where the archives are gitignored and absent.
  * Tests that genuinely need the archives are marked and skip when they are
    not present, following the pattern the AHN tests already use.

The gate tests are the ones to read first. They fail if a later change starts
reporting something the evidence does not support.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from benchmark import gates
from benchmark.association import EXACT_GRID_NODE, associate, target_for_trace
from benchmark.bam_ingest import (
    EXPECTED_GRID, BenchmarkIngestError, BenchmarkScan, GridSpec, line_traces,
    load_grid, load_scan, load_volume,
)
from benchmark.bam_truth import (
    TRANSCRIBED, BenchmarkTruthError, build_footprint, load_control, load_targets,
)
from benchmark.detection import BenchmarkDetection, DetectionRun, detect_line
from benchmark.scoring import (
    MIN_LINES_FOR_A_RATE, score_detection, score_false_alarms, score_localization,
)

ARCHIVES = Path("datasets/raw/bam_concrete")
PK266 = ARCHIVES / "Pk266_Dataset.zip"
PK050 = ARCHIVES / "Pk050_Dataset.zip"

REAL_PK266 = pytest.mark.skipif(not PK266.exists(), reason="BAM Pk266 archive not present locally")
REAL_BOTH = pytest.mark.skipif(not (PK266.exists() and PK050.exists()),
                               reason="BAM archives not present locally")


@pytest.fixture(scope="module")
def grid():
    """The documented benchmark grid, without needing the archives."""
    return GridSpec(
        x=np.arange(0, 2005, 5),
        y=np.arange(0, 805, 5),
        z=np.linspace(0.0, 15.0, 512),
    )


@pytest.fixture(scope="module")
def targets(grid):
    return load_targets(grid, "Pk266")


def _det(scan_id, line, peak_trace, traces=None, n_cells=5):
    traces = traces if traces is not None else (peak_trace,)
    return BenchmarkDetection(
        scan_id=scan_id, line_index=line,
        detection_id=f"{scan_id}:L{line}:{peak_trace}",
        trace_indices=tuple(traces), sample_indices=(100, 101),
        peak_trace=peak_trace, peak_sample=100, peak_z=5.0, n_cells=n_cells,
    )


def _run(detections, lines, specimen="Pk266", scan_id="S"):
    return DetectionRun(scan_id=scan_id, specimen_id=specimen,
                        detections=detections, lines_processed=lines,
                        threshold=3.0, min_cells=3)


# ---------------------------------------------------------------- grid shape

def test_the_documented_grid_is_what_ingestion_expects():
    assert EXPECTED_GRID["n_x"] == 401 and EXPECTED_GRID["n_y"] == 161
    assert EXPECTED_GRID["n_z"] == 512
    assert EXPECTED_GRID["x_step"] == 5 and EXPECTED_GRID["y_step"] == 5


def test_grid_vectors_have_the_documented_shape_and_spacing(grid):
    assert grid.x.size == 401 and grid.y.size == 161 and grid.z.size == 512
    assert grid.x_step == 5 and grid.y_step == 5
    assert grid.x[0] == 0 and grid.x[-1] == 2000
    assert grid.y[0] == 0 and grid.y[-1] == 800


def test_no_crs_is_invented(grid):
    assert grid.crs is None
    assert grid.crs_provenance == "none"


def test_no_absolute_origin_is_claimed(grid):
    assert grid.absolute_origin_verified is False


def test_units_are_carried_as_documentation_not_as_fact(grid):
    assert grid.units_provenance == "inferred_from_documentation"
    assert "no file in either archive declares one" in grid.units_note


def test_a_non_node_x_value_raises_rather_than_rounding(grid):
    with pytest.raises(BenchmarkIngestError) as e:
        grid.x_node(252)
    assert "nearest-neighbour matching is not permitted" in str(e.value)


# ---------------------------------------------------------------- ground truth

def test_pk266_has_exactly_four_targets(targets):
    assert len(targets) == 4


def test_target_x_values_are_the_published_ones(targets):
    assert [t.x for t in targets] == [250.0, 750.0, 1250.0, 1750.0]


def test_grid_indices_are_exactly_50_150_250_350(targets):
    assert [t.x_node for t in targets] == [50, 150, 250, 350]


def test_every_target_position_is_labelled_transcribed(targets):
    assert all(t.provenance == TRANSCRIBED for t in targets)


def test_footprint_generation_is_deterministic(grid, targets):
    for t in targets:
        again = build_footprint(t.x, t.outer_diameter, grid)
        assert again.nodes == t.footprint.nodes
        assert again.rule == t.footprint.rule


def test_the_footprint_is_thirteen_nodes_and_contains_the_centre(targets):
    for t in targets:
        assert t.footprint.n_nodes == 13
        assert t.x_node in t.footprint


def test_footprints_do_not_overlap(targets):
    ordered = sorted(targets, key=lambda t: t.footprint.first_node)
    for a, b in zip(ordered, ordered[1:]):
        assert b.footprint.first_node > a.footprint.last_node


def test_overlapping_footprints_are_rejected(grid):
    """A grid too coarse to separate the targets must fail, not silently merge."""
    from benchmark.bam_truth import _check_disjoint
    from dataclasses import replace
    ts = load_targets(grid, "Pk266")
    clashing = [ts[0], replace(ts[1], footprint=ts[0].footprint)]
    with pytest.raises(BenchmarkTruthError) as e:
        _check_disjoint(clashing)
    assert "overlap" in str(e.value)


def test_pk050_is_a_control_region_with_an_attestation():
    c = load_control("Pk050")
    assert c.specimen_id == "Pk050"
    assert c.attested is True
    assert "does not contain any embedded elements" in c.attestation


def test_the_control_caveat_about_back_walls_survives():
    assert "not featureless" in load_control("Pk050").caveat


def test_a_specimen_with_targets_cannot_be_loaded_as_a_control():
    with pytest.raises(BenchmarkTruthError):
        load_control("Pk266")


# ---------------------------------------------------------------- association

@pytest.fixture(scope="module")
def scan_stub(grid):
    return BenchmarkScan(benchmark_id="bam-concrete-gpr", specimen_id="Pk266",
                         scan_id="Pk266_1_5_GHz_Rot00", archive="Pk266_Dataset.zip",
                         volume_member="x/3D_Dataset_NPY_Data/v.npy", grid=grid)


def test_association_is_exact_not_nearest_neighbour(scan_stub, targets):
    for r in associate(scan_stub, targets):
        assert r.association_method == EXACT_GRID_NODE
        assert r.provenance["interpolation"] == "none"


def test_each_target_associates_to_its_expected_grid_index(scan_stub, targets):
    got = {r.target_id: r.target_grid_index for r in associate(scan_stub, targets)}
    assert sorted(got.values()) == [50, 150, 250, 350]


def test_association_records_carry_the_required_fields(scan_stub, targets):
    required = {"benchmark_id", "scan_id", "target_id", "target_x",
                "target_grid_index", "associated_trace_indices",
                "footprint_definition", "association_method",
                "association_status", "provenance"}
    for r in associate(scan_stub, targets):
        assert required <= set(r.as_dict())


def test_association_is_stable_between_runs(scan_stub, targets):
    a = [r.as_dict() for r in associate(scan_stub, targets)]
    b = [r.as_dict() for r in associate(scan_stub, targets)]
    assert a == b


def test_association_does_not_claim_a_verified_origin(scan_stub, targets):
    for r in associate(scan_stub, targets):
        assert r.provenance["absolute_origin_verified"] is False
        assert "not localisation" in r.provenance["note"]


def test_a_trace_outside_every_footprint_maps_to_no_target(targets):
    assert target_for_trace(targets, 100) is None
    assert target_for_trace(targets, 50).target_id == "Pk266-duct-1"


# ---------------------------------------------------------------- detection scoring

def test_a_detection_on_every_target_on_every_line_scores_perfectly(targets):
    dets = [_det("S", line, t.x_node) for line in range(4) for t in targets]
    s = score_detection(_run(dets, lines=4), targets)
    assert (s.true_positives, s.false_positives, s.false_negatives) == (16, 0, 0)
    assert s.recall == 1.0 and s.precision == 1.0 and s.f1 == 1.0


def test_a_missed_target_becomes_a_false_negative(targets):
    dets = [_det("S", line, t.x_node) for line in range(2) for t in targets[:3]]
    s = score_detection(_run(dets, lines=2), targets)
    assert s.true_positives == 6
    assert s.false_negatives == 2          # duct-4 missed on both lines
    assert s.recall == pytest.approx(6 / 8)


def test_a_detection_away_from_every_target_is_a_false_positive(targets):
    dets = [_det("S", 0, 100), _det("S", 0, targets[0].x_node)]
    s = score_detection(_run(dets, lines=1), targets)
    assert s.false_positives == 1 and s.true_positives == 1
    assert s.precision == 0.5


def test_f1_is_the_harmonic_mean(targets):
    dets = [_det("S", 0, targets[0].x_node), _det("S", 0, 300)]
    s = score_detection(_run(dets, lines=1), targets)
    expected = 2 * s.precision * s.recall / (s.precision + s.recall)
    assert s.f1 == pytest.approx(expected)


def test_matching_uses_the_peak_node_and_says_so(targets):
    """A component straddling a footprint edge is credited by its peak only."""
    edge = targets[0].footprint.last_node
    outside = _det("S", 0, peak_trace=edge + 3, traces=(edge, edge + 1, edge + 2, edge + 3))
    s = score_detection(_run([outside], lines=1), targets)
    assert s.true_positives == 0 and s.false_positives == 1
    assert s.overlapping_any_node == 1          # reported, not silently counted
    assert "peak trace node" in s.match_rule


def test_no_tolerance_is_added_to_the_footprint(targets):
    just_outside = targets[1].footprint.last_node + 1
    s = score_detection(_run([_det("S", 0, just_outside)], lines=1), targets)
    assert s.true_positives == 0
    assert "no additional tolerance" in s.match_rule


def test_scores_record_the_thresholds_that_produced_them(targets):
    s = score_detection(_run([], lines=1), targets)
    assert s.threshold == 3.0 and s.min_cells == 3


def test_every_score_carries_the_scope_statement(targets):
    s = score_detection(_run([], lines=1), targets)
    assert "not evidence of soil/utility-scale" in s.scope
    assert s.localization_scored is False


def test_per_target_detail_names_provenance_and_footprint(targets):
    s = score_detection(_run([], lines=1), targets)
    for t in targets:
        d = s.per_target[t.target_id]
        assert d["position_provenance"] == TRANSCRIBED
        assert d["grid_index"] == t.x_node


# ---------------------------------------------------------------- false alarms

def test_detections_on_the_attested_empty_control_are_false_alarms():
    control = load_control("Pk050")
    run = _run([_det("C", i, 7) for i in range(20)], lines=20, specimen="Pk050", scan_id="C")
    fa = score_false_alarms(run, control)
    assert fa.n_detections == 20
    assert fa.detections_per_line == 1.0
    assert fa.sufficient_for_a_rate is True
    assert fa.false_alarm_rate == 1.0


def test_too_few_lines_reports_a_count_and_refuses_a_rate():
    control = load_control("Pk050")
    run = _run([_det("C", 0, 7)], lines=MIN_LINES_FOR_A_RATE - 1,
               specimen="Pk050", scan_id="C")
    fa = score_false_alarms(run, control)
    assert fa.sufficient_for_a_rate is False
    assert fa.false_alarm_rate is None
    assert fa.n_detections == 1                 # the measurable quantity survives
    assert "fewer than" in fa.limitation


def test_no_per_area_rate_is_invented():
    control = load_control("Pk050")
    fa = score_false_alarms(_run([], lines=20, specimen="Pk050", scan_id="C"), control)
    assert fa.per_area_rate is None
    assert "declare no physical unit" in fa.per_area_note


def test_the_control_caveat_travels_with_the_number():
    control = load_control("Pk050")
    fa = score_false_alarms(_run([], lines=20, specimen="Pk050", scan_id="C"), control)
    assert "not featureless" in fa.control_caveat


def test_false_alarm_scoring_refuses_a_non_control_specimen():
    with pytest.raises(ValueError) as e:
        score_false_alarms(_run([], lines=5, specimen="Pk266"), load_control("Pk050"))
    assert "needs the control specimen" in str(e.value)


# ---------------------------------------------------------------- the gate

def test_localization_is_blocked():
    assert gates.LOCALIZATION_STATUS == gates.BLOCKED
    assert gates.LOCALIZATION_BLOCKED_REASON == "absolute origin is not verified"


def test_detection_scoring_is_not_blocked_by_the_localization_gate():
    assert gates.DETECTION_STATUS == gates.RESOLVED


def test_asking_for_localization_raises_and_names_the_blocker():
    with pytest.raises(gates.LocalizationBlocked) as e:
        gates.require_localization_evidence()
    msg = str(e.value)
    assert "absolute origin is not verified" in msg
    assert "absolute-origin" in msg
    assert "Detection and false-alarm scoring remain available" in msg


def test_the_scoring_entry_point_for_localization_also_refuses():
    with pytest.raises(gates.LocalizationBlocked):
        score_localization()


def test_the_two_named_open_questions_are_still_open():
    ids = {q.id: q for q in gates.OPEN_QUESTIONS}
    assert ids["absolute-origin"].status == gates.BLOCKED
    assert ids["depth-reference-surface"].status == gates.BLOCKED
    assert "BAM appendix drawings" in ids["absolute-origin"].resolution_route
    assert "Table 4" in ids["depth-reference-surface"].resolution_route


def test_the_dzt_to_grid_mapping_is_recorded_as_unresolved():
    q = next(q for q in gates.OPEN_QUESTIONS if q.id == "dzt-to-grid-mapping")
    assert "152,222" in q.statement and "64,561" in q.statement


# ---------------------------------------------------------------- detector adapter

def test_the_adapter_reproduces_the_existing_detector_rule():
    """
    The adapter must select exactly the components
    `interpretation.anomaly_candidates.find_anomaly_candidates` would: |z| over
    threshold, `ndimage.label` at its default 4-connectivity, then min_cells.

    This is deliberately an equivalence test rather than a sensitivity test.
    Asserting that the detector finds a feature planted in synthetic noise
    would be asserting detector physics from data invented for the purpose --
    and the ring statistic's measured width saturation means a broad planted
    feature legitimately may NOT clear the threshold.
    """
    from scipy import ndimage

    from preprocessing.spatial_grid import anomaly_grid_from_traces

    rng = np.random.default_rng(3)
    traces = rng.normal(scale=0.01, size=(120, 200))
    traces[58:63, 95:105] += 6.0

    z = anomaly_grid_from_traces(traces)
    mask = np.abs(np.nan_to_num(z, nan=0.0)) > 3.0
    labeled, n = ndimage.label(mask)
    expected = sum(1 for i in range(1, n + 1) if int((labeled == i).sum()) >= 3)

    assert len(detect_line(traces, "synthetic", 0, threshold=3.0, min_cells=3)) == expected


def test_a_detection_reports_the_peak_cell_of_its_component():
    from preprocessing.spatial_grid import anomaly_grid_from_traces

    rng = np.random.default_rng(3)
    traces = rng.normal(scale=0.01, size=(120, 200))
    traces[58:63, 95:105] += 6.0
    z = np.abs(np.nan_to_num(anomaly_grid_from_traces(traces), nan=0.0))

    for d in detect_line(traces, "synthetic", 0):
        assert d.peak_trace in d.trace_indices
        assert d.peak_sample in d.sample_indices
        assert z[d.peak_sample, d.peak_trace] == pytest.approx(abs(d.peak_z))
        assert d.n_cells >= 3


def test_flat_data_produces_no_detection():
    assert detect_line(np.zeros((60, 80)), "flat", 0) == []


def test_raising_the_threshold_cannot_increase_detections():
    rng = np.random.default_rng(11)
    traces = rng.normal(size=(80, 150))
    strict = len(detect_line(traces, "s", 0, threshold=5.0))
    loose = len(detect_line(traces, "s", 0, threshold=3.0))
    assert strict <= loose


def test_the_detector_reports_the_pipeline_it_used():
    run = _run([], lines=0)
    assert "anomaly_grid_from_traces" in run.detector
    assert run.parameters_changed == "none"


# ---------------------------------------------------------------- real archives

@REAL_PK266
def test_the_real_grid_matches_the_documented_one():
    g = load_grid(PK266)
    assert g.x.size == 401 and g.y.size == 161 and g.z.size == 512
    assert g.x_step == 5 and g.y_step == 5
    assert float(g.z[-1]) == 15.0


@REAL_PK266
def test_the_real_dzt_opens_with_the_existing_gssi_reader():
    scan = load_scan("Pk266", "Pk266_3D_Dataset_1_5_GHz_Rot00")
    assert scan.dzt_header["n_samples"] == 512
    assert scan.dzt_header["range_ns"] == 15.0
    assert scan.dzt_header["read_by"].startswith("converters.gssi_converter")


@REAL_PK266
def test_the_dzt_trace_count_is_recorded_as_not_matching_the_grid():
    """The mismatch is the reason the NPY is the amplitude source."""
    scan = load_scan("Pk266", "Pk266_3D_Dataset_1_5_GHz_Rot00")
    assert scan.dzt_header["dzt_matches_grid"] is False
    assert scan.dzt_header["dzt_trace_count"] == 152222
    assert scan.dzt_header["grid_trace_count"] == 64561


@REAL_PK266
def test_provenance_is_attached_to_every_ingested_scan():
    scan = load_scan("Pk266", "Pk266_3D_Dataset_1_5_GHz_Rot00")
    p = scan.provenance
    assert p["doi"] == "10.7910/DVN/FCMUJQ"
    assert p["licence"] == "CC0-1.0"
    assert p["archive_md5_verified"] is True
    assert p["source_files_unmodified"] is True


@REAL_PK266
def test_the_real_volume_has_the_grid_shape_and_one_line_is_a_bscan():
    scan = load_scan("Pk266", "Pk266_3D_Dataset_1_5_GHz_Rot00")
    vol = load_volume(scan)
    assert vol.shape == (401, 161, 512)
    assert line_traces(vol, 0).shape == (401, 512)


@REAL_BOTH
def test_both_specimens_share_one_grid():
    a, b = load_grid(PK266), load_grid(PK050)
    assert np.array_equal(a.x, b.x)
    assert np.array_equal(a.y, b.y)
    assert np.array_equal(a.z, b.z)
