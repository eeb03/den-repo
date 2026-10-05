"""
EXPERIMENTAL calibrated candidate generator ("Candidate V2-cal"). Research only.

Status: EXPERIMENTAL (benchmark.gates.CAPABILITY_STATUS
["candidate_generation_v2_calibrated"]). No production path imports this
module, and the production detector is unchanged. The previous Candidate V2
(`benchmark.candidate_v2`) is also unchanged; three of its private helpers are
imported, not edited.

TRUTH-BLIND. This module imports no truth module and reads no manifest. Its
only external physical input is an optional `calibration`:
    {"t0_ns", "velocity_m_per_ns", "pick_convention", "pick_precision_ns"}
which the CALLER may pass only when the line's depth_calibration is
scientifically sufficient (accepted, >= 3 reflectors, leave-one-out passed).
With `calibration=None` the generator runs UNCALIBRATED: it never invents a
velocity or a time zero. It then uses the scan's own blind direct-wave time as
an exclusion gate only, searches a velocity grid for shape (as V2 did), and
reports no depth. Every proposal says which basis it used (`physics_basis`).

It is a HIGH-RECALL PROPOSAL GENERATOR with separate, interpretable evidence
terms. The only hard gates are the proposal threshold and the lateral extent.
Hyperbola shape is evidence in the score, never a filter.

FREQUENCY. Every time tolerance is a fraction of the dominant period P = 1/f_c,
with f_c measured blind from the scan (mean conditioned spectrum).

Stage A, conditioning, per B-scan line:
  dewow (running mean over DEWOW_NS); horizontal background removal (running
  median over W traces); Hilbert envelope. Then ROBUST PER-TIME-ROW
  normalisation, one of two (chosen on development data): "line", the median
  and MAD of the gated line (as V2), or "row", the median and MAD at each time
  sample across every trace of every line. Direct-wave
  exclusion: t >= t_dw + 0.5 P, where t_dw is the calibrated t0 (peak
  convention) or, uncalibrated, the blind direct-wave time. Late-time noise:
  each time row's robust scale is compared with the scan's noise floor.
  Structure and edges: on the dewowed envelope WITHOUT background removal,
  a lateral running median over STRUCT_WINDOW_MM marks laterally continuous
  events; those prominent against their own time-local level AND flat over at
  least HORIZON_MIN_RUN_MM are "horizons" (back walls, layers). Horizon endpoints mark step edges and terminations.
  Ringing: a proposal with an earlier, at least as strong proposal directly
  above it (within 0.75-4 P) is more likely a reverberation or multiple.

Stage B, proposals: local maxima of the row-normalised envelope z (window
  25 mm x 0.25 P) above the proposal threshold, with lateral ridge extent
  (tracked while >= half the apex), lateral background contrast (annulus), and
  cross-line persistence.

Stage C, physical consistency. Calibrated: the apex depth is
  d = v (t_a - t0) / 2 and the response of a reflector of half-width a is
      t(x) = t0 + sqrt((t_a - t0)^2 + (2 max(|x - x_a| - a, 0) / v)^2)
  with v FIXED by the calibration (a point or thin cylinder is a = 0; a = 30
  and 60 mm allow flat-topped, void-like reflectors with edge diffractions, so
  a non-hyperbolic response is not forced into a point-diffractor model).
  The envelope is stacked along this curve within +/- 0.2 P. Sub-scores: fit,
  velocity consistency (the calibrated curve must explain the response at
  least as well as a flat line and curves at 0.6 v and 1.6 v), symmetry,
  continuity. Uncalibrated: same, with v searched over V_GRID and the
  velocity-consistency term computed against the flat line only.
  depth_plausibility: 0 if the apex would be above the surface, ramped to 1
  at MIN_COVER_M (calibrated only), and reduced to BELOW_STRUCTURE_FACTOR when
  the apex is below the strongest horizon at that position.

Stage D, duplicates: per-line NMS on the final score within +/- 50 mm and
  +/- 0.75 P (the envelope side lobe of one wavelet), then union-find
  clustering across adjacent lines.

Stage E, confidence. Components in [0, 1]:
  signal_strength, background_contrast, persistence, shape_consistency,
  depth_plausibility (evidence) and direct_wave_penalty, edge_penalty,
  structure_penalty, ringing_penalty, noise_penalty (penalties).
  final_score = mean(evidence) - PENALTY_WEIGHT * sum(penalties). The weights
  are fixed in advance, not tuned. Ablations remove one term at a time.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field, replace

import numpy as np
from scipy.ndimage import distance_transform_edt, label, maximum_filter, median_filter, uniform_filter1d
from scipy.ndimage import median as ndi_median
from scipy.signal import hilbert

from benchmark.candidate_v2 import _contrast, _dominant_freq, _lateral_extent, direct_wave_time

END_GUARD_NS = 0.5
DEWOW_NS = 2.0
PROP_NMS_X_MM = 25.0
PROP_NMS_T_PERIODS = 0.25
SHAPE_TOL_PERIODS = 0.2
ARM_MAX_MM = 200.0
ARM_MAX_PERIODS = 2.0
HALF_WIDTHS_MM = (0.0, 30.0, 60.0)
V_GRID_M_PER_NS = (0.08, 0.10, 0.12, 0.14, 0.16)
WRONG_V_FACTORS = (0.6, 1.6)
PERSIST_LINES, PERSIST_DX_MM, PERSIST_DT_PERIODS = 6, 10.0, 0.15
NMS_X_MM, NMS_T_PERIODS = 50.0, 0.75
CLUSTER_DX_MM, CLUSTER_DT_PERIODS, CLUSTER_LINE_GAP = 25.0, 0.4, 2
STRUCT_WINDOW_MM = 400.0
STRUCT_LOCAL_PERIODS = 3.0
HORIZON_MIN_RUN_MM = 300.0
RING_DX_MM, RING_MAX_PERIODS, RING_AMP_RATIO = 25.0, 4.0, 1.0
EDGE_LAG_MM = 50.0
EDGE_SIGMA_MM, EDGE_SIGMA_PERIODS = 40.0, 1.0
STRUCT_SIGMA_MM, STRUCT_SIGMA_PERIODS = 10.0, 0.4
MIN_COVER_M = 0.015
BELOW_STRUCTURE_FACTOR = 0.3
Z_SCALE = 10.0
FREQ_SIGMA_LN = 0.35
PENALTY_WEIGHT = 0.25
EVIDENCE = ("signal_strength", "background_contrast", "persistence", "shape_consistency",
            "depth_plausibility")
PENALTIES = ("direct_wave_penalty", "edge_penalty", "structure_penalty", "ringing_penalty",
             "noise_penalty")


@dataclass(frozen=True)
class V2CalParams:
    background_window_traces: int = 81
    horizon_ratio: float = 2.0           # horizon: lateral-median envelope >= ratio x its time-local level
    proposal_threshold: float = 4.0      # robust row-z
    min_lateral_extent_mm: float = 15.0
    normalisation: str = "line"          # "line": median/MAD of the gated line; "row": per time row over the scan
    use_calibration: bool = True         # False: ignore a supplied calibration (ablation)
    dropped_terms: frozenset = field(default_factory=frozenset)   # score-term ablation

    def without(self, *terms: str) -> "V2CalParams":
        unknown = set(terms) - set(EVIDENCE) - set(PENALTIES)
        if unknown:
            raise ValueError(f"unknown terms {unknown}")
        return replace(self, dropped_terms=self.dropped_terms | frozenset(terms))


def _check_calibration(cal):
    if cal is None:
        return None
    need = ("t0_ns", "velocity_m_per_ns", "pick_convention")
    if any(cal.get(k) is None for k in need):
        raise ValueError(f"calibration must carry {need}; pass None when there is none")
    v = float(cal["velocity_m_per_ns"])
    if not 0.01 <= v <= 0.30:
        raise ValueError("calibrated velocity outside 0.01-0.30 m/ns")
    return {"t0_ns": float(cal["t0_ns"]), "v": v, "pick_convention": cal["pick_convention"]}


def dominant_frequency_ghz(volume: np.ndarray, dt: float, t_from_ns: float) -> float:
    """Blind: peak of the mean amplitude spectrum of dewowed traces after t_from."""
    n_x, n_l, n_t = volume.shape
    i0 = min(n_t - 8, max(0, int(t_from_ns / dt)))
    sub = volume[::8, ::8, i0:].reshape(-1, n_t - i0).astype(float)
    sub = sub - uniform_filter1d(sub, size=max(3, int(round(DEWOW_NS / dt))), axis=1, mode="nearest")
    spec = np.abs(np.fft.rfft(sub * np.hanning(sub.shape[1])[None, :], axis=1)).mean(0)
    f = np.fft.rfftfreq(sub.shape[1], d=dt)
    spec[f < 0.2] = 0
    return float(f[int(np.argmax(spec))])


# ------------------------------------------------------------- stage A
def _condition(traces, dt, W):
    x = traces.astype(float)
    x = x - uniform_filter1d(x, size=max(3, int(round(DEWOW_NS / dt))), axis=1, mode="nearest")
    raw_env = np.abs(hilbert(x, axis=1))
    cond = x - median_filter(x, size=(W, 1), mode="nearest")
    return np.abs(hilbert(cond, axis=1)), cond, raw_env


def _structure_maps(raw_env, dt, dx, P, i0, i1, ratio):
    """
    Horizon mask, edge and structure penalty maps, and the time of the most
    prominent horizon per trace. A horizon is a local maximum in time of the
    lateral running median (over STRUCT_WINDOW_MM) of the dewowed envelope that
    is `ratio` times its own time-local level (running median over
    +/- STRUCT_LOCAL_PERIODS P) and above the line's continuous-energy floor.
    Time-local prominence, not a line-wide level, so an attenuated deep back
    wall is still recognised as structure.
    """
    n_x, n_t = raw_env.shape
    wc = max(3, int(round(STRUCT_WINDOW_MM / dx))) | 1
    cont = median_filter(raw_env, size=(wc, 1), mode="nearest")
    local = median_filter(cont, size=(1, 2 * max(1, int(round(STRUCT_LOCAL_PERIODS * P / dt))) + 1),
                          mode="nearest") + 1e-12
    floor = np.percentile(cont[:, i0:i1], 10) + 1e-12
    prominence = cont / local
    tw = max(1, int(round(0.25 * P / dt)))
    is_max = cont == maximum_filter(cont, size=(1, 2 * tw + 1), mode="nearest")
    H = is_max & (prominence >= ratio) & (cont >= 2.0 * floor)
    H[:, :i0] = False
    H[:, i1:] = False
    # DEV ITERATION 2: a horizon must be FLAT and laterally continuous: at least
    # HORIZON_MIN_RUN_MM of positions within +/- 0.25 P of the component's
    # median time. Without this, the broad apex and arms of a deep compact
    # scatterer (a duct at 241 mm on the development scan) passed as a
    # "horizon" and were then penalised as structure and as a step edge.
    lab, n = label(maximum_filter(H, size=(1, 3)) & (cont >= 2.0 * floor), structure=np.ones((3, 3)))
    if n:
        ts = np.broadcast_to(np.arange(n_t)[None, :], (n_x, n_t))
        xs = np.broadcast_to(np.arange(n_x)[:, None], (n_x, n_t))
        sel = lab > 0
        med_t = np.zeros(n + 1)
        med_t[1:] = ndi_median(ts, lab, index=np.arange(1, n + 1))
        near = sel & (np.abs(ts - med_t[lab]) <= max(1, int(round(0.25 * P / dt))))
        pairs = np.unique(lab[near].astype(np.int64) * n_x + xs[near])
        counts = np.bincount((pairs // n_x).astype(int), minlength=n + 1)
        flat_long = counts * dx >= HORIZON_MIN_RUN_MM
        flat_long[0] = False
        H &= flat_long[lab]
    lag = max(1, int(round(EDGE_LAG_MM / dx)))
    Hd = maximum_filter(H, size=(1, 2 * max(1, int(round(0.15 * P / dt))) + 1))
    left = np.zeros_like(H)
    right = np.zeros_like(H)
    left[lag:] = Hd[:-lag]
    right[:-lag] = Hd[lag:]
    E = H & (~left | ~right)
    edge = np.zeros((n_x, n_t))
    struct = np.zeros((n_x, n_t))
    if E.any():
        d = distance_transform_edt(~E, sampling=(dx / EDGE_SIGMA_MM, dt / (EDGE_SIGMA_PERIODS * P)))
        edge = np.exp(-0.5 * d ** 2)
    if H.any():
        d = distance_transform_edt(~H, sampling=(dx / STRUCT_SIGMA_MM, dt / (STRUCT_SIGMA_PERIODS * P)))
        struct = np.exp(-0.5 * d ** 2)
    masked = np.where(H, prominence, -np.inf)
    t_base = np.where(H.any(axis=1), np.argmax(masked, axis=1) * dt, np.inf)
    return edge, struct, t_base, H


def _ringing(props, P):
    """1 when an earlier proposal at least as strong sits directly above (same
    trace +/- RING_DX_MM, 0.75-RING_MAX_PERIODS periods earlier): the later one
    is then more likely the earlier reflector's ringing or internal multiple."""
    by_line: dict[int, list] = {}
    for p in props:
        by_line.setdefault(p["line"], []).append(p)
    for line in by_line.values():
        xs = np.array([p["x"] for p in line])
        ts = np.array([p["t_ns"] for p in line])
        amp = np.array([p["_amp"] for p in line])
        for k, p in enumerate(line):
            dtk = p["t_ns"] - ts
            above = ((np.abs(xs - p["x"]) <= RING_DX_MM) & (dtk >= 0.75 * P)
                     & (dtk <= RING_MAX_PERIODS * P) & (amp >= RING_AMP_RATIO * p["_amp"]))
            p["ringing_penalty"] = 1.0 if above.any() else 0.0


