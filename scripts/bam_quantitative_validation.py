"""
BAM quantitative validation: time zero, velocity, depth, localisation and the
frozen baseline detector, measured against fabrication drawings.

RESEARCH BENCHMARK. Reads the archives on disk, writes JSON artifacts, changes
no production code, no manifest and no gate.

GROUND TRUTH comes only from `evidence/bam/specimen_ground_truth.csv`
(Grohmann et al. 2026, Data in Brief 68:113103, Appendices A-C). Radar responses
are never used to position a target.

CALIBRATION uses only the stepped BACK WALL (aluminium-backed, four known
thicknesses per specimen), which is specimen geometry, never a scored target.
Known objects are EXCLUDED from the calibration windows using their drawn
positions -- exclusion, not fitting.

PRE-REGISTERED RULES (fixed before any result was computed; see the doc):
  * back-wall pick: strongest Hilbert-envelope peak after BACKWALL_MIN_NS in the
    object-free mean trace of a step. No thickness prior.
  * target time pick (known-position depth): background-subtracted mean trace at
    the drawn X (and Y for cuboids); strongest envelope peak between
    TARGET_MIN_NS and the measured back-wall time minus BACKWALL_GUARD_NS.
  * detector matching L-X: per scan line crossing a target, detections whose
    peak X is within MATCH_RADIUS_MM of the target X; the highest-|z| one is the
    match, others are duplicates. A detection near no target is a false positive.
  * matching L-XZ (secondary): L-X plus |depth - z_top| <= MATCH_DEPTH_MM using
    the back-wall-calibrated conversion of the same scan.
  * central band: Y in [CENTRAL_Y_MIN, CENTRAL_Y_MAX] (outside it lies the edge
    reinforcement drawn in the appendices); both bands are reported.

    venv/bin/python -m scripts.bam_quantitative_validation --out-dir artifacts/bam/validation
"""
from __future__ import annotations

import argparse
import csv
import json
import types
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks, hilbert

from benchmark.bam_ingest import load_scan, load_volume, line_traces
from benchmark.detection import detect_line
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS
from preprocessing.spatial_grid import anomaly_grid_from_traces
from preprocessing.time_zero import UNRESOLVED_VENDOR_FIELDS, direct_wave_consensus_time_zero

GT_CSV = Path("evidence/bam/specimen_ground_truth.csv")

# ---- pre-registered constants (do not move after seeing results) ----------
BACKWALL_MIN_NS = 3.5
BACKWALL_GUARD_NS = 0.4
#: AMENDMENT (made after seeing the first back-wall picks, BEFORE any target or
#: detector metric was inspected): the analytic-signal envelope has an end
#: artefact, and the thickest step was being "picked" at the last sample
#: (15.0 ns). Picks must now be a genuine local maximum (scipy find_peaks) and
#: lie before the final END_GUARD_NS of the record.
END_GUARD_NS = 0.5
N_CANDIDATES = 6
V_BOUNDS = (0.08, 0.16)       # m/ns: concrete, eps_r ~3.5-14
T0_BOUNDS = (-0.5, 2.5)       # ns
#: AMENDMENT 3 (calibration outputs only seen): a selected combination is a
#: calibration only if its residual RMS is <= CAL_MAX_RMS_NS (~7 samples) AND the
#: as-drawn orientation fits better than the mirrored one. Otherwise REFUSED.
CAL_MAX_RMS_NS = 0.2
TARGET_MIN_NS = 1.2
MATCH_RADIUS_MM = 100.0
MATCH_DEPTH_MM = 60.0
CENTRAL_Y_MIN, CENTRAL_Y_MAX = 100.0, 700.0
STEP_EDGE_GUARD_MM = 60.0
DUCT_OUTER_RADIUS_MM = 33.5
DUCT_INNER_RADIUS_MM = 30.0

