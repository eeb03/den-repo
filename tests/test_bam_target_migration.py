"""
BAM Pk266/Pk050 migrated to the generic target schema without changing their
scientific meaning.

Two things are proved:
  1. FIELD BY FIELD, the generic manifests say exactly what
     `benchmark/bam_pk266_targets.json` says -- read independently here, not
     through the script that generated them -- and nothing more: unknowns stay
     unknown, and every open question survives with what it blocks.
  2. ON THE SAME DETECTIONS, the generic scorer reproduces the legacy scorer
     (`benchmark.scoring.score_detection`) wherever the two define the same
     quantity. Precision is defined differently (legacy counts every detection
     inside a footprint; generic is one-to-one) and that difference is exactly
     the duplicate count.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from benchmark import gates
from benchmark.bam_ingest import DEFAULT_ROOT, GridSpec
from benchmark.bam_truth import load_targets
from benchmark.blind_detection import bam_frame_id
from benchmark.detection import BenchmarkDetection, DetectionRun
from benchmark.predictions import AcquisitionLine, Prediction, PredictionArtifact, TimingProvenance
from benchmark.scoring import score_detection
from benchmark.target_scoring import BAM_FOOTPRINT_RULE, score
from benchmark.targets import MANIFEST_DIR, Capability, MeasuredTo, load_manifest

LEGACY = json.loads(Path("benchmark/bam_pk266_targets.json").read_text())
PK266 = load_manifest(MANIFEST_DIR / "bam-pk266.targets.json")
PK050 = load_manifest(MANIFEST_DIR / "bam-pk050.targets.json")
FRAME = bam_frame_id("Pk266")


def legacy_spec(sid):
    return next(s for s in LEGACY["specimens"] if s["id"] == sid)


# ---------------------------------------------------------------------------
# 1. the same physical meaning
# ---------------------------------------------------------------------------

def test_all_four_targets_load_in_the_specimen_frame():
    assert [t.target_id for t in PK266.targets] == [
        t["target_id"] for t in legacy_spec("Pk266")["targets"]]
    assert all(t.location_in(FRAME) for t in PK266.targets)


@pytest.mark.parametrize("i", range(4))
def test_each_target_says_exactly_what_the_legacy_file_says(i):
    old = legacy_spec("Pk266")["targets"][i]
    new = PK266.targets[i]
    assert new.object_class == old["type"]
    assert new.material == old["material"]
    assert new.dimensions.shape == old["geometry"]["shape"]
    assert new.dimensions.outer_diameter == old["geometry"]["outer_diameter_mm"]
    assert new.dimensions.inner_diameter == old["geometry"]["inner_diameter_mm"]
    assert new.dimensions.units == "mm"
    assert new.dimensions.length is None            # not stated; not invented
    loc = new.location_in(FRAME)
    assert loc.start == (old["x_mm"], old["extent"]["y_from_mm"])
    assert loc.end == (old["x_mm"], old["extent"]["y_to_mm"])
    assert loc.uncertainty is None                  # no tolerance is published
    centre, cover = new.depths
    assert (centre.value, centre.measured_to) == (old["centre_depth_mm"], MeasuredTo.CENTRE)
    assert (cover.value, cover.uncertainty) == (old["concrete_cover_mm"],
                                                old["concrete_cover_tolerance_mm"])
    assert cover.measured_to is MeasuredTo.UNRESOLVED
    assert cover.open_question == "cover-vs-centre-reference"
    assert {d.reference_surface for d in new.depths} == {"measuring_surface"}
    assert new.absolute_elevation is None           # no vertical datum exists here


def test_the_evidence_is_published_placement_not_a_subterra_verification():
    for t in PK266.targets:
        assert t.evidence.basis.value == "publication_transcription"
        assert t.evidence.grade.value == "measurement_associated"      # B, not A
        assert t.evidence.independent_of_gpr is True
        assert t.evidence.verified_by_subterra is False


def test_the_frame_keeps_the_legacy_frame_and_its_doubts():
    f = PK266.frame(FRAME)
    assert f.kind.value == "local_cartesian" and f.crs is None and f.units == "mm"
    assert f.origin_status == "corroborated"        # not declared: see absolute-origin
    assert f.units_status == "documentation_prose"  # see coordinate-units
    assert f.registration_to_radar == "corroborated"


def test_every_open_question_is_carried():
    ids = {q.id for q in PK266.open_questions}
    assert {q.id for q in gates.OPEN_QUESTIONS} <= ids
    assert {q["id"] for q in LEGACY["open_questions"]} <= ids


def test_the_gates_match_the_legacy_gates():
    ok, _ = PK266.capability(Capability.DETECTION_MATCHING, FRAME)
    assert ok is True and gates.DETECTION_STATUS == gates.RESOLVED
    for cap in (Capability.LOCALIZATION_ERROR, Capability.FALSE_ALARMS_PER_METRE,
                Capability.DEPTH_SCORING):
        ok, reasons = PK266.capability(cap, FRAME)
        assert ok is False and reasons
    assert gates.LOCALIZATION_STATUS == gates.BLOCKED


def test_readiness_is_derived_from_the_gates():
    assert PK266.readiness()["status"] == "scoring_ready"
    assert PK050.readiness()["status"] == "control_only"


def test_the_control_is_attested_empty_with_its_caveat():
    c = legacy_spec("Pk050")
    assert PK050.targets == ()
    assert PK050.exhaustive["value"] is bool(c["empty_is_attested"]) is True
    assert PK050.exhaustive["caveat"] == c["back_wall_note"]


# ---------------------------------------------------------------------------
# 2. the same score on the same detections
# ---------------------------------------------------------------------------

def bam_grid():
    return GridSpec(x=np.arange(0.0, 2000.1, 5.0), y=np.arange(0.0, 800.1, 5.0),
                    z=np.linspace(0.0, 15.0, 512))


def run_and_artifact(peaks):
    """`peaks`: (line, peak_trace) pairs. The same detections, two shapes."""
    grid = bam_grid()
    dets = [BenchmarkDetection(scan_id="s", line_index=ln, detection_id=f"s:L{ln}:{k}",
                               trace_indices=(tr,), sample_indices=(10,), peak_trace=tr,
                               peak_sample=10, peak_z=4.0, n_cells=3)
            for k, (ln, tr) in enumerate(peaks)]
    lines = range(161)
    run = DetectionRun(scan_id="s", specimen_id="Pk266", detections=dets,
                       lines_processed=len(lines), threshold=3.0, min_cells=3)
    art = PredictionArtifact(
        dataset_id="bam-concrete-gpr:Pk266", acquisition_id="s", frame_id=FRAME,
        frame_units="mm", detector={}, preprocessing={}, input_sha256="x",
        timing=TimingProvenance(), antenna_frequency_mhz=1500.0,
        lines=tuple(AcquisitionLine(f"L{i}", (0.0, float(grid.y[i])), (2000.0, float(grid.y[i])))
                    for i in lines),
        predictions=tuple(Prediction(prediction_id=d.detection_id, line_id=f"L{d.line_index}",
                                     position=(float(grid.x[d.peak_trace]),
                                               float(grid.y[d.line_index])))
                          for d in dets))
    return grid, run, art


PEAKS = [(0, 50), (0, 44), (0, 56), (0, 43), (0, 57), (3, 150), (3, 151), (7, 250),
         (7, 300), (9, 350), (9, 356), (9, 344), (12, 100), (160, 50), (160, 350)]


def test_generic_and_legacy_agree_on_the_same_detections():
    grid, run, art = run_and_artifact(PEAKS)
    legacy = score_detection(run, load_targets(grid, "Pk266"))
    generic = score(art, PK266, BAM_FOOTPRINT_RULE)
    c = generic["counts"]

    hits = sum(v["lines_with_a_match"] for v in legacy.per_target.values())
    assert c["true_positives"] == hits
    assert generic["metrics"]["recall"] == legacy.recall
    assert c["false_negatives"] == legacy.false_negatives
    assert c["matched_detections_incl_duplicates"] == legacy.true_positives
    assert c["false_positives"] - c["duplicate_detections"] == legacy.false_positives
    assert {k: v["matched"] for k, v in generic["per_target"].items()} == \
        {k: v["lines_with_a_match"] for k, v in legacy.per_target.items()}


def test_the_footprint_edge_is_the_same_edge():
    """Node 43/57 sit 35 mm from duct-1's axis, outside its 33.5 mm radius; 44/56
    sit 30 mm, inside. Legacy footprint [44, 56] and the generic radius agree."""
    grid, run, art = run_and_artifact([(0, 43), (1, 44), (2, 56), (3, 57)])
    generic = score(art, PK266, BAM_FOOTPRINT_RULE)
    assert {m["line_id"] for m in generic["matches"]} == {"L1", "L2"}


# ---------------------------------------------------------------------------
# real archive (skipped when the BAM archives are not present)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (DEFAULT_ROOT / "Pk266_Dataset.zip").exists(),
                    reason="BAM archive not present")
def test_real_blind_run_matches_the_legacy_scorer_on_a_line_subset():
    from benchmark.bam_ingest import load_scan
    from benchmark.blind_detection import run_bam

    lines = list(range(0, 161, 20))
    art = run_bam("Pk266", "1_5_GHz_Rot00", line_indices=lines)
    generic = score(art, PK266, BAM_FOOTPRINT_RULE)

    scan = load_scan("Pk266", "Pk266_3D_Dataset_1_5_GHz_Rot00")
    dets = [BenchmarkDetection(
        scan_id=art.acquisition_id, line_index=int(p.line_id[1:]), detection_id=p.prediction_id,
        trace_indices=(p.detail["peak_trace"],), sample_indices=(p.detail["peak_sample"],),
        peak_trace=p.detail["peak_trace"], peak_sample=p.detail["peak_sample"],
        peak_z=p.detail["peak_z"], n_cells=p.detail["n_cells"]) for p in art.predictions]
    legacy = score_detection(
        DetectionRun(scan_id=art.acquisition_id, specimen_id="Pk266", detections=dets,
                     lines_processed=len(lines), threshold=3.0, min_cells=3),
        load_targets(scan.grid, "Pk266"))
    assert generic["counts"]["matched_detections_incl_duplicates"] == legacy.true_positives
    assert generic["metrics"]["recall"] == legacy.recall
