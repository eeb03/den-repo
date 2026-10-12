"""
Three-detector x three-background experiment on the simulated corpus.

The protocol -- arms, search spaces, conditions, matching, metrics, the
selection rule and the decision gate -- is pre-registered in
docs/detector-saturation-experiment.md (committed before any run) and is
implemented here, not restated. Production code is unchanged; the two
candidate detectors live beside it.

STAGES, so the test split cannot leak into a choice:

    select    train + val only, primary condition, every configuration of
              every detector -> <out>/selection.json and the freeze file.
              Test scenes are never loaded (asserted).
    evaluate  frozen configurations only, every condition x arm, the splits
              asked for. Refuses to run without a freeze file.

    python -m simulation.detector_comparison select   --corpus C --out D --freeze simulation/detector_freeze.json
    python -m simulation.detector_comparison evaluate --corpus C --out D --freeze simulation/detector_freeze.json --splits test

Every number is a SIMULATION result on 2D TM data. None is field accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import tracemalloc
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from benchmark.detection import detect_line
from benchmark.hyperbola_stack import estimate_time_zero, hyperbola_stack
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS
from preprocessing.spatial_grid import TRACE_ANOMALY_WINDOWS, _local_anomaly_grid
from preprocessing.trace_processing import apply_gain, dewow
from simulation.background_benchmark import DEPTH_BINS, SOIL_CLASSES, _bin, digitise, score_located
from simulation.interface import SyntheticLine, load_line

# --- the pre-registered grid (docs/detector-saturation-experiment.md §3-§6) ---

#: simulation/noise_calibration.py over all 759 raw 4TU lines, 2026-10-12.
NOISE_RATIO_4TU = {"median": 2.9913636133038383e-4, "p90": 1.246990587060574e-3}
SAMPLINGS = {"instrument_20spp": 20, "native": None}
NOISES = {"noise_free": None, "noise_4tu_median": NOISE_RATIO_4TU["median"],
          "noise_4tu_p90": NOISE_RATIO_4TU["p90"]}
CONDITIONS = ("instrument_20spp|noise_free", "instrument_20spp|noise_4tu_median",
              "instrument_20spp|noise_4tu_p90", "native|noise_free", "native|noise_4tu_median")
PRIMARY_CONDITION = "instrument_20spp|noise_4tu_median"
PRIMARY_ARM = "mean_trace_subtraction"
THRESHOLDS = (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0, 30.0)
FP_PER_SCAN_BUDGET = 1.0
STRENGTH_BINS = ((-math.inf, 10.0, "weak"), (10.0, 25.0, "moderate"), (25.0, math.inf, "strong"))
BOOTSTRAP = {"resamples": 2000, "seed": 0}

CONFIGS = {
    "ring": [{}],
    "ring_widened": [{"trace": t, "depth": d}
                     for t in ((5, 9), (7, 13), (11, 21)) for d in ((5, 15), (9, 27))],
    "hyperbola_stack": [{"cone_half_angle_deg": a, "tolerance_periods": tol}
                        for a in (30.0, 45.0, 60.0) for tol in (0.0, 0.25)],
}

BACKGROUNDS = {
    "mean_trace_subtraction": lambda line: line.traces - line.traces.mean(axis=0),
    "no_background_removal": lambda line: line.traces,
    "target_free_reference_oracle": lambda line: line.traces - line.background,
}


def config_id(det: str, cfg: dict) -> str:
    if det == "ring":
        return "ring"
    if det == "ring_widened":
        return f"ring_widened[t{cfg['trace'][0]}-{cfg['trace'][1]},d{cfg['depth'][0]}-{cfg['depth'][1]}]"
    return f"hyperbola_stack[cone{cfg['cone_half_angle_deg']:g},tol{cfg['tolerance_periods']:g}]"


# --- inputs ------------------------------------------------------------------

def _filtered(traces: np.ndarray) -> np.ndarray:
    return np.array([apply_gain(dewow(t.tolist(), window=15), gain_type="linear", power=1.0)
                     for t in traces], dtype=float)


def detector_grid(det: str, cfg: dict, traces: np.ndarray, line: SyntheticLine,
                  time_zero_s: float, f_nominal_hz: float):
    """(z, v_hat or None). Inputs: the background-handled traces and
    acquisition facts only -- never truth."""
    if det == "ring":
        z, _ = _local_anomaly_grid(_filtered(traces).T, **TRACE_ANOMALY_WINDOWS)
        return z, None
    if det == "ring_widened":
        windows = {**TRACE_ANOMALY_WINDOWS,
                   "inner_window": (cfg["depth"][0], cfg["trace"][0]),
                   "outer_window": (cfg["depth"][1], cfg["trace"][1])}
        z, _ = _local_anomaly_grid(_filtered(traces).T, **windows)
        return z, None
    return hyperbola_stack(traces, line.midpoint_x_m, line.dt_s, line.time_offset_s,
                           time_zero_s, f_nominal_hz, **cfg)


def reference_amplitude(traces: np.ndarray) -> float:
    """noise_calibration's reference: per trace max |a| over the first
    quarter of the window; the median over traces."""
    return float(np.median(np.abs(traces[:, : traces.shape[1] // 4]).max(axis=1)))


def add_noise(line: SyntheticLine, ratio: float | None, salt: int) -> SyntheticLine:
    """White Gaussian noise on the traces only (never the twin), seeded from
    the scene id -- not Python's per-process salted hash()."""
    if ratio is None:
        return line
    seed = int.from_bytes(hashlib.sha256(line.scenario_id.encode()).digest()[:8], "big")
    rng = np.random.default_rng([seed, salt])
    sigma = ratio * reference_amplitude(line.traces)
    return SyntheticLine(**{**line.__dict__, "traces": line.traces + rng.normal(0.0, sigma, line.traces.shape)})


