"""
Candidate front-end feasibility, Phase 2: arms A, B, C on BAM (EXPLORATORY,
CONCRETE NDT ONLY). Implements docs/frontend-phase2-bc-protocol.md.

    python -m scripts.frontend_phase2 dev-b --workers 6     # B grid on the development scan
    python -m scripts.frontend_phase2 dev-c --workers 6     # C permutation-null alpha + grid on dev
    python -m scripts.frontend_phase2 freeze                # writes scripts/frontend_phase2_freeze.json
    python -m scripts.frontend_phase2 holdout --workers 6   # A, B, C on holdouts + gates (needs committed freeze)

Truth (object positions, calibrations) is used only in `score_*`. Arm D, 4TU and
synthetic parts are not run (protocol scope).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import shutil
import subprocess
import sys
import time
import tracemalloc
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter

OUT = Path("artifacts/frontend_feasibility/phase2")
FREEZE = Path("scripts/frontend_phase2_freeze.json")
DEV = ("Pk266", "1_5_GHz_Rot00")
HOLDOUTS = (("Pk266", "2_6_GHz_Rot00"), ("Pk266", "1_5_GHz_Rot90"), ("Pk266", "2_6_GHz_Rot90"),
            ("Pk401", "1_5_GHz_Rot00"), ("Pk401", "1_5_GHz_Rot90"),
            ("Pk050", "1_5_GHz_Rot00"), ("Pk050", "1_5_GHz_Rot90"))
B_GRID = {"k": (1.5, 2.0, 3.0), "w": (41, 81, 161)}
C_GRID = {"G": (1, 3), "dx": (0.25, 0.5), "dt": (0.25, 0.5)}
ALPHAS = (0.3, 0.4, 0.5, 0.6, 0.7)
NULL_RATE_MAX = 0.1


def f_hz(scan: str) -> float:
    return 2.6e9 if scan.startswith("2_6") else 1.5e9


# --- arm-specific background step (no truth) ------------------------------------------

def preprocess_b(traces: np.ndarray, t_s: np.ndarray, t0_s: float, period_s: float, k: float, w: int) -> np.ndarray:
    """Lateral running median over w traces, then an early-time raised-cosine mute ending at t0 + kT."""
    bg = traces - median_filter(traces, size=(w, 1), mode="nearest")
    t_m = t0_s + k * period_s
    wgt = np.clip((t_s - (t_m - 0.5 * period_s)) / (0.5 * period_s), 0.0, 1.0)
    wgt = 0.5 - 0.5 * np.cos(np.pi * wgt)
    return bg * wgt[None, :]


def _process_line(spec, scan, j, freeze_v2, arm, params, keep_maps=False, null_perm=False, z_star=None):
    from benchmark.hyperbola_stack import estimate_time_zero
    from benchmark.hyperbola_v2 import (StackContext, calibrated_threshold, canonical_line, detections_at, group,
                                        null_peaks, stack_line)
    from scripts.ccd_v1_stage1 import scan_data
    s, vol = scan_data(spec, scan)
    g = s.grid
    f = f_hz(scan)
    T = 1.0 / f
    c0 = time.process_time()
    can = canonical_line(vol[:, j, :].astype(float), np.asarray(g.x, float) / 1000.0,
                         (g.z[1] - g.z[0]) * 1e-9, g.z[0] * 1e-9, f)
    tz = estimate_time_zero(can.traces, can.dt_s, can.time_offset_s)
    t_s = can.time_offset_s + np.arange(can.traces.shape[1]) * can.dt_s
    if arm == "B":
        bg = preprocess_b(can.traces, t_s, tz, T, params["k"], params["w"])
    else:
        bg = can.traces - can.traces.mean(axis=0)
    if null_perm:
        rng = np.random.default_rng(int.from_bytes(hashlib.sha256(
            f"C-null:bam:{spec}_{scan}:L{j}".encode()).digest()[:8], "big"))
        bg = bg[rng.permutation(bg.shape[0])]
    z, v_hat, env = stack_line(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f)
    if z_star is None:
        peaks = null_peaks(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f, f"bam:{spec}_{scan}:L{j}",
                           freeze_v2["grouping"])
        thr = calibrated_threshold(peaks, freeze_v2["lambda0"])
    else:
        thr = z_star
    ctx = StackContext.build(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f, env)
    kept = group(detections_at(z, v_hat, thr), ctx, freeze_v2["grouping"])
    cpu = time.process_time() - c0
    out = {"line": j, "y_mm": float(g.y[j]), "z_star": thr, "cpu_s": cpu,
           "kept": [{"sample": d["sample"], "trace": d["trace"], "z": d["z"],
                     "v": d["v"] if np.isfinite(d.get("v", np.nan)) else None} for d in kept],
           "x_mm": (can.x_m * 1000.0).tolist() if j == 0 else None,
           "t0_canon_ns": can.time_offset_s * 1e9, "dt_canon_ns": can.dt_s * 1e9}
    if keep_maps:
        out["z"] = z.astype(np.float32)
        out["v_hat"] = v_hat.astype(np.float32)
    return out


def _job(args):
    return _process_line(*args)


def run_scan(spec, scan, arm, params, workers, freeze_v2, keep_maps=False, null_perm=False, z_stars=None):
    from scripts.ccd_v1_stage1 import scan_data
    s, _ = scan_data(spec, scan)
    n = len(s.grid.y)
    jobs = [(spec, scan, j, freeze_v2, arm, params, keep_maps, null_perm,
             None if z_stars is None else z_stars[j]) for j in range(n)]
    with Pool(workers) as pool:
        rows = pool.map(_job, jobs, chunksize=1)
    x_mm = np.array(rows[0]["x_mm"])
    return {"spec": spec, "scan": scan, "arm": arm, "params": params, "lines": rows, "x_mm": x_mm,
            "t0_canon_ns": rows[0]["t0_canon_ns"], "dt_canon_ns": rows[0]["dt_canon_ns"]}


def peak_memory_one_line(spec, scan, arm, params, freeze_v2) -> float:
    tracemalloc.start()
    _process_line(spec, scan, 80, freeze_v2, arm, params)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1e6


# --- arm C: cross-line hysteresis (no truth) --------------------------------------------

def grow(res: dict, cfg: dict, alpha: float) -> tuple[list[list[dict]], int]:
    """Seeds = kept detections; returns (per-line detections incl. grown, n tracks spanning >= 2 lines)."""
    lines = res["lines"]
    n = len(lines)
    x_mm = res["x_mm"]
    dt_ns = res["dt_canon_ns"]
    f = f_hz(res["scan"])
    T_ns = 1e9 / f
    vmed = []
    for L in lines:
        v = L["v_hat"][np.isfinite(L["v_hat"])]
        vmed.append(float(np.median(v)) if v.size else 1.0e8)
    seeds = {(j, d["sample"], d["trace"]): {**d, "line": j, "grown": False} for j, L in enumerate(lines) for d in L["kept"]}
    used = set()
    out = [[dict(d, line=j, grown=False) for d in L["kept"]] for j, L in enumerate(lines)]
    multi = 0
    order = sorted(seeds.values(), key=lambda d: -d["z"])
    for sd in order:
        key0 = (sd["line"], sd["sample"], sd["trace"])
        if key0 in used:
            continue
        used.add(key0)
        track = {sd["line"]: sd}
        frontier = [sd]
        while frontier:
            m = frontier.pop()
            v = m["v"] if m.get("v") else vmed[m["line"]]
            half_x = cfg["dx"] * (v / f) * 1000.0
            xi = np.nonzero(np.abs(x_mm - x_mm[m["trace"]]) <= half_x)[0]
            ds = int(math.ceil(cfg["dt"] * T_ns / dt_ns))
            for dj in [d for g_ in range(1, cfg["G"] + 1) for d in (-g_, g_)]:
                jj = m["line"] + dj
                if jj < 0 or jj >= n or jj in track:
                    continue
                s_lo, s_hi = max(0, m["sample"] - ds), m["sample"] + ds + 1
                joined = None
                for d in lines[jj]["kept"]:
                    k2 = (jj, d["sample"], d["trace"])
                    if k2 not in used and s_lo <= d["sample"] < s_hi and d["trace"] in set(xi.tolist()):
                        joined = {**d, "line": jj, "grown": False}
                        used.add(k2)
                        break
                if joined is None:
                    zz = lines[jj]["z"][s_lo:s_hi][:, xi]
                    if not np.isfinite(zz).any():
                        continue
                    a = int(np.nanargmax(zz))
                    si, ti = np.unravel_index(a, zz.shape)
                    zmax = float(zz[si, ti])
                    if zmax < alpha * lines[jj]["z_star"]:
                        continue
                    s_new, t_new = s_lo + int(si), int(xi[ti])
                    vv = float(lines[jj]["v_hat"][s_new, t_new])
                    joined = {"sample": s_new, "trace": t_new, "z": zmax, "v": vv if np.isfinite(vv) else None,
                              "line": jj, "grown": True}
                    if not any(abs(e["sample"] - s_new) <= 1 and abs(e["trace"] - t_new) <= 1 for e in out[jj]):
                        out[jj].append(joined)
                track[jj] = joined
                frontier.append(joined)
        if len(track) >= 2:
            multi += 1
    return out, multi


# --- scoring (truth enters here only) ----------------------------------------------------

def to_mm_ns(res, d):
    return float(res["x_mm"][d["trace"]]), res["t0_canon_ns"] + d["sample"] * res["dt_canon_ns"]


def score(res: dict, dets_by_line: list[list[dict]] | None = None) -> dict:
    from scripts.ccd_v1_stage1 import _classify, calibration, expected_time, lines_for, objects, scan_data, step_of
    spec, scan = res["spec"], res["scan"]
    s, _ = scan_data(spec, scan)
    g = s.grid
    cal = calibration(spec, scan)
    T = 1e9 / f_hz(scan)
    objs = objects(spec) if spec != "Pk050" else []
    dets_by_line = dets_by_line if dets_by_line is not None else [L["kept"] for L in res["lines"]]
    classes, other_sub = {}, {}
    detected = {o["id"]: set() for o in objs}
    n_lines = len(res["lines"])
    for j, dl in enumerate(dets_by_line):
        for d in dl:
            x, t = to_mm_ns(res, d)
            dd = {"x_mm": x, "t_ns": t, "y_mm": float(g.y[j])}
            c, oid = _classify(dd, objs, cal, T)
            classes[c] = classes.get(c, 0) + 1
            if c == "object":
                detected[oid].add(j)
            if c == "other":
                sub = "other_residual"
                t_bw = cal["backwall_t_ns"][step_of(x)]
                if abs(t - (cal["t0"] + 2 * (t_bw - cal["t0"]))) <= T:
                    sub = "backwall_multiple"
                else:
                    for e in (500.0, 1000.0, 1500.0):
                        k_left, k_right = step_of(e - 1), step_of(e + 1)
                        if abs(x - e) <= 60 and t >= min(cal["backwall_t_ns"][k_left], cal["backwall_t_ns"][k_right]):
                            sub = "step_edge_tail"
                            break
                    if sub == "other_residual":
                        for o in objs:
                            te = expected_time(cal, o["z_top"])
                            if abs(x - o["x"]) <= 100 and (o["y"] is None or abs(dd["y_mm"] - o["y"]) <= 60) \
                                    and te + T < t <= te + 3 * T:
                                sub = "object_ringing"
                                break
                other_sub[sub] = other_sub.get(sub, 0) + 1
    per_obj = {}
    for o in objs:
        lines = lines_for(g.y, o)
        det = [j in detected[o["id"]] for j in lines]
        runs, gaps, cr, cg = [], [], 0, 0
        for d in det:
            if d:
                cr += 1
                if cg:
                    gaps.append(cg)
                cg = 0
            else:
                cg += 1
                if cr:
                    runs.append(cr)
                cr = 0
        if cr:
            runs.append(cr)
        if cg:
            gaps.append(cg)
        per_obj[o["id"]] = {"n_lines": len(lines), "detected_lines": int(sum(det)), "line_recall": float(np.mean(det)),
                            "longest_run": max(runs) if runs else 0, "longest_gap": max(gaps) if gaps else 0,
                            "runs": len(runs)}
    n_fp = sum(v for k, v in classes.items() if k != "object")
    return {"classes": classes, "other_subclasses": other_sub, "per_object": per_obj,
            "artefact_fp_per_line": (classes.get("direct", 0) + classes.get("below_back_wall", 0)) / n_lines,
            "fp_per_line": n_fp / n_lines, "n_detections": sum(classes.values()),
            "median_z_star": float(np.median([L["z_star"] for L in res["lines"]])),
            "median_cpu_s_per_line": float(np.median([L["cpu_s"] for L in res["lines"]]))}


def detectable(res_a: dict) -> dict:
    """Phase 1 definition: median arm-A z at the crossing window >= 6 (needs maps)."""
    from scripts.ccd_v1_stage1 import calibration, expected_time, lines_for, objects, scan_data
    spec, scan = res_a["spec"], res_a["scan"]
    if spec == "Pk050":
        return {}
    s, _ = scan_data(spec, scan)
    cal = calibration(spec, scan)
    T = 1e9 / f_hz(scan)
    out = {}
    for o in objects(spec):
        te = expected_time(cal, o["z_top"])
        xi = np.nonzero(np.abs(res_a["x_mm"] - o["x"]) <= 10.0)[0]
        vals = []
        for j in lines_for(s.grid.y, o):
            L = res_a["lines"][j]
            t = res_a["t0_canon_ns"] + np.arange(L["z"].shape[0]) * res_a["dt_canon_ns"]
            ti = np.nonzero((t >= te - 0.5 * T) & (t <= te + T))[0]
            w = L["z"][np.ix_(ti, xi)]
            vals.append(float(np.nanmax(w)) if np.isfinite(w).any() else np.nan)
        out[o["id"]] = {"median_z": float(np.nanmedian(vals)), "detectable": bool(np.nanmedian(vals) >= 6.0)}
    return out


def _duct_median_recall(sc):
    return float(np.median([v["line_recall"] for k, v in sc["per_object"].items() if "duct" in k]))


# --- stages ------------------------------------------------------------------------------

def _v2():
    from benchmark.hyperbola_v2 import load_committed_freeze
    return load_committed_freeze(Path("simulation/hyperbola_v2_freeze.json"))


def dev_b(workers):
    fv = _v2()
    a = run_scan(*DEV, "A", {}, workers, fv)
    sa = score(a)
    table = [{"arm": "A", "score": sa}]
    for k, w in itertools.product(B_GRID["k"], B_GRID["w"]):
        r = run_scan(*DEV, "B", {"k": k, "w": w}, workers, fv)
        sc = score(r)
        table.append({"arm": "B", "params": {"k": k, "w": w}, "score": sc,
                      "admissible": sc["artefact_fp_per_line"] <= sa["artefact_fp_per_line"],
                      "median_duct_recall": _duct_median_recall(sc)})
    adm = [t for t in table if t.get("admissible")]
    adm.sort(key=lambda t: (-t["median_duct_recall"], -t["params"]["k"], -t["params"]["w"]))
    res = {"A": {"median_duct_recall": _duct_median_recall(sa), "score": sa},
           "chosen": adm[0]["params"] if adm else None, "status": "selected" if adm else "FAILED at selection",
           "table": table}
    (OUT / "dev_b.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def dev_c(workers):
    fv = _v2()
    a = run_scan(*DEV, "A", {}, workers, fv, keep_maps=True)
    zst = [L["z_star"] for L in a["lines"]]
    nul = run_scan(*DEV, "A", {}, workers, fv, keep_maps=True, null_perm=True, z_stars=zst)
    sa = score(a)
    table = []
    for G, dx, dt in itertools.product(C_GRID["G"], C_GRID["dx"], C_GRID["dt"]):
        cfg = {"G": G, "dx": dx, "dt": dt}
        rates = {}
        alpha = None
        for al in ALPHAS:
            _, multi = grow(nul, cfg, al)
            rates[al] = multi / len(nul["lines"])
            if alpha is None and rates[al] <= NULL_RATE_MAX:
                alpha = al
        row = {"config": cfg, "null_false_track_rate": rates, "alpha": alpha}
        if alpha is not None:
            dets, _ = grow(a, cfg, alpha)
            sc = score(a, dets)
            row.update({"score": sc, "median_duct_recall": _duct_median_recall(sc)})
        table.append(row)
    ok = [r for r in table if r["alpha"] is not None]
    ok.sort(key=lambda r: (-r["median_duct_recall"], r["config"]["G"], r["config"]["dx"], r["config"]["dt"]))
    res = {"A": {"median_duct_recall": _duct_median_recall(sa), "score": sa},
           "chosen": ({**ok[0]["config"], "alpha": ok[0]["alpha"]} if ok else None),
           "status": "selected" if ok else "FAILED: no configuration meets the null budget", "table": table}
    (OUT / "dev_c.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def write_freeze():
    b = json.loads((OUT / "dev_b.json").read_text())
    c = json.loads((OUT / "dev_c.json").read_text())
    FREEZE.write_text(json.dumps({"frozen_before_holdouts": True, "B": b["chosen"], "B_status": b["status"],
                                  "C": c["chosen"], "C_status": c["status"],
                                  "front_end": "V2 A3, simulation/hyperbola_v2_freeze.json (09dc288)",
                                  "development_scan": "_".join(DEV)}, indent=1))
    return json.loads(FREEZE.read_text())


def committed_freeze() -> dict:
    data = FREEZE.read_bytes()
    if shutil.which("git"):
        ok = subprocess.run(["git", "ls-files", "--error-unmatch", str(FREEZE)], capture_output=True).returncode == 0 \
            and subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(FREEZE)]).returncode == 0
    else:
        ok = os.environ.get("FE2_FREEZE_BLOB", "") == hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    if not ok:
        raise SystemExit(f"{FREEZE} must be committed (and unmodified) before holdouts")
    return json.loads(data)


def holdout(workers):
    frz = committed_freeze()
    fv = _v2()
    per_scan = {}
    for spec, scan in HOLDOUTS + (DEV,):
        key = f"{spec}_{scan}"
        a = run_scan(spec, scan, "A", {}, workers, fv, keep_maps=True)
        entry = {"A": score(a), "detectable": detectable(a)}
        if frz["B"]:
            b = run_scan(spec, scan, "B", frz["B"], workers, fv)
            entry["B"] = score(b)
        if frz["C"]:
            c0 = time.process_time()
            dets, multi = grow(a, frz["C"], frz["C"]["alpha"])
            g_cpu = (time.process_time() - c0) / len(a["lines"])
            sc = score(a, dets)
            sc["median_cpu_s_per_line"] = entry["A"]["median_cpu_s_per_line"] + g_cpu
            sc["growth_cpu_s_per_line"] = g_cpu
            sc["tracks_ge2_lines"] = multi
            entry["C"] = sc
        per_scan[key] = entry
        del a
    mem = {"A": peak_memory_one_line(*DEV, "A", {}, fv)}
    if frz["B"]:
        mem["B"] = peak_memory_one_line(*DEV, "B", frz["B"], fv)
    res = {"label": "EXPLORATORY; CONCRETE NDT ONLY; units are objects; D, 4TU and synthetic parts not run",
           "freeze": frz, "per_scan": per_scan, "peak_mb_one_line": mem}
    res["gates"] = gates(res)
    (OUT / "holdout.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def _sign_p(k, n):
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n if n else None


def gates(res) -> dict:
    ps = res["per_scan"]
    hold266 = [f"Pk266_{s}" for s in ("2_6_GHz_Rot00", "1_5_GHz_Rot90", "2_6_GHz_Rot90")]
    hold401 = ["Pk401_1_5_GHz_Rot00", "Pk401_1_5_GHz_Rot90"]
    hold050 = ["Pk050_1_5_GHz_Rot00", "Pk050_1_5_GHz_Rot90"]
    holds = [f"{s}_{c}" for s, c in HOLDOUTS]
    out = {}
    for arm in ("B", "C"):
        if not all(arm in ps[k] for k in holds):
            out[arm] = {"status": "not run"}
            continue
        g = {}
        # G-REC
        ducts = sorted({o for k in hold266 for o in ps[k]["A"]["per_object"]})
        improved, n_det, drops, pooled = 0, 0, [], {}
        for o in ducts:
            ks = [k for k in hold266 if ps[k]["detectable"].get(o, {}).get("detectable")]
            if ks:
                n_det += 1
                ra = sum(ps[k]["A"]["per_object"][o]["detected_lines"] for k in ks) / sum(ps[k]["A"]["per_object"][o]["n_lines"] for k in ks)
                rx = sum(ps[k][arm]["per_object"][o]["detected_lines"] for k in ks) / sum(ps[k][arm]["per_object"][o]["n_lines"] for k in ks)
                pooled[o] = {"A": ra, arm: rx, "scans": ks}
                improved += rx > ra
        for grp in (hold266, hold401):
            for o in sorted({o for k in grp for o in ps[k]["A"]["per_object"]}):
                ra = sum(ps[k]["A"]["per_object"][o]["detected_lines"] for k in grp) / sum(ps[k]["A"]["per_object"][o]["n_lines"] for k in grp)
                rx = sum(ps[k][arm]["per_object"][o]["detected_lines"] for k in grp) / sum(ps[k][arm]["per_object"][o]["n_lines"] for k in grp)
                if rx < ra - 0.10:
                    drops.append({"object": o, "A": ra, arm: rx})
        g["G_REC"] = {"pass": n_det > 0 and improved == n_det and not drops, "improved": improved, "n_detectable": n_det,
                      "sign_test_p": _sign_p(improved, n_det), "pooled": pooled, "drops_gt_0_10": drops}
        # G-CONT
        cont_ok = 0
        cont_detail = {}
        for k in hold266:
            det = [o for o, v in ps[k]["detectable"].items() if v["detectable"]]
            ok = bool(det) and all(ps[k][arm]["per_object"][o]["longest_gap"] <= 10 and
                                   ps[k][arm]["per_object"][o]["runs"] <= max(ps[k]["A"]["per_object"][o]["runs"], 1)
                                   for o in det)
            cont_detail[k] = {"detectable": det, "ok": ok,
                              "gaps": {o: ps[k][arm]["per_object"][o]["longest_gap"] for o in det},
                              "gaps_A": {o: ps[k]["A"]["per_object"][o]["longest_gap"] for o in det}}
            cont_ok += ok
        g["G_CONT"] = {"pass": cont_ok >= 2, "scans_ok": cont_ok, "detail": cont_detail}
        # G-ART (BAM part)
        art = {k: {"A": ps[k]["A"]["artefact_fp_per_line"], arm: ps[k][arm]["artefact_fp_per_line"]} for k in holds}
        g["G_ART_BAM_ONLY"] = {"pass": all(v[arm] <= 0.5 * v["A"] for v in art.values()), "detail": art,
                               "note": "synthetic part not run -> incomplete"}
        # G-FREE
        fr = {k: {"A": ps[k]["A"]["fp_per_line"], arm: ps[k][arm]["fp_per_line"]} for k in hold050}
        g["G_FREE"] = {"pass": all(v[arm] <= v["A"] for v in fr.values()), "detail": fr}
        # G-NULL
        if arm == "B":
            zs = {k: {"A": ps[k]["A"]["median_z_star"], "B": ps[k]["B"]["median_z_star"]} for k in hold050 + hold266}
            g["G_NULL"] = {"pass": all(v["B"] <= 0.75 * v["A"] for v in zs.values()), "detail": zs}
        else:
            dc = json.loads((OUT / "dev_c.json").read_text())
            cfg = res["freeze"]["C"]
            rate = next(r["null_false_track_rate"][str(cfg["alpha"])] if str(cfg["alpha"]) in r["null_false_track_rate"]
                        else r["null_false_track_rate"][cfg["alpha"]]
                        for r in dc["table"] if r["config"] == {k: cfg[k] for k in ("G", "dx", "dt")})
            g["G_NULL"] = {"pass": rate <= NULL_RATE_MAX, "dev_null_false_track_rate": rate}
        # G-COST
        cost = {k: {"A": ps[k]["A"]["median_cpu_s_per_line"], arm: ps[k][arm]["median_cpu_s_per_line"]} for k in holds}
        mem = res["peak_mb_one_line"].get(arm, res["peak_mb_one_line"]["A"])
        g["G_COST_BAM_ONLY"] = {"pass": all(v[arm] <= 2 * v["A"] for v in cost.values()) and mem <= 1000,
                                "detail": cost, "peak_mb_one_line": mem, "note": "4TU part not run -> incomplete"}
        # G-FREQ/POL
        fp_ok = 0
        fp_detail = {}
        for k in hold266:
            det = [o for o, v in ps[k]["detectable"].items() if v["detectable"]]
            rec_ok = bool(det) and all(ps[k][arm]["per_object"][o]["line_recall"] > ps[k]["A"]["per_object"][o]["line_recall"]
                                       for o in det) and \
                all(ps[k][arm]["per_object"][o]["line_recall"] >= ps[k]["A"]["per_object"][o]["line_recall"] - 0.10
                    for o in ps[k]["A"]["per_object"])
            art_ok = ps[k][arm]["artefact_fp_per_line"] <= 0.5 * ps[k]["A"]["artefact_fp_per_line"]
            fp_detail[k] = {"rec_ok": rec_ok, "art_ok": art_ok}
            fp_ok += rec_ok and art_ok
        g["G_FREQ_POL"] = {"pass": fp_ok >= 2, "scans_ok": fp_ok, "detail": fp_detail}
        out[arm] = g
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("dev-b", "dev-c", "freeze", "holdout"))
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.stage == "dev-b":
        r = dev_b(a.workers)
        print(json.dumps({k: v for k, v in r.items() if k != "table"}, indent=1, default=str)[:3000])
        for t in r["table"]:
            print(t.get("params"), t.get("admissible"), t.get("median_duct_recall"),
                  round(t["score"]["artefact_fp_per_line"], 3), round(t["score"]["median_z_star"], 1),
                  {o: round(v["line_recall"], 2) for o, v in t["score"]["per_object"].items()})
    elif a.stage == "dev-c":
        r = dev_c(a.workers)
        print(json.dumps({k: v for k, v in r.items() if k != "table"}, indent=1, default=str)[:2000])
        for t in r["table"]:
            print(t["config"], t["alpha"], t["null_false_track_rate"], t.get("median_duct_recall"))
    elif a.stage == "freeze":
        print(json.dumps(write_freeze(), indent=1))
    else:
        r = holdout(a.workers)
        print(json.dumps(r["gates"], indent=1, default=str)[:8000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
