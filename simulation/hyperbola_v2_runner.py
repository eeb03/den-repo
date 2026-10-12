"""
Synthetic runner for the hyperbola V2 experiment (docs/hyperbola-v2-experiment.md).

Stages, in this order only:

    select-grouping  dev data only: A1 at 6.0 and A2 under each of the 8 §3
                     grouping configurations; applies the §3 rule.
    select-lambda    dev data only: A3 (canonical input, the chosen grouping)
                     under each lambda0; applies the §6.2 rule; writes the
                     freeze file (to be COMMITTED before evaluate).
    evaluate         corpus_s1_v2 eval split, frozen configuration only, every
                     arm, the §7 conditions. Refuses to run unless the freeze
                     file is committed and unmodified in git.
    report           aggregates evaluate output (§7 metrics, per family).

Dev data (§4.3): corpus_s0 (all splits) + corpus_s1_v2 split 'dev'. The
eval split is never loaded by the select stages (asserted).

    python -m simulation.hyperbola_v2_runner select-grouping --workers 6
    python -m simulation.hyperbola_v2_runner select-lambda --workers 6
    python -m simulation.hyperbola_v2_runner evaluate --workers 6
    python -m simulation.hyperbola_v2_runner report
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
import tracemalloc
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from benchmark.hyperbola_stack import estimate_time_zero
from benchmark.hyperbola_v2 import (
    A1_THRESHOLD, GROUPING_GRID, LAMBDA0_GRID, StackContext, calibrated_threshold, canonical_line,
    detections_at, group, null_peaks, stack_line,
)
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD
from simulation.background_benchmark import digitise, score_located
from simulation.detector_comparison import (
    BACKGROUNDS, PRIMARY_ARM, PRIMARY_CONDITION, SAMPLINGS, _errors, _group_recall, _locate, _rates,
    bootstrap, condition_line, detector_grid, target_attributes,
)
from simulation.interface import SyntheticLine, load_line
from simulation.scenario import CLUTTER_PREFIX

CORPORA = {"s0": Path("artifacts/simulation/corpus_s0"), "s1v2": Path("artifacts/simulation/corpus_s1_v2")}
OUT = Path("artifacts/simulation/hyperbola_v2")
FREEZE = Path("simulation/hyperbola_v2_freeze.json")
EVAL_CONDITIONS = (PRIMARY_CONDITION, "instrument_20spp|noise_4tu_p90", "native|noise_4tu_median")
FP_PER_SCAN_BUDGET = 1.0
PRECISION_FLOOR = 0.60
GROUPING_RECALL_SLACK = 0.02
GROUPING_HARD_SLACK = 0.05
BOOTSTRAP = {"resamples": 2000, "seed": 0}


def grouping_id(cfg: dict) -> str:
    k = "inf" if math.isinf(cfg["kappa"]) else f"{cfg['kappa']:g}"
    return f"d{cfg['delta_periods']:g}_k{k}_r{cfg['rho']:g}"


# --- data selection ---------------------------------------------------------------------

def scenes(split_sets: dict[str, set[str]]) -> list[tuple[str, str, dict]]:
    """[(corpus key, scene id, index entry)] for the requested splits per corpus."""
    out = []
    for key, splits in split_sets.items():
        meta = json.loads((CORPORA[key] / "index.json").read_text())["scenes"]
        for sid in sorted(meta):
            if meta[sid]["split"] in splits:
                out.append((key, sid, meta[sid]))
    return out


DEV = {"s0": {"train", "val", "test"}, "s1v2": {"dev"}}


def dev_scenes():
    sel = scenes(DEV)
    assert not any(k == "s1v2" and m["split"] == "eval" for k, _, m in sel)
    return sel


# --- scoring ----------------------------------------------------------------------------

def scored_view(line: SyntheticLine) -> SyntheticLine:
    """The line with clutter stones removed from the truth used for recall."""
    truth = {**line.truth, "targets": [t for t in line.truth["targets"]
                                       if not t["target_id"].startswith(CLUTTER_PREFIX)]}
    return SyntheticLine(**{**line.__dict__, "truth": truth})


def score_v2(line: SyntheticLine, located: list[dict]) -> dict:
    """score_located on scored targets, plus the §4.1 FP classes."""
    r = score_located(scored_view(line), located)
    f = line.truth["wavelet"]["centre_frequency_hz"]
    period, lam = 1 / f, line.soil_velocity_m_per_s / f
    stones = []
    for t in line.truth["targets"]:
        if t["target_id"].startswith(CLUTTER_PREFIX):
            ev = [np.array([np.nan if v is None else v for v in e["two_way_time_s"]], float)
                  for e in (t.get("predicted_events") or {"top": t["predicted"]}).values()]
            stones.append((t["geometry"]["centre_x_m"], float(np.nanmin(ev[0])) - period,
                           max(float(np.nanmin(e)) for e in ev) + period))
    layer = line.truth.get("layer")
    classes = list(r["detection_classes"])
    for i, (d, c) in enumerate(zip(located, classes)):
        if c not in ("early", "clutter"):
            continue
        if any(abs(d["x"] - x) <= lam and lo <= d["t"] <= hi for x, lo, hi in stones):
            classes[i] = "clutter_object"
        elif layer is not None and abs(d["t"] - layer["predicted_two_way_time_s"][d["trace"]]) <= period:
            classes[i] = "layer"
    unmatched = {}
    for c in classes:
        if c != "matched":
            unmatched[c] = unmatched.get(c, 0) + 1
    return {
        "n_det": r["n_detections"], "matched": sum(t["detected"] for t in r["targets"]),
        "fp_strict": r["fp_strict"], "fp_clutter": unmatched.get("early", 0) + unmatched.get("clutter", 0),
        "classes": unmatched,
        "t": [[t["detected"], t.get("lateral_error_wavelengths"), t.get("lateral_error_m"),
               t.get("depth_error_wavelengths"), t.get("depth_error_own_velocity_wavelengths"),
               t.get("velocity_error_fraction")] for t in r["targets"]],
    }


def _a1_located(line, z, v_hat, thr):
    return _locate(line, z, v_hat, thr)


def _grouped_located(line, ctx, dets, cfg):
    kept = group(dets, ctx, cfg)
    times = line.sample_times_s
    return [{"x": float(line.midpoint_x_m[d["trace"]]), "t": float(times[d["sample"]]), "trace": d["trace"],
             "abs_z": d["z"], "merged": d["merged"], **({"v_est": d["v"]} if np.isfinite(d["v"]) else {})}
            for d in kept]


def _scene_header(key, sid, meta, base):
    attrs = target_attributes(scored_view(digitise(base, SAMPLINGS["instrument_20spp"])))
    return {"uid": f"{key}:{sid}", "corpus": key, "sid": sid, "split": meta["split"],
            "family": meta.get("family", "corpus_s0"),
            "frequency_hz": meta["centre_frequency_hz"], "soil_eps": meta["soil_relative_permittivity"],
            "targets": [attrs[t["target_id"]] for t in scored_view(base).truth["targets"]]}


def job_grouping(args):
    key, sid, meta, cond = args
    base = load_line(CORPORA[key] / sid)
    out = {**_scene_header(key, sid, meta, base), "condition": cond, "res": {}}
    line = condition_line(base, cond)
    f = float(meta["centre_frequency_hz"])
    tz = estimate_time_zero(line.traces, line.dt_s, line.time_offset_s)
    bg = BACKGROUNDS[PRIMARY_ARM](line)
    z, v_hat, env = stack_line(bg, line.midpoint_x_m, line.dt_s, line.time_offset_s, tz, f)
    out["res"][f"A1@{A1_THRESHOLD}"] = score_v2(line, _a1_located(line, z, v_hat, A1_THRESHOLD))
    ctx = StackContext.build(bg, line.midpoint_x_m, line.dt_s, line.time_offset_s, tz, f, env)
    dets = detections_at(z, v_hat, A1_THRESHOLD)
    for cfg in GROUPING_GRID:
        out["res"][f"A2[{grouping_id(cfg)}]"] = score_v2(line, _grouped_located(line, ctx, dets, cfg))
    return out


def _a3(line, f, identity, grouping, lambdas, measure=False):
    """A3 on a synthetic line: canonical input, null peaks once, every lambda0."""
    cost = {}
    if measure:
        tracemalloc.start()
        c0, w0 = time.process_time(), time.perf_counter()
    can = canonical_line(line.traces, line.midpoint_x_m, line.dt_s, line.time_offset_s, f)
    tz = estimate_time_zero(can.traces, can.dt_s, can.time_offset_s)
    bg = can.traces - can.traces.mean(axis=0)
    z, v_hat, env = stack_line(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f)
    peaks = null_peaks(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f, identity, grouping)
    ctx = StackContext.build(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f, env)
    out = {}
    for lam0 in lambdas:
        thr = calibrated_threshold(peaks, lam0)
        kept = group(detections_at(z, v_hat, thr), ctx, grouping)
        located = [{"x": float(can.x_m[d["trace"]]), "t": float(can.time_offset_s + d["sample"] * can.dt_s),
                    "trace": can.original_trace(float(can.x_m[d["trace"]])), "abs_z": d["z"],
                    **({"v_est": d["v"]} if np.isfinite(d["v"]) else {})} for d in kept]
        out[lam0] = (thr, located)
    if measure:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        cost = {"cpu_s": time.process_time() - c0, "wall_s": time.perf_counter() - w0, "peak_bytes": peak}
    return out, peaks, cost


def job_lambda(args):
    key, sid, meta, cond, grouping = args
    base = load_line(CORPORA[key] / sid)
    out = {**_scene_header(key, sid, meta, base), "condition": cond, "res": {}, "thresholds": {}}
    line = condition_line(base, cond)
    a3, peaks, _ = _a3(line, float(meta["centre_frequency_hz"]), f"{key}:{sid}:{cond}", grouping, LAMBDA0_GRID)
    for lam0, (thr, located) in a3.items():
        out["res"][f"A3[{lam0:g}]"] = score_v2(line, located)
        out["thresholds"][f"{lam0:g}"] = thr
    out["n_null_peaks"] = len(peaks)
    return out


def job_evaluate(args):
    key, sid, meta, cond, freeze, measure = args
    base = load_line(CORPORA[key] / sid)
    out = {**_scene_header(key, sid, meta, base), "condition": cond, "res": {}, "cost": {}, "thresholds": {}}
    line = condition_line(base, cond)
    f = float(meta["centre_frequency_hz"])
    tz = estimate_time_zero(line.traces, line.dt_s, line.time_offset_s)
    bg = BACKGROUNDS[PRIMARY_ARM](line)

    def timed(name, fn):
        if measure:
            tracemalloc.start()
            c0, w0 = time.process_time(), time.perf_counter()
        r = fn()
        if measure:
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            out["cost"][name] = {"cpu_s": time.process_time() - c0, "wall_s": time.perf_counter() - w0,
                                 "peak_bytes": peak}
        return r

    def a0():
        z, _ = detector_grid("ring", {}, bg, line, tz, f)
        return _locate(line, z, None, DEFAULT_ANOMALY_THRESHOLD)
    out["res"]["A0"] = score_v2(line, timed("A0", a0))

    def a12():
        z, v_hat, env = stack_line(bg, line.midpoint_x_m, line.dt_s, line.time_offset_s, tz, f)
        a1 = _a1_located(line, z, v_hat, A1_THRESHOLD)
        ctx = StackContext.build(bg, line.midpoint_x_m, line.dt_s, line.time_offset_s, tz, f, env)
        return a1, _grouped_located(line, ctx, detections_at(z, v_hat, A1_THRESHOLD), freeze["grouping"])
    a1, a2 = timed("A1+A2", a12)
    out["res"]["A1"] = score_v2(line, a1)
    out["res"]["A2"] = score_v2(line, a2)
    a3, peaks, cost = _a3(line, f, f"{key}:{sid}:{cond}", freeze["grouping"], [freeze["lambda0"]], measure)
    thr, located = a3[freeze["lambda0"]]
    out["res"]["A3"] = score_v2(line, located)
    out["thresholds"]["A3"] = thr
    if measure:
        out["cost"]["A3"] = cost
    return out


# --- aggregation ------------------------------------------------------------------------

def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.open()]


def rates(rows: list[dict], arm: str, ci: bool = False) -> dict:
    rr = [{"sid": r["uid"], "res": r["res"], "attrs": r["targets"]} for r in rows]
    empty = {r["uid"] for r in rows if not r["targets"]}
    out = {**_rates(rr, arm, empty), **_errors(rr, arm)}
    if ci and rr:
        out["ci95"] = bootstrap(rr, arm, empty, **BOOTSTRAP)
    return out


def breakdowns(rows: list[dict], arm: str) -> dict:
    rr = [{"sid": r["uid"], "res": r["res"], "attrs": r["targets"]} for r in rows]
    attr = lambda r, i, k: r["attrs"][i][k]  # noqa: E731
    out = {f"by_{k}": _group_recall(rr, arm, attr, k) for k in ("label", "depth_bin", "strength", "overlapping")}
    for name, fn in (("family", lambda r: r["family"]),
                     ("frequency", lambda r: f"{r['frequency_hz'] / 1e9:g} GHz"),
                     ("soil", lambda r: "dry" if r["soil_eps"] < 8 else "moist" if r["soil_eps"] < 15 else "wet")):
        groups: dict[str, list] = {}
        for r in rows:
            groups.setdefault(fn(r), []).append(r)
        out[f"by_{name}"] = {g: rates(rs, arm) for g, rs in sorted(groups.items())}
    classes: dict[str, int] = {}
    for r in rows:
        for c, n in r["res"][arm].get("classes", {}).items():
            classes[c] = classes.get(c, 0) + n
    out["unmatched_classes"] = classes
    return out


def _run(job, args, path: Path, workers: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Pool(workers) as pool, path.open("w") as fh:
        for r in pool.imap(job, args, chunksize=1):
            fh.write(json.dumps(r) + "\n")
            fh.flush()


def select_grouping(workers: int) -> dict:
    sel = dev_scenes()
    path = OUT / "select_grouping.jsonl"
    _run(job_grouping, [(k, s, m, PRIMARY_CONDITION) for k, s, m in sel], path, workers)
    rows = _rows(path)
    hard = [r for r in rows if r["family"] in ("close_pair", "overlap")]
    a1 = rates(rows, f"A1@{A1_THRESHOLD}")
    a1_hard = rates(hard, f"A1@{A1_THRESHOLD}") if hard else None
    table, ok = {}, []
    for cfg in GROUPING_GRID:
        arm = f"A2[{grouping_id(cfg)}]"
        r = rates(rows, arm)
        rh = rates(hard, arm) if hard else None
        admissible = (r["recall"] >= a1["recall"] - GROUPING_RECALL_SLACK and
                      (rh is None or rh["recall"] >= a1_hard["recall"] - GROUPING_HARD_SLACK))
        table[arm] = {"config": cfg, "all": r, "close_pair_overlap": rh, "admissible": admissible}
        if admissible:
            ok.append(cfg)
    # ties -> less suppression: smaller delta, smaller kappa, larger rho
    pick = max(ok, key=lambda c: (round(table[f"A2[{grouping_id(c)}]"]["all"]["precision"] or 0, 12),
                                  -c["delta_periods"], -c["kappa"], c["rho"])) if ok else None
    result = {"rule": "§3", "dev_scenes": len(rows), "dev_close_pair_overlap_scenes": len(hard),
              "A1": a1, "A1_close_pair_overlap": a1_hard, "table": table, "chosen": pick}
    (OUT / "select_grouping.json").write_text(json.dumps(result, indent=1, default=str))
    return result


def select_lambda(workers: int) -> dict:
    g = json.loads((OUT / "select_grouping.json").read_text())["chosen"]
    if g is None:
        raise SystemExit("no admissible grouping configuration; §3 rule leaves A2/A3 ungrouped -- decide explicitly")
    g = {**g, "kappa": float(g["kappa"])}
    sel = dev_scenes()
    path = OUT / "select_lambda.jsonl"
    _run(job_lambda, [(k, s, m, PRIMARY_CONDITION, g) for k, s, m in sel], path, workers)
    rows = _rows(path)
    table = {f"{l:g}": rates(rows, f"A3[{l:g}]") for l in LAMBDA0_GRID}
    ok = [l for l in LAMBDA0_GRID if (table[f"{l:g}"]["precision"] or 0) >= PRECISION_FLOOR
          and table[f"{l:g}"]["fp_per_scan"] <= FP_PER_SCAN_BUDGET]
    if ok:
        pick = max(ok, key=lambda l: (table[f"{l:g}"]["recall"], -l))
        rule = "max dev recall s.t. precision >= 0.60 and FP/scan <= 1.0; ties -> smaller lambda0"
    else:
        pick = max(LAMBDA0_GRID, key=lambda l: ((table[f"{l:g}"]["precision"] or 0), -l))
        rule = "no lambda0 met both; highest dev precision; ties -> smaller lambda0"
    freeze = {"frozen_before_eval": True, "grouping": g, "grouping_id": grouping_id(g), "lambda0": pick,
              "rule": rule, "stack": "PR #12 frozen: cone 45, tolerance T/4; fast implementation",
              "A1_threshold": A1_THRESHOLD, "R_cal": 8, "z_floor": 3.0, "canonical_spp": 20,
              "dev_scenes": len(rows), "dev_table": table}
    (OUT / "select_lambda.json").write_text(json.dumps(freeze, indent=1))
    FREEZE.write_text(json.dumps({k: v for k, v in freeze.items() if k != "dev_table"}, indent=1))
    return freeze


def _freeze_committed() -> dict:
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(FREEZE)], capture_output=True)
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(FREEZE)])
    if tracked.returncode != 0 or dirty.returncode != 0:
        raise SystemExit(f"{FREEZE} must be committed (and unmodified) before evaluate")
    f = json.loads(FREEZE.read_text())
    f["grouping"]["kappa"] = float(f["grouping"]["kappa"])
    return f


def evaluate(workers: int, measure_cost: bool = False) -> Path:
    freeze = _freeze_committed()
    sel = scenes({"s1v2": {"eval"}})
    path = OUT / ("evaluate_cost.jsonl" if measure_cost else "evaluate.jsonl")
    conds = (PRIMARY_CONDITION,) if measure_cost else EVAL_CONDITIONS
    _run(job_evaluate, [(k, s, m, c, freeze, measure_cost) for c in conds for k, s, m in sel], path,
         1 if measure_cost else workers)
    return path


def report() -> dict:
    rows = _rows(OUT / "evaluate.jsonl")
    out = {"simulated": True, "claim_scope": "simulation only; not a field accuracy claim",
           "freeze": json.loads(FREEZE.read_text()), "conditions": {}}
    for cond in EVAL_CONDITIONS:
        rc = [r for r in rows if r["condition"] == cond]
        out["conditions"][cond] = {arm: {"all": rates(rc, arm, ci=True), **breakdowns(rc, arm)}
                                   for arm in ("A0", "A1", "A2", "A3")}
    cost_path = OUT / "evaluate_cost.jsonl"
    if cost_path.exists():
        cr = _rows(cost_path)
        out["cost"] = {name: {"median_cpu_s": float(np.median([r["cost"][name]["cpu_s"] for r in cr])),
                              "max_cpu_s": float(np.max([r["cost"][name]["cpu_s"] for r in cr])),
                              "median_peak_mb": float(np.median([r["cost"][name]["peak_bytes"] for r in cr])) / 1e6,
                              "max_peak_mb": float(np.max([r["cost"][name]["peak_bytes"] for r in cr])) / 1e6}
                       for name in ("A0", "A1+A2", "A3")}
    (OUT / "report.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("select-grouping", "select-lambda", "evaluate", "evaluate-cost", "report"))
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args(argv)
    if a.stage == "select-grouping":
        r = select_grouping(a.workers)
        print(json.dumps({"chosen": r["chosen"], "A1": r["A1"]}, default=str, indent=1))
    elif a.stage == "select-lambda":
        print(json.dumps(select_lambda(a.workers), indent=1, default=str))
    elif a.stage == "evaluate":
        print(evaluate(a.workers))
    elif a.stage == "evaluate-cost":
        print(evaluate(1, measure_cost=True))
    else:
        report()
        print(OUT / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