def condition_line(base: SyntheticLine, condition: str) -> SyntheticLine:
    sampling, noise = condition.split("|")
    line = digitise(base, SAMPLINGS[sampling])
    return add_noise(line, NOISES[noise], list(NOISES).index(noise))


# --- per-target attributes (scoring only) ---------------------------------------

def _windows(line: SyntheticLine):
    f = line.truth["wavelet"]["centre_frequency_hz"]
    lam = line.soil_velocity_m_per_s / f
    out = []
    for tg in line.truth["targets"]:
        events = tg.get("predicted_events") or {"top": tg["predicted"]}
        apex = [min(t for t in e["two_way_time_s"] if t is not None) for e in events.values()]
        top = min(t for t in events["top"]["two_way_time_s"] if t is not None)
        out.append((tg, tg["geometry"]["centre_x_m"], top - 1 / f, max(apex) + 1 / f, lam))
    return out


def target_attributes(line: SyntheticLine) -> dict[str, dict]:
    """Strength (dB SNR at the 4TU median noise, from the noise-free
    scattered field in the target's match region) and overlap, per target."""
    scattered = np.abs(line.traces - line.background)
    ref = reference_amplitude(line.traces)
    times = line.sample_times_s
    wins = _windows(line)
    out = {}
    for tg, x, lo, hi, lam in wins:
        cols = np.abs(line.midpoint_x_m - x) <= lam
        rows = (times >= lo) & (times <= hi)
        a = float(scattered[np.ix_(cols, rows)].max()) if cols.any() and rows.any() else 0.0
        strength_db = 20 * math.log10(a / ref) if a > 0 and ref > 0 else -math.inf
        snr = strength_db - 20 * math.log10(NOISE_RATIO_4TU["median"])
        overlapping = any(o is not tg and abs(ox - x) <= lam and olo <= hi and lo <= ohi
                          for o, ox, olo, ohi, _ in wins)
        depth_wl = tg["geometry"]["depth_to_centre_m"] / lam
        out[tg["target_id"]] = {"label": tg["label"], "depth_bin": _bin(depth_wl, DEPTH_BINS),
                                "snr_db_4tu_median": snr, "strength": _bin(snr, STRENGTH_BINS),
                                "overlapping": overlapping}
    return out


