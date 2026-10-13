"""
EXPERIMENTAL hyperbola detector V2 (docs/hyperbola-v2-experiment.md). No
production path imports it.

Pieces, each pre-registered:

* canonical_line (§6.1): Fourier-resample time to CANONICAL_SPP samples per
  nominal period; regularise irregular trace spacing onto a uniform grid at
  the median step (linear interpolation along x).
* components (§2): the find_anomaly_candidates / detect_line rule, bit-for-bit
  (|z| > threshold, 4-connected, min_cells, peak = max |z| cell).
* group (§3): geometric NMS -- a detection is merged into a stronger one only
  if its apex lies inside the stronger one's aperture, ON its fitted curve
  (within delta_g), at a compatible velocity (kappa), and most of its own
  envelope support is shared (rho). No suppression radius.
* null_peaks / calibrated_threshold (§6.2): R_CAL trace permutations of the
  line itself, run through the same stack + components + grouping; the line's
  threshold is the value at which lambda0 null detections per line are
  expected (floored at Z_FLOOR). Ground-truth free.

Inference inputs: traces, positions, dt, time offset, nominal frequency, and a
data-derived time zero. Nothing from simulator truth or annotations.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.ndimage import maximum_filter1d
from scipy.signal import resample

from benchmark.hyperbola_stack import DEFAULT_CONE_DEG, MIN_HALF_APERTURE, envelope, estimate_time_zero
from benchmark.hyperbola_stack_fast import hyperbola_stack_fast, is_uniform
from interpretation.anomaly_candidates import DEFAULT_MIN_CELLS

CANONICAL_SPP = 20
R_CAL = 8
Z_FLOOR = 3.0
STACK_CFG = {"cone_half_angle_deg": DEFAULT_CONE_DEG, "tolerance_periods": 0.25}  # PR #12 frozen
A1_THRESHOLD = 6.0                                                             # PR #12 frozen
SUPPORT_MAD_K = 3.0
#: §3 grid, in pre-registered order.
GROUPING_GRID = tuple({"delta_periods": d, "kappa": k, "rho": r}
                      for d in (0.5, 1.0) for k in (0.25, math.inf) for r in (0.3, 0.6))
LAMBDA0_GRID = (0.1, 0.25, 0.5, 1.0)


# --- canonical input --------------------------------------------------------------------

@dataclass
class Canonical:
    traces: np.ndarray        # (n_traces, n_samples), raw (before any background step)
    x_m: np.ndarray
    dt_s: float
    time_offset_s: float
    x_original_m: np.ndarray
    resampled: bool
    regularised: bool

    def original_trace(self, x: float) -> int:
        return int(np.argmin(np.abs(self.x_original_m - x)))


def canonical_line(traces: np.ndarray, x_m: np.ndarray, dt_s: float, time_offset_s: float,
                   f_nominal_hz: float, spp: int = CANONICAL_SPP) -> Canonical:
    tr = np.asarray(traces, dtype=float)
    x = np.asarray(x_m, dtype=float)
    n_old = tr.shape[1]
    n_new = max(2, round(n_old * dt_s * f_nominal_hz * spp))
    resampled = n_new != n_old
    if resampled:
        tr = resample(tr, n_new, axis=1)
        dt = dt_s * n_old / n_new
    else:
        dt = dt_s
    regularised = not is_uniform(x)
    xu = x
    if regularised:
        order = np.argsort(x, kind="stable")
        xs, ts = x[order], tr[order]
        keep = np.concatenate([[True], np.diff(xs) > 0])
        xs, ts = xs[keep], ts[keep]
        step = float(np.median(np.diff(xs)))
        xu = xs[0] + np.arange(int(np.floor((xs[-1] - xs[0]) / step + 1e-9)) + 1) * step
        j = np.clip(np.searchsorted(xs, xu, side="right") - 1, 0, len(xs) - 2)
        w = ((xu - xs[j]) / (xs[j + 1] - xs[j]))[:, None]
        tr = ts[j] * (1 - w) + ts[j + 1] * w
    return Canonical(tr, xu, dt, time_offset_s, x, resampled, regularised)


# --- components (the detect_line rule) --------------------------------------------------

def components(z: np.ndarray, threshold: float, min_cells: int = DEFAULT_MIN_CELLS) -> list[dict]:
    """Same rule as benchmark.detection.detect_line, returning peak cells."""
    absz = np.abs(np.nan_to_num(z, nan=0.0))
    labeled, n = ndimage.label(absz > threshold)
    out = []
    for lab in range(1, n + 1):
        samples, tr_idx = np.nonzero(labeled == lab)
        if samples.size < min_cells:
            continue
        p = int(np.argmax(absz[samples, tr_idx]))
        out.append({"sample": int(samples[p]), "trace": int(tr_idx[p]),
                    "z": float(absz[samples[p], tr_idx[p]]), "n_cells": int(samples.size)})
    return out


# --- grouping / NMS ---------------------------------------------------------------------

@dataclass
class StackContext:
    """What grouping needs about one (canonical) line."""
    env_tol: np.ndarray       # (n_traces, n_samples), the tolerance-filtered envelope the stack used
    x_m: np.ndarray
    dt_s: float
    time_offset_s: float
    time_zero_s: float
    f_nominal_hz: float
    support_floor: float

    @classmethod
    def build(cls, traces_bg, x_m, dt_s, time_offset_s, time_zero_s, f_nominal_hz, env=None):
        env = envelope(np.asarray(traces_bg, dtype=float)) if env is None else env
        half_w = int(round(STACK_CFG["tolerance_periods"] / f_nominal_hz / dt_s))
        env_tol = maximum_filter1d(env, size=2 * half_w + 1, axis=1, mode="nearest") if half_w > 0 else env
        med = float(np.median(env_tol))
        mad = 1.4826 * float(np.median(np.abs(env_tol - med)))
        return cls(env_tol, np.asarray(x_m, float), dt_s, time_offset_s, time_zero_s, f_nominal_hz,
                   med + SUPPORT_MAD_K * mad)


def _curve(ctx: StackContext, det: dict):
    """(t_apex, half-aperture m, function x -> t) of a detection's fitted curve."""
    t_apex = ctx.time_offset_s + det["sample"] * ctx.dt_s
    tau = max(t_apex - ctx.time_zero_s, 0.0)
    v = det["v"]
    step = float(np.median(np.abs(np.diff(ctx.x_m)))) if ctx.x_m.size > 1 else 1.0
    half_ap = max(math.tan(math.radians(STACK_CFG["cone_half_angle_deg"])) * v * tau / 2,
                  MIN_HALF_APERTURE * step * (1 + 1e-9))
    x0 = ctx.x_m[det["trace"]]

    def t_of(x):
        return ctx.time_zero_s + np.sqrt(tau ** 2 + (2 * (np.asarray(x) - x0) / v) ** 2)
    return t_apex, half_ap, t_of


