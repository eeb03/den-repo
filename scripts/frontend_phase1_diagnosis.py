"""
Candidate front-end feasibility, Phase 1 diagnosis (descriptive; no new method).

For every BAM line crossing a known object, decompose the UNCHANGED V2 front-end
(A3, freeze 09dc288) at that crossing:

    detected            a kept (post-grouping) detection within +/-100 mm, +/-1T
    lost_in_grouping    a component above the line's threshold z* exists there, but grouping removed it
    threshold_limited   max z at the crossing >= 6 (A1's fixed threshold) but < the line's z*
    weak_3_to_6         3 <= max z < 6
    statistic_limited   max z < 3
    no_valid_z          the stack is undefined there (aperture/time-zero limits)

The crossing window is |x - x_obj| <= 10 mm, t in [t_e - 0.5T, t_e + 1T], with
t_e from the stored known-geometry calibration. Truth positions are used ONLY to
read the detector's own outputs at known crossings; nothing is tuned or selected.
EXPLORATORY: every BAM scan was used in earlier research. CONCRETE NDT ONLY.

    python -m scripts.frontend_phase1_diagnosis --workers 6
"""
from __future__ import annotations

import argparse
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

OUT = Path("artifacts/frontend_feasibility")
SCANS = (("Pk266", "1_5_GHz_Rot00", "all"), ("Pk266", "2_6_GHz_Rot00", "objects"),
         ("Pk266", "1_5_GHz_Rot90", "objects"), ("Pk401", "1_5_GHz_Rot00", "all"),
         ("Pk401", "1_5_GHz_Rot90", "objects"))
A1_Z = 6.0


def _line(args):
    spec, scan, j, freeze = args
    from benchmark.hyperbola_stack import estimate_time_zero
    from benchmark.hyperbola_v2 import (StackContext, calibrated_threshold, canonical_line, detections_at, group,
                                        null_peaks, stack_line)
    from scripts.ccd_v1_stage1 import calibration, expected_time, lines_for, objects, scan_data
    s, vol = scan_data(spec, scan)
    g = s.grid
    f = 2.6e9 if scan.startswith("2_6") else 1.5e9
    T = 1e9 / f
    dt, toff = (g.z[1] - g.z[0]) * 1e-9, g.z[0] * 1e-9
    can = canonical_line(vol[:, j, :].astype(float), np.asarray(g.x, float) / 1000.0, dt, toff, f)
    tz = estimate_time_zero(can.traces, can.dt_s, can.time_offset_s)
    bg = can.traces - can.traces.mean(axis=0)
    z, v_hat, env = stack_line(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f)
    peaks = null_peaks(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f, f"bam:{spec}_{scan}:L{j}", freeze["grouping"])
    thr = calibrated_threshold(peaks, freeze["lambda0"])
    comps = detections_at(z, v_hat, thr)
    ctx = StackContext.build(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f, env)
    kept = group(comps, ctx, freeze["grouping"])
    t_ns = (can.time_offset_s + np.arange(z.shape[0]) * can.dt_s) * 1e9
    x_mm = can.x_m * 1000.0
    cal = calibration(spec, scan)
    rows = []
    for o in objects(spec):
        if j not in lines_for(g.y, o) or cal is None:
            continue
        te = expected_time(cal, o["z_top"])
        xi = np.nonzero(np.abs(x_mm - o["x"]) <= 10.0)[0]
        ti = np.nonzero((t_ns >= te - 0.5 * T) & (t_ns <= te + 1.0 * T))[0]
        win = z[np.ix_(ti, xi)]
        zmax = float(np.nanmax(win)) if np.isfinite(win).any() else float("nan")

        def near(ds):
            return any(abs(x_mm[d["trace"]] - o["x"]) <= 100 and abs(t_ns[d["sample"]] - te) <= T for d in ds)
        if near(kept):
            cls = "detected"
        elif near([d for d in comps]):
            cls = "lost_in_grouping"
        elif not np.isfinite(zmax):
            cls = "no_valid_z"
        elif zmax >= A1_Z:
            cls = "threshold_limited" if zmax < thr else "above_threshold_off_window"
        elif zmax >= 3.0:
            cls = "weak_3_to_6"
        else:
            cls = "statistic_limited"
        rows.append({"object": o["id"], "line": j, "y_mm": float(g.y[j]), "z_obj": zmax, "z_star": thr, "class": cls})
    return {"line": j, "n_kept": len(kept), "z_star": thr, "rows": rows}