# --- scoring one scene ---------------------------------------------------------

def _locate(line, z, v_hat, threshold):
    dets = detect_line(line.traces, line.scenario_id, 0, threshold=threshold,
                       min_cells=DEFAULT_MIN_CELLS, estimator=lambda _t: z)
    times = line.sample_times_s
    return [{"x": float(line.midpoint_x_m[d.peak_trace]), "t": float(times[d.peak_sample]),
             "trace": d.peak_trace, "abs_z": abs(d.peak_z),
             **({"v_est": float(v_hat[d.peak_sample, d.peak_trace])}
                if v_hat is not None and np.isfinite(v_hat[d.peak_sample, d.peak_trace]) else {})}
            for d in dets]


def _compact(score: dict) -> dict:
    u = score["unmatched"]
    return {
        "n_det": score["n_detections"],
        "matched": sum(t["detected"] for t in score["targets"]),
        "fp_strict": score["fp_strict"], "fp_clutter": score["fp_clutter"],
        "dup": u.get("duplicate", 0), "limb": u.get("limb", 0),
        "early": u.get("early", 0), "clutter": u.get("clutter", 0),
        # per target, truth order: detected, lateral (lambda, m), depth (oracle v,
        # lambda), depth (own v, lambda), velocity error fraction; null if missed
        "t": [[t["detected"], t.get("lateral_error_wavelengths"), t.get("lateral_error_m"),
               t.get("depth_error_wavelengths"), t.get("depth_error_own_velocity_wavelengths"),
               t.get("velocity_error_fraction")] for t in score["targets"]],
    }


def score_scene(args: tuple) -> dict:
    """args = (scene_dir, meta_entry, jobs, measure_cost); jobs are
    (condition, detector, config) triples, each run under every arm."""
    scene_dir, meta, jobs, measure_cost = args
    base = load_line(Path(scene_dir))
    f_nominal = float(meta["centre_frequency_hz"])   # acquisition metadata
    attrs = target_attributes(digitise(base, SAMPLINGS["instrument_20spp"]))
    out = {"scenario_id": base.scenario_id, "targets": [attrs[t["target_id"]] for t in base.truth["targets"]],
           "results": {}, "cost": {}}
    lines = {}
    for cond, det, cfg in jobs:
        if cond not in lines:
            line = condition_line(base, cond)
            lines[cond] = (line, estimate_time_zero(line.traces, line.dt_s, line.time_offset_s))
        line, tz = lines[cond]
        cid = config_id(det, cfg)
        for arm, bg in BACKGROUNDS.items():
            traces = bg(line)
            if measure_cost:
                tracemalloc.start()
                c0 = time.process_time()
            z, v_hat = detector_grid(det, cfg, traces, line, tz, f_nominal)
            if measure_cost:
                cpu = time.process_time() - c0
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                out["cost"][f"{cond}|{cid}|{arm}"] = {"cpu_s": cpu, "peak_bytes": peak}
            out["results"][f"{cond}|{cid}|{arm}"] = {
                str(thr): _compact(score_located(line, _locate(line, z, v_hat, thr))) for thr in THRESHOLDS}
    return out


# --- aggregation -----------------------------------------------------------------

