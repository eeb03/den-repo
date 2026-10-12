"""
Real-data arm (INGV-UNISA and 4TU) of the detector-saturation experiment,
under docs/detector-saturation-experiment.md §7. BAM has its own script
(scripts/bam_detector_saturation.py) because it has object truth; these two
corpora do not.

* INGV-UNISA: the 50 content-unique lines (150 files, md5-deduplicated) of the
  2026-08-06 false-alarm baseline (production: 2,551 candidates, at the
  trace-permutation chance rate).
* 4TU: the file subset chosen by scripts/characterise_4tu_null.py's own
  rule (random.Random(20260807).sample of the sorted file list, 40 files),
  plus the activity-level comparison of benchmark.fourtu_scoring.

Detector configurations and thresholds are those frozen on synthetic
train+val (simulation/detector_freeze.json); the production ring is also run
at 3.0. Arm: mean-trace subtraction (the production path). For each line:
candidates (components >= min_cells), multi-trace candidates (>= 3 trace
columns), and the same count on N_DRAWS trace-order permutations of the raw
line (positions kept in place: the null destroys lateral structure only).

Inputs at inference are the traces, the sample interval, trace positions from
the SEG-Y headers (along-line distance; INGV source X/Y, 4TU group X), and a
frequency: 4TU's nominal 500 MHz; for INGV, whose antenna frequency is not in
the headers, the spectral peak of the line's own mean amplitude spectrum.

    python -m scripts.real_data_detector_saturation --corpus ingv --out artifacts/realdata/ingv.json
    python -m scripts.real_data_detector_saturation --corpus 4tu  --out artifacts/realdata/4tu.json
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy import ndimage

from benchmark.hyperbola_stack import estimate_time_zero
from converters.segy_endian import BIG, LITTLE, LittleEndianSegyFile, detect_endianness
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS
from simulation.detector_comparison import detector_grid

INGV_GLOB = "datasets/downloads/INGV-UNISA*_extracted/**/*.[sS][gG][yY]"
FOURTU_CORPUS = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")
FOURTU_SEED, FOURTU_FILES = 20260807, 40
FOURTU_NOMINAL_HZ = 500e6
N_DRAWS = 10


def read_line(path: Path) -> tuple[np.ndarray, float, np.ndarray, str]:
    """(traces (n_traces, n_samples), dt_s, along-line x in m, position source)."""
    order, _ = detect_endianness(path)
    if order == BIG:
        import segyio
        with segyio.open(str(path), "r", ignore_geometry=True) as f:
            traces = np.array([f.trace[i] for i in range(f.tracecount)], dtype=float)
            dt_ps = float(segyio.tools.dt(f))
            h = f.header
            sx = np.array([h[i][segyio.TraceField.SourceX] for i in range(f.tracecount)], float)
            sy = np.array([h[i][segyio.TraceField.SourceY] for i in range(f.tracecount)], float)
            sc = h[0][segyio.TraceField.SourceGroupScalar]
            gx = np.array([h[i][segyio.TraceField.GroupX] for i in range(f.tracecount)], float)
    else:
        with LittleEndianSegyFile(path, order=LITTLE) as f:
            traces = np.array([f.trace[i] for i in range(f.tracecount)], dtype=float)
            dt_ps = float(f.interval)
            hs = [f._read_trace_header(i) for i in range(f.tracecount)]
            sx = np.array([x[73] for x in hs], float)
            sy = np.array([x[77] for x in hs], float)
            gx = np.array([x[81] for x in hs], float)
            sc = hs[0][71]
    scale = (1.0 / abs(sc)) if sc < 0 else (float(sc) if sc > 0 else 1.0)
    # The sample interval is stored in picoseconds by these GPR writers (4TU:
    # 97 -> 512 samples over 50 ns, its documented window).
    dt_s = dt_ps * 1e-12
    n = traces.shape[0]
    step = np.hypot(np.diff(sx), np.diff(sy)) * scale
    if order == BIG and step.sum() > 0:
        # GPS positions repeat between fixes: spread the measured path length
        # uniformly over the traces (constant-speed assumption).
        x = np.arange(n) * (step.sum() / max(n - 1, 1))
        return traces, dt_s, x, "source_xy_path_length_uniform"
    if np.ptp(gx) > 0:
        return traces, dt_s, gx * scale, "group_x"
    raise ValueError(f"{path}: no usable trace positions in the headers")


def dominant_frequency(traces: np.ndarray, dt_s: float) -> float:
    spec = np.abs(np.fft.rfft(traces - traces.mean(axis=1, keepdims=True), axis=1)).mean(axis=0)
    freqs = np.fft.rfftfreq(traces.shape[1], dt_s)
    spec[0] = 0.0
    return float(freqs[int(np.argmax(spec))])


def count(z: np.ndarray, threshold: float) -> tuple[int, int]:
    """(candidates, candidates spanning >= 3 trace columns): the
    find_anomaly_candidates rule, 4-connected, min_cells."""
    mask = np.abs(np.nan_to_num(z, nan=0.0)) > threshold
    labeled, n = ndimage.label(mask)
    if n == 0:
        return 0, 0
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= DEFAULT_MIN_CELLS]
    wide = 0
    for sl, lab in zip(ndimage.find_objects(labeled), range(1, n + 1)):
        if lab in keep and sl is not None and (sl[1].stop - sl[1].start) >= 3:
            wide += 1
    return len(keep), wide


def _line_job(args):
    path, freq_mode, jobs, draws, seed = args
    traces, dt, x, pos_src = read_line(Path(path))
    f = FOURTU_NOMINAL_HZ if freq_mode == "4tu_nominal" else dominant_frequency(traces, dt)

    class _L:  # the acquisition facts detector_grid reads
        midpoint_x_m, dt_s, time_offset_s = x, dt, 0.0
    rng = np.random.default_rng([seed, int(hashlib.md5(path.encode()).hexdigest()[:8], 16)])
    perms = [rng.permutation(traces.shape[0]) for _ in range(draws)]
    out = {"path": path, "traces": int(traces.shape[0]), "samples": int(traces.shape[1]),
           "dt_ns": dt * 1e9, "spacing_m": float(np.median(np.diff(x))), "position_source": pos_src,
           "frequency_hz": f, "frequency_source": freq_mode, "detectors": {}}
    for name, det, cfg, thr in jobs:
        def run(tr):
            tz = estimate_time_zero(tr, dt, 0.0)
            z, _ = detector_grid(det, cfg, tr - tr.mean(axis=0), _L, tz, f)
            return count(z, thr)
        c0 = time.process_time()
        cand, wide = run(traces)
        cpu = time.process_time() - c0
        null = np.array([run(traces[p]) for p in perms], float).reshape(-1, 2)
        out["detectors"][name] = {
            "threshold": thr, "candidates": cand, "multi_trace": wide, "cpu_s": cpu,
            "null_candidates_mean": float(null[:, 0].mean()), "null_candidates_p95": float(np.percentile(null[:, 0], 95)),
            "null_multi_trace_mean": float(null[:, 1].mean()),
            "p_candidates": float((1 + (null[:, 0] >= cand).sum()) / (1 + len(null))),
            "p_multi_trace": float((1 + (null[:, 1] >= wide).sum()) / (1 + len(null))),
        }
    return out


def files_for(corpus: str) -> list[str]:
    if corpus == "ingv":
        unique = {}
        for f in sorted(glob.glob(INGV_GLOB, recursive=True)):
            unique.setdefault(hashlib.md5(Path(f).read_bytes()).hexdigest(), f)
        return sorted(unique.values())
    all_files = sorted(glob.glob(str(FOURTU_CORPUS / "*/**/*.sgy"), recursive=True))
    return sorted(random.Random(FOURTU_SEED).sample(all_files, min(FOURTU_FILES, len(all_files))))


def detector_jobs(freeze: dict) -> list:
    jobs = [("ring@3.0_production", "ring", {}, DEFAULT_ANOMALY_THRESHOLD)]
    for det, d in freeze["detectors"].items():
        if det in ("ring_production_threshold",) or d["threshold"] is None:
            continue
        jobs.append((f"{det}@{d['threshold']}_synthetic_frozen", det, d["config"], d["threshold"]))
    return jobs


def fourtu_activity_level(rows: list[dict], name: str) -> dict:
    from benchmark.fourtu_scoring import ActivityObservation, score_activities
    from benchmark.fourtu_truth import load_truth
    from ingestion.four_tu_velocity import load_metadata, normalise_location_id
    known = set(load_metadata(FOURTU_CORPUS))
    obs: dict[str, list] = {}
    for r in rows:
        loc, _ = normalise_location_id(Path(r["path"]).relative_to(FOURTU_CORPUS).parts[2], known)
        obs.setdefault(loc, []).append(r)
    from benchmark.fourtu_truth import normalise_location_id as norm
    observations = {norm(loc): ActivityObservation(norm(loc), sum(r["detectors"][name]["candidates"] for r in rs),
                                                   sum(r["traces"] for r in rs)) for loc, rs in obs.items()}
    return score_activities(load_truth(), observations).as_dict()


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", choices=("ingv", "4tu"), required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--freeze", type=Path, default=Path("simulation/detector_freeze.json"))
    p.add_argument("--draws", type=int, default=N_DRAWS)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = p.parse_args(argv)
    freeze = json.loads(args.freeze.read_text())
    jobs = detector_jobs(freeze)
    files = files_for(args.corpus)[: args.limit]
    mode = "4tu_nominal" if args.corpus == "4tu" else "spectral_peak"
    rows = []
    with Pool(args.workers) as pool:
        for r in pool.imap(_line_job, [(f, mode, jobs, args.draws, 0) for f in files]):
            rows.append(r)
            print(Path(r["path"]).name, {k: (v["candidates"], v["multi_trace"], round(v["null_candidates_mean"], 1))
                                         for k, v in r["detectors"].items()}, flush=True)
    summary = {}
    for name, *_ in jobs:
        c = [r["detectors"][name] for r in rows]
        summary[name] = {
            "lines": len(c), "candidates": sum(x["candidates"] for x in c),
            "candidates_per_line": float(np.mean([x["candidates"] for x in c])),
            "multi_trace": sum(x["multi_trace"] for x in c),
            "null_candidates_mean_total": float(sum(x["null_candidates_mean"] for x in c)),
            "null_multi_trace_mean_total": float(sum(x["null_multi_trace_mean"] for x in c)),
            "lines_candidates_above_null_p95": int(sum(x["candidates"] > x["null_candidates_p95"] for x in c)),
            "lines_multi_trace_p_below_0_05": int(sum(x["p_multi_trace"] < 0.05 for x in c)),
            "median_cpu_s_per_line": float(np.median([x["cpu_s"] for x in c])),
        }
        if args.corpus == "4tu":
            summary[name]["activity_level"] = fourtu_activity_level(rows, name)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"protocol": __doc__, "corpus": args.corpus, "draws": args.draws,
                                    "files": len(files), "summary": summary, "lines": rows}, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
