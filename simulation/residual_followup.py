"""
Scientific follow-up of the validation picker's apex-time residual
(docs/hyperbola-v2-experiment.md §10). Separate from detector work; no
detector choice depends on it, and no tolerance or truth model changes.

    analytic   H_2D: predicted envelope-peak delay of a 2D line-source field
               relative to truth.ricker_peak_delay + travel time, per scene,
               against the measured residual on corpus_s0's passing scenes.
    quarter    scene 13 re-simulated at cell/4 (D, D/2 from the half-cell
               run); fits residual(D) = r0 + c D^p.

The 2D model (frequency domain, exact 2D Green's function):

    received(w) = (j w) R(w) G2(w),  R = gprMax Ricker, j w = the far-field
    time derivative of a Hertzian (line-current) source,

with two bracketing scattering models at the scene's predicted travel time
tau = t_apex - chi (so k rho = w tau in the soil):

    image      G2 = H0^(2)(w tau)            -- specular, large-radius target
    point      G2 = H0^(2)(w tau / 2)^2      -- small scatterer, two legs

Delay = (envelope peak of the model's received pulse) - tau - chi, the same
envelope-maximum pick the validation uses, in periods. Pure power-law
filters (the far-field limit) have constant phase and so do NOT move the
Hilbert-envelope peak; only the near-field departure of the Hankel phase can.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy.signal import hilbert
from scipy.special import hankel2
from scipy.stats import spearmanr

METHOD = "target_free_reference"
SCENE_13 = "gen_s0_00013"


def ricker(t: np.ndarray, f: float) -> np.ndarray:
    """gprMax 'ricker': -(2 zeta (t - chi)^2 - 1) exp(-zeta (t - chi)^2), zeta = pi^2 f^2, chi = sqrt2/f."""
    chi = math.sqrt(2.0) / f
    zeta = math.pi ** 2 * f ** 2
    return -(2 * zeta * (t - chi) ** 2 - 1) * np.exp(-zeta * (t - chi) ** 2)


def model_delay(f: float, tau: float, model: str, oversample: int = 64) -> float:
    """Envelope-peak delay (s) of the 2D model pulse relative to tau + chi."""
    chi = math.sqrt(2.0) / f
    dt = 1 / (f * oversample)
    n = int(2 ** math.ceil(math.log2((tau + 12 / f) / dt)))
    t = np.arange(n) * dt
    w = 2 * math.pi * np.fft.rfftfreq(n, dt)
    spec = np.fft.rfft(ricker(t, f))
    with np.errstate(invalid="ignore"):
        if model == "image":
            g = hankel2(0, w * tau)
        else:
            g = hankel2(0, w * tau / 2) ** 2
    g[0] = 0.0
    # Remove the bulk delay exactly (multiply by e^{+j w tau}) so the pulse
    # stays inside the window; the residual phase is what moves the peak.
    out = np.fft.irfft(1j * w * spec * g * np.exp(1j * w * tau), n)
    env = np.abs(hilbert(out))
    i = int(np.argmax(env))
    if 0 < i < n - 1:                         # parabolic refinement
        a, b, c = env[i - 1], env[i], env[i + 1]
        i = i + 0.5 * (a - c) / (a - 2 * b + c)
    return i * dt - chi


def analytic(corpus: Path) -> dict:
    index = json.loads((corpus / "index.json").read_text())["scenes"]
    rows = []
    for sid, e in sorted(index.items()):
        p = corpus / sid / "validation.json"
        if not p.exists():
            continue
        v = json.loads(p.read_text())
        m = v.get("methods", {}).get(METHOD)
        if not m or "checks" not in m:
            continue
        truth = json.loads((corpus / sid / "truth.json").read_text())
        f = float(e["centre_frequency_hz"])
        event = truth["targets"][0]["predicted_events"][m["scored_event"]]
        tau = event["apex_time_s"] - math.sqrt(2.0) / f
        rows.append({"scene": sid, "frequency_hz": f, "pass": m["pass"], "scored_event": m["scored_event"],
                     "tau_periods": tau * f,
                     "measured_periods": m["checks"]["apex_time"]["error_s"] * f,
                     "image_periods": model_delay(f, tau, "image") * f,
                     "point_periods": model_delay(f, tau, "point") * f})
    passing = [r for r in rows if r["pass"]]
    out = {"n_scored": len(rows), "n_passing": len(passing), "rows": rows}
    for model in ("image", "point"):
        x = np.array([r[f"{model}_periods"] for r in passing])
        y = np.array([r["measured_periods"] for r in passing])
        rho = spearmanr(x, y).statistic if len(x) > 2 else None
        out[model] = {"spearman_rho": None if rho is None else float(rho),
                      "median_predicted_periods": float(np.median(x)),
                      "median_measured_periods": float(np.median(y)),
                      "median_ratio_predicted_over_measured": float(np.median(x) / np.median(y))}
    s13 = next((r for r in rows if r["scene"] == SCENE_13), None)
    out["scene_13"] = s13
    return out


def quarter(corpus: Path, out_dir: Path) -> dict:
    from simulation.failure_investigation import scenario_from_manifest
    from simulation.run_gprmax import run_scenario
    manifest = json.loads((corpus / SCENE_13 / "manifest.json").read_text())
    s = scenario_from_manifest(manifest)
    q = replace(s, scenario_id=f"{SCENE_13}_quartercell", cell=s.cell / 4)
    m = run_scenario(q, out_dir)
    res = {}
    for name, path, cell in (("D", corpus / SCENE_13, s.cell),
                             ("D/2", out_dir / f"{SCENE_13}_halfcell", s.cell / 2),
                             ("D/4", out_dir / q.scenario_id, s.cell / 4)):
        v = json.loads((path / "validation.json").read_text())["methods"][METHOD]
        res[name] = {"cell_m": cell, "apex_time_error_s": v["checks"]["apex_time"]["error_s"],
                     "pass": v["pass"], "vertex_error_traces": v["checks"]["apex_trace"]["error_traces"]}
    r1, r2, r4 = (res[k]["apex_time_error_s"] for k in ("D", "D/2", "D/4"))
    fit = {}
    if (r1 - r2) * (r2 - r4) > 0:
        p = math.log((r1 - r2) / (r2 - r4)) / math.log(2)
        c_term = (r2 - r4) / (1 - 2 ** -p)       # = c (D/2)^p
        fit = {"order_p": p, "r0_s": r4 - c_term * 2 ** -p}
    else:
        fit = {"note": "non-monotone convergence; no extrapolation"}
    return {"scene": SCENE_13, "levels": res, "richardson": fit, "wall_seconds": m["runtime"]["wall_seconds"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("analytic", "quarter"))
    p.add_argument("--corpus", type=Path, default=Path("artifacts/simulation/corpus_s0"))
    p.add_argument("--out", type=Path, default=Path("artifacts/simulation/investigation"))
    a = p.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    r = analytic(a.corpus) if a.stage == "analytic" else quarter(a.corpus, a.out)
    (a.out / f"residual_{a.stage}.json").write_text(json.dumps(r, indent=1))
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