def _rates(rows: list[dict], thr: str, empty: set[str]) -> dict:
    n_targets = sum(len(r["res"][thr]["t"]) for r in rows)
    matched = sum(r["res"][thr]["matched"] for r in rows)
    n_det = sum(r["res"][thr]["n_det"] for r in rows)
    empties = [r for r in rows if r["sid"] in empty]
    return {
        "scenes": len(rows), "targets": n_targets, "matched": matched, "detections": n_det,
        "recall": matched / n_targets if n_targets else None,
        "precision": matched / n_det if n_det else None,
        "fp_per_scan": sum(r["res"][thr]["fp_strict"] for r in rows) / len(rows) if rows else None,
        "fp_clutter_per_scan": sum(r["res"][thr]["fp_clutter"] for r in rows) / len(rows) if rows else None,
        "empty_scenes": len(empties),
        "fp_per_empty_scene": (sum(r["res"][thr]["n_det"] for r in empties) / len(empties)) if empties else None,
    }


def _errors(rows: list[dict], thr: str, keep=lambda sid, i: True) -> dict:
    cols = {"lateral_wl": 1, "lateral_m": 2, "depth_oracle_v_wl": 3, "depth_own_v_wl": 4, "velocity_frac": 5}
    vals = defaultdict(list)
    signed = []
    for r in rows:
        for i, t in enumerate(r["res"][thr]["t"]):
            if not t[0] or not keep(r["sid"], i):
                continue  # missed targets have undefined error: excluded, never zero
            for k, c in cols.items():
                if t[c] is not None:
                    vals[k].append(abs(t[c]))
            if t[3] is not None:
                signed.append(t[3])
    out = {f"median_abs_{k}": (float(np.median(v)) if v else None) for k, v in
           ((k, vals.get(k, [])) for k in cols)}
    out["median_signed_depth_oracle_v_wl"] = float(np.median(signed)) if signed else None
    out["n_matched_with_errors"] = len(vals.get("lateral_wl", []))
    return out


def bootstrap(rows: list[dict], thr: str, empty: set[str], resamples: int, seed: int) -> dict:
    """Scene-level percentile bootstrap, 95%."""
    rng = np.random.default_rng(seed)
    n = len(rows)
    m = np.array([r["res"][thr]["matched"] for r in rows], float)
    nt = np.array([len(r["res"][thr]["t"]) for r in rows], float)
    nd = np.array([r["res"][thr]["n_det"] for r in rows], float)
    fp = np.array([r["res"][thr]["fp_strict"] for r in rows], float)
    is_empty = np.array([r["sid"] in empty for r in rows])
    stats = defaultdict(list)
    for _ in range(resamples):
        idx = rng.integers(0, n, n)
        if nt[idx].sum():
            stats["recall"].append(m[idx].sum() / nt[idx].sum())
        if nd[idx].sum():
            stats["precision"].append(m[idx].sum() / nd[idx].sum())
        stats["fp_per_scan"].append(fp[idx].mean())
        e = idx[is_empty[idx]]
        if e.size:
            stats["fp_per_empty_scene"].append(nd[e].mean())
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in stats.items()}


def _group_recall(rows, thr, attr_of, key) -> dict:
    groups = defaultdict(lambda: [0, 0])
    for r in rows:
        for i, t in enumerate(r["res"][thr]["t"]):
            g = attr_of(r, i, key)
            groups[g][0] += bool(t[0])
            groups[g][1] += 1
    return {str(g): {"targets": n, "matched": h, "recall": h / n if n else None}
            for g, (h, n) in sorted(groups.items(), key=lambda kv: str(kv[0]))}


def breakdown(rows, thr, meta, empty) -> dict:
    def scene_cat(sid, key):
        e = meta[sid]
        return {"frequency": f"{e['centre_frequency_hz'] / 1e9:g} GHz",
                "soil": _bin(e["soil_relative_permittivity"], SOIL_CLASSES)}[key]

    out = {}
    for key in ("frequency", "soil"):
        groups = defaultdict(list)
        for r in rows:
            groups[scene_cat(r["sid"], key)].append(r)
        out[f"by_{key}"] = {g: {**_rates(rs, thr, empty), **_errors(rs, thr)} for g, rs in sorted(groups.items())}
    attr_of = lambda r, i, key: r["attrs"][i][key]  # noqa: E731
    for key in ("label", "depth_bin", "strength", "overlapping"):
        out[f"by_{key}"] = _group_recall(rows, thr, attr_of, key)
    return out


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open() as fh:
        for line in fh:
            s = json.loads(line)
            for key, res in s["results"].items():
                rows.append({"sid": s["scenario_id"], "key": key, "res": res, "attrs": s["targets"],
                             "cost": s["cost"].get(key)})
    return rows


