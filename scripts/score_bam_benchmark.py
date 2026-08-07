"""
Score Subterra's existing detector on the BAM concrete benchmark.

Detection and false alarms only. Localisation is gated in `benchmark.gates` and
is not attempted.

    python scripts/score_bam_benchmark.py \
        --scan 1_5_GHz_Rot00 --lines 40 --out artifacts/bam/score.json

`--lines N` scores an evenly spaced subset of the 161 Y lines; the count is
recorded in the output so a partial run can never read as a full one.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from benchmark import gates
from benchmark.association import associate
from benchmark.bam_ingest import DEFAULT_ROOT, load_scan, load_volume
from benchmark.bam_truth import load_control, load_targets
from benchmark.detection import detect_scan
from benchmark.scoring import score_detection, score_false_alarms
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS


def _lines(n_total: int, wanted: int | None):
    if not wanted or wanted >= n_total:
        return list(range(n_total))
    return [int(round(i)) for i in np.linspace(0, n_total - 1, wanted)]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scan", default="1_5_GHz_Rot00",
                   help="antenna/polarisation suffix, e.g. 1_5_GHz_Rot00")
    p.add_argument("--lines", type=int, default=None,
                   help="score an evenly spaced subset of Y lines (default: all 161)")
    p.add_argument("--threshold", type=float, default=DEFAULT_ANOMALY_THRESHOLD)
    p.add_argument("--min-cells", type=int, default=DEFAULT_MIN_CELLS)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--out", type=Path, default=Path("artifacts/bam/score.json"))
    args = p.parse_args()

    started = time.time()
    report: dict = {
        "benchmark": "bam-concrete-gpr",
        "scope": gates.SCOPE_STATEMENT,
        "localization_status": gates.LOCALIZATION_STATUS,
        "localization_blocked_reason": gates.LOCALIZATION_BLOCKED_REASON,
        "open_questions": [q.id for q in gates.OPEN_QUESTIONS],
        "threshold": args.threshold,
        "min_cells": args.min_cells,
        "parameters_changed_for_this_benchmark": "none",
    }

    # --- targets ---
    target_scan = load_scan("Pk266", f"Pk266_3D_Dataset_{args.scan}", root=args.root)
    targets = load_targets(target_scan.grid, "Pk266")
    report["grid"] = target_scan.grid.as_dict()
    report["dzt"] = target_scan.dzt_header
    report["provenance"] = target_scan.provenance
    report["association"] = [r.as_dict() for r in associate(target_scan, targets)]

    vol = load_volume(target_scan, root=args.root)
    lines = _lines(vol.shape[1], args.lines)
    run = detect_scan(target_scan, vol, threshold=args.threshold,
                      min_cells=args.min_cells, line_indices=lines)
    del vol
    report["detection"] = score_detection(run, targets).as_dict()
    report["detection"]["lines_requested"] = args.lines
    report["detection"]["lines_available"] = 161
    report["detection"]["n_detections"] = len(run.detections)

    # --- control ---
    control_scan = load_scan("Pk050", f"Pk050_3D_Dataset_{args.scan}", root=args.root)
    cvol = load_volume(control_scan, root=args.root)
    crun = detect_scan(control_scan, cvol, threshold=args.threshold,
                       min_cells=args.min_cells, line_indices=_lines(cvol.shape[1], args.lines))
    del cvol
    report["false_alarms"] = score_false_alarms(crun, load_control("Pk050")).as_dict()

    report["wall_seconds"] = round(time.time() - started, 1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1))

    d, fa = report["detection"], report["false_alarms"]
    print(f"scan={args.scan} lines={d['lines_processed']}/161 "
          f"threshold={args.threshold} min_cells={args.min_cells}")
    print(f"  detections on Pk266: {d['n_detections']}")
    print(f"  TP={d['true_positives']} FP={d['false_positives']} FN={d['false_negatives']}")
    print(f"  recall={d['recall']} precision={d['precision']} f1={d['f1']}")
    print(f"  control Pk050: {fa['n_detections']} detections, "
          f"per_line={fa['detections_per_line']}, rate={fa['false_alarm_rate']}")
    print(f"  localisation: {report['localization_status']} "
          f"({report['localization_blocked_reason']})")
    print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
