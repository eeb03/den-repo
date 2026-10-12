"""
Real data for the hyperbola V2 experiment (docs/hyperbola-v2-experiment.md §6, §8).

    diagnose   §6 calibration diagnosis (no choice depends on it): sampling,
               spacing, noise floor, direct-wave duration, dynamic range, and the
               ORIGINAL stack's null component-peak z under 8 trace permutations
               per line, for corpus_s0, BAM dev, INGV and 4TU.
    bam        A0-A3 on every BAM scan (PR #12 protocol and scorer; nothing tuned).
    ingv|4tu   A0-A3 candidate counts per line with a 99-draw trace-permutation
               null (p = (1 + #null >= obs) / 100); 30-min-per-arm fallback to
               null mean +- sd with no p-value.

bam / ingv / 4tu read the COMMITTED freeze (simulation/hyperbola_v2_freeze.json).

    python -m scripts.hyperbola_v2_realdata diagnose --workers 2
    python -m scripts.hyperbola_v2_realdata bam --workers 6
    python -m scripts.hyperbola_v2_realdata ingv --workers 6
    python -m scripts.hyperbola_v2_realdata 4tu --workers 6
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import tracemalloc
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.signal import hilbert

from benchmark.hyperbola_stack import estimate_time_zero
from benchmark.hyperbola_v2 import (
    A1_THRESHOLD, R_CAL, StackContext, components, detect_v2, detections_at, group, line_seed, stack_line,
)
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS
from preprocessing.spatial_grid import TRACE_ANOMALY_WINDOWS, _local_anomaly_grid
from simulation.detector_comparison import _filtered

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("artifacts/realdata/hyperbola_v2")
FREEZE = Path("simulation/hyperbola_v2_freeze.json")
N_NULL = 99
NULL_BUDGET_S = 30 * 60
ARMS = ("A0", "A1", "A2", "A3")


def _freeze() -> dict:
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(FREEZE)], capture_output=True)
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(FREEZE)])
    if tracked.returncode or dirty.returncode:
        raise SystemExit(f"{FREEZE} must be committed before any real-data detector run")
    f = json.loads(FREEZE.read_text())
    f["grouping"]["kappa"] = float(f["grouping"]["kappa"])
    return f


# --- the four arms on one real line -------------------------------------------------------

def run_arms(raw: np.ndarray, x_m: np.ndarray, dt: float, toff: float, f: float, identity: str,
             freeze: dict, arms=ARMS) -> dict:
    """{arm: (detections [{sample-time t (s), x (m), z}], cpu s, peak bytes)}."""
    out = {}
    bg = raw - raw.mean(axis=0)
    tz = estimate_time_zero(raw, dt, toff)

    def timed(fn):
        tracemalloc.start()
        c0 = time.process_time()
        r = fn()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return r, time.process_time() - c0, peak

    if "A0" in arms:
        def a0():
            z, _ = _local_anomaly_grid(_filtered(bg).T, **TRACE_ANOMALY_WINDOWS)
            return [{"t": toff + d["sample"] * dt, "x": float(x_m[d["trace"]]), "z": d["z"]}
                    for d in components(z, DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS)]
        out["A0"] = timed(a0)
    if "A1" in arms or "A2" in arms:
        def a12():
            z, v_hat, env = stack_line(bg, x_m, dt, toff, tz, f)
            dets = detections_at(z, v_hat, A1_THRESHOLD)
            ctx = StackContext.build(bg, x_m, dt, toff, tz, f, env)
            kept = group(dets, ctx, freeze["grouping"])
            loc = lambda d: {"t": toff + d["sample"] * dt, "x": float(x_m[d["trace"]]), "z": d["z"]}  # noqa: E731
            return [loc(d) for d in dets], [loc(d) for d in kept]
        (a1, a2), cpu, peak = timed(a12)
        out["A1"] = (a1, cpu, peak)
        out["A2"] = (a2, cpu, peak)
    if "A3" in arms:
        def a3():
            r = detect_v2(raw, x_m, dt, toff, f, identity, freeze["grouping"], freeze["lambda0"])
            return [{"t": d["t"], "x": d["x"], "z": d["abs_z"]} for d in r["detections"]], r["threshold"]
        (dets, thr), cpu, peak = timed(a3)
        out["A3"] = (dets, cpu, peak)
        out["A3_threshold"] = thr
    return out


# --- §6 diagnosis --------------------------------------------------------------------------

def _diag_line(args):
    corpus, identity, raw, x, dt, toff, f = args
    raw = np.asarray(raw, float)
    tz = estimate_time_zero(raw, dt, toff)
    env_raw = np.abs(hilbert(np.median(raw, axis=0)))
    half = env_raw >= env_raw.max() / 2
    dw = np.nonzero(half)[0]
    n_tr, n_s = raw.shape
    # simulation.noise_calibration.line_ratios, on the array (median over traces)
    if n_tr >= 3:
        ref_t = np.abs(raw[:, : n_s // 4]).max(axis=1)[1:]
        noise_t = np.diff(raw[:, int(0.9 * n_s):], axis=0).std(axis=1) / np.sqrt(2)
        ok = ref_t > 0
        noise_ratio = float(np.median(noise_t[ok] / ref_t[ok])) if ok.any() else None
    else:
        noise_ratio = None
    bg = raw - raw.mean(axis=0)
    filt = _filtered(bg)
    rng = np.random.default_rng(line_seed("diag:" + identity))
    null = []
    for _ in range(R_CAL):
        p = bg[rng.permutation(n_tr)]
        z, v_hat, _ = stack_line(p, x, dt, toff, tz, f)
        null.extend(d["z"] for d in components(z, 3.0))
    z, v_hat, _ = stack_line(bg, x, dt, toff, tz, f)
    obs = [d["z"] for d in components(z, 3.0)]
    step = float(np.median(np.abs(np.diff(x)))) if x.size > 1 else float("nan")
    return {"corpus": corpus, "line": identity, "traces": n_tr, "samples": n_s,
            "samples_per_period": 1 / (f * dt), "traces_per_wavelength_eps9": (3e8 / 3 / f) / step,
            "noise_ratio": noise_ratio,
            "direct_wave_half_power_periods": (dw[-1] - dw[0] + 1) * dt * f if dw.size else None,
            "dynamic_range_db_after_gain": float(20 * np.log10(np.abs(filt).max() / (np.median(np.abs(filt)) + 1e-30))),
            "null_peaks_per_line": len(null) / R_CAL,
            "null_peak_z_p50": float(np.median(null)) if null else None,
            "null_peak_z_p90": float(np.percentile(null, 90)) if null else None,
            "null_peak_z_max": float(max(null)) if null else None,
            "null_components_above_6_per_line": sum(z_ > A1_THRESHOLD for z_ in null) / R_CAL,
            "observed_components_above_6": sum(z_ > A1_THRESHOLD for z_ in obs)}


def _bam_lines(spec, scan, every=1):
    from benchmark.bam_ingest import line_traces, load_scan, load_volume
    s = load_scan(spec, f"{spec}_3D_Dataset_{scan}")
    vol = load_volume(s)
    g = s.grid
    dt, toff = (g.z[1] - g.z[0]) * 1e-9, g.z[0] * 1e-9
    x = np.asarray(g.x, float) / 1000.0
    f = 1.5e9 if scan.startswith("1_5") else 2.6e9
    for y in range(0, len(g.y), every):
        yield f"bam:{spec}_{scan}:L{y}", line_traces(vol, y).astype(float), x, dt, toff, f


def _real_lines(corpus):
    from scripts.real_data_detector_saturation import FOURTU_NOMINAL_HZ, dominant_frequency, files_for, read_line
    for path in files_for(corpus):
        tr, dt, x, _ = read_line(Path(path))
        f = FOURTU_NOMINAL_HZ if corpus == "4tu" else dominant_frequency(tr, dt)
        yield f"{corpus}:{path}", tr, x, dt, 0.0, f


def diagnose(workers: int) -> dict:
    from simulation.detector_comparison import PRIMARY_CONDITION, condition_line
    from simulation.interface import load_line
    jobs = []
    corpus = Path("artifacts/simulation/corpus_s0")
    meta = json.loads((corpus / "index.json").read_text())["scenes"]
    for cond in (PRIMARY_CONDITION, "native|noise_4tu_median"):
        for sid in sorted(meta)[::5]:                        # 60 scenes per condition
            line = condition_line(load_line(corpus / sid), cond)
            jobs.append((f"corpus_s0 {cond}", sid, line.traces, line.midpoint_x_m, line.dt_s,
                         line.time_offset_s, float(meta[sid]["centre_frequency_hz"])))
    for ident, tr, x, dt, toff, f in _bam_lines("Pk266", "1_5_GHz_Rot00", every=8):
        jobs.append(("BAM dev Pk266 1.5", ident, tr, x, dt, toff, f))
    for c in ("ingv", "4tu"):
        for ident, tr, x, dt, toff, f in _real_lines(c):
            if tr.shape[0] > 3000:
                continue                                      # diagnosis only; long lines are timed in §8
            jobs.append((c.upper(), ident, tr, x, dt, toff, f))
    with Pool(workers) as pool:
        rows = list(pool.imap(_diag_line, jobs, chunksize=1))
    summary = {}
    for c in sorted({r["corpus"] for r in rows}):
        rs = [r for r in rows if r["corpus"] == c]
        summary[c] = {k: (float(np.median([r[k] for r in rs if r[k] is not None]))
                          if any(r[k] is not None for r in rs) else None)
                      for k in rs[0] if k not in ("corpus", "line")}
        summary[c]["lines"] = len(rs)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "diagnose.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    return summary


# --- C1 / C2 cost (run alone: one process, nothing else on the machine) ---------------------

def _measure(fn):
    tracemalloc.start()
    c0, w0 = time.process_time(), time.perf_counter()
    r = fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return r, time.process_time() - c0, time.perf_counter() - w0, peak


def cost() -> dict:
    """C1: original vs fast stack on the 41 PR #12 BAM dev lines, and V2's total
    (with calibration) per line. C2: peak memory on the largest 4TU subset line
    and on 4x the largest synthetic line. Single process."""
    from benchmark.hyperbola_stack import hyperbola_stack
    from benchmark.hyperbola_stack_fast import hyperbola_stack_fast
    from scripts.bam_detector_saturation import N_LINES
    freeze = _freeze()
    rows = []
    lines = list(_bam_lines("Pk266", "1_5_GHz_Rot00"))
    pick = [int(round(i)) for i in np.linspace(0, len(lines) - 1, N_LINES)]
    for k in pick:
        ident, raw, x, dt, toff, f = lines[k]
        bg = raw - raw.mean(axis=0)
        tz = estimate_time_zero(raw, dt, toff)
        _, c_orig, w_orig, m_orig = _measure(lambda: hyperbola_stack(bg, x, dt, toff, tz, f, 45, 0.25))
        _, c_fast, w_fast, m_fast = _measure(lambda: hyperbola_stack_fast(bg, x, dt, toff, tz, f, 45, 0.25))
        _, c_v2, w_v2, m_v2 = _measure(lambda: detect_v2(raw, x, dt, toff, f, ident, freeze["grouping"],
                                                          freeze["lambda0"]))
        rows.append({"line": ident, "orig_cpu_s": c_orig, "fast_cpu_s": c_fast, "v2_total_cpu_s": c_v2,
                     "orig_wall_s": w_orig, "fast_wall_s": w_fast, "v2_total_wall_s": w_v2,
                     "orig_peak_mb": m_orig / 1e6, "fast_peak_mb": m_fast / 1e6, "v2_peak_mb": m_v2 / 1e6})
        print(json.dumps(rows[-1]), flush=True)
    med = lambda k: float(np.median([r[k] for r in rows]))  # noqa: E731
    out = {"bam_dev_41_lines": {k: med(k) for k in rows[0] if k != "line"},
           "speedup_median_cpu": float(np.median([r["orig_cpu_s"] / r["fast_cpu_s"] for r in rows])),
           "rows": rows}
    # C2: the largest 4TU subset line, and 4x the largest synthetic line
    from scripts.real_data_detector_saturation import FOURTU_NOMINAL_HZ, files_for, read_line
    big = max(files_for("4tu"), key=lambda p: Path(p).stat().st_size)
    tr, dt, x, _ = read_line(Path(big))
    _, c, w, m = _measure(lambda: detect_v2(tr, x, dt, 0.0, FOURTU_NOMINAL_HZ, "cost:" + big,
                                            freeze["grouping"], freeze["lambda0"]))
    out["largest_4tu_line"] = {"path": big, "traces": int(tr.shape[0]), "v2_cpu_s": c, "v2_wall_s": w,
                               "v2_peak_mb": m / 1e6}
    from simulation.interface import load_line
    corpus = Path("artifacts/simulation/corpus_s0")
    meta = json.loads((corpus / "index.json").read_text())["scenes"]
    sid = max(meta, key=lambda s: meta[s]["n_traces"])
    line = load_line(corpus / sid)
    tr4 = np.tile(line.traces, (4, 1))
    x4 = line.midpoint_x_m[0] + np.arange(tr4.shape[0]) * float(np.median(np.diff(line.midpoint_x_m)))
    f = float(meta[sid]["centre_frequency_hz"])
    _, c, w, m = _measure(lambda: detect_v2(tr4, x4, line.dt_s, line.time_offset_s, f, "cost:4x" + sid,
                                            freeze["grouping"], freeze["lambda0"]))
    out["synthetic_4x_largest"] = {"scene": sid, "traces": int(tr4.shape[0]), "v2_cpu_s": c, "v2_wall_s": w,
                                   "v2_peak_mb": m / 1e6}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cost.json").write_text(json.dumps(out, indent=1))
    return {k: v for k, v in out.items() if k != "rows"}


# --- BAM -----------------------------------------------------------------------------------

def _bam_job(args):
    ident, raw, x, dt, toff, f, freeze, y = args
    r = run_arms(raw, x, dt, toff, f, ident, freeze)
    out = {"line": y, "A3_threshold": r.pop("A3_threshold")}
    for arm, (dets, cpu, peak) in r.items():
        out[arm] = {"dets": [{"line": y, "x": d["x"] * 1000.0, "t_ns": d["t"] * 1e9, "z": d["z"]} for d in dets],
                    "cpu_s": cpu, "peak_bytes": peak}
    return out


def bam(workers: int) -> dict:
    from scripts.bam_detector_saturation import CONTROL, DEV, PUBLISHED_PRODUCTION, TEST, VAL, Scan, score
    from scripts.bam_quantitative_validation import load_gt
    freeze = _freeze()
    val = json.loads(VAL.read_text())
    targets, _ = load_gt()
    report = {"freeze": freeze, "published_production": PUBLISHED_PRODUCTION, "scans": {}}
    for role, specs in (("development", [DEV]), ("held_out", TEST), ("control", CONTROL)):
        for spec, scan in specs:
            sc = Scan(spec, scan, val, targets)
            lines = list(range(len(sc.s.grid.y)))
            jobs = [(ident, tr, x, dt, toff, f, freeze, int(ident.rsplit("L", 1)[1]))
                    for ident, tr, x, dt, toff, f in _bam_lines(spec, scan)]
            with Pool(workers) as pool:
                rows = list(pool.imap(_bam_job, jobs, chunksize=1))
            entry = {"role": role, "lines": len(lines)}
            for arm in ARMS:
                dets = [d for r in rows for d in r[arm]["dets"]]
                entry[arm] = {**score(dets, sc, lines),
                              "median_cpu_s_per_line": float(np.median([r[arm]["cpu_s"] for r in rows])),
                              "max_peak_mb": float(max(r[arm]["peak_bytes"] for r in rows)) / 1e6}
            entry["A3_threshold_median"] = float(np.median([r["A3_threshold"] for r in rows]))
            entry["A3_threshold_p10_p90"] = [float(np.percentile([r["A3_threshold"] for r in rows], q))
                                             for q in (10, 90)]
            report["scans"][sc.sid] = entry
            print(sc.sid, json.dumps({a: (entry[a]["recall"], round(entry[a]["false_positives_per_line"], 2))
                                      for a in ARMS}), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bam.json").write_text(json.dumps(report, indent=1))
    return report


# --- INGV / 4TU -----------------------------------------------------------------------------

def _count_job(args):
    ident, raw, x, dt, toff, f, freeze = args
    obs = run_arms(raw, x, dt, toff, f, ident, freeze)
    out = {"line": ident, "traces": int(raw.shape[0]), "frequency_hz": f, "A3_threshold": obs["A3_threshold"],
           "arms": {}}
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(("null99:" + ident).encode()).digest()[:8], "big"))
    perms = [rng.permutation(raw.shape[0]) for _ in range(N_NULL)]
    nulls: dict[str, list] = {}
    for group_arms in (("A0",), ("A1", "A2"), ("A3",)):   # A1 and A2 share one stack per draw
        started = time.perf_counter()
        for i, p in enumerate(perms):
            if time.perf_counter() - started > NULL_BUDGET_S:
                break
            r = run_arms(raw[p], x, dt, toff, f, f"{ident}:perm{i}", freeze, arms=group_arms)
            for arm in group_arms:
                nulls.setdefault(arm, []).append(len(r[arm][0]))
    for arm in ARMS:
        dets, cpu, peak = obs[arm]
        n_obs = len(dets)
        null = np.array(nulls.get(arm, []), float)
        complete = len(null) == N_NULL
        out["arms"][arm] = {
            "candidates": n_obs, "cpu_s": cpu, "peak_mb": peak / 1e6,
            "null_draws": int(len(null)), "null_mean": float(null.mean()) if len(null) else None,
            "null_sd": float(null.std(ddof=1)) if len(null) > 1 else None,
            "p": float((1 + (null >= n_obs).sum()) / (1 + N_NULL)) if complete else None,
            "null_counts": null.astype(int).tolist(),
        }
    return out


def counts(corpus: str, workers: int) -> dict:
    freeze = _freeze()
    jobs = [(ident, tr, x, dt, toff, f, freeze) for ident, tr, x, dt, toff, f in _real_lines(corpus)]
    with Pool(workers) as pool:
        rows = []
        for r in pool.imap(_count_job, jobs, chunksize=1):
            rows.append(r)
            print(Path(r["line"]).name, {a: (v["candidates"], v["p"]) for a, v in r["arms"].items()}, flush=True)
    summary = {}
    for arm in ARMS:
        c = [r["arms"][arm] for r in rows]
        full = [x for x in c if x["p"] is not None]
        # corpus-level: observed total vs the 99 permuted corpus totals (lines with all 99 draws)
        if full:
            totals = np.sum([x["null_counts"] for x in full], axis=0)
            obs_total = sum(x["candidates"] for x in full)
            corpus_p = float((1 + (totals >= obs_total).sum()) / (1 + N_NULL))
        else:
            corpus_p = None
        summary[arm] = {
            "lines": len(c), "candidates": sum(x["candidates"] for x in c),
            "candidates_per_line": float(np.mean([x["candidates"] for x in c])),
            "lines_with_99_draws": len(full),
            "lines_p_le_0_05": sum(x["p"] <= 0.05 for x in full),
            "expected_under_global_null": 0.05 * len(full),
            "corpus_level_p": corpus_p,
            "lines_fallback_no_p": [r["line"] for r, x in zip(rows, c) if x["p"] is None],
            "median_cpu_s_per_line": float(np.median([x["cpu_s"] for x in c])),
            "max_peak_mb": float(max(x["peak_mb"] for x in c)),
        }
    if corpus == "4tu":
        from scripts.real_data_detector_saturation import fourtu_activity_level
        shim = [{"path": r["line"].split(":", 1)[1], "traces": r["traces"],
                 "detectors": {a: {"candidates": r["arms"][a]["candidates"]} for a in ARMS}} for r in rows]
        for arm in ARMS:
            summary[arm]["activity_level"] = fourtu_activity_level(shim, arm)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{corpus}.json").write_text(json.dumps({"summary": summary, "lines": rows}, indent=1, default=str))
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("diagnose", "cost", "bam", "ingv", "4tu"))
    p.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    a = p.parse_args(argv)
    if a.stage == "diagnose":
        r = diagnose(a.workers)
    elif a.stage == "cost":
        r = cost()
    elif a.stage == "bam":
        r = bam(a.workers)["scans"]
    else:
        r = counts(a.stage, a.workers)
    print(json.dumps(r, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
