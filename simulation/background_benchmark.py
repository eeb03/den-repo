"""
Does mean-trace background removal help or hurt the platform's EXISTING
detector? Measured on the simulated corpus, where every target is known.

ARMS. Each changes ONE step -- the background -- and reuses everything else
bit for bit: dewow(15) -> linear gain -> ring z-score with
`TRACE_ANOMALY_WINDOWS` -> |z| > 3 -> 4-connected components -> min 3 cells,
via `benchmark.detection.detect_line`. No threshold is tuned.

* mean_trace_subtraction -- production: `anomaly_grid_from_traces`, as-is.
* no_background_removal -- the same chain without the mean-trace step.
* target_free_reference_oracle -- subtract the target-free twin. Only a
  simulation has one; it is an upper reference, never a deployable method.

SAMPLING. The solver samples at 135-250 samples per wavelet period (its
Courant limit), while the ring windows are 5/15 SAMPLES deep: at native
sampling every echo sits inside its own background ring and the detector is
structurally blind (the width saturation already measured on real lines,
now in time). Real instruments digitise far coarser -- 4TU, the platform's
main real dataset: 512 samples over 50 ns at 500 MHz, 20.5 samples per
period. So the PRIMARY condition digitises each trace (and its twin) to 20
samples per centre period by band-limited Fourier resampling, before any
arm runs; "native" is reported beside it. Fixed before any corpus result
was seen: it was found from an analytic test fixture.

SCORING RULES, fixed before the benchmark was run on any scene (a smoke run
on one scene checked only that the code executes):

* A detection is located at its peak |z| cell: lateral position = midpoint x
  of that trace; time = that sample's two-way time.
* MATCH: a detection matches a target when |x - centre_x| <= lambda_c (the
  centre wavelength in the soil) AND its time lies in
  [top-echo apex time - T, latest predicted-event apex time + T], T = 1/f.
  Each target takes the matching detection with the largest |peak z|.
* An unmatched detection is classed, first rule that applies:
    duplicate  inside a match window of an already-matched target
    limb       within T of a target's predicted event time on its own trace
               (a fragment of a real hyperbola, not clutter)
    early      before the direct ground wave has passed: t <= offset / v + chi + 2 T
    clutter    anything else
  fp_strict counts every unmatched detection; fp_clutter only early + clutter.
* Depth of a matched detection, from its time: the true soil velocity (an
  ORACLE velocity, exact in simulation), wavelet delay removed, antenna
  half-offset h removed: d = sqrt((v (t - chi) / 2)^2 - h^2). Compared with
  depth to the target's TOP. This isolates the detector's time error; it
  says nothing about velocity estimation, which real data needs.
* Categories reported: frequency, soil class (eps_r 3-8 dry, 8-15 moist,
  15-25 wet), label, depth to centre (< 1.5, 1.5-2.5, >= 2.5 lambda_c; the
  last is "deep"), and split. No parameter is fitted, so there is nothing to
  leak; the test split is still reported on its own.

Every number here is a SIMULATION result. None is a field accuracy claim.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.signal import resample

from benchmark.detection import detect_line
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS
from preprocessing.spatial_grid import TRACE_ANOMALY_WINDOWS, _local_anomaly_grid, anomaly_grid_from_traces
from preprocessing.trace_processing import apply_gain, dewow
from simulation.interface import SyntheticLine, load_line

#: name -> samples per centre period (None = the solver's own sampling).
SAMPLINGS = {"instrument_20spp": 20, "native": None}
DEPTH_BINS = ((0.0, 1.5, "shallow"), (1.5, 2.5, "mid"), (2.5, math.inf, "deep"))
SOIL_CLASSES = ((0.0, 8.0, "dry"), (8.0, 15.0, "moist"), (15.0, math.inf, "wet"))


def _filters_then_ring(traces: np.ndarray) -> np.ndarray:
    """anomaly_grid_from_traces minus its first step (background removal)."""
    processed = np.array(
        [apply_gain(dewow(t.tolist(), window=15), gain_type="linear", power=1.0) for t in traces],
        dtype=float,
    )
    z, _ = _local_anomaly_grid(processed.T, **TRACE_ANOMALY_WINDOWS)
    return z


ARMS = {
    "mean_trace_subtraction": lambda line: anomaly_grid_from_traces(line.traces),
    "no_background_removal": lambda line: _filters_then_ring(line.traces),
    "target_free_reference_oracle": lambda line: _filters_then_ring(line.traces - line.background),
}


def digitise(line: SyntheticLine, samples_per_period: float | None) -> SyntheticLine:
    """Resample traces and twin to an instrument's sampling. The time window
    is unchanged; only the sample count (and so dt) changes."""
    if samples_per_period is None:
        return line
    f = line.truth["wavelet"]["centre_frequency_hz"]
    n_old = line.traces.shape[1]
    n_new = max(2, round(n_old * line.dt_s * f * samples_per_period))
    return SyntheticLine(**{
        **line.__dict__,
        "traces": resample(line.traces, n_new, axis=1),
        "background": resample(line.background, n_new, axis=1),
        "dt_s": line.dt_s * n_old / n_new,
    })


def _bin(value: float, bins) -> str:
    return next(name for lo, hi, name in bins if lo <= value < hi)


def _event_times(target: dict) -> dict[str, np.ndarray]:
    events = target.get("predicted_events") or {"top": target["predicted"]}
    return {k: np.array([np.nan if t is None else t for t in e["two_way_time_s"]], dtype=float)
            for k, e in events.items()}


def score_scene(line: SyntheticLine, arm: str) -> dict:
    z = ARMS[arm](line)
    detections = detect_line(line.traces, line.scenario_id, 0,
                             threshold=DEFAULT_ANOMALY_THRESHOLD, min_cells=DEFAULT_MIN_CELLS,
                             estimator=lambda _traces: z)
    times = line.sample_times_s
    located = [{"x": float(line.midpoint_x_m[d.peak_trace]), "t": float(times[d.peak_sample]),
                "trace": d.peak_trace, "abs_z": abs(d.peak_z)} for d in detections]
    return {"scenario_id": line.scenario_id, "arm": arm, **score_located(line, located)}


def score_located(line: SyntheticLine, located: list[dict]) -> dict:
    """The pre-registered match/classify/localise rules, for any detector.
    A located detection is {x, t, trace, abs_z}, optionally with v_est (a
    velocity the detector itself estimated, m/s)."""
    truth = line.truth
    f = truth["wavelet"]["centre_frequency_hz"]
    period = 1.0 / f
    chi = truth["wavelet"]["peak_delay_s"]
    v = line.soil_velocity_m_per_s
    wavelength = v / f
    tx, rx = np.asarray(truth["antennas"]["tx_x_m"]), np.asarray(truth["antennas"]["rx_x_m"])
    half_offset = float(rx[0] - tx[0]) / 2

    windows = []
    for tg in truth["targets"]:
        ev = _event_times(tg)
        apex_times = [float(np.nanmin(t)) for t in ev.values()]
        windows.append({
            "target": tg, "events": ev,
            "t_lo": float(np.nanmin(ev["top"])) - period, "t_hi": max(apex_times) + period,
            "x": tg["geometry"]["centre_x_m"],
        })

    def in_window(det, w):
        return abs(det["x"] - w["x"]) <= wavelength and w["t_lo"] <= det["t"] <= w["t_hi"]

    matched: dict[int, int] = {}
    for wi, w in enumerate(windows):
        cands = [i for i, d in enumerate(located) if in_window(d, w) and i not in matched.values()]
        if cands:
            matched[wi] = max(cands, key=lambda i: located[i]["abs_z"])

    used = set(matched.values())
    classes = defaultdict(int)
    direct_end = 2 * half_offset / v + chi + 2 * period
    for i, d in enumerate(located):
        if i in used:
            continue
        if any(in_window(d, w) for w in windows):
            classes["duplicate"] += 1
        elif any(abs(d["t"] - t[d["trace"]]) <= period
                 for w in windows for t in w["events"].values() if np.isfinite(t[d["trace"]])):
            classes["limb"] += 1
        elif d["t"] <= direct_end:
            classes["early"] += 1
        else:
            classes["clutter"] += 1

    targets = []
    for wi, w in enumerate(windows):
        g = w["target"]["geometry"]
        depth_centre_wl = g["depth_to_centre_m"] / wavelength
        entry = {"target_id": w["target"]["target_id"], "label": w["target"]["label"],
                 "depth_bin": _bin(depth_centre_wl, DEPTH_BINS),
                 "depth_to_centre_wavelengths": depth_centre_wl, "detected": wi in matched}
        if wi in matched:
            d = located[matched[wi]]
            path_half = v * max(d["t"] - chi, 0.0) / 2
            depth_est = math.sqrt(max(path_half ** 2 - half_offset ** 2, 0.0))
            entry.update({
                "lateral_error_m": d["x"] - w["x"],
                "lateral_error_wavelengths": (d["x"] - w["x"]) / wavelength,
                "depth_error_m": depth_est - g["depth_to_top_m"],
                "depth_error_wavelengths": (depth_est - g["depth_to_top_m"]) / wavelength,
                "peak_abs_z": d["abs_z"],
            })
            if d.get("v_est"):
                path_est = d["v_est"] * max(d["t"] - chi, 0.0) / 2
                depth_v = math.sqrt(max(path_est ** 2 - half_offset ** 2, 0.0))
                entry.update({
                    "velocity_error_fraction": d["v_est"] / v - 1.0,
                    "depth_error_own_velocity_wavelengths": (depth_v - g["depth_to_top_m"]) / wavelength,
                })
        targets.append(entry)

    return {
        "n_detections": len(located),
        "unmatched": dict(classes),
        "fp_strict": sum(classes.values()),
        "fp_clutter": classes["early"] + classes["clutter"],
        "targets": targets,
    }


def _summary(rows: list[dict]) -> dict:
    """rows: per-scene results of ONE arm."""
    targets = [t for r in rows for t in r["targets"]]
    hits = [t for t in targets if t["detected"]]

    def med(key, absolute=True):
        vals = [abs(t[key]) if absolute else t[key] for t in hits]
        return float(np.median(vals)) if vals else None

    return {
        "scenes": len(rows),
        "targets": len(targets),
        "recall": len(hits) / len(targets) if targets else None,
        "fp_strict_per_scene": float(np.mean([r["fp_strict"] for r in rows])) if rows else None,
        "fp_clutter_per_scene": float(np.mean([r["fp_clutter"] for r in rows])) if rows else None,
        "median_abs_lateral_error_wavelengths": med("lateral_error_wavelengths"),
        "median_abs_lateral_error_m": med("lateral_error_m"),
        "median_abs_depth_error_wavelengths": med("depth_error_wavelengths"),
        "median_signed_depth_error_wavelengths": med("depth_error_wavelengths", absolute=False),
    }


def run(corpus: Path, index: dict) -> dict:
    meta = dict(index["scenes"])
    lines = {sid: load_line(corpus / sid) for sid in sorted(meta)}
    return {name: _run_sampling(lines, meta, spp) for name, spp in SAMPLINGS.items()}


def _run_sampling(lines: dict, meta: dict, samples_per_period) -> dict:
    per_scene = {arm: [] for arm in ARMS}
    for sid, line in lines.items():
        line = digitise(line, samples_per_period)
        for arm in ARMS:
            per_scene[arm].append(score_scene(line, arm))

    def cat(sid: str, key: str) -> str:
        e = meta[sid]
        if key == "frequency":
            return f"{e['centre_frequency_hz'] / 1e9:g} GHz"
        if key == "soil":
            return _bin(e["soil_relative_permittivity"], SOIL_CLASSES)
        if key == "split":
            return e["split"]
        if key == "scene_kind":
            return {0: "empty", 1: "single"}.get(e["n_targets"], "multi")
        raise KeyError(key)

    report = {"simulated": True, "claim_scope": "simulation only; not a field accuracy claim",
              "samples_per_period": samples_per_period,
              "threshold": DEFAULT_ANOMALY_THRESHOLD, "min_cells": DEFAULT_MIN_CELLS, "arms": {}}
    for arm, rows in per_scene.items():
        arm_report = {"overall": _summary(rows)}
        for key in ("frequency", "soil", "split", "scene_kind"):
            groups = defaultdict(list)
            for r in rows:
                groups[cat(r["scenario_id"], key)].append(r)
            arm_report[f"by_{key}"] = {g: _summary(rs) for g, rs in sorted(groups.items())}
        for key in ("label", "depth_bin"):
            groups = defaultdict(list)
            for r in rows:
                for t in r["targets"]:
                    groups[t[key]].append({**r, "targets": [t]})
            # Per-target categories: FP rates are scene properties and are
            # not split by target, so they are dropped here.
            arm_report[f"by_{key}"] = {g: {k: v for k, v in _summary(rs).items()
                                           if not k.startswith("fp_") and k != "scenes"}
                                       for g, rs in sorted(groups.items())}
        arm_report["unmatched_classes_total"] = dict(sum((Counter(r["unmatched"]) for r in rows), Counter()))
        report["arms"][arm] = arm_report
    report["per_scene"] = per_scene
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Background-removal benchmark on a simulated corpus.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    index = json.loads((args.corpus / "index.json").read_text())
    report = {"simulated": True, "corpus_seed": index.get("seed"), "by_sampling": run(args.corpus, index)}
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps({s: {arm: r["overall"] for arm, r in rep["arms"].items()}
                      for s, rep in report["by_sampling"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