def support(ctx: StackContext, det: dict, delta_s: float) -> np.ndarray:
    """Flat indices (trace * n_samples + sample) of the cells on the detection's
    curve (within delta) inside its aperture whose envelope exceeds the floor."""
    _, half_ap, t_of = _curve(ctx, det)
    n_tr, n_s = ctx.env_tol.shape
    x0 = ctx.x_m[det["trace"]]
    traces = np.nonzero(np.abs(ctx.x_m - x0) <= half_ap)[0]
    if traces.size == 0:
        return np.empty(0, dtype=np.int64)
    centre = (t_of(ctx.x_m[traces]) - ctx.time_offset_s) / ctx.dt_s
    half = delta_s / ctx.dt_s
    out = []
    for i, c in zip(traces, centre):
        lo, hi = max(0, int(math.ceil(c - half))), min(n_s - 1, int(math.floor(c + half)))
        if hi < lo:
            continue
        j = np.arange(lo, hi + 1)
        j = j[ctx.env_tol[i, j] > ctx.support_floor]
        out.append(i * n_s + j)
    return np.concatenate(out) if out else np.empty(0, dtype=np.int64)


def group(dets: list[dict], ctx: StackContext, cfg: dict) -> list[dict]:
    """§3. `dets` carry sample, trace, z, v. Returns the kept detections (in
    descending z), each with `merged` = number of detections folded into it."""
    delta_s = cfg["delta_periods"] / ctx.f_nominal_hz
    kept: list[tuple[dict, tuple, np.ndarray]] = []
    for d in sorted(dets, key=lambda d: -d["z"]):
        if not np.isfinite(d.get("v", np.nan)):
            kept.append(({**d, "merged": 0}, None, np.empty(0, dtype=np.int64)))
            continue
        t_b = ctx.time_offset_s + d["sample"] * ctx.dt_s
        x_b = ctx.x_m[d["trace"]]
        s_b = None
        merged_into = None
        for a, (t_a, half_a, t_of_a), s_a in ((k[0], k[1], k[2]) for k in kept if k[1] is not None):
            if abs(x_b - ctx.x_m[a["trace"]]) > half_a:
                continue
            if abs(t_b - float(t_of_a(x_b))) > delta_s:
                continue
            if abs(d["v"] - a["v"]) / a["v"] > cfg["kappa"]:
                continue
            if s_b is None:
                s_b = support(ctx, d, delta_s)
            if s_b.size == 0:
                continue
            if np.isin(s_b, s_a, assume_unique=True).mean() >= cfg["rho"]:
                merged_into = a
                break
        if merged_into is not None:
            merged_into["merged"] += 1
            continue
        kept.append(({**d, "merged": 0}, _curve(ctx, d), support(ctx, d, delta_s)))
    return [k[0] for k in kept]


# --- one line, end to end ---------------------------------------------------------------