def run(workers: int) -> dict:
    from benchmark.hyperbola_v2 import load_committed_freeze
    from scripts.ccd_v1_stage1 import lines_for, objects, scan_data
    freeze = load_committed_freeze(Path("simulation/hyperbola_v2_freeze.json"))
    res = {"label": "EXPLORATORY; CONCRETE NDT ONLY; unchanged V2 front-end; units for any inference are objects",
           "scans": {}}
    for spec, scan, which in SCANS:
        s, _ = scan_data(spec, scan)
        if which == "all":
            lines = list(range(len(s.grid.y)))
        else:
            lines = sorted({j for o in objects(spec) for j in lines_for(s.grid.y, o)})
        with Pool(workers) as pool:
            out = pool.map(_line, [(spec, scan, j, freeze) for j in lines])
        rows = [r for o in out for r in o["rows"]]
        per_obj = {}
        for oid in sorted({r["object"] for r in rows}):
            rs = sorted([r for r in rows if r["object"] == oid], key=lambda r: r["line"])
            cls = [r["class"] for r in rs]
            det = np.array([c == "detected" for c in cls])
            zo = np.array([r["z_obj"] for r in rs])
            gaps, runs, cur_gap, cur_run = [], [], 0, 0
            for d in det:
                if d:
                    cur_run += 1
                    if cur_gap:
                        gaps.append(cur_gap)
                    cur_gap = 0
                else:
                    cur_gap += 1
                    if cur_run:
                        runs.append(cur_run)
                    cur_run = 0
            if cur_run:
                runs.append(cur_run)
            if cur_gap:
                gaps.append(cur_gap)
            fin = np.isfinite(zo)
            lag1 = float(np.corrcoef(zo[fin][:-1], zo[fin][1:])[0, 1]) if fin.sum() > 3 else None
            per_obj[oid] = {
                "n_lines": len(rs), "class_counts": {c: cls.count(c) for c in sorted(set(cls))},
                "line_recall": float(det.mean()), "max_detected_run_lines": max(runs) if runs else 0,
                "max_gap_lines": max(gaps) if gaps else 0,
                "z_obj_median": float(np.nanmedian(zo)), "z_obj_q10_q90": [float(np.nanpercentile(zo, 10)),
                                                                           float(np.nanpercentile(zo, 90))],
                "z_star_median": float(np.median([r["z_star"] for r in rs])),
                "z_obj_lag1_autocorr_along_y": lag1}
        res["scans"][f"{spec}_{scan}"] = {
            "lines_run": len(lines), "total_kept_detections": sum(o["n_kept"] for o in out) if which == "all" else None,
            "z_star_q10_50_90": [float(np.percentile([o["z_star"] for o in out], q)) for q in (10, 50, 90)],
            "per_object": per_obj}
        (OUT / f"phase1_rows_{spec}_{scan}.json").write_text(json.dumps(rows))
    (OUT / "phase1_diagnosis.json").write_text(json.dumps(res, indent=1))
    return res


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    r = run(a.workers)
    for k, v in r["scans"].items():
        print(k, v["total_kept_detections"], v["z_star_q10_50_90"])
        for o, x in v["per_object"].items():
            print("  ", o, x["class_counts"], "recall", round(x["line_recall"], 3), "maxrun", x["max_detected_run_lines"],
                  "maxgap", x["max_gap_lines"], "zobj", round(x["z_obj_median"], 1), "z*", round(x["z_star_median"], 1),
                  "lag1", x["z_obj_lag1_autocorr_along_y"] and round(x["z_obj_lag1_autocorr_along_y"], 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
