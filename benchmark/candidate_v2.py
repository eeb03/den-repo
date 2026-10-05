"""
EXPERIMENTAL staged candidate generator, version 2. Research only.

Status: EXPERIMENTAL (benchmark.gates.CAPABILITY_STATUS["candidate_generation_v2"]).
No production path imports this module; the production detector
(`benchmark.detection`, ring z-score) is unchanged. Like the detection path, it
is truth-blind: it imports no truth module and reads no manifest
(`tests/test_candidate_v2.py` checks this).

It is deterministic and has no learned parameters. Every proposal carries
interpretable component scores, so a rejected or accepted candidate can be
explained term by term.

Stages, per scan (a volume of n_x traces x n_lines x n_t samples):

  0. CONDITIONING, per B-scan line: dewow (subtract a running mean along time),
     horizontal background removal (subtract a running median along X over W
     traces, which removes laterally continuous events such as the direct wave
     and flat reflectors), Hilbert envelope, then robust normalisation (median
     and MAD over the gated line) giving an envelope z-map.
  1. PROPOSALS: local envelope maxima above an adaptive threshold (the robust
     z, so the threshold follows each line's own noise level). They must
     persist across several traces: the ridge is tracked left and right of the
     apex while it stays above half the apex value.
  2. PHYSICAL SHAPE: a point or cylindrical scatterer gives a diffraction
     hyperbola t(x) = t_s + sqrt(tau0^2 + (2 dx / v)^2), where tau0 is the
     apex time after the surface reflection and v lies in a physical range for
     concrete. The envelope is stacked along that hyperbola for each v in the
     grid, and the best v is kept. Sub-scores:
       fit         mean envelope along the hyperbola arms / apex envelope
       curvature   how much better the hyperbola stack is than a flat line
                   (a layer or step edge gives a flat stack equal to the
                   hyperbola stack)
       symmetry    1 - |L - R| / (L + R) of the two arm stacks
       continuity  fraction of arm offsets with envelope >= 0.25 x apex
       stability   apex stack / max(apex stack, stacks one or two traces aside)
       frequency   dominant frequency at the apex relative to the scan median
                   (feeds noise_penalty, not shape)
     shape_score is the geometric mean of the five sub-scores.
  3. SPATIAL PERSISTENCE: the fraction of neighbouring lines (up to
     +/- PERSIST_LINES) that hold a stage-1 proposal within PERSIST_DX_MM and
     PERSIST_DT_NS. Real objects are continuous across lines; noise is not.
  4. NMS AND CLUSTERING: per-line non-maximum suppression on the final score,
     in the same window as the envelope baseline (100 mm x 0.5 ns), then
     union-find clustering of survivors across adjacent lines.

Component scores, each in [0, 1]:
  signal_strength       1 - exp(-z / 10), z = robust envelope z at the apex
  background_contrast   1 - (median envelope of a lateral annulus at the same
                        time) / (apex envelope), clipped
  shape_score           as above
  persistence_score     as above
  noise_penalty         spectral mismatch, 1 - exp(-ln(f / f_ref)^2 / (2 s^2))
  direct_wave_penalty   exp(-(t - t_dw) / lambda), t_dw = blind direct-wave
                        time estimated from the scan itself

final_score = mean(signal_strength, background_contrast, shape_score,
              persistence_score) - 0.25 noise_penalty - 0.25 direct_wave_penalty.
The weights were fixed before any evaluation; they are not tuned.

The hard filters (F_*) are the gates whose effect is measured by ablation:
  F_lateral       lateral ridge extent >= min_lateral_extent_mm
  F_shape         shape_score >= shape_min
  F_persistence   persistence_score >= persistence_min
  F_penalties     direct_wave_penalty <= 0.5 and noise_penalty <= 0.8
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from scipy.ndimage import maximum_filter, median_filter, uniform_filter1d
from scipy.signal import hilbert

#: Shared with the envelope baseline so the arms differ only where intended.
TARGET_MIN_NS = 1.2
END_GUARD_NS = 0.5
FINAL_NMS_X_MM, FINAL_NMS_T_NS = 100.0, 0.5

DEWOW_NS = 2.0
PROP_NMS_X_MM, PROP_NMS_T_NS = 25.0, 0.15
V_GRID_M_PER_NS = (0.08, 0.10, 0.12, 0.14, 0.16)   # concrete, eps_r ~3.5-14
ARM_HALF_WIDTH_MM = 150.0
T_TOLERANCE_NS = 0.06
ANNULUS_MM = (150.0, 300.0)
PERSIST_LINES = 6
#: Tightened on the development scan only: at 25 mm / 0.3 ns almost every
#: proposal had support on every neighbouring line (no discrimination).
PERSIST_DX_MM, PERSIST_DT_NS = 10.0, 0.1
CLUSTER_DX_MM, CLUSTER_DT_NS, CLUSTER_LINE_GAP = 25.0, 0.3, 2
DIRECT_WAVE_DECAY_NS = 0.5
FREQ_SIGMA_LN = 0.35
SPECTRAL_HALF_WINDOW_NS = 0.75
WEIGHTS = {"signal_strength": 0.25, "background_contrast": 0.25, "shape_score": 0.25,
           "persistence_score": 0.25, "noise_penalty": -0.25, "direct_wave_penalty": -0.25}
FILTERS = ("F_lateral", "F_shape", "F_persistence", "F_penalties")


@dataclass(frozen=True)
class V2Params:
    background_window_traces: int = 81
    proposal_threshold: float = 4.0
    min_lateral_extent_mm: float = 20.0
    shape_min: float = 0.3
    persistence_min: float = 0.25
    disabled: frozenset = field(default_factory=frozenset)   # filters switched off (ablation)
    conditioning: bool = True                                  # False: envelope of raw traces

    def without(self, *filters: str) -> "V2Params":
        unknown = set(filters) - set(FILTERS)
        if unknown:
            raise ValueError(f"unknown filters {unknown}")
        return replace(self, disabled=self.disabled | frozenset(filters))


# ------------------------------------------------------------- stage 0
def condition_line(traces: np.ndarray, dt: float, W: int, conditioning: bool = True) -> np.ndarray:
    """Envelope of the conditioned B-scan (n_x, n_t)."""
    x = traces.astype(float)
    if conditioning:
        x = x - uniform_filter1d(x, size=max(3, int(round(DEWOW_NS / dt))), axis=1, mode="nearest")
        x = x - median_filter(x, size=(W, 1), mode="nearest")
    else:
        x = x - x.mean(axis=1, keepdims=True)
    return np.abs(hilbert(x, axis=1)), x


def robust_z(env: np.ndarray, i0: int, i1: int) -> np.ndarray:
    g = env[:, i0:i1]
    med = np.median(g)
    mad = np.median(np.abs(g - med)) * 1.4826 + 1e-12
    return (env - med) / mad


def direct_wave_time(volume: np.ndarray, dt: float) -> float:
    """Blind: time of the strongest mean-trace envelope peak in the first 3 ns."""
    n = min(volume.shape[2], int(3.0 / dt))
    mean_trace = volume.reshape(-1, volume.shape[2]).mean(axis=0)
    e = np.abs(hilbert(mean_trace - mean_trace.mean()))
    return float(np.argmax(e[:n]) * dt)


# ------------------------------------------------------------- stages 1-2
def _proposals_on_line(z, env, cond, dt, dx, i0, i1, p: V2Params):
    fx = max(1, int(round(PROP_NMS_X_MM / dx))) | 1
    ft = max(1, int(round(PROP_NMS_T_NS / dt))) | 1
    gated = np.full_like(z, -np.inf)
    gated[:, i0:i1] = z[:, i0:i1]
    peaks = (gated == maximum_filter(gated, size=(fx, ft), mode="nearest")) & (gated >= p.proposal_threshold)
    xi, ti = np.nonzero(peaks)
    return xi, ti


def _lateral_extent(env, xi, ti, n_x):
    """Ridge tracked +/-1 sample per trace while >= half the apex envelope."""
    out = np.zeros(xi.size)
    n_t = env.shape[1]
    for k, (x0, t0) in enumerate(zip(xi, ti)):
        half = 0.5 * env[x0, t0]
        width = 0
        for step in (-1, 1):
            x, t = x0, t0
            while True:
                x += step
                if x < 0 or x >= n_x:
                    break
                lo, hi = max(0, t - 1), min(n_t, t + 2)
                j = lo + int(np.argmax(env[x, lo:hi]))
                if env[x, j] < half:
                    break
                t = j
                width += 1
        out[k] = width
    return out


def _shape(env, xi, ti, dt, dx, t_surface):
    """Hyperbola stack sub-scores for every proposal (vectorised)."""
    n_x, n_t = env.shape
    K = int(round(ARM_HALF_WIDTH_MM / dx))
    offs = np.arange(-K, K + 1)
    arm = np.abs(offs) >= max(1, K // 3)
    tol = max(1, int(round(T_TOLERANCE_NS / dt)))
    P = xi.size
    apex = env[xi, ti] + 1e-12
    tau0 = np.maximum((ti * dt) - t_surface, 0.2)

    def stack_at(xc, tc_ns_rows):
        # tc_ns_rows: (P, len(offs)) times; returns (P, len(offs)) envelope, max over +/-tol, NaN off-grid
        xs = xc[:, None] + offs[None, :]
        valid = (xs >= 0) & (xs < n_x)
        xs = np.clip(xs, 0, n_x - 1)
        tt = np.rint(tc_ns_rows / dt).astype(int)
        best = np.full(xs.shape, -np.inf)
        for d in range(-tol, tol + 1):
            t2 = tt + d
            ok = (t2 >= 0) & (t2 < n_t)
            v = np.where(ok, env[xs, np.clip(t2, 0, n_t - 1)], -np.inf)
            best = np.maximum(best, v)
        best[~valid] = np.nan
        best[~np.isfinite(best)] = np.nan
        return best

    dxm = np.abs(offs) * dx / 1000.0
    best_fit = np.full(P, -np.inf)
    best_prof = np.zeros((P, offs.size))
    best_v = np.zeros(P)
    for v in V_GRID_M_PER_NS:
        t_h = t_surface + np.sqrt(tau0[:, None] ** 2 + (2 * dxm[None, :] / v) ** 2)
        prof = stack_at(xi, t_h) / apex[:, None]
        fit = np.nanmean(np.where(arm[None, :], prof, np.nan), axis=1)
        fit = np.nan_to_num(fit, nan=0.0)
        better = fit > best_fit
        best_fit = np.where(better, fit, best_fit)
        best_prof[better] = prof[better]
        best_v = np.where(better, v, best_v)
    flat_t = np.repeat((ti * dt)[:, None], offs.size, axis=1)
    flat = np.nanmean(np.where(arm[None, :], stack_at(xi, flat_t) / apex[:, None], np.nan), axis=1)
    flat = np.nan_to_num(flat, nan=0.0)

    def _arm_mean(mask):
        a = np.where(mask[None, :], best_prof, np.nan)
        n = np.sum(~np.isnan(a), axis=1)
        return np.where(n > 0, np.nansum(a, axis=1) / np.maximum(n, 1), 0.0)

    left, right = _arm_mean((offs < 0) & arm), _arm_mean((offs > 0) & arm)
    symmetry = 1.0 - np.abs(left - right) / (left + right + 1e-12)
    armp = np.where(arm[None, :], best_prof, np.nan)
    continuity = np.nanmean(np.where(np.isnan(armp), np.nan, (armp >= 0.25).astype(float)), axis=1)
    continuity = np.nan_to_num(continuity, nan=0.0)
    curvature = np.clip((best_fit - flat) / (best_fit + 1e-12), 0.0, 1.0)
    fit_c = np.clip(best_fit, 0.0, 1.0)

    # apex stability: same hyperbola, apex shifted by 1 and 2 traces
    t_best = t_surface + np.sqrt(tau0[:, None] ** 2 + (2 * dxm[None, :] / best_v[:, None]) ** 2)
    s0 = np.nansum(stack_at(xi, t_best), axis=1)
    s_side = np.zeros(P)
    for sh in (-2, -1, 1, 2):
        s_side = np.maximum(s_side, np.nansum(stack_at(np.clip(xi + sh, 0, n_x - 1), t_best), axis=1))
    stability = s0 / np.maximum(np.maximum(s0, s_side), 1e-12)

    subs = np.vstack([fit_c, curvature, symmetry, continuity, stability])
    shape = np.exp(np.mean(np.log(np.clip(subs, 1e-6, 1.0)), axis=0))
    return {"fit": fit_c, "curvature": curvature, "symmetry": symmetry, "continuity": continuity,
            "stability": stability, "shape_score": shape, "velocity_m_per_ns": best_v}


def _contrast(env, xi, ti, dx, dt):
    n_x = env.shape[0]
    a0, a1 = int(round(ANNULUS_MM[0] / dx)), int(round(ANNULUS_MM[1] / dx))
    tw = max(1, int(round(0.15 / dt)))
    out = np.zeros(xi.size)
    for k, (x0, t0) in enumerate(zip(xi, ti)):
        cols = [c for c in list(range(x0 - a1, x0 - a0 + 1)) + list(range(x0 + a0, x0 + a1 + 1))
                if 0 <= c < n_x]
        if not cols:
            continue
        bg = np.median(env[cols, max(0, t0 - tw):t0 + tw + 1].max(axis=1))
        out[k] = np.clip(1.0 - bg / (env[x0, t0] + 1e-12), 0.0, 1.0)
    return out


def _dominant_freq(cond, xi, ti, dt):
    h = max(4, int(round(SPECTRAL_HALF_WINDOW_NS / dt)))
    n_t = cond.shape[1]
    win = np.hanning(2 * h + 1)
    idx = np.clip(ti[:, None] + np.arange(-h, h + 1)[None, :], 0, n_t - 1)
    seg = cond[xi[:, None], idx] * win[None, :]
    nfft = 4 * (2 * h + 1)
    spec = np.abs(np.fft.rfft(seg, n=nfft, axis=1))
    freqs = np.fft.rfftfreq(nfft, d=dt)            # GHz
    spec[:, 0] = 0
    return freqs[np.argmax(spec, axis=1)]


# ------------------------------------------------------------- public
def propose(volume: np.ndarray, x_mm: np.ndarray, y_mm: np.ndarray, t_ns: np.ndarray,
            params: V2Params = V2Params()) -> list[dict]:
    """
    Stages 0-3 for a whole scan: every proposal with its component scores.
    Filters and NMS are applied separately (`select`) so ablations are cheap.
    `volume` is (n_x, n_lines, n_t).
    """
    dt = float(t_ns[1] - t_ns[0])
    dx = float(x_mm[1] - x_mm[0])
    n_x, n_lines, n_t = volume.shape
    i0, i1 = int(TARGET_MIN_NS / dt), n_t - int(END_GUARD_NS / dt)
    t_dw = direct_wave_time(volume, dt)
    props = []
    for j in range(n_lines):
        env, cond = condition_line(volume[:, j, :], dt, params.background_window_traces, params.conditioning)
        z = robust_z(env, i0, i1)
        xi, ti = _proposals_on_line(z, env, cond, dt, dx, i0, i1, params)
        if xi.size == 0:
            continue
        ext = _lateral_extent(env, xi, ti, n_x) * dx
        shp = _shape(env, xi, ti, dt, dx, t_dw)
        con = _contrast(env, xi, ti, dx, dt)
        fdom = _dominant_freq(cond, xi, ti, dt)
        for k in range(xi.size):
            props.append({
                "line": j, "y": float(y_mm[j]), "x": float(x_mm[xi[k]]), "t_ns": float(t_ns[ti[k]]),
                "trace": int(xi[k]), "sample": int(ti[k]),
                "z_env": float(z[xi[k], ti[k]]), "lateral_extent_mm": float(ext[k]),
                "f_dom_ghz": float(fdom[k]),
                "signal_strength": float(1.0 - np.exp(-max(z[xi[k], ti[k]], 0.0) / 10.0)),
                "background_contrast": float(con[k]),
                "shape": {s: float(shp[s][k]) for s in ("fit", "curvature", "symmetry", "continuity",
                                                         "stability", "velocity_m_per_ns")},
                "shape_score": float(shp["shape_score"][k]),
                "direct_wave_penalty": float(np.clip(np.exp(-(t_ns[ti[k]] - t_dw) / DIRECT_WAVE_DECAY_NS), 0, 1)),
            })
    if not props:
        return props
    f_ref = float(np.median([p["f_dom_ghz"] for p in props]))
    for p in props:
        r = np.log(max(p["f_dom_ghz"], 1e-6) / max(f_ref, 1e-6))
        p["noise_penalty"] = float(1.0 - np.exp(-(r ** 2) / (2 * FREQ_SIGMA_LN ** 2)))
    _persistence(props, n_lines, params)
    for p in props:
        p["final_score"] = float(sum(w * p[k] for k, w in WEIGHTS.items()))
    return props


def _persistence(props, n_lines, params: V2Params):
    """Fraction of neighbouring lines holding a laterally persistent proposal nearby."""
    support = {}
    for i, p in enumerate(props):
        if p["lateral_extent_mm"] >= params.min_lateral_extent_mm:
            support.setdefault(p["line"], []).append((p["x"], p["t_ns"]))
    arr = {j: np.array(v) for j, v in support.items()}
    for p in props:
        j = p["line"]
        avail, hit = 0, 0
        for d in range(-PERSIST_LINES, PERSIST_LINES + 1):
            if d == 0 or not (0 <= j + d < n_lines):
                continue
            avail += 1
            a = arr.get(j + d)
            if a is not None and np.any((np.abs(a[:, 0] - p["x"]) <= PERSIST_DX_MM)
                                        & (np.abs(a[:, 1] - p["t_ns"]) <= PERSIST_DT_NS)):
                hit += 1
        p["persistence_score"] = hit / avail if avail else 0.0


def passes(p: dict, params: V2Params) -> dict:
    """Per-filter verdicts for one proposal (True = kept by that filter)."""
    return {
        "F_lateral": p["lateral_extent_mm"] >= params.min_lateral_extent_mm,
        "F_shape": p["shape_score"] >= params.shape_min,
        "F_persistence": p["persistence_score"] >= params.persistence_min,
        "F_penalties": p["direct_wave_penalty"] <= 0.5 and p["noise_penalty"] <= 0.8,
    }


def select(props: list[dict], params: V2Params, dx_mm: float = 5.0) -> list[dict]:
    """Stage 4: apply the enabled filters, per-line NMS on final_score, clustering."""
    kept = [p for p in props
            if all(ok or name in params.disabled for name, ok in passes(p, params).items())]
    by_line: dict[int, list] = {}
    for p in kept:
        by_line.setdefault(p["line"], []).append(p)
    out = []
    for j in sorted(by_line):
        chosen = []
        for p in sorted(by_line[j], key=lambda q: (-q["final_score"], q["x"], q["t_ns"])):
            if all(abs(p["x"] - c["x"]) > FINAL_NMS_X_MM / 2 or abs(p["t_ns"] - c["t_ns"]) > FINAL_NMS_T_NS / 2
                   for c in chosen):
                chosen.append(p)
        out.extend(chosen)
    _cluster(out)
    return out


def _cluster(dets):
    parent = list(range(len(dets)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_line: dict[int, list] = {}
    for i, d in enumerate(dets):
        by_line.setdefault(d["line"], []).append(i)
    for j, idx in by_line.items():
        for g in range(1, CLUSTER_LINE_GAP + 1):
            for a in idx:
                for b in by_line.get(j + g, []):
                    if (abs(dets[a]["x"] - dets[b]["x"]) <= CLUSTER_DX_MM
                            and abs(dets[a]["t_ns"] - dets[b]["t_ns"]) <= CLUSTER_DT_NS):
                        parent[find(a)] = find(b)
    roots = {}
    for i, d in enumerate(dets):
        d["cluster"] = roots.setdefault(find(i), len(roots))


def detect(volume, x_mm, y_mm, t_ns, params: V2Params = V2Params()) -> list[dict]:
    return select(propose(volume, x_mm, y_mm, t_ns, params), params)
