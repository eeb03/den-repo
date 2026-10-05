"""
BAM: SCOREABLE is not VALIDATED.

Opening the benchmark gates (2026-10-05) means Subterra has independent ground
truth and a declared frame sufficient to COMPUTE depth and localisation metrics.
It does not mean any method performs well. These tests keep the two apart, keep
the appendix-drawing frame and its unresolved conflict with the paper's prose on
record, keep depth provenance attached to every depth score, and make sure an
X-only coincidence at the wrong depth can never count as a localisation hit.
"""
import json
from pathlib import Path

import pytest

from benchmark import gates
from benchmark.detection import BenchmarkDetection, DetectionRun
from benchmark.scoring import (LOCALIZATION_DEPTH_TOLERANCE_MM, LOCALIZATION_RADIUS_MM,
                               DepthCalibration, ScoringTarget, bam_scoring_targets,
                               score_depth, score_localization)
from benchmark.targets import MANIFEST_DIR, Capability, load_manifest

RESULTS = Path("evidence/bam/results/quantitative_validation.json")


# ------------------------------------------------------------- scoreable

@pytest.mark.parametrize("specimen", ["Pk266", "Pk401"])
def test_bam_is_scoreable_because_frame_units_and_truth_are_resolved(specimen):
    m = load_manifest(MANIFEST_DIR / f"bam-{specimen.lower()}.targets.json")
    frame = f"bam:{specimen}:specimen_mm"
    f = m.frame(frame)
    assert (f.origin_status, f.units_status, f.registration_to_radar) == ("declared",) * 3
    assert m.targets, "object ground truth from the appendix drawing is present"
    for cap in (Capability.LOCALIZATION_ERROR, Capability.DEPTH_SCORING,
                Capability.DETECTION_MATCHING, Capability.FALSE_ALARMS_PER_METRE):
        ok, reasons = m.capability(cap, frame)
        assert ok, (cap, reasons)
    resolved = {q.id for q in gates.OPEN_QUESTIONS if q.status == gates.RESOLVED}
    assert {"absolute-origin", "coordinate-units", "dzt-to-grid-mapping",
            "depth-reference-surface"} <= resolved
    assert all(q.resolution for q in gates.OPEN_QUESTIONS if q.status == gates.RESOLVED)


def test_scoreable_does_not_imply_validated():
    assert gates.LOCALIZATION_STATUS == gates.RESOLVED and gates.DEPTH_SCORING_STATUS == gates.RESOLVED
    s = gates.CAPABILITY_STATUS
    expected = {
        "dzt_ingestion": gates.VALIDATED,
        "amplitude_preservation": gates.VALIDATED,
        "backwall_time_zero_velocity_calibration": gates.PARTIALLY_VALIDATED,
        "duct_depth_at_known_position_backwall_calibrated": gates.PARTIALLY_VALIDATED,
        "foam_block_depth": gates.EXPERIMENTAL,
        "method_c_depth_chain_time_zero": gates.FAILED,
        "current_detector_localisation": gates.FAILED,
        "current_detector_detection": gates.FAILED,
        "lateral_localisation": gates.FAILED,
        "candidate_generation": gates.FAILED,
        "false_positive_rejection": gates.FAILED,
        "experimental_envelope_detector": gates.EXPERIMENTAL,
    }
    assert s == expected
    # the RESOLVED vocabulary of the gates never appears as a capability status
    assert gates.RESOLVED not in s.values()


def test_the_strong_duct_result_is_described_as_known_position_not_detection():
    text = gates.CAPABILITY_EVIDENCE["duct_depth_at_known_position_backwall_calibrated"]
    assert "INDEPENDENTLY KNOWN object position" in text
    assert "known-thickness back wall" in text
    assert "Not a detection result" in text


def test_method_c_remains_failed_with_its_numbers():
    assert gates.CAPABILITY_STATUS["method_c_depth_chain_time_zero"] == gates.FAILED
    text = gates.CAPABILITY_EVIDENCE["method_c_depth_chain_time_zero"]
    assert "+72 mm" in text and "+43 mm" in text and "+7 mm" in text


def test_candidate_generation_failure_reasons_are_recorded():
    text = gates.CAPABILITY_EVIDENCE["candidate_generation"]
    for reason in ("1.7-2.0", "3.0 threshold", "direct wave", "late-time noise",
                   "step edges", "X-only matching"):
        assert reason in text, reason
    assert gates.CAPABILITY_STATUS["experimental_envelope_detector"] == gates.EXPERIMENTAL


# ------------------------------------------------------------- frame and conflict

def test_the_appendix_drawing_reference_frame_is_recorded():
    assert gates.REFERENCE_FRAME_SOURCE.startswith("appendix construction drawings")
    for spec in ("pk266", "pk050", "pk401"):
        d = json.loads((MANIFEST_DIR / f"bam-{spec}.targets.json").read_text())
        ts = d["truth_source"]
        assert ts["reference_frame_source"] == gates.REFERENCE_FRAME_SOURCE
        assert "appendix construction drawing" in d["frames"][0]["origin"].lower()