#: Paper Table 4 (1.5 GHz, Rot00 only): back-wall-derived apparent velocity and t0.
PAPER_TABLE4 = {
    "Pk266": {"v_m_per_ns": 0.1271, "t0_ns": 0.7308, "eps_r": 5.56},
    "Pk050": {"v_m_per_ns": 0.1246, "t0_ns": 0.6723, "eps_r": 5.79},
    "Pk401": {"v_m_per_ns": 0.1088, "t0_ns": 0.6868, "eps_r": 7.6},
}
STEP_THICKNESS_MM = {   # grid X 0-500, 500-1000, 1000-1500, 1500-2000 (drawing order)
    "Pk266": [569.9, 448.2, 329.8, 210.3],
    "Pk050": [571.3, 452.0, 330.9, 210.8],
    "Pk401": [573.8, 453.4, 333.1, 210.4],
}
SCANS = ["1_5_GHz_Rot00", "2_6_GHz_Rot00", "1_5_GHz_Rot90", "2_6_GHz_Rot90"]


def load_gt():
    rows = list(csv.DictReader(GT_CSV.open(encoding="utf-8")))
    targets = {}
    for r in rows:
        if r["role"] != "target":
            continue
        targets.setdefault(r["specimen_id"], []).append({
            "id": r["object_id"], "type": r["object_type"], "x": float(r["x_mm"]),
            "y": float(r["y_mm"]) if r["y_mm"] else None,
            "z_centre": float(r["z_centre_mm"]), "z_top": float(r["z_top_mm"]),
        })
    boreholes = [{"id": r["object_id"], "x": float(r["x_mm"]), "y": float(r["y_mm"])}
                 for r in rows if r["object_type"] == "grouted_borehole"]
    return targets, boreholes


def env(tr):
    return np.abs(hilbert(tr - tr.mean()))


