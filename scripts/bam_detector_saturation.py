"""
Real-data arm of the detector-saturation experiment: the production ring,
the widened ring and the hyperbola stack on BAM concrete, under the
pre-registration in docs/detector-saturation-experiment.md §7.

* Detector configurations come from simulation/detector_freeze.json, unchanged.
  Only the operating THRESHOLD is re-frozen, on the development scan only.
  The rule: the lowest FP/line at dev L-XZ recall >= 0.80; if unreachable,
  the highest dev recall at FP/line <= 2.04 (production's dev rate). The
  frozen threshold is then applied unchanged to the held-out and control scans.
* Split and matching are those of the Candidate-V2 experiment
  (research/candidate-generation-v2): dev Pk266 1.5 GHz; held out Pk266 2.6,
  Pk401 1.5, Pk401 2.6 (L-X only: calibration refused); controls Pk050 1.5
  and 2.6. L-XZ: per (line, target), the highest-|z| detection with
  |dx| <= 100 mm must lie within 60 mm of the drawn top depth under the
  scan's back-wall calibration. The scorer is ported verbatim from that
  harness.
* Cost: the hyperbola stack's cone spans hundreds of traces on these 401-trace
  lines, so every detector is scored on the SAME 41 evenly spaced lines
  per scan (`score_bam_benchmark.py --lines` convention; recorded). The
  production ring is also run on all 161 lines, to check that this harness
  reproduces the published production numbers.
* Arms: mean-trace subtraction (production) and no removal. Real data has no
  target-free twin.

    python -m scripts.bam_detector_saturation --out artifacts/bam/detector_saturation.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from benchmark.bam_ingest import line_traces, load_scan, load_volume
from benchmark.detection import detect_line
from benchmark.hyperbola_stack import estimate_time_zero
from interpretation.anomaly_candidates import DEFAULT_MIN_CELLS
from preprocessing.spatial_grid import anomaly_grid_from_traces
from scripts.bam_quantitative_validation import (MATCH_DEPTH_MM, MATCH_RADIUS_MM, depth_mm, lines_for,
                                                 load_gt, run_detector)
from simulation.detector_comparison import THRESHOLDS, detector_grid

warnings.filterwarnings("ignore", category=RuntimeWarning)

DEV = ("Pk266", "1_5_GHz_Rot00")
TEST = [("Pk266", "2_6_GHz_Rot00"), ("Pk401", "1_5_GHz_Rot00"), ("Pk401", "2_6_GHz_Rot00")]
CONTROL = [("Pk050", "1_5_GHz_Rot00"), ("Pk050", "2_6_GHz_Rot00")]
VAL = Path("artifacts/bam/validation/quantitative_validation.json")
N_LINES = 41
TARGET_RECALL = 0.80
PRODUCTION_DEV_FP_PER_LINE = 2.04
#: Published production results (all 161 lines), research/candidate-generation-v2.
PUBLISHED_PRODUCTION = {
    "Pk266_1_5_GHz_Rot00": {"recall": 0.005, "fp_per_line": 2.04},
    "Pk266_2_6_GHz_Rot00": {"recall": 0.0528, "fp_per_line": 2.4348},
    "Pk401_1_5_GHz_Rot00": {"recall": 0.000, "fp_per_line": 5.03},
    "Pk401_2_6_GHz_Rot00": {"recall": 0.271, "fp_per_line": 2.77},
    "Pk050_1_5_GHz_Rot00": {"recall": None, "fp_per_line": 2.7888},
    "Pk050_2_6_GHz_Rot00": {"recall": None, "fp_per_line": 1.70},
}
ARMS = {"mean_trace_subtraction": lambda tr: tr - tr.mean(axis=0),
        "no_background_removal": lambda tr: tr}


class Scan:
    def __init__(self, spec, scan, val, targets_by_spec):
        self.spec, self.scan = spec, scan
        self.sid = f"{spec}_3D_Dataset_{scan}"
        self.s = load_scan(spec, self.sid)
        self.cal = val["scans"][self.sid]["calibration_backwall_peak"]
        self.targets = targets_by_spec.get(spec, [])
        self.f_nominal = 1.5e9 if scan.startswith("1_5") else 2.6e9

    @property
    def depth_scoreable(self):
        return self.cal is not None


def score(dets, sc: Scan, lines: list[int]) -> dict:
    """Ported from scripts/bam_candidate_v2_experiment.py (research branch):
    strict L-XZ where calibrated, otherwise L-X; ranked by |z|; restricted to
    the scored lines."""
    by_line: dict[int, list] = {}
    for i, d in enumerate(dets):
        by_line.setdefault(d["line"], []).append(i)
    used, dx, dz, dup, hits, opp = set(), [], [], 0, 0, 0
    lineset = set(lines)

    def depth_of(d):
        return depth_mm(d["t_ns"], sc.cal["t0_ns"], sc.cal["v_m_per_ns"])

    for t in sc.targets:
        for j in [j for j in lines_for(t, sc.s.grid) if j in lineset]:
            opp += 1
            win = [i for i in by_line.get(j, []) if abs(dets[i]["x"] - t["x"]) <= MATCH_RADIUS_MM]
            if not win:
                continue
            best = max(win, key=lambda i: dets[i]["z"])
            if sc.depth_scoreable:
                if abs(depth_of(dets[best]) - t["z_top"]) > MATCH_DEPTH_MM:
                    continue
                good = [i for i in win if abs(depth_of(dets[i]) - t["z_top"]) <= MATCH_DEPTH_MM]
                dz.append(depth_of(dets[best]) - t["z_top"])
            else:
                good = win
            used.update(good)
            dup += len(good) - 1
            dx.append(dets[best]["x"] - t["x"])
            hits += 1
    fp = len(dets) - len(used)
    rec = hits / opp if opp else None
    prec = hits / (hits + fp) if (hits + fp) else None
    return {"rule": "L-XZ" if sc.depth_scoreable else "L-X (depth not scoreable: calibration refused)",
            "lines": len(lines), "n_detections": len(dets), "opportunities": opp, "hits": hits,
            "recall": rec, "precision": prec, "false_positives": fp,
            "false_positives_per_line": fp / len(lines), "duplicates": dup,
            "median_abs_dx_mm": float(np.median(np.abs(dx))) if dx else None,
            "median_abs_dz_mm": float(np.median(np.abs(dz))) if dz else None}


_VOL = None
_SCAN = None


def _init(vol, scan_meta):
    global _VOL, _SCAN
    _VOL, _SCAN = vol, scan_meta


def _line_job(args):
    """One line, one detector, one arm: detections at every threshold."""
    y, det, cfg, arm = args
    grid = _SCAN["grid"]
    raw = line_traces(_VOL, y).astype(float)                 # (n_traces, n_samples)
    dt = (grid.z[1] - grid.z[0]) * 1e-9
    t_off = grid.z[0] * 1e-9
    x_m = np.asarray(grid.x, float) / 1000.0                 # BAM X is mm (open question `coordinate-units`)

    class _L:  # the acquisition facts detector_grid reads; nothing else
        midpoint_x_m, dt_s, time_offset_s = x_m, dt, t_off
    tz = estimate_time_zero(raw, dt, t_off)
    c0 = time.process_time()
    z, _ = detector_grid(det, cfg, ARMS[arm](raw), _L, tz, _SCAN["f_nominal"])
    cpu = time.process_time() - c0
    out = {}
    for thr in THRESHOLDS:
        out[str(thr)] = [{"line": y, "x": float(grid.x[d.peak_trace]), "t_ns": float(grid.z[d.peak_sample]),
                          "z": abs(d.peak_z)}
                         for d in detect_line(raw, _SCAN["sid"], y, threshold=thr,
                                              min_cells=DEFAULT_MIN_CELLS, estimator=lambda _t: z)]
    return y, out, cpu


def run_scan(sc: Scan, freeze: dict, lines: list[int], workers: int) -> dict:
    vol = load_volume(sc.s)
    res = {}
    with Pool(workers, initializer=_init,
              initargs=(vol, {"grid": sc.s.grid, "f_nominal": sc.f_nominal, "sid": sc.sid})) as pool:
        for det, d in freeze["detectors"].items():
            if det == "ring_production_threshold":
                continue
            for arm in ARMS:
                per_thr = {str(t): [] for t in THRESHOLDS}
                cpus = []
                for _y, out, cpu in pool.imap(_line_job, [(y, det, d["config"], arm) for y in lines]):
                    cpus.append(cpu)
                    for thr, dets in out.items():
                        per_thr[thr].extend(dets)
                res[f"{det}|{arm}"] = {"curve": {thr: score(dets, sc, lines) for thr, dets in per_thr.items()},
                                       "median_cpu_s_per_line": float(np.median(cpus))}
    # harness check: production exactly as published (anomaly_grid_from_traces, all lines, 3.0)
    all_lines = list(range(len(sc.s.grid.y)))
    prod = run_detector(vol, sc.s.grid, sc.sid, estimator=anomaly_grid_from_traces)
    res["harness_check_production_all_lines"] = score(prod, sc, all_lines)
    del vol
    return res


def freeze_threshold(curve: dict) -> tuple[float | None, str]:
    pts = [(float(t), r) for t, r in curve.items()]
    ok = [(t, r) for t, r in pts if (r["recall"] or 0) >= TARGET_RECALL]
    if ok:
        t, _ = min(ok, key=lambda p: (p[1]["false_positives_per_line"], -p[0]))
        return t, f"lowest FP/line at dev recall >= {TARGET_RECALL}"
    ok = [(t, r) for t, r in pts if r["false_positives_per_line"] <= PRODUCTION_DEV_FP_PER_LINE]
    if ok:
        t, _ = max(ok, key=lambda p: (p[1]["recall"] or 0, p[0]))
        return t, f"recall {TARGET_RECALL} unreachable; highest dev recall at FP/line <= {PRODUCTION_DEV_FP_PER_LINE}"
    return None, "no threshold meets either rule on dev"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("artifacts/bam/detector_saturation.json"))
    p.add_argument("--freeze", type=Path, default=Path("simulation/detector_freeze.json"))
    p.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = p.parse_args(argv)
    freeze = json.loads(args.freeze.read_text())
    val = json.loads(VAL.read_text())
    targets, _ = load_gt()
    report = {"protocol": __doc__, "freeze": freeze, "published_production": PUBLISHED_PRODUCTION, "scans": {}}

    dev = Scan(*DEV, val, targets)
    lines = [int(round(i)) for i in np.linspace(0, len(dev.s.grid.y) - 1, N_LINES)]
    report["lines_scored"] = lines
    report["scans"][dev.sid] = {"role": "development", **run_scan(dev, freeze, lines, args.workers)}
    thresholds = {}
    for key, r in report["scans"][dev.sid].items():
        if "|" in key and key.endswith("|mean_trace_subtraction"):
            det = key.split("|")[0]
            thresholds[det] = dict(zip(("threshold", "rule"), freeze_threshold(r["curve"])))
    report["dev_frozen_thresholds"] = thresholds
    print(json.dumps(thresholds, indent=1), flush=True)

    for role, scans in (("held_out", TEST), ("control", CONTROL)):
        for spec, scan in scans:
            sc = Scan(spec, scan, val, targets)
            report["scans"][sc.sid] = {"role": role, **run_scan(sc, freeze, lines, args.workers)}
            print(sc.sid, "done", flush=True)
    for sid, entry in report["scans"].items():
        for key, r in entry.items():
            if "|" not in key:
                continue
            det = key.split("|")[0]
            thr = thresholds[det]["threshold"]
            r["at_dev_frozen_threshold"] = r["curve"][str(thr)] if thr is not None else None
    args.out.write_text(json.dumps(report, indent=1))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