def test_the_paper_drawing_origin_conflict_is_retained_not_resolved():
    assert "thin side" in gates.REFERENCE_FRAME_CONFLICT
    assert "Not resolved" in gates.REFERENCE_FRAME_CONFLICT
    assert "not proof of intent" in gates.REFERENCE_FRAME_SUPPORT
    for spec in ("pk266", "pk050", "pk401"):
        d = json.loads((MANIFEST_DIR / f"bam-{spec}.targets.json").read_text())
        assert d["truth_source"]["reference_frame_conflict"] == gates.REFERENCE_FRAME_CONFLICT
        assert "not scientifically resolved" in d["truth_source"]["reference_frame_resolution"]
        assert "CONFLICT RETAINED" in d["frames"][0]["registration_note"]


# ------------------------------------------------------------- depth provenance

def test_depth_calibration_requires_a_known_provenance_and_source():
    with pytest.raises(ValueError):
        DepthCalibration(1.0, 0.12, "hyperbola_on_the_scored_targets", "x")
    with pytest.raises(ValueError):
        DepthCalibration(1.0, 0.12, "known_thickness_backwall", "  ")
    for p in gates.DEPTH_PROVENANCES:
        DepthCalibration(1.0, 0.12, p, "source")


def test_depth_scores_keep_provenance_and_position_source():
    cal = DepthCalibration(1.0812, 0.12889, "known_thickness_backwall", "Pk266 1.5 GHz back-wall fit")
    r = score_depth([("Pk266-duct-1", 248.1, 241.0), ("Pk266-duct-2", 183.8, 181.1)], cal,
                    position_source="independently known from the appendix drawing")
    assert r["depth_provenance"] == "known_thickness_backwall"
    assert r["position_source"].startswith("independently known")
    assert r["error_mm"]["n"] == 2 and r["error_mm"]["mean_signed"] == pytest.approx(4.9)
    with pytest.raises(ValueError):
        score_depth([], cal, position_source="")


# ------------------------------------------------------------- localisation rule

class _Grid:
    def __init__(self):
        self.x = [5.0 * i for i in range(401)]
        self.y = [0.0, 5.0]
        self.z = [0.02935421 * i for i in range(512)]


def _det(line, x_node, sample, z=5.0, did="d"):
    return BenchmarkDetection(scan_id="S", line_index=line, detection_id=did,
                              trace_indices=(x_node,), sample_indices=(sample,),
                              peak_trace=x_node, peak_sample=sample, peak_z=z, n_cells=3)


def test_an_x_coincidence_at_the_wrong_depth_is_not_a_hit():
    grid = _Grid()
    cal = DepthCalibration(1.0, 0.12, "known_thickness_backwall", "test")
    target = ScoringTarget("T", x_mm=250.0, z_top_mm=241.0)
    # right X (node 50 = 250 mm), depth ~ 0.1 ns -> far above the target: a coincidence
    shallow = _det(0, 50, 5, did="coincidence")
    run = DetectionRun(scan_id="S", specimen_id="Pk266", detections=[shallow], lines_processed=2,
                       threshold=3.0, min_cells=3)
    r = score_localization(run, grid, [target], cal)
    assert r["recall"] == 0.0 and r["false_positives"] == 1

    # same X, depth at the target top -> a hit with ~0 error
    t_top = 1.0 + 2 * 0.241 / 0.12
    good = _det(0, 50, int(round(t_top / grid.z[1])), did="hit")
    run = DetectionRun(scan_id="S", specimen_id="Pk266", detections=[good], lines_processed=2,
                       threshold=3.0, min_cells=3)
    r = score_localization(run, grid, [target], cal)
    assert r["per_target"]["T"]["lines_matched"] == 1 and r["false_positives"] == 0
    assert abs(r["depth_error_mm"]["mean_signed"]) < LOCALIZATION_DEPTH_TOLERANCE_MM
    assert r["depth_provenance"] == "known_thickness_backwall"


def test_the_strongest_x_window_detection_must_itself_be_at_the_right_depth():
    """Pre-registered L-XZ: the highest-|z| detection in the X window is the candidate;
    a weaker detection at the right depth does not rescue a strong wrong-depth one."""
    grid = _Grid()
    cal = DepthCalibration(1.0, 0.12, "known_thickness_backwall", "test")
    target = ScoringTarget("T", x_mm=250.0, z_top_mm=241.0)
    t_top = 1.0 + 2 * 0.241 / 0.12
    strong_wrong = _det(0, 52, 5, z=9.0, did="strong-wrong-depth")
    weak_right = _det(0, 50, int(round(t_top / grid.z[1])), z=4.0, did="weak-right-depth")
    run = DetectionRun(scan_id="S", specimen_id="Pk266", detections=[strong_wrong, weak_right],
                       lines_processed=2, threshold=3.0, min_cells=3)
    r = score_localization(run, grid, [target], cal)
    assert r["per_target"]["T"]["lines_matched"] == 0
    assert r["false_positives"] == 2


