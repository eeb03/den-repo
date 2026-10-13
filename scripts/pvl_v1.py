"""
Plan-View Linearity V1: L1 (select and freeze on BAM development data) and L1-R
(replication on BAM scans not used for selection). EXPLORATORY, CONCRETE NDT ONLY.

Implements docs/plan-view-linearity-v1-brief.md §3-4 with the operational
details fixed in docs/pvl-v1-l1-protocol.md. No ground truth is read by
`candidates`, `link` or `label`; truth enters only in `evaluate` (scoring).

    python -m scripts.pvl_v1 candidates --workers 6     # L1 inputs (re-run A3, verify vs stored Arm D)
    python -m scripts.pvl_v1 select                     # L1 grid, selection, writes the freeze file
    python -m scripts.pvl_v1 replicate --workers 6      # L1-R; requires the committed freeze

Outputs: artifacts/pvl_v1/. Nothing existing is overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import shutil
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import hilbert

OUT = Path("artifacts/pvl_v1")
FREEZE = Path("scripts/pvl_v1_freeze.json")
ARMD = Path("artifacts/ccd_v1")

GRID = {"G": (1, 3, 5), "dx": (0.1, 0.25, 0.5), "dt": (0.25, 0.5), "L": (2, 3, 4), "W": (1, 2, 3)}
MAX_ANGLE_DEG = 60.0
S_MAX = 0.5
MIN_LINES = 3
OBJ_X_MM, CUBOID_Y_MM, EDGE_X_MM = 100.0, 60.0, 60.0
STEP_EDGES = (500.0, 1000.0, 1500.0)
L1_SCANS = (("Pk266", "1_5_GHz_Rot00"), ("Pk401", "1_5_GHz_Rot00"), ("Pk050", "1_5_GHz_Rot00"))
L1R_SCANS = (("Pk266", "2_6_GHz_Rot00"), ("Pk266", "1_5_GHz_Rot90"), ("Pk401", "1_5_GHz_Rot90"))


def f_ghz(scan: str) -> float:
    return 2.6 if scan.startswith("2_6") else 1.5


# --- candidates and in-line width (no truth) ----------------------------------------------

def inline_width_m(env_t: np.ndarray, i: int, k: int, m: int, dx_m: float) -> float:
    """Contiguous half-maximum width along x of the time-averaged envelope at sample k."""
    prof = env_t[:, max(0, k - m):k + m + 1].mean(axis=1)
    thr = 0.5 * prof[i]
    lo = i
    while lo - 1 >= 0 and prof[lo - 1] >= thr:
        lo -= 1
    hi = i
    while hi + 1 < prof.size and prof[hi + 1] >= thr:
        hi += 1
    return (hi - lo) * dx_m


def dewowed_envelope(traces: np.ndarray, period_samples: int) -> np.ndarray:
    """(n_x, n_t) Hilbert envelope after a one-period running-mean dewow; no lateral removal."""
    rm = uniform_filter1d(traces, size=max(1, period_samples), axis=1, mode="nearest")
    return np.abs(hilbert(traces - rm, axis=1))


def _line_job(args):
    spec, scan, j, freeze = args
    from benchmark.hyperbola_v2 import detect_v2
    from scripts.ccd_v1_stage1 import scan_data
    s, vol = scan_data(spec, scan)
    g = s.grid
    dt_ns = float(g.z[1] - g.z[0])
    f = f_ghz(scan)
    tr = vol[:, j, :].astype(float)
    r = detect_v2(tr, np.asarray(g.x, float) / 1000.0, dt_ns * 1e-9, g.z[0] * 1e-9, f * 1e9,
                  f"bam:{spec}_{scan}:L{j}", freeze["grouping"], freeze["lambda0"])
    T = 1.0 / f
    env = dewowed_envelope(tr, int(round(T / dt_ns)))
    m = int(round(0.25 * T / dt_ns))
    dx_m = float(np.median(np.diff(g.x))) / 1000.0
    out = []
    for d in r["detections"]:
        x_mm, t_ns = d["x"] * 1000.0, d["t"] * 1e9
        i = int(np.argmin(np.abs(g.x - x_mm)))
        k = int(np.clip(round((t_ns - g.z[0]) / dt_ns), 0, tr.shape[1] - 1))
        out.append({"spec": spec, "scan": scan, "line": j, "y_mm": float(g.y[j]), "x_mm": x_mm, "t_ns": t_ns,
                    "abs_z": d["abs_z"], "v_est": d.get("v_est"), "W_m": inline_width_m(env, i, k, m, dx_m)})
    return out


def _assign_lambda(cands: list[dict], f: float) -> None:
    by_line: dict[int, list[float]] = {}
    for c in cands:
        if c["v_est"]:
            by_line.setdefault(c["line"], []).append(c["v_est"])
    allv = [v for vs in by_line.values() for v in vs]
    scan_med = float(np.median(allv)) if allv else 1.0e8
    for c in cands:
        v = c["v_est"] or (float(np.median(by_line[c["line"]])) if c["line"] in by_line else scan_med)
        c["lam_mm"] = v / (f * 1e9) * 1000.0
        c["W"] = c["W_m"] * 1000.0 / c["lam_mm"]


def run_candidates(scans, workers: int, freeze: dict) -> dict:
    from benchmark.bam_ingest import load_scan
    res = {}
    for spec, scan in scans:
        n_lines = len(load_scan(spec, f"{spec}_3D_Dataset_{scan}").grid.y)
        with Pool(workers) as pool:
            cands = [c for part in pool.map(_line_job, [(spec, scan, j, freeze) for j in range(n_lines)]) for c in part]
        _assign_lambda(cands, f_ghz(scan))
        res[f"{spec}_{scan}"] = cands
        (OUT / f"candidates_{spec}_{scan}.json").write_text(json.dumps(cands))
    return res


def verify_against_armd(cands: dict) -> dict:
    """N1: the re-run must equal the stored CCD-V1 Arm D detections."""
    out = {}
    for spec, scan in L1_SCANS:
        stored = json.loads((ARMD / f"stage1_armd_{spec}_detections.json").read_text())
        new = cands[f"{spec}_{scan}"]
        key = lambda d: (d["line"], round(d["x_mm"], 6), round(d["t_ns"], 6), round(d["abs_z"], 6))  # noqa: E731
        same = len(stored) == len(new) and all(key(a) == key(b) for a, b in zip(stored, new))
        out[spec] = {"stored": len(stored), "rerun": len(new), "identical": same}
        if same:
            for a, b in zip(stored, new):
                b["armd_class"], b["armd_object"] = a["class"], a["object"]
    return out


# --- linking and labels (no truth) --------------------------------------------------------

class Track:
    __slots__ = ("members", "a", "b")

    def __init__(self, c):
        self.members = [c]
        self.a, self.b = c["x_mm"], 0.0

    def fit(self, extra=None):
        ms = self.members + ([extra] if extra else [])
        y = np.array([m["y_mm"] for m in ms])
        x = np.array([m["x_mm"] for m in ms])
        if len(ms) == 1:
            return x[0], 0.0
        b, a = np.polyfit(y, x, 1)
        return float(a), float(b)


def link(cands: list[dict], cfg: dict, period_ns: float) -> list[Track]:
    tan_max = math.tan(math.radians(MAX_ANGLE_DEG))
    tracks: list[Track] = []
    by_line: dict[int, set[int]] = {}
    for c in sorted(cands, key=lambda d: -d["abs_z"]):
        best, best_res = None, None
        near = set()
        for jj in range(c["line"] - cfg["G"], c["line"] + cfg["G"] + 1):
            near |= by_line.get(jj, set())
        for ti in near:
            tk = tracks[ti]
            lines = [m["line"] for m in tk.members]
            if c["line"] in lines:
                continue
            nearest = min(tk.members, key=lambda m: abs(m["line"] - c["line"]))
            if abs(c["t_ns"] - nearest["t_ns"]) > cfg["dt"] * period_ns:
                continue
            tol = cfg["dx"] * c["lam_mm"]
            if len(tk.members) == 1:
                res = abs(c["x_mm"] - nearest["x_mm"])
                if res > tol + abs(c["y_mm"] - nearest["y_mm"]) * tan_max:
                    continue
            else:
                res = abs(c["x_mm"] - (tk.a + tk.b * c["y_mm"]))
                if res > tol:
                    continue
            a, b = tk.fit(c)
            if abs(b) > tan_max:
                continue
            if best_res is None or res < best_res:
                best, best_res = ti, res
        if best is None:
            tracks.append(Track(c))
            by_line.setdefault(c["line"], set()).add(len(tracks) - 1)
        else:
            tk = tracks[best]
            tk.members.append(c)
            tk.a, tk.b = tk.fit()
            by_line.setdefault(c["line"], set()).add(best)
    return tracks


def describe(tk: Track) -> dict:
    ms = tk.members
    lam = float(np.median([m["lam_mm"] for m in ms]))
    y = np.array([m["y_mm"] for m in ms])
    x = np.array([m["x_mm"] for m in ms])
    dy = float(y.max() - y.min())
    L = math.hypot(dy, tk.b * dy) / lam
    s = None
    if len(ms) >= 3:
        r = x - (tk.a + tk.b * y)
        s = float(np.sqrt(np.mean(r ** 2)) * math.cos(math.atan(tk.b)) / lam)
    return {"n_lines": len({m["line"] for m in ms}), "L": L, "s": s,
            "W_med": float(np.median([m["W"] for m in ms])), "x_med": float(np.median(x)),
            "y_range": [float(y.min()), float(y.max())], "t_med": float(np.median([m["t_ns"] for m in ms])),
            "slope": tk.b}


def label(desc: dict, cfg: dict) -> str:
    if desc["W_med"] > cfg["W"]:
        return "planar"
    if desc["L"] >= cfg["L"] and desc["n_lines"] >= MIN_LINES and desc["s"] is not None and desc["s"] <= S_MAX:
        return "linear"
    return "compact"


def apply(cands_by_scan: dict, cfg: dict) -> dict:
    out = {}
    for key, cands in cands_by_scan.items():
        period = 1.0 / f_ghz(key.split("_", 1)[1])
        tracks = link(cands, cfg, period)
        rows = []
        for tk in tracks:
            d = describe(tk)
            d["label"] = label(d, cfg)
            d["member_ids"] = [id(m) for m in tk.members]
            d["_members"] = tk.members
            rows.append(d)
        out[key] = rows
    return out


# --- scoring (truth enters only here) --------------------------------------------------------

def _objects(spec):
    from scripts.ccd_v1_stage1 import objects
    return objects(spec)


def evaluate(tracks_by_scan: dict, cfg: dict) -> dict:
    from scripts.ccd_v1_stage1 import calibration, expected_time
    res = {"ducts": {}, "cuboids": {}, "step_edges": {}, "backwall": None, "label_mix_by_armd_class": {}}
    for key, rows in tracks_by_scan.items():
        spec, scan = key.split("_", 1)
        linear = [r for r in rows if r["label"] == "linear"]
        T = 1.0 / f_ghz(scan)
        cal = calibration(spec, scan)
        for o in _objects(spec) if spec in ("Pk266", "Pk401") else []:
            hits = [r for r in linear if abs(r["x_med"] - o["x"]) <= OBJ_X_MM and
                    (o["y"] is None or (r["y_range"][0] <= o["y"] + CUBOID_Y_MM and r["y_range"][1] >= o["y"] - CUBOID_Y_MM))]
            entry = {"carries_linear": bool(hits), "n_tracks": len(hits)}
            if hits and cal is not None:
                best = max(hits, key=lambda r: r["n_lines"])
                entry.update({"best_n_lines": best["n_lines"], "best_L": best["L"], "best_W": best["W_med"],
                              "best_y_range": best["y_range"],
                              "time_within_1T_of_expected": abs(best["t_med"] - expected_time(cal, o["z_top"])) <= T})
            res["ducts" if o["y"] is None else "cuboids"].setdefault(key, {})[o["id"]] = entry
        res["step_edges"][key] = {str(int(e)): any(abs(r["x_med"] - e) <= EDGE_X_MM for r in linear) for e in STEP_EDGES}
        for r in rows:
            for m in r["_members"]:
                cls = m.get("armd_class")
                if cls:
                    mix = res["label_mix_by_armd_class"].setdefault(cls, {"planar": 0, "linear": 0, "compact": 0})
                    mix[r["label"]] += 1
    bw = res["label_mix_by_armd_class"].get("back_wall")
    res["backwall"] = None if not bw else {"n": sum(bw.values()), "planar_fraction": bw["planar"] / max(1, sum(bw.values()))}
    return res


def configs():
    for G, dx, dt, L, W in itertools.product(GRID["G"], GRID["dx"], GRID["dt"], GRID["L"], GRID["W"]):
        yield {"G": G, "dx": dx, "dt": dt, "L": L, "W": W}


def select(cands_by_scan: dict) -> dict:
    table = []
    for cfg in configs():
        ev = evaluate(apply(cands_by_scan, cfg), cfg)
        ducts = ev["ducts"].get("Pk266_1_5_GHz_Rot00", {})
        cubs = ev["cuboids"].get("Pk401_1_5_GHz_Rot00", {})
        adm = len(ducts) == 4 and all(v["carries_linear"] for v in ducts.values()) and \
            len(cubs) == 4 and not any(v["carries_linear"] for v in cubs.values())
        table.append({"config": cfg, "admissible": adm,
                      "ducts_linear": sum(v["carries_linear"] for v in ducts.values()),
                      "cuboids_linear": sum(v["carries_linear"] for v in cubs.values()),
                      "backwall_planar_fraction": ev["backwall"]["planar_fraction"] if ev["backwall"] else None,
                      "eval": ev})
    adm = [r for r in table if r["admissible"]]
    if not adm:
        return {"status": "STOP: no admissible configuration", "table": table}
    adm.sort(key=lambda r: (-(r["backwall_planar_fraction"] or 0), r["config"]["dx"], r["config"]["G"],
                            -r["config"]["L"], r["config"]["dt"], r["config"]["W"]))
    return {"status": "selected", "chosen": adm[0]["config"], "n_admissible": len(adm), "chosen_eval": adm[0]["eval"],
            "table": table}


# --- freeze -----------------------------------------------------------------------------

def committed_freeze() -> dict:
    data = FREEZE.read_bytes()
    if shutil.which("git"):
        ok = subprocess.run(["git", "ls-files", "--error-unmatch", str(FREEZE)], capture_output=True).returncode == 0 \
            and subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(FREEZE)]).returncode == 0
    else:
        ok = os.environ.get("PVL_FREEZE_BLOB", "") == hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    if not ok:
        raise SystemExit(f"{FREEZE} must be committed (and unmodified) before L1-R")
    return json.loads(data)


def _v2_freeze():
    from benchmark.hyperbola_v2 import load_committed_freeze
    return load_committed_freeze(Path("simulation/hyperbola_v2_freeze.json"))


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not k.startswith("_") and k != "member_ids"}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("candidates", "select", "replicate"))
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.stage == "candidates":
        cands = run_candidates(L1_SCANS, a.workers, _v2_freeze())
        check = verify_against_armd(cands)
        for k, v in cands.items():
            (OUT / f"candidates_{k}.json").write_text(json.dumps(v))
        (OUT / "l1_candidates_check.json").write_text(json.dumps(check, indent=1))
        print(json.dumps(check, indent=1))
        return 0 if all(v["identical"] for v in check.values()) else 1
    if a.stage == "select":
        check = json.loads((OUT / "l1_candidates_check.json").read_text())
        if not all(v["identical"] for v in check.values()):
            raise SystemExit("N1 failed: re-run does not reproduce the stored Arm D detections")
        cands = {f"{s}_{c}": json.loads((OUT / f"candidates_{s}_{c}.json").read_text()) for s, c in L1_SCANS}
        r = select(cands)
        (OUT / "l1_selection.json").write_text(json.dumps(_clean(r), indent=1, default=str))
        if r["status"] == "selected":
            FREEZE.write_text(json.dumps({"frozen_before_L1R": True, "config": r["chosen"],
                                          "fixed": {"max_angle_deg": MAX_ANGLE_DEG, "s_max": S_MAX,
                                                    "min_lines": MIN_LINES},
                                          "front_end": "V2 A3, simulation/hyperbola_v2_freeze.json (09dc288)",
                                          "selected_on": [f"{s}_{c}" for s, c in L1_SCANS],
                                          "n_admissible": r["n_admissible"]}, indent=1))
        print(json.dumps(_clean({k: v for k, v in r.items() if k != "table"}), indent=1, default=str)[:5000])
        return 0
    frz = committed_freeze()
    cands = run_candidates(L1R_SCANS, a.workers, _v2_freeze())
    ev = evaluate(apply(cands, frz["config"]), frz["config"])
    res = {"label": "EXPLORATORY: same specimens as L1; CONCRETE NDT ONLY; n = 4 per class", "freeze": frz,
           "eval": ev, "n_candidates": {k: len(v) for k, v in cands.items()}}
    (OUT / "l1r_replication.json").write_text(json.dumps(_clean(res), indent=1, default=str))
    print(json.dumps(_clean(res), indent=1, default=str)[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