def stack_line(traces_bg: np.ndarray, x_m, dt_s, time_offset_s, time_zero_s, f_nominal_hz):
    """(z, v_hat, env) with the PR #12 frozen stack configuration, fast path."""
    env = envelope(np.asarray(traces_bg, dtype=float))
    z, v_hat = hyperbola_stack_fast(traces_bg, x_m, dt_s, time_offset_s, time_zero_s, f_nominal_hz,
                                    env=env, **STACK_CFG)
    return z, v_hat, env


def detections_at(z, v_hat, threshold) -> list[dict]:
    out = components(z, threshold)
    for d in out:
        v = v_hat[d["sample"], d["trace"]]
        d["v"] = float(v) if np.isfinite(v) else float("nan")
    return out


def line_seed(identity: str) -> int:
    return int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big")


def null_peaks(traces_bg, x_m, dt_s, time_offset_s, time_zero_s, f_nominal_hz, identity: str,
               grouping: dict | None, r: int = R_CAL) -> list[float]:
    """Peak z of every (grouped) null detection above Z_FLOOR, over r trace
    permutations of the line (positions kept): the line's own null."""
    rng = np.random.default_rng(line_seed(identity))
    peaks: list[float] = []
    tr = np.asarray(traces_bg, dtype=float)
    for _ in range(r):
        p = tr[rng.permutation(tr.shape[0])]
        z, v_hat, env = stack_line(p, x_m, dt_s, time_offset_s, time_zero_s, f_nominal_hz)
        dets = detections_at(z, v_hat, Z_FLOOR)
        if grouping is not None:
            dets = group(dets, StackContext.build(p, x_m, dt_s, time_offset_s, time_zero_s, f_nominal_hz, env),
                         grouping)
        peaks.extend(d["z"] for d in dets)
    return sorted(peaks, reverse=True)


def calibrated_threshold(peaks: list[float], lambda0: float, r: int = R_CAL) -> float:
    """The ceil(lambda0 r)-th largest null peak, floored at Z_FLOOR."""
    k = math.ceil(lambda0 * r)
    return max(Z_FLOOR, peaks[k - 1]) if len(peaks) >= k else Z_FLOOR


def detect_v2(raw_traces, x_m, dt_s, time_offset_s, f_nominal_hz, identity: str, grouping: dict,
              lambda0: float | None, background=lambda tr: tr - tr.mean(axis=0),
              precomputed_peaks: list[float] | None = None) -> dict:
    """A3 on one line. With lambda0=None returns the stack/peaks only (for
    selection). Detections carry canonical x (m), t (s), the nearest original
    trace, abs_z and v_est."""
    can = canonical_line(raw_traces, x_m, dt_s, time_offset_s, f_nominal_hz)
    tz = estimate_time_zero(can.traces, can.dt_s, can.time_offset_s)
    bg = background(can.traces)
    z, v_hat, env = stack_line(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f_nominal_hz)
    peaks = precomputed_peaks if precomputed_peaks is not None else null_peaks(
        bg, can.x_m, can.dt_s, can.time_offset_s, tz, f_nominal_hz, identity, grouping)
    out = {"canonical": {"resampled": can.resampled, "regularised": can.regularised, "dt_s": can.dt_s,
                         "n_traces": int(can.x_m.size)},
           "time_zero_s": tz, "null_peaks": peaks}
    if lambda0 is None:
        return out
    thr = calibrated_threshold(peaks, lambda0)
    ctx = StackContext.build(bg, can.x_m, can.dt_s, can.time_offset_s, tz, f_nominal_hz, env)
    kept = group(detections_at(z, v_hat, thr), ctx, grouping)
    out["threshold"] = thr
    out["detections"] = [located(can, d) for d in kept]
    return out


def located(can: Canonical, d: dict) -> dict:
    x = float(can.x_m[d["trace"]])
    out = {"x": x, "t": float(can.time_offset_s + d["sample"] * can.dt_s), "trace": can.original_trace(x),
           "abs_z": d["z"], "merged": d.get("merged", 0)}
    if np.isfinite(d.get("v", np.nan)):
        out["v_est"] = d["v"]
    return out


def load_committed_freeze(path) -> dict:
    """The frozen V2 parameters, refusing unless the file is exactly as committed.

    Uses git when present; inside a container without git, the host passes
    FREEZE_BLOB = `git rev-parse HEAD:<path>` and the file's git blob hash
    must equal it.
    """
    import os
    import shutil
    import subprocess
    path = Path(path)
    data = path.read_bytes()
    if shutil.which("git"):
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)], capture_output=True)
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(path)])
        ok = tracked.returncode == 0 and dirty.returncode == 0
    else:
        blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        ok = os.environ.get("FREEZE_BLOB", "") == blob
    if not ok:
        raise SystemExit(f"{path} must be committed (and unmodified) before evaluation")
    f = json.loads(data)
    f["grouping"]["kappa"] = float(f["grouping"]["kappa"])
    return f