def test_the_rule_is_the_pre_registered_one():
    assert (LOCALIZATION_RADIUS_MM, LOCALIZATION_DEPTH_TOLERANCE_MM) == (100.0, 60.0)
    import scripts.bam_quantitative_validation as research
    assert (research.MATCH_RADIUS_MM, research.MATCH_DEPTH_MM) == (100.0, 60.0)


def test_scoring_targets_come_from_the_declared_manifests():
    pk266 = {t.target_id: t for t in bam_scoring_targets("Pk266")}
    assert pk266["Pk266-duct-1"].x_mm == 250.0
    assert pk266["Pk266-duct-1"].z_top_mm == pytest.approx(274.5 - 33.5)
    assert pk266["Pk266-duct-1"].y_mm is None
    pk401 = {t.target_id: t for t in bam_scoring_targets("Pk401")}
    c3 = pk401["Pk401-cuboid-3"]
    assert (c3.x_mm, c3.y_mm, c3.z_top_mm, c3.y_half_extent_mm) == (1250.0, 498.2, 120.0, 60.0)


# ------------------------------------------------------------- real data: still FAILED

@pytest.mark.skipif(not Path("datasets/raw/bam_concrete/Pk266_Dataset.zip").exists(),
                    reason="BAM archive not present")
def test_current_detector_is_still_failed_after_the_gate_opens():
    """The production detector, scored by the now-open scorer, is still far from usable."""
    from benchmark.bam_ingest import load_scan, load_volume
    from benchmark.detection import detect_scan
    res = json.loads(RESULTS.read_text())["scans"]["Pk266_3D_Dataset_1_5_GHz_Rot00"]
    c = res["calibration_backwall_peak"]
    cal = DepthCalibration(c["t0_ns"], c["v_m_per_ns"], "known_thickness_backwall",
                           "evidence/bam/results/quantitative_validation.json")
    scan = load_scan("Pk266", "Pk266_3D_Dataset_1_5_GHz_Rot00")
    vol = load_volume(scan)
    run = detect_scan(scan, vol)
    r = score_localization(run, scan.grid, bam_scoring_targets("Pk266"), cal)
    # identical to the pre-registered research scorer's L-XZ recall (0.0047)
    assert r["recall"] == pytest.approx(res["baseline_detector"]["recall_LXZ"], abs=1e-4)
    assert r["recall"] < 0.05
    assert gates.CAPABILITY_STATUS["current_detector_localisation"] == gates.FAILED


# ------------------------------------------------------------- vocabulary separation

def test_scoring_and_capability_vocabularies_are_separate():
    assert set(gates.SCORING_STATUSES) == {gates.BLOCKED, gates.RESOLVED}
    assert gates.RESOLVED not in gates.CAPABILITY_STATUSES
    assert gates.VALIDATED not in gates.SCORING_STATUSES
    assert set(gates.CAPABILITY_STATUS.values()) <= set(gates.CAPABILITY_STATUSES)


def test_the_legacy_name_is_an_alias_of_the_scoring_gate():
    assert gates.LOCALIZATION_STATUS is gates.LOCALIZATION_SCORING_STATUS
    assert gates.LOCALIZATION_SCORING_STATUS in gates.SCORING_STATUSES


def test_the_status_report_puts_gate_and_capability_side_by_side():
    r = gates.bam_status_report()
    assert r["localization_scoring_status"] == gates.RESOLVED
    assert "not a performance claim" in r["scoring_status_meaning"]
    assert r["capability_status"]["current_detector_localisation"] == gates.FAILED
    assert r["capability_status"]["foam_block_depth"] == gates.EXPERIMENTAL
    assert "localization_status" not in r          # the ambiguous name is never emitted
    assert r["reference_frame_conflict"] == gates.REFERENCE_FRAME_CONFLICT


def test_new_bam_artifacts_never_carry_the_ambiguous_field():
    src = Path("scripts/score_bam_benchmark.py").read_text()
    assert '"localization_status"' not in src
    assert "bam_status_report()" in src
    assert "q.status != gates.RESOLVED" in src     # open_questions lists only unresolved ones


def test_generic_localisation_output_is_labelled_horizontal_only_and_not_a_capability():
    """The generic manifest scorer matches horizontally; it must say so wherever it reports."""
    import inspect

    from benchmark import target_scoring
    src = inspect.getsource(target_scoring)
    assert '"depth_checked": False' in src
    assert "not a capability claim" in src
    assert "score_localization" in src
