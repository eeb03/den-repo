"""
CONTROLLED EXPERIMENT: calibrated Candidate V2 on BAM, against three unchanged
baselines. Research only; changes no production code.

ARMS
  A production   benchmark.detection ring z-score (threshold 3.0, min_cells 3),
                 unchanged; ranked by |peak z|; operating point z >= 3.0.
  B envelope     E1 (scripts.bam_candidate_experiment), frozen W=81 global;
                 curve from T=4, operating point T=10.
  C v2_prev      benchmark.candidate_v2 with its frozen parameters (W=81, T=6,
                 extent 60 mm, shape_min 0.2, persistence_min 0); operating
                 point final_score >= 0.768.
  D v2_cal       benchmark.candidate_v2_calibrated with the frozen
                 configuration in configs/candidate_v2_calibrated_frozen.json.

PHASES
  dev       Rot00 only (all six scans: Pk266 ducts, Pk401 foam cuboids, Pk050
            empty control; 1.5 and 2.6 GHz). Baselines, V2-cal design grid,
            operating-point selection, ablations, PR curves.
  heldout   Rot90 only, after the frozen config is committed
            (scripts.bam_v2cal_harness.frozen_commit enforces it). Runs every
            arm unchanged, once.

SCORING (unchanged from the previous V2 experiment; `score` is imported)
  L-XZ where the scan's back-wall calibration is accepted: per (line, target)
  the highest-ranked detection within |dx| <= 100 mm must lie within 60 mm of
  the drawn top depth; other in-depth window entries are duplicates; every
  other detection is a false positive. L-X where calibration is refused.

    python -m scripts.bam_candidate_v2_calibrated --phase dev
    python -m scripts.bam_candidate_v2_calibrated --phase heldout
"""
from __future__ import annotations

import argparse
import json
import time
import warnings
from pathlib import Path

import numpy as np

from benchmark import candidate_v2 as v2prev
from benchmark import candidate_v2_calibrated as vc
from scripts.bam_candidate_experiment import e1_detect
from scripts.bam_candidate_v2_experiment import fp_at_recall, pr_curve, score
from scripts.bam_quantitative_validation import (MATCH_DEPTH_MM, MATCH_RADIUS_MM, STEP_EDGE_GUARD_MM,
                                                 CENTRAL_Y_MAX, CENTRAL_Y_MIN, TARGET_MIN_NS, depth_mm,
                                                 run_detector)
from scripts.bam_v2cal_harness import (CACHE, DEV_SCANS, FROZEN_CONFIG, HELDOUT_SCANS, cached, jsonable,
                                       load_dev_scan, load_eval_scan, load_frozen)

warnings.filterwarnings("ignore", category=RuntimeWarning)

V2PREV_FROZEN = v2prev.V2Params(background_window_traces=81, proposal_threshold=6.0,
                                min_lateral_extent_mm=60.0, shape_min=0.2, persistence_min=0.0)
OPS = {"production": 3.0, "envelope": 10.0, "v2_prev": 0.768}
KEYS = {"production": "z", "envelope": "z", "v2_prev": "final_score", "v2_cal": "final_score"}
OUT = Path("artifacts/bam/v2cal")


# ---------------------------------------------------------------- baseline arms (unchanged code)
def arm_production(sc):
    return cached("production", sc.sid, lambda: run_detector(sc.volume(), sc.s.grid, sc.sid))


def arm_envelope(sc):
    return cached("envelope", sc.sid, lambda: e1_detect(sc.volume(), sc.s.grid, sc.sid, W=81,
                                                        N="global", T=4.0))


def arm_v2_prev(sc):
    def run():
        g = sc.s.grid
        return v2prev.detect(sc.volume(), g.x, g.y, g.z, V2PREV_FROZEN)
    return cached("v2_prev", sc.sid, run)