def _by_key(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["key"]].append(r)
    return out


# --- stages -------------------------------------------------------------------

def _run(corpus: Path, meta: dict, sids: list[str], jobs: list, out_path: Path, workers: int,
         measure_cost: bool) -> None:
    args = [(str(corpus / sid), meta[sid], jobs, measure_cost) for sid in sids]
    with Pool(workers) as pool, out_path.open("w") as fh:
        for result in pool.imap(score_scene, args, chunksize=1):
            fh.write(json.dumps(result) + "\n")
            fh.flush()


def select(corpus: Path, out: Path, freeze_path: Path, workers: int) -> dict:
    index = json.loads((corpus / "index.json").read_text())
    meta = index["scenes"]
    sids = sorted(s for s, e in meta.items() if e["split"] in ("train", "val"))
    assert not any(meta[s]["split"] == "test" for s in sids)
    jobs = [(PRIMARY_CONDITION, det, cfg) for det, cfgs in CONFIGS.items() for cfg in cfgs]
    raw = out / "selection_scenes.jsonl"
    _run(corpus, meta, sids, jobs, raw, workers, measure_cost=False)

    empty = {s for s in sids if meta[s]["n_targets"] == 0}
    rows = [r for r in load_rows(raw) if r["key"].endswith("|" + PRIMARY_ARM)]
    by_key = _by_key(rows)
    table, frozen = {}, {}
    for det, cfgs in CONFIGS.items():
        cands = []
        for order, cfg in enumerate(cfgs):
            key = f"{PRIMARY_CONDITION}|{config_id(det, cfg)}|{PRIMARY_ARM}"
            for thr in THRESHOLDS:
                r_all = _rates(by_key[key], str(thr), empty)
                r_val = _rates([r for r in by_key[key] if meta[r["sid"]]["split"] == "val"], str(thr), empty)
                r_tr = _rates([r for r in by_key[key] if meta[r["sid"]]["split"] == "train"], str(thr), empty)
                table[f"{config_id(det, cfg)}@{thr}"] = {"train_val": r_all, "train": r_tr, "val": r_val}
                if r_all["fp_per_scan"] <= FP_PER_SCAN_BUDGET:
                    cands.append((r_all["recall"] or 0.0, thr, -order, cfg))
        if cands:
            recall, thr, neg_order, cfg = max(cands, key=lambda c: (c[0], c[1], c[2]))
            frozen[det] = {"config": cfg, "config_id": config_id(det, cfg), "threshold": thr,
                           "train_val_recall": recall}
        else:
            frozen[det] = {"config": cfgs[0], "config_id": config_id(det, cfgs[0]), "threshold": None,
                           "note": f"no configuration met fp_per_scan <= {FP_PER_SCAN_BUDGET} on train+val"}
    frozen["ring_production_threshold"] = {"config": {}, "config_id": "ring", "threshold": DEFAULT_ANOMALY_THRESHOLD}
    freeze = {
        "frozen_before_test": True,
        "rule": f"max train+val recall with fp_per_scan <= {FP_PER_SCAN_BUDGET}; ties -> higher threshold, "
                "then the configuration listed first",
        "primary_condition": PRIMARY_CONDITION, "primary_arm": PRIMARY_ARM,
        "selection_scenes": len(sids), "detectors": frozen,
    }
    (out / "selection.json").write_text(json.dumps({"freeze": freeze, "table": table}, indent=1))
    freeze_path.write_text(json.dumps(freeze, indent=2) + "\n")
    return freeze