def step_of(x):
    return min(int(x // 500), 3)


# ---------------------------------------------------------------- calibration
def object_free_mask(grid, targets, boreholes, k):
    xs = []
    for i, x in enumerate(grid.x):
        if not (k * 500 + STEP_EDGE_GUARD_MM <= x <= (k + 1) * 500 - STEP_EDGE_GUARD_MM):
            continue
        if any(abs(x - t["x"]) <= 120 for t in targets if t["y"] is None):
            continue
        xs.append(i)
    ys = []
    for j, y in enumerate(grid.y):
        if not (150 <= y <= 650):
            continue
        ys.append(j)
    return xs, ys


def backwall_candidates(vol, grid, dt, targets, boreholes):
    """Per step: up to N_CANDIDATES envelope local maxima (time, amplitude) in the
    object-free mean trace. No thickness prior is used here."""
    out = []
    for k in range(4):
        xs, ys = object_free_mask(grid, targets, boreholes, k)
        sub = vol[np.ix_(xs, ys)]
        keep = np.ones(sub.shape[:2], bool)
        for t in targets:
            if t["y"] is None:
                continue
            for a, i in enumerate(xs):
                for b, j in enumerate(ys):
                    if abs(grid.x[i] - t["x"]) <= 120 and abs(grid.y[j] - t["y"]) <= 120:
                        keep[a, b] = False
        for bh in boreholes:
            for a, i in enumerate(xs):
                for b, j in enumerate(ys):
                    if abs(grid.x[i] - bh["x"]) <= 60 and abs(grid.y[j] - bh["y"]) <= 60:
                        keep[a, b] = False
        e = env(sub[keep].mean(0))
        i0 = int(BACKWALL_MIN_NS / dt)
        i1 = len(e) - int(END_GUARD_NS / dt)
        pk, _ = find_peaks(e[:i1])
        pk = pk[pk >= i0]
        pk = pk[np.argsort(-e[pk])][:N_CANDIDATES]
        out.append({"step": k, "n_traces": int(keep.sum()),
                    "candidates": [{"t_ns": round(float(i * dt), 4), "amp": float(e[i])} for i in pk]})
    return out


def select_backwall(cands, thick_mm):
    """AMENDMENT 2 (made after seeing calibration outputs only, before any target
    or detector metric): the strongest-peak rule fails on thick steps, where
    attenuation makes the true back wall weaker than earlier internal events.
    The back wall is therefore SELECTED as the one-candidate-per-step combination
    that best fits t = t0 + 2d/v within physical bounds, using only the known
    back-wall thicknesses. Both orientations are tried; the result reports both
    residuals, so orientation is decided by the fit, not assumed."""
    import itertools
    best = {}
    for name, order in (("as_drawn", list(thick_mm)), ("mirrored", list(thick_mm)[::-1])):
        b = None
        for combo in itertools.product(*[c["candidates"] for c in cands]):
            times = [c["t_ns"] for c in combo]
            fit = _lsq(times, order)
            if not (V_BOUNDS[0] <= fit[0] <= V_BOUNDS[1] and T0_BOUNDS[0] <= fit[1] <= T0_BOUNDS[1]):
                continue
            if b is None or fit[2] < b["rms_ns"]:
                b = {"times": times, "v": fit[0], "t0": fit[1], "rms_ns": fit[2]}
        best[name] = b
    return best


def _lsq(times, thick_mm):
    d2 = 2 * np.asarray(thick_mm) / 1000.0
    A = np.vstack([d2, np.ones_like(d2)]).T
    (slope, t0), *_ = np.linalg.lstsq(A, np.asarray(times), rcond=None)
    rms = float(np.sqrt(np.mean((np.asarray(times) - (t0 + slope * d2)) ** 2)))
    return (1.0 / slope if slope > 0 else -1.0), float(t0), rms


def fit_calibration(times_ns, thick_mm):
    d2 = 2 * np.asarray(thick_mm) / 1000.0          # two-way path, m
    t = np.asarray(times_ns)
    A = np.vstack([d2, np.ones_like(d2)]).T
    (slope, t0), *_ = np.linalg.lstsq(A, t, rcond=None)
    v = 1.0 / slope
    resid = t - (t0 + slope * d2)
    loso = []
    for i in range(len(t)):
        m = np.arange(len(t)) != i
        (s_i, t0_i), *_ = np.linalg.lstsq(A[m], t[m], rcond=None)
        pred_mm = (t[i] - t0_i) / s_i / 2 * 1000.0
        loso.append({"held_out_step": i, "true_mm": thick_mm[i],
                     "predicted_mm": round(float(pred_mm), 2),
                     "error_mm": round(float(pred_mm - thick_mm[i]), 2)})
    return {"v_m_per_ns": round(float(v), 5), "t0_ns": round(float(t0), 4),
            "residual_rms_ns": round(float(np.sqrt(np.mean(resid ** 2))), 4),
            "leave_one_step_out": loso}


# ---------------------------------------------------------------- time zero
def method_c(vol, grid, dt, y_mm):
    j = int(np.argmin(np.abs(grid.y - y_mm)))
    recs = [types.SimpleNamespace(signal=list(map(float, vol[i, j, :]))) for i in range(vol.shape[0])]
    r = direct_wave_consensus_time_zero(recs, dt)
    return {"y_mm": float(grid.y[j]), "status": r.status.value,
            "t0_ns": r.correction_ns, "spread_ns": r.spread_ns, "basis": r.basis}


# ---------------------------------------------------------------- target depth
def target_time(vol, grid, dt, t, t_bw):
    xs = [i for i, x in enumerate(grid.x) if abs(x - t["x"]) <= 10]
    ref = [i for i, x in enumerate(grid.x)
           if 120 <= abs(x - t["x"]) <= 200 and step_of(x) == step_of(t["x"])]
    if t["y"] is None:
        ys = [j for j, y in enumerate(grid.y) if 150 <= y <= 650]
    else:
        ys = [j for j, y in enumerate(grid.y) if abs(y - t["y"]) <= 40]
    sig = vol[np.ix_(xs, ys)].reshape(-1, vol.shape[2]).mean(0)
    bg = vol[np.ix_(ref, ys)].reshape(-1, vol.shape[2]).mean(0)
    e = env(sig - bg)
    i0, i1 = int(TARGET_MIN_NS / dt), int((t_bw - BACKWALL_GUARD_NS) / dt)
    ipk = i0 + int(np.argmax(e[i0:i1]))
    return ipk * dt, float(e[ipk] / (np.median(e[i0:i1]) + 1e-9))


def depth_mm(t_ns, t0, v):
    return (t_ns - t0) * v / 2 * 1000.0


def stats(errs):
    a = np.asarray([e for e in errs if e is not None], float)
    if a.size == 0:
        return None
    ab = np.abs(a)
    return {"n": int(a.size), "mean_signed": round(float(a.mean()), 2),
            "mean_abs": round(float(ab.mean()), 2), "median_abs": round(float(np.median(ab)), 2),
            "rmse": round(float(np.sqrt((a ** 2).mean())), 2),
            "p95_abs": round(float(np.percentile(ab, 95)), 2), "max_abs": round(float(ab.max()), 2)}


# ---------------------------------------------------------------- detection
def run_detector(vol, grid, scan_id, estimator=anomaly_grid_from_traces):
    dets = []
    for y in range(vol.shape[1]):
        for d in detect_line(line_traces(vol, y), scan_id, y,
                             threshold=DEFAULT_ANOMALY_THRESHOLD, min_cells=DEFAULT_MIN_CELLS,
                             estimator=estimator):
            dets.append({"line": y, "y": float(grid.y[y]), "x": float(grid.x[d.peak_trace]),
                         "t_ns": float(grid.z[d.peak_sample]), "z": float(abs(d.peak_z)),
                         "x_span": (float(grid.x[d.trace_indices[0]]), float(grid.x[d.trace_indices[-1]])),
                         "n_cells": d.n_cells})
    return dets


def lines_for(t, grid):
    if t["y"] is None:
        return list(range(len(grid.y)))
    return [j for j, y in enumerate(grid.y) if abs(y - t["y"]) <= 60]


def evaluate_detections(dets, targets, grid, cal, t_bw_by_step, boreholes):
    by_line = {}
    for d in dets:
        by_line.setdefault(d["line"], []).append(d)
    used = set()
    per_target = {}
    loc_err, depth_err, dup = [], [], 0
    for t in targets:
        rows = []
        for j in lines_for(t, grid):
            cands = [d for d in by_line.get(j, []) if abs(d["x"] - t["x"]) <= MATCH_RADIUS_MM]
            if not cands:
                rows.append({"line": j, "matched": False})
                continue
            best = max(cands, key=lambda d: d["z"])
            for d in cands:
                used.add(id(d))
            dup += len(cands) - 1
            dz = depth_mm(best["t_ns"], cal["t0_ns"], cal["v_m_per_ns"]) - t["z_top"]
            rows.append({"line": j, "matched": True, "dx": best["x"] - t["x"], "dz": dz,
                         "xz_match": abs(dz) <= MATCH_DEPTH_MM, "y": best["y"], "z": best["z"]})
        m = [r for r in rows if r["matched"]]
        loc_err += [r["dx"] for r in m]
        depth_err += [r["dz"] for r in m]
        lat = None
        if t["y"] is not None and m:
            w = np.array([r["z"] for r in m]); yy = np.array([r["y"] for r in m])
            lat = float((w * yy).sum() / w.sum() - t["y"])
        per_target[t["id"]] = {
            "lines": len(rows), "lines_matched_LX": len(m),
            "lines_matched_LXZ": sum(r["xz_match"] for r in m),
            "recall_LX": round(len(m) / len(rows), 4) if rows else None,
            "dx_stats": stats([r["dx"] for r in m]), "dz_stats": stats([r["dz"] for r in m]),
            "lateral_error_mm": None if lat is None else round(lat, 1),
        }
    fps = [d for d in dets if id(d) not in used]
    n_lines = len(grid.y)

    def cat(d):
        k = step_of(d["x"])
        if d["t_ns"] < TARGET_MIN_NS:
            return "direct_wave_band"
        if abs(d["t_ns"] - t_bw_by_step[k]) <= 0.5:
            return "back_wall_band"
        if d["t_ns"] > t_bw_by_step[k] + 0.5:
            return "below_back_wall_multiples"
        if any(abs(d["x"] - e) <= STEP_EDGE_GUARD_MM for e in (500, 1000, 1500)):
            return "step_edge"
        if d["y"] < CENTRAL_Y_MIN or d["y"] > CENTRAL_Y_MAX:
            return "edge_reinforcement_zone"
        if any(abs(d["x"] - b["x"]) <= 80 and abs(d["y"] - b["y"]) <= 80 for b in boreholes):
            return "grouted_borehole"
        if any(MATCH_RADIUS_MM < abs(d["x"] - t["x"]) <= 250 for t in targets):
            return "near_target_outside_radius"
        return "unexplained"

    cats = {}
    for d in fps:
        c = cat(d)
        cats[c] = cats.get(c, 0) + 1
    total_opp = sum(len(lines_for(t, grid)) for t in targets)
    matched_opp = sum(v["lines_matched_LX"] for v in per_target.values())
    tp = matched_opp
    central_fp = [d for d in fps if CENTRAL_Y_MIN <= d["y"] <= CENTRAL_Y_MAX]
    return {
        "n_detections": len(dets), "opportunities": total_opp,
        "recall_LX": round(matched_opp / total_opp, 4) if total_opp else None,
        "recall_LXZ": round(sum(v["lines_matched_LXZ"] for v in per_target.values()) / total_opp, 4) if total_opp else None,
        "precision_LX": round(tp / (tp + len(fps)), 4) if (tp + len(fps)) else None,
        "false_positives": len(fps), "false_positives_per_line": round(len(fps) / n_lines, 3),
        "false_positives_central_band_per_line": round(len(central_fp) / n_lines, 3),
        "duplicates": dup,
        "fp_categories": dict(sorted(cats.items(), key=lambda kv: -kv[1])),
        "longitudinal_error_mm": stats(loc_err),
        "depth_error_mm_of_matched_detections": stats(depth_err),
        "per_target": per_target,
    }


def missed_diagnosis(vol, grid, targets, dt, cal):
    """For target crossings, what is the max |z| of the ring statistic near the target?"""
    out = {}
    for t in targets:
        zmax, peak_elsewhere = [], 0
        for j in lines_for(t, grid)[::4]:
            z = anomaly_grid_from_traces(line_traces(vol, j))
            xs = [i for i, x in enumerate(grid.x) if abs(x - t["x"]) <= DUCT_OUTER_RADIUS_MM]
            t_top = cal["t0_ns"] + 2 * t["z_top"] / 1000.0 / cal["v_m_per_ns"]
            s0, s1 = int((t_top - 0.4) / dt), int((t_top + 1.2) / dt)
            zz = np.abs(np.nan_to_num(z[s0:s1, xs[0]:xs[-1] + 1]))
            zmax.append(float(zz.max()) if zz.size else 0.0)
        a = np.asarray(zmax)
        out[t["id"]] = {"lines_sampled": int(a.size), "median_max_abs_z": round(float(np.median(a)), 2),
                        "fraction_above_threshold": round(float((a > DEFAULT_ANOMALY_THRESHOLD).mean()), 3)}
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, default=Path("artifacts/bam/validation"))
    p.add_argument("--detector-scans", nargs="*", default=["1_5_GHz_Rot00", "2_6_GHz_Rot00"])
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    targets_all, boreholes_all = load_gt()

    report = {"pre_registered": {k: v for k, v in globals().items()
                                 if k.isupper() and isinstance(v, (int, float))},
              "method_a": {"status": "REFUSED", "reason": (
                  f"DZT time-zero header fields {UNRESOLVED_VENDOR_FIELDS} are untrusted by "
                  "preprocessing.time_zero.metadata_instrument_time_zero")},
              "scans": {}}
    for spec in ["Pk266", "Pk401", "Pk050"]:
        targets = targets_all.get(spec, [])
        boreholes = [b for b in boreholes_all if b["id"].startswith(spec)]
        for scan in SCANS:
            sid = f"{spec}_3D_Dataset_{scan}"
            s = load_scan(spec, sid)
            vol = load_volume(s)
            grid = s.grid
            dt = float(grid.z[1] - grid.z[0])
            cands = backwall_candidates(vol, grid, dt, targets, boreholes)
            sel = select_backwall(cands, STEP_THICKNESS_MM[spec])
            orient_rms = {k: (None if v is None else round(v["rms_ns"], 4)) for k, v in sel.items()}
            if sel["as_drawn"] is not None and sel["as_drawn"]["rms_ns"] > CAL_MAX_RMS_NS:
                sel_rejected = sel["as_drawn"]
                sel = dict(sel, as_drawn=None)
            if sel["as_drawn"] is None:
                orientation_ok, times, cal = None, [None] * 4, None
                refusal = ("REFUSED: no one-candidate-per-step combination of the top "
                           f"{N_CANDIDATES} envelope peaks fits t = t0 + 2d/v within "
                           f"v in {V_BOUNDS} m/ns and t0 in {T0_BOUNDS} ns")
            else:
                orientation_ok = (sel["mirrored"] is None or sel["as_drawn"]["rms_ns"] < sel["mirrored"]["rms_ns"])
                times = sel["as_drawn"]["times"]
                cal = fit_calibration(times, STEP_THICKNESS_MM[spec])
                cal["orientation_fit_rms_ns"] = orient_rms
                refusal = None
            bw = [{"step": k, "t_ns": times[k], "candidates": cands[k]["candidates"],
                   "n_traces": cands[k]["n_traces"]} for k in range(4)]
            mc = [method_c(vol, grid, dt, y) for y in (250, 400, 550)]
            t0_c = float(np.median([m["t0_ns"] for m in mc if m["t0_ns"] is not None])) \
                if any(m["t0_ns"] is not None for m in mc) else None
            paper = PAPER_TABLE4[spec] if scan == "1_5_GHz_Rot00" else None
            entry = {"backwall": bw, "orientation_thick_end_at_grid_x0": orientation_ok,
                     "orientation_fit_rms_ns": orient_rms, "calibration_refusal": refusal,
                     "calibration_backwall_peak": cal, "method_c": mc, "method_c_t0_ns": t0_c,
                     "method_b_declared_from_paper": paper}

            # known-position depth for each target under each provenance
            if targets:
                rows = []
                for t in targets:
                    t_bw_k = times[step_of(t["x"])] if times[0] is not None else \
                        float(grid.z[-1]) - END_GUARD_NS
                    tt, snr = target_time(vol, grid, dt, t, t_bw_k)
                    row = {"target": t["id"], "type": t["type"], "t_pick_ns": round(tt, 4),
                           "pick_contrast": round(snr, 2), "z_top": t["z_top"], "z_centre": t["z_centre"]}
                    combos = {} if cal is None else {
                        "D2_subterra_backwall_t0_v": (cal["t0_ns"], cal["v_m_per_ns"]),
                        "D3_methodC_t0_backwall_v": (t0_c, cal["v_m_per_ns"]) if t0_c is not None else None,
                        "D5_no_t0_backwall_v": (0.0, cal["v_m_per_ns"]),
                    }
                    if paper:
                        combos["D1_paper_t0_v"] = (paper["t0_ns"], paper["v_m_per_ns"])
                        if t0_c is not None:
                            combos["D4_methodC_t0_paper_v"] = (t0_c, paper["v_m_per_ns"])
                    for name, c in combos.items():
                        if c is None:
                            continue
                        d = depth_mm(tt, *c)
                        row[name] = {"depth_mm": round(d, 1), "err_top_mm": round(d - t["z_top"], 1),
                                     "err_centre_mm": round(d - t["z_centre"], 1)}
                    rows.append(row)
                entry["known_position_depth"] = rows

            if scan in args.detector_scans:
                dets = run_detector(vol, grid, sid)
                tbw = {b["step"]: (b["t_ns"] if b["t_ns"] is not None else 99.0) for b in bw}
                cal_eval = cal or {"t0_ns": t0_c or 0.0, "v_m_per_ns": 0.11, "note": "no calibration; depth gate not meaningful"}
                entry["baseline_detector"] = evaluate_detections(dets, targets, grid, cal_eval, tbw, boreholes)
                entry["baseline_detector"]["depth_conversion_used"] = "backwall_calibration" if cal else "NONE (calibration refused) - depth fields not meaningful"
                if targets and cal:
                    entry["missed_diagnosis_ring_z"] = missed_diagnosis(vol, grid, targets, dt, cal)
                (args.out_dir / f"detections_baseline_{sid}.json").write_text(json.dumps(dets))
            report["scans"][sid] = entry
            print(sid, "orient", orientation_ok, "cal", None if cal is None else (cal["v_m_per_ns"], cal["t0_ns"]),
                  "C", t0_c, flush=True)
            del vol
    (args.out_dir / "quantitative_validation.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