# ---------------------------------------------------------------- metrics
def full_metrics(dets, sc, key, threshold):
    r = score(dets, sc, key, threshold, full=True)
    r["false_negatives"] = (r["opportunities"] - r["hits"]) if r["opportunities"] else None
    r["duplicates_per_matched_target_crossing"] = (r["duplicates"] / r["hits"]) if r["hits"] else None
    kept = [d[key] for d in dets if d[key] >= threshold]
    if kept:
        q = np.quantile(kept, [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
        r["confidence_distribution"] = dict(zip(["min", "p10", "p25", "median", "p75", "p90", "max"],
                                                [round(float(v), 4) for v in q]))
    return r


def evaluate_arm(dets, sc, key, op, n_curve=80):
    curve = pr_curve(dets, sc, key, n=n_curve)
    return {"at_operating_point": full_metrics(dets, sc, key, op), "operating_threshold": op,
            "curve": curve,
            "fp_per_line_at_recall_0.75": fp_at_recall(curve, 0.75),
            "fp_per_line_at_recall_0.8": fp_at_recall(curve, 0.8),
            "max_recall": max((c["recall"] or 0.0 for c in curve), default=0.0)}


def summary_line(name, r):
    o = r["at_operating_point"]
    f = lambda v: "-" if v is None else f"{v:.3f}"
    return (f"  {name:10s} R {f(o['recall'])} P {f(o['precision'])} F1 {f(o['f1'])} "
            f"FP/line {o['false_positives_per_line']:.2f} n {o['n_detections']} [{o['rule'][:4]}]")


def run_baselines(scans, label):
    out = {}
    for spec, scan in scans:
        t0 = time.time()
        sc = load_dev_scan(spec, scan) if label == "dev" else load_eval_scan(spec, scan)[0]
        res = {"calibration": sc.calibration_record, "object_type": sc.object_type,
               "antenna": sc.antenna, "arms": {}}
        for name, fn in (("production", arm_production), ("envelope", arm_envelope),
                         ("v2_prev", arm_v2_prev)):
            res["arms"][name] = evaluate_arm(fn(sc), sc, KEYS[name], OPS[name])
        sc.release()
        out[sc.sid] = res
        print(sc.sid, f"{time.time() - t0:.0f}s", flush=True)
        for name, r in res["arms"].items():
            print(summary_line(name, r), flush=True)
    return out



# ---------------------------------------------------------------- PRE-REGISTERED DEV GRID AND RULE
# Written and committed BEFORE the grid was run. Only Rot00 scans enter it.
#: DEV ITERATION 2 (after iteration 1 on Rot00 only): "row" normalisation was
#: dominated everywhere (mean FP/line 19-61 at macro recall 0.75 vs 4.0-10.5 for
#: "line"), so it is dropped; the horizon rule now requires a flat run
#: (benchmark.candidate_v2_calibrated, HORIZON_MIN_RUN_MM). Selection rule unchanged.
PROPOSAL_GRID = {"normalisation": ["line"], "background_window_traces": [41, 81],
                 "horizon_ratio": [1.5, 2.5]}
DEV_ITERATIONS = [
    {"iteration": 1, "commit": "2d9086e", "chosen": "line W41 h2.5 T4 ext15 theta 0.65",
     "dev_macro_recall": 0.766, "dev_mean_fp_per_line": 4.02,
     "finding": "duct-1 (241 mm) mislabelled as a horizon -> structure / step-edge penalties "
                "(64 of its missed crossings on Pk266 1.5 GHz)"},
]
GATE_GRID = {"proposal_threshold": [3.0, 4.0, 6.0], "min_lateral_extent_mm": [0.0, 15.0, 30.0]}
THETAS = np.round(np.arange(-1.50, 1.0001, 0.01), 2)
TARGET_MACRO_RECALL = 0.75
SELECTION_RULE = (
    "Development = the six Rot00 scans. For every (proposal config, gate config, final-score "
    "threshold theta): macro_recall = mean recall over the four target scans (Pk266 / Pk401 x "
    "1.5 / 2.6 GHz; L-XZ where the scan's calibration is accepted, else L-X); mean_fp = mean "
    "false positives per line over all six scans, controls included. Feasible: macro_recall >= "
    f"{TARGET_MACRO_RECALL}. Choose the feasible point with the lowest mean_fp; ties by higher "
    "macro_recall, then fewer detections. If nothing is feasible, choose the highest macro F1. "
    "Macro averaging gives each object type and antenna equal weight (pooling would let 644 duct "
    "crossings per scan swamp 100 cuboid crossings).")
PROPOSAL_MIN_THRESHOLD = min(GATE_GRID["proposal_threshold"])


def cfg_name(c: dict) -> str:
    return f"{c['normalisation']}_W{c['background_window_traces']}_h{c['horizon_ratio']}"


def proposals_for(sc, cfg: dict, use_calibration=True):
    import hashlib
    import inspect
    import pickle
    src = hashlib.sha256(Path(inspect.getfile(vc)).read_bytes()).hexdigest()[:10]
    tag = cfg_name(cfg) + ("" if use_calibration else "_uncal") + "_" + src
    p = CACHE / f"props__{tag}__{sc.sid}.pkl"
    if p.exists():
        return pickle.loads(p.read_bytes())
    g = sc.s.grid
    params = vc.V2CalParams(**cfg, use_calibration=use_calibration)
    res = vc.propose(sc.volume(), g.x, g.y, g.z, params, sc.generator_cal,
                     min_threshold=PROPOSAL_MIN_THRESHOLD)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(pickle.dumps(res))
    return res


def sweep(dets, sc, key, thetas):
    """Exactly `score`'s recall / FP / count at every threshold, vectorised.
    The window's top-ranked detection at threshold theta is its overall top
    when that top >= theta, so a hit is fixed per window; a detection is
    'used' iff it is depth-good in some hit window and >= theta."""
    s = np.array([d[key] for d in dets], float)
    by_line: dict[int, list] = {}
    for i, d in enumerate(dets):
        by_line.setdefault(d["line"], []).append(i)
    used = np.zeros(len(dets), bool)
    top_score, top_good = [], []

    def good(i, t):
        if not sc.depth_scoreable:
            return True
        return abs(depth_mm(dets[i]["t_ns"], sc.cal["t0_ns"], sc.cal["v_m_per_ns"]) - t["z_top"]) <= MATCH_DEPTH_MM

    opp = 0
    for t, lines in sc.windows:
        opp += len(lines)
        for j in lines:
            win = [i for i in by_line.get(j, []) if abs(dets[i]["x"] - t["x"]) <= MATCH_RADIUS_MM]
            if not win:
                continue
            best = max(win, key=lambda i: s[i])
            ok = good(best, t)
            top_score.append(s[best])
            top_good.append(ok)
            if ok:
                for i in win:
                    if good(i, t):
                        used[i] = True
    top_score, top_good = np.array(top_score), np.array(top_good, bool)
    n = np.array([(s >= th).sum() for th in thetas])
    u = np.array([(used & (s >= th)).sum() for th in thetas])
    hits = np.array([(top_good & (top_score >= th)).sum() for th in thetas])
    fp = n - u
    rec = hits / opp if opp else np.full(len(thetas), np.nan)
    prec = np.where(hits + fp > 0, hits / np.maximum(hits + fp, 1), np.nan)
    return {"recall": rec, "precision": prec, "fp_per_line": fp / sc.n_lines, "n": n, "hits": hits,
            "opportunities": opp}


def pooled(per_scan: dict, target_sids, all_sids):
    rec = np.mean([per_scan[s]["recall"] for s in target_sids], axis=0)
    fp = np.mean([per_scan[s]["fp_per_line"] for s in all_sids], axis=0)
    prec = np.nanmean([per_scan[s]["precision"] for s in target_sids], axis=0)
    n = np.sum([per_scan[s]["n"] for s in all_sids], axis=0)
    f1 = np.where(rec + prec > 0, 2 * rec * prec / np.maximum(rec + prec, 1e-12), 0.0)
    return {"macro_recall": rec, "mean_fp_per_line": fp, "macro_precision": prec, "macro_f1": f1, "n": n}


def choose(points):
    """points: list of (key, theta, macro_recall, mean_fp, n, macro_f1). The pre-registered rule."""
    feas = [p for p in points if p[2] >= TARGET_MACRO_RECALL]
    if feas:
        return min(feas, key=lambda p: (round(p[3], 6), -p[2], p[4])), "feasible"
    return max(points, key=lambda p: p[5]), "infeasible: max macro F1"


def load_scans(scans, heldout=False):
    out = []
    commit = None
    for spec, scan in scans:
        if heldout:
            sc, commit = load_eval_scan(spec, scan)
        else:
            sc = load_dev_scan(spec, scan)
        out.append(sc)
    return out, commit


def run_grid():
    scans, _ = load_scans(DEV_SCANS)
    target_sids = [sc.sid for sc in scans if sc.targets]
    all_sids = [sc.sid for sc in scans]
    import itertools
    rows, points = [], []
    for vals in itertools.product(*PROPOSAL_GRID.values()):
        pcfg = dict(zip(PROPOSAL_GRID.keys(), vals))
        props = {}
        for sc in scans:
            t0 = time.time()
            props[sc.sid] = proposals_for(sc, pcfg)
            sc.release()
            print(cfg_name(pcfg), sc.sid, f"{time.time() - t0:.0f}s", flush=True)
        for T, ext in itertools.product(*GATE_GRID.values()):
            params = vc.V2CalParams(**pcfg, proposal_threshold=T, min_lateral_extent_mm=ext)
            per = {sc.sid: sweep(vc.select(props[sc.sid], params), sc, "final_score", THETAS) for sc in scans}
            pl = pooled(per, target_sids, all_sids)
            key = {**pcfg, "proposal_threshold": T, "min_lateral_extent_mm": ext}
            for i, th in enumerate(THETAS):
                points.append((json.dumps(key), float(th), float(pl["macro_recall"][i]),
                               float(pl["mean_fp_per_line"][i]), int(pl["n"][i]), float(pl["macro_f1"][i])))
            k75 = [i for i in range(len(THETAS)) if pl["macro_recall"][i] >= TARGET_MACRO_RECALL]
            rows.append({**key, "max_macro_recall": float(pl["macro_recall"].max()),
                         "min_mean_fp_at_macro_recall_0.75": (float(min(pl["mean_fp_per_line"][i] for i in k75))
                                                              if k75 else None)})
            print("  ", T, ext, rows[-1]["max_macro_recall"], rows[-1]["min_mean_fp_at_macro_recall_0.75"],
                  flush=True)
    best, how = choose(points)
    out = {"selection_rule": SELECTION_RULE, "proposal_grid": PROPOSAL_GRID, "gate_grid": GATE_GRID,
           "thetas": [float(THETAS[0]), float(THETAS[-1]), 0.01], "grid": rows,
           "chosen": {"params": json.loads(best[0]), "operating_threshold": best[1],
                      "dev_macro_recall": best[2], "dev_mean_fp_per_line": best[3], "dev_n": best[4],
                      "dev_macro_f1": best[5], "how": how}}
    (OUT / "dev_grid.json").write_text(json.dumps(jsonable(out), indent=1))
    print("CHOSEN", out["chosen"], flush=True)
    return out


def write_frozen(chosen: dict):
    import hashlib
    import inspect
    consts = {k: v for k, v in vars(vc).items() if k.isupper() and isinstance(v, (int, float, str, tuple))}
    cfg = {
        "frozen": True,
        "note": ("Frozen on Rot00 development scans only. The Rot90 held-out evaluation must load "
                 "this file unchanged; the commit that last changed it is recorded with every "
                 "held-out result."),
        "module": "benchmark.candidate_v2_calibrated",
        "module_sha256": hashlib.sha256(Path(inspect.getfile(vc)).read_bytes()).hexdigest(),
        "params": chosen["params"],
        "operating_threshold_final_score": chosen["operating_threshold"],
        "selection_rule": SELECTION_RULE,
        "selection_result_on_dev": {k: chosen[k] for k in ("dev_macro_recall", "dev_mean_fp_per_line",
                                                           "dev_n", "dev_macro_f1", "how")},
        "module_constants": jsonable(consts),
        "calibration_input": {"source": "per-scan back-wall picks through schemas.depth_calibration",
                              "pick_convention": "peak", "pick_precision_ns": 0.1,
                              "used_only_if": "status calibrated AND redundant (scientifically sufficient)"},
        "baselines": {"production": {"threshold": 3.0, "min_cells": 3},
                      "envelope": {"W": 81, "N": "global", "curve_T": 4.0, "operating_T": 10.0},
                      "v2_prev": {"params": {"background_window_traces": 81, "proposal_threshold": 6.0,
                                             "min_lateral_extent_mm": 60.0, "shape_min": 0.2,
                                             "persistence_min": 0.0},
                                  "operating_threshold_final_score": 0.768}},
        "scoring": "scripts.bam_candidate_v2_experiment.score (L-XZ 100 mm / 60 mm; L-X where calibration refused)",
        "heldout_scans": [f"{s}_3D_Dataset_{f}" for s, f in HELDOUT_SCANS],
    }
    FROZEN_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    FROZEN_CONFIG.write_text(json.dumps(cfg, indent=1) + "\n")
    print("wrote", FROZEN_CONFIG)


# ---------------------------------------------------------------- failure analysis
def _in_window(d, sc):
    for t, lines in sc.windows:
        if d["line"] in lines and abs(d["x"] - t["x"]) <= MATCH_RADIUS_MM:
            return t
    return None


def fp_category(d, sc, used_ids):
    """Category of one false positive (L-XZ, or L-X where depth is not scoreable)."""
    t = _in_window(d, sc)
    if t is not None:
        if sc.depth_scoreable:
            dz = depth_mm(d["t_ns"], sc.cal["t0_ns"], sc.cal["v_m_per_ns"]) - t["z_top"]
            return "wrong-depth response in a target window (below: ringing / multiple)" if dz > 0 \
                else "wrong-depth response in a target window (above the target)"
        return "duplicate response"
    k = min(int(d["x"] // 500), 3)
    tbw = sc.tbw[k]
    if d["t_ns"] < TARGET_MIN_NS:
        return "direct wave"
    if abs(d["t_ns"] - tbw) <= 0.5:
        return "back wall / structural boundary"
    if d["t_ns"] > tbw + 0.5:
        return "below back wall (multiples / late-time)"
    if any(abs(d["x"] - e) <= STEP_EDGE_GUARD_MM for e in (500, 1000, 1500)):
        return "step edge"
    if d["y"] < CENTRAL_Y_MIN or d["y"] > CENTRAL_Y_MAX:
        return "real non-target reflector (edge reinforcement zone)"
    if any(abs(d["x"] - b["x"]) <= 80 and abs(d["y"] - b["y"]) <= 80 for b in sc.boreholes):
        return "real non-target reflector (grouted borehole)"
    if any(MATCH_RADIUS_MM < abs(d["x"] - tt["x"]) <= 250 for tt in sc.targets):
        return "near a target, outside the match radius"
    if d.get("noise_penalty", 0) >= 0.5:
        return "late-time noise"
    if d.get("ringing_penalty", 0) >= 1.0:
        return "ringing"
    return "unknown"


def classify_fps(dets, sc, key, theta):
    dets = [d for d in dets if d[key] >= theta]
    by_line: dict[int, list] = {}
    for i, d in enumerate(dets):
        by_line.setdefault(d["line"], []).append(i)
    used = set()
    for t, lines in sc.windows:
        for j in lines:
            win = [i for i in by_line.get(j, []) if abs(dets[i]["x"] - t["x"]) <= MATCH_RADIUS_MM]
            if not win:
                continue
            best = max(win, key=lambda i: dets[i][key])

            def ok(i):
                return (not sc.depth_scoreable) or abs(
                    depth_mm(dets[i]["t_ns"], sc.cal["t0_ns"], sc.cal["v_m_per_ns"]) - t["z_top"]) <= MATCH_DEPTH_MM
            if ok(best):
                used.update(i for i in win if ok(i))
    cats: dict[str, int] = {}
    for i, d in enumerate(dets):
        if i not in used:
            c = fp_category(d, sc, used)
            cats[c] = cats.get(c, 0) + 1
    return dict(sorted(cats.items(), key=lambda kv: -kv[1]))


def classify_misses(result, dets, sc, params, theta):
    """Why each missed (target, line) opportunity was missed by V2-cal."""
    sel = [d for d in dets if d["final_score"] >= theta]
    by_line: dict[int, list] = {}
    for d in sel:
        by_line.setdefault(d["line"], []).append(d)
    allp: dict[int, list] = {}
    for p in result["proposals"]:
        allp.setdefault(p["line"], []).append(p)

    def at_depth(p, t):
        if not sc.depth_scoreable:
            return True
        return abs(depth_mm(p["t_ns"], sc.cal["t0_ns"], sc.cal["v_m_per_ns"]) - t["z_top"]) <= MATCH_DEPTH_MM

    out: dict[str, dict] = {}
    for t, lines in sc.windows:
        c: dict[str, int] = {}
        for j in lines:
            win = [d for d in by_line.get(j, []) if abs(d["x"] - t["x"]) <= MATCH_RADIUS_MM]
            if win and at_depth(max(win, key=lambda d: d["final_score"]), t):
                continue
            cand = [p for p in allp.get(j, []) if abs(p["x"] - t["x"]) <= MATCH_RADIUS_MM and at_depth(p, t)]
            if not cand:
                why = "no proposal at the target (insufficient amplitude or preprocessing loss)"
            else:
                p = max(cand, key=lambda q: q["z_row"])
                fs = vc.final_score(p, params)
                if p["z_row"] < params.proposal_threshold:
                    why = "insufficient amplitude (below the proposal threshold)"
                elif p["lateral_extent_mm"] < params.min_lateral_extent_mm:
                    why = "persistence failure (lateral extent gate)"
                elif win and fs >= theta:
                    why = "outranked in the window by a wrong-depth response"
                elif fs < theta:
                    terms = {"shape (non-hyperbolic / shape term)": 1 - p["shape_consistency"],
                             "depth gate (depth_plausibility)": 1 - p["depth_plausibility"],
                             "persistence failure (cross-line)": 1 - p["persistence"],
                             "insufficient amplitude (signal / contrast)":
                                 1 - min(p["signal_strength"], p["background_contrast"]),
                             "penalised as direct wave": p["direct_wave_penalty"],
                             "penalised as step edge": p["edge_penalty"],
                             "penalised as structure": p["structure_penalty"],
                             "penalised as ringing": p["ringing_penalty"],
                             "penalised as noise": p["noise_penalty"]}
                    why = "below operating score; largest deficit: " + max(terms, key=terms.get)
                else:
                    why = "suppressed by NMS (a stronger response nearby)"
            c[why] = c.get(why, 0) + 1
        out[t["id"]] = dict(sorted(c.items(), key=lambda kv: -kv[1]))
    return out


# ---------------------------------------------------------------- full evaluation of the frozen config
def frozen_params(cfg) -> vc.V2CalParams:
    return vc.V2CalParams(**cfg["params"])


def evaluate_frozen(scans, cfg, label):
    params = frozen_params(cfg)
    theta = cfg["operating_threshold_final_score"]
    pcfg = {k: cfg["params"][k] for k in PROPOSAL_GRID}
    out = {}
    for sc in scans:
        t0 = time.time()
        res = {"calibration": sc.calibration_record, "object_type": sc.object_type, "antenna": sc.antenna,
               "depth_rule": "L-XZ" if sc.depth_scoreable else "L-X (calibration refused)", "arms": {}}
        arms = {"production": arm_production(sc), "envelope": arm_envelope(sc), "v2_prev": arm_v2_prev(sc)}
        result = proposals_for(sc, pcfg)
        arms["v2_cal"] = vc.select(result, params)
        ops = {**OPS, "v2_cal": theta}
        for name, dets in arms.items():
            res["arms"][name] = evaluate_arm(dets, sc, KEYS[name], ops[name])
            res["arms"][name]["fp_categories"] = classify_fps(dets, sc, KEYS[name], ops[name])
        res["v2_cal_scan"] = {k: v for k, v in result["scan"].items() if k != "calibration_used"}
        res["v2_cal_misses"] = classify_misses(result, arms["v2_cal"], sc, params, theta)
        # ablations at the frozen threshold (reporting only; nothing re-tuned)
        abl = {}
        for term in vc.EVIDENCE + vc.PENALTIES:
            d = vc.select(result, params.without(term))
            abl[f"without_{term}"] = _abl_summary(d, sc, theta)
        abl["without_hard_gates"] = _abl_summary(
            vc.select(result, vc.V2CalParams(**{**cfg["params"], "proposal_threshold": PROPOSAL_MIN_THRESHOLD,
                                                "min_lateral_extent_mm": 0.0})), sc, theta)
        if sc.generator_cal is not None:
            unc = proposals_for(sc, pcfg, use_calibration=False)
            abl["uncalibrated (calibration withheld)"] = _abl_summary(vc.select(unc, params), sc, theta)
        abl["frozen"] = _abl_summary(arms["v2_cal"], sc, theta)
        res["v2_cal_ablations"] = abl
        sc.release()
        out[sc.sid] = res
        print(label, sc.sid, f"{time.time() - t0:.0f}s", flush=True)
        for name, r in res["arms"].items():
            print(summary_line(name, r), flush=True)
    return out


def _abl_summary(dets, sc, theta):
    r = score(dets, sc, "final_score", theta)
    curve = pr_curve(dets, sc, "final_score", n=80)
    return {"recall": r["recall"], "precision": r["precision"],
            "false_positives_per_line": r["false_positives_per_line"], "n_detections": r["n_detections"],
            "max_recall": max((c["recall"] or 0.0 for c in curve), default=0.0),
            "fp_per_line_at_recall_0.75": (fp_at_recall(curve, 0.75) or {}).get("false_positives_per_line")}


def ablation_refrozen(scans, cfg):
    """Score-term and calibration ablations, each with its operating threshold
    RE-CHOSEN ON DEV by the same pre-registered rule (dev only)."""
    params = frozen_params(cfg)
    pcfg = {k: cfg["params"][k] for k in PROPOSAL_GRID}
    target_sids = [sc.sid for sc in scans if sc.targets]
    all_sids = [sc.sid for sc in scans]
    variants = {"frozen": (params, True)}
    for term in vc.EVIDENCE + vc.PENALTIES:
        variants[f"without_{term}"] = (params.without(term), True)
    variants["uncalibrated (calibration withheld)"] = (params, False)
    out = {}
    for name, (p, use_cal) in variants.items():
        per = {}
        for sc in scans:
            res = proposals_for(sc, pcfg, use_calibration=use_cal or sc.generator_cal is None)
            sc.release()
            per[sc.sid] = sweep(vc.select(res, p), sc, "final_score", THETAS)
        pl = pooled(per, target_sids, all_sids)
        pts = [(name, float(th), float(pl["macro_recall"][i]), float(pl["mean_fp_per_line"][i]),
                int(pl["n"][i]), float(pl["macro_f1"][i])) for i, th in enumerate(THETAS)]
        best, how = choose(pts)
        out[name] = {"theta": best[1], "macro_recall": best[2], "mean_fp_per_line": best[3],
                     "macro_f1": best[5], "how": how,
                     "max_macro_recall": float(pl["macro_recall"].max()),
                     "per_scan_at_theta": {s: {"recall": float(per[s]["recall"][list(THETAS).index(best[1])]),
                                               "fp_per_line": float(per[s]["fp_per_line"][list(THETAS).index(best[1])])}
                                           for s in all_sids}}
        print("ablation", name, out[name]["theta"], round(best[2], 3), round(best[3], 3), how, flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["baselines", "grid", "freeze", "dev_report", "heldout"], required=True)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.phase == "baselines":
        res = run_baselines(DEV_SCANS, "dev")
        (OUT / "dev_baselines.json").write_text(json.dumps(jsonable(res), indent=1))
    elif args.phase == "grid":
        run_grid()
    elif args.phase == "freeze":
        chosen = json.loads((OUT / "dev_grid.json").read_text())["chosen"]
        write_frozen(chosen)
    elif args.phase == "dev_report":
        cfg = json.loads(FROZEN_CONFIG.read_text())
        scans, _ = load_scans(DEV_SCANS)
        res = {"evaluation": evaluate_frozen(scans, cfg, "dev"),
               "ablations_refrozen_on_dev": ablation_refrozen(scans, cfg)}
        (OUT / "dev_report.json").write_text(json.dumps(jsonable(res), indent=1))
    elif args.phase == "heldout":
        cfg, commit = load_frozen()
        scans, commit = load_scans(HELDOUT_SCANS, heldout=True)
        res = {"frozen_config_commit": commit, "frozen_config": cfg,
               "evaluation": evaluate_frozen(scans, cfg, "heldout")}
        (OUT / "heldout_report.json").write_text(json.dumps(jsonable(res), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
