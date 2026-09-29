"""
The BAM baseline through the generic, blind workflow.

    python scripts/score_bam_generic.py [--out artifacts/bam/generic_baseline.json]

For each antenna (1.5 and 2.6 GHz, Rot00) and each specimen (Pk266 targets,
Pk050 attested-empty control):

  1. DETECT, blind, in a separate interpreter (`python -m
     benchmark.blind_detection`), writing a prediction artifact to disk. That
     process never imports a truth module.
  2. SCORE, reading the artifact back from disk and the generic manifest.

Then the Pk266 result is checked against the legacy scorer
(`benchmark.scoring.score_detection`) on the SAME detections, wherever the two
define the same quantity. The detector is unchanged and untuned.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCANS = ("1_5_GHz_Rot00", "2_6_GHz_Rot00")


def detect(specimen: str, scan: str, out: Path) -> None:
    subprocess.run([sys.executable, "-m", "benchmark.blind_detection", specimen, scan, str(out)],
                   check=True, cwd=ROOT)


def legacy_equivalence(artifact, result) -> dict:
    """Legacy score on the SAME detections, rebuilt from the artifact."""
    from benchmark.bam_ingest import load_scan
    from benchmark.bam_truth import load_targets
    from benchmark.detection import BenchmarkDetection, DetectionRun
    from benchmark.scoring import score_detection

    scan = load_scan("Pk266", artifact.acquisition_id)
    dets = [BenchmarkDetection(
        scan_id=artifact.acquisition_id, line_index=int(p.line_id[1:]),
        detection_id=p.prediction_id,
        trace_indices=tuple(range(p.detail["trace_span"][0], p.detail["trace_span"][1] + 1)),
        sample_indices=(p.detail["peak_sample"],), peak_trace=p.detail["peak_trace"],
        peak_sample=p.detail["peak_sample"], peak_z=p.detail["peak_z"],
        n_cells=p.detail["n_cells"]) for p in artifact.predictions]
    run = DetectionRun(scan_id=artifact.acquisition_id, specimen_id="Pk266", detections=dets,
                       lines_processed=len(artifact.lines), threshold=artifact.detector["threshold"],
                       min_cells=artifact.detector["min_cells"])
    legacy = score_detection(run, load_targets(scan.grid, "Pk266"))
    c, m = result["counts"], result["metrics"]
    hits = sum(v["lines_with_a_match"] for v in legacy.per_target.values())
    checks = {
        "target_line_hits (legacy) == true_positives (generic)": (hits, c["true_positives"]),
        "recall": (legacy.recall, m["recall"]),
        "matched detections: legacy true_positives == generic TP + duplicates":
            (legacy.true_positives, c["matched_detections_incl_duplicates"]),
        "legacy false_positives == generic FP - duplicates":
            (legacy.false_positives, c["false_positives"] - c["duplicate_detections"]),
        "false_negatives": (legacy.false_negatives, c["false_negatives"]),
        "per-target lines matched": (
            {k: v["lines_with_a_match"] for k, v in legacy.per_target.items()},
            {k: v["matched"] for k, v in result["per_target"].items()}),
    }
    return {"equal": {k: a == b for k, (a, b) in checks.items()},
            "values": {k: [a, b] for k, (a, b) in checks.items()},
            "precision_definitions_differ": {
                "legacy": legacy.precision, "generic_one_to_one": m["precision"],
                "why": "legacy counts every detection inside a footprint as a true positive, so "
                       "a second detection of the same duct on the same line raises precision; "
                       "the generic scorer is one-to-one and counts that second detection as a "
                       "duplicate false positive"}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/bam/generic_baseline.json")
    args = ap.parse_args()
    work = args.out.parent
    work.mkdir(parents=True, exist_ok=True)

    report = {"scans": {}}
    for scan in SCANS:
        paths = {s: work / f"predictions_{s}_{scan}.json" for s in ("Pk266", "Pk050")}
        for specimen, path in paths.items():
            detect(specimen, scan, path)

        # --- truth is read only from here on ---
        from benchmark.predictions import PredictionArtifact
        from benchmark.target_scoring import BAM_FOOTPRINT_RULE, score
        from benchmark.targets import MANIFEST_DIR, load_manifest

        a266 = PredictionArtifact.read(paths["Pk266"])
        r266 = score(a266, load_manifest(MANIFEST_DIR / "bam-pk266.targets.json"),
                     BAM_FOOTPRINT_RULE)
        a050 = PredictionArtifact.read(paths["Pk050"])
        r050 = score(a050, load_manifest(MANIFEST_DIR / "bam-pk050.targets.json"),
                     BAM_FOOTPRINT_RULE)
        report["scans"][scan] = {"Pk266": r266, "Pk050_control": r050,
                                 "legacy_equivalence": legacy_equivalence(a266, r266)}

    from benchmark.target_scoring import by_frequency
    report["by_frequency_Pk266"] = by_frequency([v["Pk266"] for v in report["scans"].values()])
    args.out.write_text(json.dumps(report, indent=1, default=str))

    for scan, v in report["scans"].items():
        r, c = v["Pk266"], v["Pk050_control"]
        print(f"{scan}: Pk266 {r['counts']} metrics recall={r['metrics']['recall']} "
              f"precision={r['metrics']['precision']} f1={r['metrics']['f1']}")
        print(f"   Pk050 control: {c['counts']['predictions']} predictions, "
              f"FP/line={c['metrics']['false_positives_per_line']}")
        print(f"   legacy equivalence: {v['legacy_equivalence']['equal']}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