def frozen_jobs(freeze: dict) -> list:
    jobs = []
    for name, d in freeze["detectors"].items():
        if name == "ring_production_threshold":
            continue
        for cond in CONDITIONS:
            jobs.append((cond, name, d["config"]))
    return jobs


def evaluate(corpus: Path, out: Path, freeze_path: Path, splits: list[str], workers: int) -> Path:
    freeze = json.loads(freeze_path.read_text())
    if not freeze.get("frozen_before_test"):
        raise SystemExit("refusing to evaluate without a freeze file")
    index = json.loads((corpus / "index.json").read_text())
    meta = index["scenes"]
    sids = sorted(s for s, e in meta.items() if e["split"] in splits)
    raw = out / f"evaluate_{'_'.join(splits)}_scenes.jsonl"
    _run(corpus, meta, sids, frozen_jobs(freeze), raw, workers, measure_cost=True)
    return raw


def report(corpus: Path, raw_files: list[Path], freeze_path: Path) -> dict:
    """Aggregate evaluate outputs: per split, every condition x detector x arm:
    rates at the frozen threshold (and ring at 3.0), bootstrap CIs, error
    medians, breakdowns, the full threshold curve, and cost."""
    freeze = json.loads(freeze_path.read_text())
    meta = json.loads((corpus / "index.json").read_text())["scenes"]
    rows = [r for p in raw_files for r in load_rows(p)]
    empty = {s for s, e in meta.items() if e["n_targets"] == 0}
    by_key = _by_key(rows)
    out = {"simulated": True, "claim_scope": "simulation only; not a field accuracy claim",
           "freeze": freeze, "results": {}}
    for key, krows in sorted(by_key.items()):
        cond, cid, arm = key.split("|")[0] + "|" + key.split("|")[1], key.split("|")[2], key.split("|")[3]
        det = cid.split("[")[0]
        ops = {"frozen": freeze["detectors"][det]["threshold"]}
        if det == "ring":
            ops["production_3.0"] = DEFAULT_ANOMALY_THRESHOLD
        entry = {}
        for split in ("train", "val", "test"):
            srows = [r for r in krows if meta[r["sid"]]["split"] == split]
            if not srows:
                continue
            se = {"curve": {str(t): _rates(srows, str(t), empty) for t in THRESHOLDS}}
            for name, thr in ops.items():
                if thr is None:
                    se[name] = None
                    continue
                se[name] = {**_rates(srows, str(thr), empty), **_errors(srows, str(thr)),
                            "ci95": bootstrap(srows, str(thr), empty, **BOOTSTRAP),
                            **breakdown(srows, str(thr), meta, empty), "threshold": thr}
            costs = [r["cost"] for r in srows if r["cost"]]
            if costs:
                se["cost"] = {"median_cpu_s_per_scene": float(np.median([c["cpu_s"] for c in costs])),
                              "max_cpu_s_per_scene": float(np.max([c["cpu_s"] for c in costs])),
                              "median_peak_mb": float(np.median([c["peak_bytes"] for c in costs]) / 1e6),
                              "max_peak_mb": float(np.max([c["peak_bytes"] for c in costs]) / 1e6)}
            entry[split] = se
        out["results"][f"{cond}|{det}|{arm}"] = entry
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("stage", choices=("select", "evaluate", "report"))
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--freeze", type=Path, default=Path("simulation/detector_freeze.json"))
    p.add_argument("--splits", default="test")
    p.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage == "select":
        print(json.dumps(select(args.corpus, args.out, args.freeze, args.workers), indent=2))
    elif args.stage == "evaluate":
        print(evaluate(args.corpus, args.out, args.freeze, args.splits.split(","), args.workers))
    else:
        raws = sorted(args.out.glob("evaluate_*_scenes.jsonl"))
        rep = report(args.corpus, raws, args.freeze)
        (args.out / "report.json").write_text(json.dumps(rep, indent=1))
        print(args.out / "report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
