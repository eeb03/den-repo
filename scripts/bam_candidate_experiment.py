"""
CONTROLLED EXPERIMENT (not the baseline): an envelope candidate generator on BAM.

Kept strictly separate from the frozen baseline (`benchmark.detection`, ring
z-score), which is not modified. Both arms are scored with the SAME pre-
registered matching rules as `scripts/bam_quantitative_validation.py`
(L-X: |dx| <= 100 mm; L-XZ: L-X and |depth - z_top| <= 60 mm under the same
scan's back-wall calibration).

Arm E1, per scan line (B-scan of n_x traces x n_t samples):
  1. horizontal background removal: subtract a running MEDIAN along X over W
     traces (removes laterally continuous events: direct wave, back wall);
  2. Hilbert envelope along time;
  3. gate: TARGET_MIN_NS <= t <= t_end - END_GUARD_NS (excludes the direct-wave
     band and the record end; no target information);
  4. normalisation N: 'global' (median/MAD over the gated line) or 'per_row'
     (median/MAD across X at each time sample);
  5. candidates: local maxima of the normalised envelope within a
     (NMS_X_MM x NMS_T_NS) window, above threshold T.

PROTOCOL. Parameters (W, N, T) are chosen on the DEVELOPMENT set only
(Pk266 1.5 GHz Rot00), by L-XZ F1, from a fixed grid declared below. They are
then frozen and applied unchanged to the TEST set (Pk266 2.6 GHz Rot00,
Pk401 1.5/2.6 GHz Rot00) and the CONTROL (Pk050 1.5/2.6 GHz Rot00). The
development scan is reported as development, never as a test result.

    venv/bin/python -m scripts.bam_candidate_experiment --out artifacts/bam/validation/experiment_E1.json
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter, median_filter
from scipy.signal import hilbert

from benchmark.bam_ingest import line_traces, load_scan, load_volume
from scripts.bam_quantitative_validation import (END_GUARD_NS, TARGET_MIN_NS, evaluate_detections,
                                                 load_gt)

GRID = {"W": [21, 41, 81], "N": ["global", "per_row"], "T": [4.0, 6.0, 8.0, 10.0]}
NMS_X_MM, NMS_T_NS = 100.0, 0.5
DEV = ("Pk266", "1_5_GHz_Rot00")
TEST = [("Pk266", "2_6_GHz_Rot00"), ("Pk401", "1_5_GHz_Rot00"), ("Pk401", "2_6_GHz_Rot00")]
CONTROL = [("Pk050", "1_5_GHz_Rot00"), ("Pk050", "2_6_GHz_Rot00")]


def e1_line_maps(traces, dt, W, N):
    bg = median_filter(traces, size=(W, 1), mode="nearest")
    e = np.abs(hilbert(traces - bg, axis=1))
    i0, i1 = int(TARGET_MIN_NS / dt), traces.shape[1] - int(END_GUARD_NS / dt)
    g = e[:, i0:i1]
    if N == "global":
        med = np.median(g); mad = np.median(np.abs(g - med)) * 1.4826 + 1e-9
        z = (g - med) / mad
    else:
        med = np.median(g, axis=0, keepdims=True)
        mad = np.median(np.abs(g - med), axis=0, keepdims=True) * 1.4826 + 1e-9
        z = (g - med) / mad
    return z, i0


def e1_detect(vol, grid, scan_id, W, N, T):
    dt = float(grid.z[1] - grid.z[0])
    dx = float(grid.x[1] - grid.x[0])
    fx, ft = max(1, int(round(NMS_X_MM / dx))) | 1, max(1, int(round(NMS_T_NS / dt))) | 1
    dets = []
    for y in range(vol.shape[1]):
        z, i0 = e1_line_maps(line_traces(vol, y), dt, W, N)
        peaks = (z == maximum_filter(z, size=(fx, ft), mode="nearest")) & (z > T)
        for xi, ti in zip(*np.nonzero(peaks)):
            dets.append({"line": y, "y": float(grid.y[y]), "x": float(grid.x[xi]),
                         "t_ns": float(grid.z[ti + i0]), "z": float(z[xi, ti]),
                         "x_span": (float(grid.x[xi]), float(grid.x[xi])), "n_cells": 1})
    return dets


def f1(r):
    if not r["recall_LXZ"] or not r["precision_LXZ"]:
        return 0.0
    return 2 * r["recall_LXZ"] * r["precision_LXZ"] / (r["recall_LXZ"] + r["precision_LXZ"])


def score(dets, spec, scan, val):
    targets_all, boreholes_all = load_gt()
    targets = targets_all.get(spec, [])
    boreholes = [b for b in boreholes_all if b["id"].startswith(spec)]
    entry = val["scans"][f"{spec}_3D_Dataset_{scan}"]
    cal = entry["calibration_backwall_peak"]
    tbw = {b["step"]: (b["t_ns"] if b["t_ns"] is not None else 99.0) for b in entry["backwall"]}
    s = load_scan(spec, f"{spec}_3D_Dataset_{scan}")
    r = evaluate_detections(dets, targets, s.grid, cal or {"t0_ns": 0.0, "v_m_per_ns": 0.11}, tbw, boreholes)
    # precision under L-XZ: XZ-matched lines over (XZ-matched + all unmatched detections + LX-only)
    if targets:
        xz = sum(p["lines_matched_LXZ"] for p in r["per_target"].values())
        lx = sum(p["lines_matched_LX"] for p in r["per_target"].values())
        r["precision_LXZ"] = round(xz / (lx + r["false_positives"]), 4) if (lx + r["false_positives"]) else None
    else:
        r["precision_LXZ"] = None
    r["depth_gate_available"] = cal is not None
    return r


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("artifacts/bam/validation/experiment_E1.json"))
    p.add_argument("--val", type=Path, default=Path("artifacts/bam/validation/quantitative_validation.json"))
    args = p.parse_args()
    val = json.loads(args.val.read_text())
    out = {"protocol": __doc__, "grid": GRID, "nms": [NMS_X_MM, NMS_T_NS], "development": [], "frozen": None,
           "test": {}, "control": {}}

    spec, scan = DEV
    s = load_scan(spec, f"{spec}_3D_Dataset_{scan}"); vol = load_volume(s)
    for W, N, T in itertools.product(GRID["W"], GRID["N"], GRID["T"]):
        r = score(e1_detect(vol, s.grid, s.scan_id, W, N, T), spec, scan, val)
        row = {"W": W, "N": N, "T": T, "recall_LX": r["recall_LX"], "recall_LXZ": r["recall_LXZ"],
               "precision_LXZ": r["precision_LXZ"], "fp_per_line": r["false_positives_per_line"],
               "f1_LXZ": round(f1(r), 4)}
        out["development"].append(row)
        print("dev", row, flush=True)
    del vol
    best = max(out["development"], key=lambda r: r["f1_LXZ"])
    frozen = {"W": best["W"], "N": best["N"], "T": best["T"]}
    out["frozen"] = frozen
    print("FROZEN", frozen, flush=True)

    for group, items in (("test", TEST), ("control", CONTROL)):
        for spec, scan in items:
            s = load_scan(spec, f"{spec}_3D_Dataset_{scan}"); vol = load_volume(s)
            dets = e1_detect(vol, s.grid, s.scan_id, **frozen)
            out[group][f"{spec}_{scan}"] = score(dets, spec, scan, val)
            del vol
            r = out[group][f"{spec}_{scan}"]
            print(group, spec, scan, {k: r.get(k) for k in ("recall_LX", "recall_LXZ", "precision_LX",
                  "precision_LXZ", "false_positives_per_line", "false_positives_central_band_per_line")}, flush=True)
    args.out.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
