"""
CONTROLLED EXPERIMENT: Candidate V2 versus the production baseline and the
envelope baseline (E1), on BAM. Research only; changes no production code.

ARMS
  PRODUCTION  benchmark.detection ring z-score (threshold 3.0, min_cells 3),
              unchanged; ranked by |peak z|.
  ENVELOPE    E1 (scripts.bam_candidate_experiment), parameters frozen in that
              experiment on the same development scan (W=81, global, T=10);
              ranked by envelope z.
  V2          benchmark.candidate_v2; ranked by final_score.

SPLIT (identical to E1; fixed before any V2 result was computed)
  DEVELOPMENT  Pk266 1.5 GHz Rot00: the only scan used to choose parameters.
  TEST         Pk266 2.6 GHz Rot00, Pk401 1.5 GHz Rot00, Pk401 2.6 GHz Rot00.
  CONTROL      Pk050 1.5 / 2.6 GHz Rot00 (no targets: every detection is a
               false positive).
  Test and control scans are never looked at while tuning. The operating
  threshold of each arm is frozen on development (V2: the highest final-score
  threshold that reaches L-XZ recall >= 0.80 there).

MATCHING (pre-registered, as benchmark.scoring.score_localization)
  L-XZ: per (line, target), the window holds detections with |dx| <= 100 mm.
  The highest-ranked one must lie within 60 mm of the drawn top depth, under
  the back-wall calibration of the same scan, or the opportunity is missed.
  Other in-depth window entries are duplicates; every other detection is a
  false positive. Where calibration was REFUSED (Pk401 2.6 GHz) depth is not
  scoreable and only L-X (horizontal) is reported, labelled as such.

    venv/bin/python -m scripts.bam_candidate_v2_experiment
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
import warnings
from pathlib import Path

import numpy as np

from benchmark import candidate_v2 as v2
from benchmark.bam_ingest import load_scan, load_volume
from scripts.bam_candidate_experiment import e1_detect
from scripts.bam_quantitative_validation import (MATCH_DEPTH_MM, MATCH_RADIUS_MM, depth_mm,
                                                 evaluate_detections, lines_for, load_gt,
                                                 run_detector, stats)

warnings.filterwarnings("ignore", category=RuntimeWarning)

DEV = ("Pk266", "1_5_GHz_Rot00")
TEST = [("Pk266", "2_6_GHz_Rot00"), ("Pk401", "1_5_GHz_Rot00"), ("Pk401", "2_6_GHz_Rot00")]
CONTROL = [("Pk050", "1_5_GHz_Rot00"), ("Pk050", "2_6_GHz_Rot00")]
E1_FROZEN = {"W": 81, "N": "global"}
E1_OPERATING_T = 10.0
E1_CURVE_T = 4.0
TUNING_GRID = {"background_window_traces": [41, 81], "proposal_threshold": [4.0, 6.0],
               "min_lateral_extent_mm": [20.0, 60.0], "shape_min": [0.0, 0.1, 0.2, 0.3],
               "persistence_min": [0.0, 0.2, 0.4]}
TARGET_RECALL = 0.80
VAL = Path("artifacts/bam/validation/quantitative_validation.json")
BASELINE_DETS = "artifacts/bam/validation/detections_baseline_{spec}_3D_Dataset_{scan}.json"


# ---------------------------------------------------------------- scoring
class Scan:
    def __init__(self, spec, scan, val):
        self.spec, self.scan = spec, scan
        self.sid = f"{spec}_3D_Dataset_{scan}"
        self.s = load_scan(spec, self.sid)
        entry = val["scans"][self.sid]
        self.cal = entry["calibration_backwall_peak"]
        self.tbw = {b["step"]: (b["t_ns"] if b["t_ns"] is not None else 99.0) for b in entry["backwall"]}
        targets, boreholes = load_gt()
        self.targets = targets.get(spec, [])
        self.boreholes = [b for b in boreholes if b["id"].startswith(spec)]
        self.n_lines = len(self.s.grid.y)
        self.windows = [(t, lines_for(t, self.s.grid)) for t in self.targets]

    @property
    def depth_scoreable(self):
        return self.cal is not None

    def volume(self):
        return load_volume(self.s)


def score(dets, sc: Scan, key: str, threshold: float = -np.inf, full: bool = False) -> dict:
    """Strict L-XZ where calibrated, otherwise L-X; `key` ranks the window."""
    dets = [d for d in dets if d[key] >= threshold]
    by_line: dict[int, list] = {}
    for i, d in enumerate(dets):
        by_line.setdefault(d["line"], []).append(i)
    used, dx, dz, dup, hits, opp = set(), [], [], 0, 0, 0
    depth_ok = sc.depth_scoreable

    def depth_of(d):
        return depth_mm(d["t_ns"], sc.cal["t0_ns"], sc.cal["v_m_per_ns"])

    for t, lines in sc.windows:
        opp += len(lines)
        for j in lines:
            win = [i for i in by_line.get(j, []) if abs(dets[i]["x"] - t["x"]) <= MATCH_RADIUS_MM]
            if not win:
                continue
            best = max(win, key=lambda i: dets[i][key])
            if depth_ok:
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
    out = {"rule": "L-XZ" if depth_ok else "L-X (depth not scoreable: calibration refused)",
           "n_detections": len(dets), "opportunities": opp, "hits": hits,
           "recall": rec, "precision": prec,
           "f1": (2 * rec * prec / (rec + prec)) if rec and prec else (0.0 if opp else None),
           "false_positives": fp, "false_positives_per_line": fp / sc.n_lines,
           "duplicates": dup, "duplicate_rate": dup / (hits + dup) if (hits + dup) else None}
    if full:
        out["longitudinal_error_mm"] = stats(dx)
        out["depth_error_mm"] = stats(dz) if depth_ok else "not scoreable (calibration refused)"
        cats = evaluate_detections([{**d, "z": d[key]} for d in dets], sc.targets, sc.s.grid,
                                   sc.cal or {"t0_ns": 0.0, "v_m_per_ns": 0.11}, sc.tbw, sc.boreholes)
        out["fp_categories_LX"] = cats["fp_categories"]
        if "cluster" in (dets[0] if dets else {}):
            out["n_clusters"] = len({d["cluster"] for d in dets})
    return out


def pr_curve(dets, sc, key, n=60):
    if not dets:
        return []
    vals = np.unique(np.quantile([d[key] for d in dets], np.linspace(0, 1, n)))
    return [{"threshold": float(t), **{k: r[k] for k in ("recall", "precision", "false_positives_per_line",
                                                         "n_detections", "duplicate_rate")}}
            for t in vals for r in [score(dets, sc, key, t)]]


def fp_at_recall(curve, r):
    ok = [c for c in curve if c["recall"] is not None and c["recall"] >= r]
    if not ok:
        return None
    best = min(ok, key=lambda c: c["false_positives_per_line"])
    return {"false_positives_per_line": round(best["false_positives_per_line"], 3),
            "precision": best["precision"], "threshold": best["threshold"],
            "note": "oracle operating point read off this scan's curve (characterisation, not a frozen result)"}


def operating_threshold(curve, r):
    ok = [c for c in curve if c["recall"] is not None and c["recall"] >= r]
    return max(c["threshold"] for c in ok) if ok else None


# ---------------------------------------------------------------- arms
def production(sc: Scan, vol):
    p = Path(BASELINE_DETS.format(spec=sc.spec, scan=sc.scan))
    dets = json.loads(p.read_text()) if p.exists() else run_detector(vol, sc.s.grid, sc.sid)
    return dets


def envelope(sc: Scan, vol):
    return e1_detect(vol, sc.s.grid, sc.sid, T=E1_CURVE_T, **E1_FROZEN)


def r4(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, dict):
        return {k: r4(v) for k, v in x.items()}
    if isinstance(x, list):
        return [r4(v) for v in x]
    return x


# ---------------------------------------------------------------- filter accounting
def filter_accounting(props, sc: Scan, params: v2.V2Params) -> dict:
    """Proposals rejected by each filter, and by that filter alone, split by whether
    the proposal is target-consistent (in a target window and, where scoreable, depth)."""
    def consistent(p):
        for t, lines in sc.windows:
            if p["line"] in lines and abs(p["x"] - t["x"]) <= MATCH_RADIUS_MM:
                if not sc.depth_scoreable:
                    return True
                if abs(depth_mm(p["t_ns"], sc.cal["t0_ns"], sc.cal["v_m_per_ns"]) - t["z_top"]) <= MATCH_DEPTH_MM:
                    return True
        return False

    out = {f: {"rejected": 0, "rejected_target_consistent": 0, "sole_rejector": 0,
               "sole_rejector_target_consistent": 0} for f in v2.FILTERS}
    for p in props:
        verdict = v2.passes(p, params)
        failed = [f for f, ok in verdict.items() if not ok]
        c = consistent(p)
        for f in failed:
            out[f]["rejected"] += 1
            out[f]["rejected_target_consistent"] += c
            if len(failed) == 1:
                out[f]["sole_rejector"] += 1
                out[f]["sole_rejector_target_consistent"] += c
    return out


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("artifacts/bam/candidate_v2/results.json"))
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    val = json.loads(VAL.read_text())
    res = {"protocol": __doc__, "candidate_v2_module_doc": v2.__doc__, "tuning_grid": TUNING_GRID,
           "development": {}, "frozen": None, "test": {}, "control": {}, "ablations": {},
           "filter_accounting": {}}

    # ---- development: tune V2 on DEV only
    sc = Scan(*DEV, val)
    vol = sc.volume()
    rows = []
    cache = {}
    for W, T, ext in itertools.product(TUNING_GRID["background_window_traces"],
                                        TUNING_GRID["proposal_threshold"],
                                        TUNING_GRID["min_lateral_extent_mm"]):
        t0 = time.time()
        props = v2.propose(vol, sc.s.grid.x, sc.s.grid.y, sc.s.grid.z,
                           v2.V2Params(background_window_traces=W, proposal_threshold=T,
                                       min_lateral_extent_mm=ext))
        cache[(W, T, ext)] = props
        for smin, pmin in itertools.product(TUNING_GRID["shape_min"], TUNING_GRID["persistence_min"]):
            p = v2.V2Params(W, T, ext, smin, pmin)
            dets = v2.select(props, p)
            curve = pr_curve(dets, sc, "final_score")
            at = fp_at_recall(curve, TARGET_RECALL)
            rows.append({"background_window_traces": W, "proposal_threshold": T, "min_lateral_extent_mm": ext,
                         "shape_min": smin, "persistence_min": pmin, "n_detections": len(dets),
                         "max_recall": max((c["recall"] for c in curve), default=0.0),
                         "fp_per_line_at_80": at["false_positives_per_line"] if at else None})
        print("dev", W, T, ext, f"{time.time() - t0:.0f}s", flush=True)
    res["development"]["v2_grid"] = rows
    feasible = [r for r in rows if r["fp_per_line_at_80"] is not None]
    best = min(feasible, key=lambda r: (r["fp_per_line_at_80"], r["n_detections"]))
    frozen = v2.V2Params(best["background_window_traces"], best["proposal_threshold"],
                         best["min_lateral_extent_mm"], best["shape_min"], best["persistence_min"])
    dev_props = cache[(frozen.background_window_traces, frozen.proposal_threshold, frozen.min_lateral_extent_mm)]
    dev_dets = v2.select(dev_props, frozen)
    dev_curve = pr_curve(dev_dets, sc, "final_score", n=200)
    op = operating_threshold(dev_curve, TARGET_RECALL)
    res["frozen"] = {"params": {k: getattr(frozen, k) for k in ("background_window_traces", "proposal_threshold",
                                                                 "min_lateral_extent_mm", "shape_min",
                                                                 "persistence_min")},
                     "operating_threshold_final_score": op,
                     "selection": f"min FP/line at L-XZ recall >= {TARGET_RECALL} on development; ties by fewer detections",
                     "envelope": {**E1_FROZEN, "T": E1_OPERATING_T}, "production": {"threshold": 3.0, "min_cells": 3}}
    print("FROZEN", res["frozen"], flush=True)
    del cache
    ops = {"production": 3.0, "envelope": E1_OPERATING_T, "v2": op}
    keys = {"production": "z", "envelope": "z", "v2": "final_score"}

    def evaluate_scan(sc, vol, props=None):
        arms = {"production": production(sc, vol), "envelope": envelope(sc, vol)}
        props = props if props is not None else v2.propose(vol, sc.s.grid.x, sc.s.grid.y, sc.s.grid.z, frozen)
        arms["v2"] = v2.select(props, frozen)
        out = {"depth_scoreable": sc.depth_scoreable, "arms": {}}
        for name, dets in arms.items():
            curve = pr_curve(dets, sc, keys[name])
            out["arms"][name] = {
                "at_frozen_operating_point": score(dets, sc, keys[name], ops[name], full=True),
                "curve": curve,
                "fp_per_line_at_recall_0.8": fp_at_recall(curve, 0.8),
                "fp_per_line_at_recall_0.9": fp_at_recall(curve, 0.9),
                "max_recall": max((c["recall"] or 0.0 for c in curve), default=0.0),
            }
        return out, props

    res["development"]["evaluation"], _ = evaluate_scan(sc, vol, dev_props)
    res["filter_accounting"][f"{DEV[0]}_{DEV[1]} (development)"] = filter_accounting(dev_props, sc, frozen)
    del vol

    variants = {f"without_{f}": frozen.without(f) for f in v2.FILTERS}
    variants["without_all_filters"] = frozen.without(*v2.FILTERS)
    for group, items in (("test", TEST), ("control", CONTROL)):
        for spec, scan in items:
            sc = Scan(spec, scan, val)
            vol = sc.volume()
            t0 = time.time()
            res[group][f"{spec}_{scan}"], props = evaluate_scan(sc, vol)
            name = f"{spec}_{scan}"
            res["filter_accounting"][name] = filter_accounting(props, sc, frozen)
            abl = {}
            for vname, p in variants.items():
                dets = v2.select(props, p)
                abl[vname] = {**{k: v for k, v in score(dets, sc, "final_score", op).items()
                                 if k in ("recall", "precision", "false_positives_per_line", "n_detections")},
                              "fp_per_line_at_recall_0.8": (fp_at_recall(pr_curve(dets, sc, "final_score"), 0.8)
                                                            or {}).get("false_positives_per_line")}
            nc = v2.V2Params(**{**res["frozen"]["params"], "conditioning": False})
            nc_dets = v2.detect(vol, sc.s.grid.x, sc.s.grid.y, sc.s.grid.z, nc)
            abl["without_conditioning"] = {**{k: v for k, v in score(nc_dets, sc, "final_score", op).items()
                                             if k in ("recall", "precision", "false_positives_per_line",
                                                      "n_detections")},
                                          "fp_per_line_at_recall_0.8": (fp_at_recall(
                                              pr_curve(nc_dets, sc, "final_score"), 0.8) or {}).get(
                                              "false_positives_per_line")}
            abl["frozen_v2"] = {k: v for k, v in res[group][name]["arms"]["v2"]["at_frozen_operating_point"].items()
                                if k in ("recall", "precision", "false_positives_per_line", "n_detections")}
            abl["frozen_v2"]["fp_per_line_at_recall_0.8"] = (res[group][name]["arms"]["v2"]
                                                             ["fp_per_line_at_recall_0.8"] or {}).get(
                "false_positives_per_line")
            res["ablations"][name] = abl
            del vol
            a = res[group][name]["arms"]
            print(group, name, f"{time.time() - t0:.0f}s",
                  {k: {m: r4(a[k]["at_frozen_operating_point"][m]) for m in ("recall", "precision",
                                                                             "false_positives_per_line")}
                   for k in a}, flush=True)
    args.out.write_text(json.dumps(r4(res), indent=1))
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
