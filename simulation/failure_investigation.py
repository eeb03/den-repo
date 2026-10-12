"""
Why do 12 scored scenes still fail validation, and where does scene 13's
+110 ps residual come from? A DIAGNOSTIC investigation, kept apart from the
detector work: it changes no tolerance, no rule, no simulator setting and no
verdict. Validation tolerances are only loosened on independent physical
grounds, and nothing here does so.

Every failing scene fails ONLY the apex-trace (kinematic vertex) check;
apex time and hyperbola shape pass. The vertex is the least-squares
parabola t^2 = a x^2 + b x + c fitted to the blind picks of ALL traces,
while the shape check uses the 21 traces around the predicted apex. So the
candidate mechanisms are:

  weak contrast      low |R| at the top boundary -> weak limbs -> far-trace
                     picks land on other energy
  overlapping echoes top and internal echoes (or the direct wave) within
                     ~1.5 periods -> the envelope maximum switches event
                     from trace to trace
  antenna effects    half-offset comparable to depth -> the zero-offset
                     parabola misfits
  scan edge          apex near the end of the line -> one-sided fit
  model limitations  the target spans few cells (staircase) or few cells per
                     wavelength (dispersion), or 2D line-source physics
                     beyond the ray model

DIAGNOSTICS per scene:
  D1 pick consistency: each trace's pick classed as on the top event, on the
     internal event (within half a period), or OTHER; event switches counted.
  D2 diagnostic vertex: the same parabola fitted only to picks ON the scored
     event. Reported beside the official vertex; never replaces it.
  D3 features: |R_top|, internal-top separation (periods), direct-wave
     clearance (periods), half-offset/depth, depth/lambda, radius/lambda,
     radius in cells, cells per wavelength inside the target, apex distance
     from the line ends (traces).
  D4 analytic forward model: a B-scan built from the PREDICTED event times
     (Ricker at each, Fresnel signs, amplitudes = the target-free residual's
     envelope maximum within half a period of each time), plus the
     simulation's own residual AWAY from the events (within one period of
     any event it is zeroed) as the floor, run through the SAME picker and
     scorer. If
     it fails the same way, timing + interference explain the failure; if it
     passes, the simulated wavefield contains something the ray model lacks.
  D5 half-cell re-simulation (pre-declared scenes: 13, plus the worst
     vertex failure scored on each event -- 135 internal, 277 top): if a
     failure or the residual changes with the cell size, it is
     discretisation.

    python -m simulation.failure_investigation diagnose --corpus artifacts/simulation/corpus_s0
    python -m simulation.failure_investigation resimulate --corpus ... --out artifacts/simulation/investigation
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from simulation.analysis import APEX_TRACE_TOLERANCE, assess_against_truth, kinematic_apex_x, pick_peaks
from simulation.scenario import CircularTarget, Scenario2D, Soil

FAILING = ("gen_s0_00022", "gen_s0_00065", "gen_s0_00066", "gen_s0_00085", "gen_s0_00106",
           "gen_s0_00135", "gen_s0_00157", "gen_s0_00177", "gen_s0_00185", "gen_s0_00241",
           "gen_s0_00245", "gen_s0_00277")
RESIMULATE = ("gen_s0_00013", "gen_s0_00135", "gen_s0_00277")
METHOD = "target_free_reference"


def scenario_from_manifest(manifest: dict) -> Scenario2D:
    sc = manifest["scenario"]
    return Scenario2D(**{**sc, "soil": Soil(**sc["soil"]),
                         "targets": tuple(CircularTarget(**t) for t in sc["targets"]),
                         "materials": tuple(Soil(**m) for m in sc.get("materials", ()))})


def _load(d: Path):
    manifest = json.loads((d / "manifest.json").read_text())
    truth = json.loads((d / "truth.json").read_text())
    validation = json.loads((d / "validation.json").read_text())
    data = np.load(d / "bscan.npz")
    return manifest, truth, validation, data


def _target_eps(s: Scenario2D, t) -> float | None:
    if t.material == "pec":
        return None
    if t.material == "free_space":
        return 1.0
    return next(m.relative_permittivity for m in s.materials if m.name == t.material)


def _ricker(t, f):
    z = (math.pi * f * t) ** 2
    return (1 - 2 * z) * np.exp(-z)


def features(d: Path) -> dict:
    manifest, truth, validation, data = _load(d)
    s = scenario_from_manifest(manifest)
    t = s.targets[0]
    f = s.centre_frequency
    period = 1 / f
    v = s.soil.velocity
    lam = v / f
    eps_t = _target_eps(s, t)
    n_s = math.sqrt(s.soil.relative_permittivity)
    r_top = 1.0 if eps_t is None else abs((n_s - math.sqrt(eps_t)) / (n_s + math.sqrt(eps_t)))
    tg = truth["targets"][0]
    ev = {k: np.array([np.nan if x is None else x for x in e["two_way_time_s"]], float)
          for k, e in tg["predicted_events"].items()}
    top_apex = float(np.nanmin(ev["top"]))
    sep = (float(np.nanmin(ev["internal"])) - top_apex) / period if "internal" in ev and np.isfinite(ev["internal"]).any() else None
    direct_end = s.antenna_offset / v + truth["wavelet"]["peak_delay_s"] + period
    apex_trace = int(np.nanargmin(ev["top"]))
    depth = tg["geometry"]["depth_to_top_m"]
    lam_t = None if eps_t is None else (299_792_458.0 / math.sqrt(eps_t)) / f
    m = validation["methods"][METHOD]
    return {
        "scene": d.name, "label": t.label, "material": t.material, "frequency_ghz": f / 1e9,
        "soil_eps": s.soil.relative_permittivity, "target_eps": eps_t,
        "abs_R_top": r_top,
        "internal_minus_top_periods": sep,
        "direct_wave_clearance_periods": (top_apex - direct_end) / period,
        "half_offset_over_depth": (s.antenna_offset / 2) / depth,
        "depth_top_over_lambda": depth / lam,
        "radius_over_lambda": t.radius / lam,
        "radius_cells": t.radius / s.cell,
        "cells_per_lambda_in_target": None if lam_t is None else lam_t / s.cell,
        "cells_per_lambda_in_soil": lam / s.cell,
        "apex_distance_from_line_end_traces": min(apex_trace, s.n_traces - 1 - apex_trace),
        "scored_event": m.get("scored_event", "top"),
        "pass": m["pass"],
        "vertex_error_traces": m["checks"]["apex_trace"]["error_traces"],
    }


def pick_consistency(d: Path) -> dict:
    """D1 + D2."""
    manifest, truth, validation, data = _load(d)
    s = scenario_from_manifest(manifest)
    f = s.centre_frequency
    half = 0.5 / f
    times, _ = pick_peaks(data["data"].astype(float), float(data["dt"]), float(data["time_offset"]),
                          background=data["background"].astype(float))
    tg = truth["targets"][0]
    ev = {k: np.array([np.nan if x is None else x for x in e["two_way_time_s"]], float)
          for k, e in tg["predicted_events"].items()}
    cls = []
    for i, t in enumerate(times):
        near = [(abs(t - e[i]), k) for k, e in ev.items() if np.isfinite(e[i]) and abs(t - e[i]) <= half]
        cls.append(min(near)[1] if near else "other")
    switches = sum(1 for a, b in zip(cls, cls[1:]) if a != b)
    scored = validation["methods"][METHOD].get("scored_event", "top")
    tx, rx = np.asarray(truth["antennas"]["tx_x_m"]), np.asarray(truth["antennas"]["rx_x_m"])
    mid = (tx + rx) / 2
    pred_apex = int(np.nanargmin(np.where(np.isfinite(ev[scored]), ev[scored], np.inf)))
    on = np.array([c == scored for c in cls])
    diag = None
    if on.sum() >= 5:
        try:
            vx = kinematic_apex_x(times[on], mid[on])
            meas = int(np.argmin(np.abs(mid - vx)))
            diag = {"vertex_trace": meas, "error_traces": meas - pred_apex,
                    "would_pass_tolerance": abs(meas - pred_apex) <= APEX_TRACE_TOLERANCE}
        except ValueError as exc:
            diag = {"failure": str(exc)}
    counts = {k: cls.count(k) for k in ("top", "internal", "other")}
    return {"pick_classes": counts, "fraction_other": counts["other"] / len(cls),
            "event_switches": switches, "scored_event": scored,
            "diagnostic_vertex_on_scored_event_only": diag,
            "official_vertex_error_traces": validation["methods"][METHOD]["checks"]["apex_trace"]["error_traces"]}


def analytic_forward_model(d: Path) -> dict:
    """D4: predicted times + Fresnel signs + measured amplitudes, through the
    same picker and scorer."""
    manifest, truth, validation, data = _load(d)
    s = scenario_from_manifest(manifest)
    f = s.centre_frequency
    dt, t_off = float(data["dt"]), float(data["time_offset"])
    resid = data["data"].astype(float) - data["background"].astype(float)       # (samples, traces)
    env = np.abs(__import__("scipy.signal", fromlist=["hilbert"]).hilbert(resid, axis=0))
    n_samp, n_tr = resid.shape
    tt = t_off + np.arange(n_samp) * dt
    tg = truth["targets"][0]
    t = s.targets[0]
    eps_t = _target_eps(s, t)
    n_s = math.sqrt(s.soil.relative_permittivity)
    sign = {"top": -1.0 if eps_t is None else float(np.sign(n_s - math.sqrt(eps_t)) or 1.0)}
    sign["internal"] = -sign["top"]       # far wall: the opposite boundary
    synth = np.zeros_like(resid)
    for k, e in tg["predicted_events"].items():
        for i, te in enumerate(e["two_way_time_s"]):
            if te is None:
                continue
            j = int(round((te - t_off) / dt))
            w = max(1, int(round(0.5 / f / dt)))           # +/- half a period
            seg = env[max(0, j - w): min(n_samp, j + w + 1), i]
            amp = float(seg.max()) if seg.size else 0.0
            synth[:, i] += sign[k] * amp * _ricker(tt - te, f)
    # The simulated residual away from the predicted events (direct-wave
    # leakage, numerical noise) is kept as the floor, so far traces whose echo
    # has faded pick what the simulation's picks see there, not sample 0.
    floor = resid.copy()
    for e in tg["predicted_events"].values():
        for i, te in enumerate(e["two_way_time_s"]):
            if te is not None:
                j = int(round((te - t_off) / dt))
                w = int(round(1.0 / f / dt))
                floor[max(0, j - w): j + w + 1, i] = 0.0
    synth = synth + floor
    background = np.zeros_like(synth)
    result = assess_against_truth(synth, dt, t_off, truth, background=background)
    m = result["methods"][METHOD] if "methods" in result else result
    sim_times, _ = pick_peaks(data["data"].astype(float), dt, t_off, background=data["background"].astype(float))
    ana_times, _ = pick_peaks(synth, dt, t_off, background=background)
    agree = float(np.mean(np.abs(sim_times - ana_times) <= 0.5 / f))
    return {"pass": m["pass"], "scored_event": m.get("scored_event"),
            "per_trace_pick_agreement_with_simulation": agree,
            "vertex_error_traces": m["checks"]["apex_trace"]["error_traces"],
            "apex_time_error_ps": round(m["checks"]["apex_time"]["error_s"] * 1e12),
            "shape_rms_ps": round(m["checks"]["hyperbola_shape"]["rms_error_s"] * 1e12)}


def diagnose(corpus: Path) -> dict:
    index = json.loads((corpus / "index.json").read_text())
    scored = [sid for sid, e in sorted(index["scenes"].items()) if e["validation_status"] == "scored"]
    feats = {sid: features(corpus / sid) for sid in scored}
    out = {"scenes": {}, "feature_comparison": {}}
    for sid in FAILING + ("gen_s0_00013",):
        out["scenes"][sid] = {"features": feats[sid], "picks": pick_consistency(corpus / sid),
                              "analytic_forward_model": analytic_forward_model(corpus / sid)}
    # failing vs passing, on the pre-registered basis (exploratory: n = 12)
    keys = [k for k, v in feats[scored[0]].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    for k in keys:
        fail = [feats[s][k] for s in scored if not feats[s]["pass"] and feats[s][k] is not None]
        ok = [feats[s][k] for s in scored if feats[s]["pass"] and feats[s][k] is not None]
        if fail and ok:
            from scipy.stats import mannwhitneyu
            out["feature_comparison"][k] = {"failing_median": float(np.median(fail)),
                                            "passing_median": float(np.median(ok)),
                                            "mann_whitney_p": float(mannwhitneyu(fail, ok).pvalue),
                                            "n_failing": len(fail), "n_passing": len(ok)}
    # picks on passing scenes too, for the base rate of OTHER picks
    out["passing_fraction_other_median"] = float(np.median(
        [pick_consistency(corpus / s)["fraction_other"] for s in scored if feats[s]["pass"]]))
    return out


def resimulate(corpus: Path, out: Path) -> dict:
    """D5: the pre-declared scenes at half the cell size."""
    from simulation.run_gprmax import run_scenario
    results = {}
    for sid in RESIMULATE:
        manifest = json.loads((corpus / sid / "manifest.json").read_text())
        s = scenario_from_manifest(manifest)
        half = replace(s, scenario_id=f"{sid}_halfcell", cell=s.cell / 2)
        m = run_scenario(half, out)
        v = json.loads((out / half.scenario_id / "validation.json").read_text())["methods"][METHOD]
        orig = json.loads((corpus / sid / "validation.json").read_text())["methods"][METHOD]

        def summary(x):
            return {"pass": x["pass"], "scored_event": x.get("scored_event"),
                    "vertex_error_traces": x["checks"]["apex_trace"]["error_traces"],
                    "apex_time_error_ps": round(x["checks"]["apex_time"]["error_s"] * 1e12),
                    "shape_rms_ps": round(x["checks"]["hyperbola_shape"]["rms_error_s"] * 1e12),
                    "shape_mean_ps": round(x["checks"]["hyperbola_shape"]["mean_error_s"] * 1e12)}
        results[sid] = {"cell_m": s.cell, "original": summary(orig),
                        "half_cell": {"cell_m": half.cell, **summary(v), "wall_seconds": m.get("wall_seconds")}}
        print(sid, json.dumps(results[sid]), flush=True)
    return results


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("diagnose", "resimulate"))
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("artifacts/simulation/investigation"))
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    result = diagnose(args.corpus) if args.stage == "diagnose" else resimulate(args.corpus, args.out)
    (args.out / f"{args.stage}.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result if args.stage == "resimulate" else
                     {k: v for k, v in result.items() if k != "scenes"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