# ------------------------------------------------------------- stage C
def _stack(env, xi, offs, t_rows_ns, dt, tol):
    n_x, n_t = env.shape
    xs = xi[:, None] + offs[None, :]
    valid = (xs >= 0) & (xs < n_x)
    xs = np.clip(xs, 0, n_x - 1)
    tt = np.rint(t_rows_ns / dt).astype(int)
    best = np.full(xs.shape, -np.inf)
    for d in range(-tol, tol + 1):
        t2 = tt + d
        ok = (t2 >= 0) & (t2 < n_t)
        best = np.maximum(best, np.where(ok, env[xs, np.clip(t2, 0, n_t - 1)], -np.inf))
    best[~valid | ~np.isfinite(best)] = np.nan
    return best


def _curve(t0, ta, dxm, a_m, v):
    lat = np.maximum(dxm[None, :] - a_m, 0.0)
    return t0 + np.sqrt((ta[:, None] - t0) ** 2 + (2 * lat / v) ** 2)


def _shape(env, xi, ti, dt, dx, P, t_ref, cal):
    """Shape sub-scores per proposal under the calibrated (or searched) velocity."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN arms are handled as 0
        return _shape_impl(env, xi, ti, dt, dx, P, t_ref, cal)


def _shape_impl(env, xi, ti, dt, dx, P, t_ref, cal):
    K = int(round(ARM_MAX_MM / dx))
    offs = np.arange(-K, K + 1)
    dxm = np.abs(offs) * dx / 1000.0
    tol = max(1, int(round(SHAPE_TOL_PERIODS * P / dt)))
    ta = ti * dt
    apex = env[xi, ti] + 1e-12
    tau = np.maximum(ta - t_ref, 0.25 * P)
    t_base = ta - tau                       # = t_ref unless the apex is within 0.25 P of it
    P_n = xi.size
    best = {"shape_consistency": np.zeros(P_n), "fit": np.zeros(P_n), "velocity_consistency": np.zeros(P_n),
            "symmetry": np.zeros(P_n), "continuity": np.zeros(P_n), "half_width_mm": np.zeros(P_n),
            "velocity_m_per_ns": np.zeros(P_n)}

    def fit_of(tcurve, arm):
        prof = np.minimum(_stack(env, xi, offs, tcurve, dt, tol) / apex[:, None], 1.0)
        a = np.where(arm, prof, np.nan)
        return np.nan_to_num(np.nanmean(a, axis=1), nan=0.0), a

    for a_mm in HALF_WIDTHS_MM:
        a_m = a_mm / 1000.0
        base_arm = (dxm[None, :] > a_m) & (np.abs(offs)[None, :] >= 1)
        velocities = (cal["v"],) if cal else V_GRID_M_PER_NS
        fit, prof, vbest = np.full(P_n, -1.0), np.full((P_n, offs.size), np.nan), np.zeros(P_n)
        for v in velocities:
            tc = _curve(0.0, tau, dxm, a_m, v) + t_base[:, None]
            arm = base_arm & ((tc - ta[:, None]) <= ARM_MAX_PERIODS * P)
            f, p = fit_of(tc, arm)
            better = f > fit
            fit = np.where(better, f, fit)
            prof[better] = p[better]
            vbest = np.where(better, v, vbest)
        arm_ok = ~np.isnan(prof)
        alt = []
        flat = np.repeat(ta[:, None], offs.size, axis=1)
        alt.append(fit_of(flat, arm_ok)[0])
        if cal:
            for fct in WRONG_V_FACTORS:
                tc = _curve(0.0, tau, dxm, a_m, cal["v"] * fct) + t_base[:, None]
                alt.append(fit_of(tc, base_arm & ((tc - ta[:, None]) <= ARM_MAX_PERIODS * P))[0])
        alt_best = np.max(np.vstack(alt), axis=0)
        vcons = np.clip(fit / np.maximum(np.maximum(fit, alt_best), 1e-12), 0, 1)
        vcons = np.clip((vcons - 0.5) * 2, 0, 1)           # 1 = model clearly best; 0 = an alternative as good
        left = np.nanmean(np.where(offs[None, :] < 0, prof, np.nan), axis=1)
        right = np.nanmean(np.where(offs[None, :] > 0, prof, np.nan), axis=1)
        left, right = np.nan_to_num(left), np.nan_to_num(right)
        sym = 1.0 - np.abs(left - right) / (left + right + 1e-12)
        cont = np.nan_to_num(np.nanmean(np.where(arm_ok, (prof >= 0.25).astype(float), np.nan), axis=1))
        fit_c = np.clip(fit, 0, 1)
        subs = np.vstack([fit_c, vcons, sym, cont])
        g = np.exp(np.mean(np.log(np.clip(subs, 1e-3, 1.0)), axis=0))
        better = g > best["shape_consistency"]
        for k, val in (("shape_consistency", g), ("fit", fit_c), ("velocity_consistency", vcons),
                       ("symmetry", sym), ("continuity", cont), ("half_width_mm", np.full(P_n, a_mm)),
                       ("velocity_m_per_ns", vbest)):
            best[k] = np.where(better, val, best[k])
    return best


# ------------------------------------------------------------- public
def propose(volume: np.ndarray, x_mm, y_mm, t_ns, params: V2CalParams = V2CalParams(),
            calibration: dict | None = None, min_threshold: float | None = None) -> dict:
    """
    Stages A-C and the evidence terms for a whole scan (n_x, n_lines, n_t).
    Returns {"proposals": [...], "scan": {...}}. `min_threshold` lets a grid
    compute proposals once at its lowest threshold; `select` applies the
    configured threshold and extent.
    """
    cal = _check_calibration(calibration) if params.use_calibration else None
    dt = float(t_ns[1] - t_ns[0])
    dx = float(x_mm[1] - x_mm[0])
    n_x, n_lines, n_t = volume.shape
    t_blind = direct_wave_time(volume, dt)
    t_dw = cal["t0_ns"] if cal else t_blind
    f_c = dominant_frequency_ghz(volume, dt, t_blind + 1.0)
    P = 1.0 / f_c
    i0 = int(np.ceil((t_dw + 0.5 * P) / dt))
    i1 = n_t - int(END_GUARD_NS / dt)
    thr = params.proposal_threshold if min_threshold is None else min(min_threshold, params.proposal_threshold)

    envs = np.empty((n_x, n_lines, n_t), np.float32)
    conds = np.empty((n_x, n_lines, n_t), np.float32)
    edge_m = np.empty((n_x, n_lines, n_t), np.float16)
    struct_m = np.empty((n_x, n_lines, n_t), np.float16)
    t_base = np.empty((n_x, n_lines))
    for j in range(n_lines):
        env, cond, raw = _condition(volume[:, j, :], dt, params.background_window_traces)
        envs[:, j], conds[:, j] = env, cond
        e, s, tb, _ = _structure_maps(raw, dt, dx, P, i0, i1, params.horizon_ratio)
        edge_m[:, j], struct_m[:, j], t_base[:, j] = e, s, tb
    flat = envs.reshape(-1, n_t)
    med = np.median(flat, axis=0)
    scale = np.median(np.abs(flat - med[None, :]), axis=0) * 1.4826 + 1e-12
    floor = float(np.percentile(scale[i0:i1], 10))
    row_noise = np.clip(floor / scale, 0, 1) ** 2

    props = []
    fx = max(1, int(round(PROP_NMS_X_MM / dx))) | 1
    ft = max(1, int(round(PROP_NMS_T_PERIODS * P / dt))) | 1
    for j in range(n_lines):
        env = envs[:, j].astype(float)
        if params.normalisation == "row":
            z = (env - med[None, :]) / scale[None, :]
        else:
            g = env[:, i0:i1]
            m = np.median(g)
            z = (env - m) / (np.median(np.abs(g - m)) * 1.4826 + 1e-12)
        gated = np.full_like(z, -np.inf)
        gated[:, i0:i1] = z[:, i0:i1]
        pk = (gated == maximum_filter(gated, size=(fx, ft), mode="nearest")) & (gated >= thr)
        xi, ti = np.nonzero(pk)
        if xi.size == 0:
            continue
        ext = _lateral_extent(env, xi, ti, n_x) * dx
        shp = _shape(env, xi, ti, dt, dx, P, t_dw, cal)
        con = _contrast(env, xi, ti, dx, dt)
        fdom = _dominant_freq(conds[:, j].astype(float), xi, ti, dt)
        for k in range(xi.size):
            x0, s0 = int(xi[k]), int(ti[k])
            t = float(t_ns[s0])
            if cal:
                depth = cal["v"] * (t - cal["t0_ns"]) / 2.0
                dp = float(np.clip(depth / MIN_COVER_M, 0.0, 1.0))
            else:
                depth, dp = None, 1.0
            if t > t_base[x0, j] + 0.5 * P:
                dp *= BELOW_STRUCTURE_FACTOR
            props.append({
                "line": j, "y": float(y_mm[j]), "x": float(x_mm[x0]), "t_ns": t,
                "trace": x0, "sample": s0, "z_row": float(z[x0, s0]),
                "lateral_extent_mm": float(ext[k]), "f_dom_ghz": float(fdom[k]),
                "depth_m": None if depth is None else float(depth),
                "physics_basis": ("calibrated_from_known_geometry" if cal
                                  else "uncalibrated: velocity searched, no depth"),
                "shape": {s: float(shp[s][k]) for s in ("fit", "velocity_consistency", "symmetry",
                                                         "continuity", "half_width_mm",
                                                         "velocity_m_per_ns")},
                "signal_strength": float(1.0 - np.exp(-max(z[x0, s0], 0.0) / Z_SCALE)),
                "background_contrast": float(con[k]),
                "shape_consistency": float(shp["shape_consistency"][k]),
                "depth_plausibility": dp,
                "direct_wave_penalty": float(np.clip(np.exp(-(t - t_dw - 0.5 * P) / (0.5 * P)), 0, 1)),
                "edge_penalty": float(edge_m[x0, j, s0]),
                "structure_penalty": float(struct_m[x0, j, s0]),
                "_late": float(row_noise[s0]), "_amp": float(env[x0, s0]),
            })
    scan = {"dominant_frequency_ghz": f_c, "period_ns": P, "t_direct_wave_ns": t_dw,
            "t_direct_wave_basis": "calibrated t0 (peak)" if cal else "blind direct-wave peak",
            "gate_start_ns": i0 * dt, "noise_floor": floor,
            "physics_basis": "calibrated_from_known_geometry" if cal else "uncalibrated",
            "calibration_used": cal}
    if not props:
        return {"proposals": [], "scan": scan}
    f_ref = float(np.median([p["f_dom_ghz"] for p in props]))
    for p in props:
        r = np.log(max(p["f_dom_ghz"], 1e-6) / max(f_ref, 1e-6))
        spectral = 1.0 - np.exp(-(r ** 2) / (2 * FREQ_SIGMA_LN ** 2))
        p["noise_penalty"] = float(max(spectral, p.pop("_late")))
    _persistence(props, n_lines, P)
    _ringing(props, P)
    for p in props:
        p.pop("_amp")
    return {"proposals": props, "scan": scan}


def _persistence(props, n_lines, P):
    support: dict[int, list] = {}
    for p in props:
        support.setdefault(p["line"], []).append((p["x"], p["t_ns"]))
    arr = {j: np.array(v) for j, v in support.items()}
    dt_tol = PERSIST_DT_PERIODS * P
    for p in props:
        j, avail, hit = p["line"], 0, 0
        for d in range(-PERSIST_LINES, PERSIST_LINES + 1):
            if d == 0 or not (0 <= j + d < n_lines):
                continue
            avail += 1
            a = arr.get(j + d)
            if a is not None and np.any((np.abs(a[:, 0] - p["x"]) <= PERSIST_DX_MM)
                                        & (np.abs(a[:, 1] - p["t_ns"]) <= dt_tol)):
                hit += 1
        p["persistence"] = hit / avail if avail else 0.0


def final_score(p: dict, params: V2CalParams) -> float:
    ev = [p[k] for k in EVIDENCE if k not in params.dropped_terms]
    pen = sum(p[k] for k in PENALTIES if k not in params.dropped_terms)
    return float((np.mean(ev) if ev else 0.0) - PENALTY_WEIGHT * pen)


def select(result: dict, params: V2CalParams) -> list[dict]:
    """Hard gates (threshold, extent), final score, per-line NMS, cross-line clustering."""
    P = result["scan"]["period_ns"]
    kept = []
    for p in result["proposals"]:
        if p["z_row"] < params.proposal_threshold or p["lateral_extent_mm"] < params.min_lateral_extent_mm:
            continue
        kept.append({**p, "final_score": final_score(p, params)})
    by_line: dict[int, list] = {}
    for p in kept:
        by_line.setdefault(p["line"], []).append(p)
    out = []
    t_rad = NMS_T_PERIODS * P
    for j in sorted(by_line):
        chosen = []
        for p in sorted(by_line[j], key=lambda q: (-q["final_score"], q["x"], q["t_ns"])):
            if all(abs(p["x"] - c["x"]) > NMS_X_MM or abs(p["t_ns"] - c["t_ns"]) > t_rad for c in chosen):
                chosen.append(p)
        out.extend(chosen)
    _cluster(out, CLUSTER_DT_PERIODS * P)
    return out


def _cluster(dets, dt_tol):
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
                            and abs(dets[a]["t_ns"] - dets[b]["t_ns"]) <= dt_tol):
                        parent[find(a)] = find(b)
    roots: dict[int, int] = {}
    for i, d in enumerate(dets):
        d["cluster"] = roots.setdefault(find(i), len(roots))


def detect(volume, x_mm, y_mm, t_ns, params: V2CalParams = V2CalParams(), calibration=None):
    return select(propose(volume, x_mm, y_mm, t_ns, params, calibration), params)
