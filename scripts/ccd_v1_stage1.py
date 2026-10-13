"""
CCD-V1 Stage 1: BAM features at known object positions. EXPLORATORY.

Implements docs/ccd-v1-stage0-1-protocol.md §B0e and §C exactly. Every BAM
specimen and scan has been used in earlier research, so nothing here is
independent validation; CONCRETE NDT ONLY. One object is one statistical
unit: line-level values are medians-of-repeated-measures, never n.

    python -m scripts.ccd_v1_stage1 footprints      # B0e (+ DZT confound table)
    python -m scripts.ccd_v1_stage1 features        # C1-C4
    python -m scripts.ccd_v1_stage1 armd --workers 6   # C5 (re-runs frozen A3; new files)

Outputs: artifacts/ccd_v1/stage1_*.json. Nothing existing is overwritten.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.signal import hilbert

from scripts.ccd_v1_stats import clopper_pearson, exact_binomial_upper, exact_mann_whitney

OUT = Path("artifacts/ccd_v1")
GT_CSV = Path("evidence/bam/specimen_ground_truth.csv")
CAL_JSON = Path("evidence/bam/results/quantitative_validation.json")
FREEZE = Path("simulation/hyperbola_v2_freeze.json")

# --- frozen constants (protocol §B0e, §C) ---------------------------------------
OBJECT_HALF_WIDTH_MM = 10.0          # object trace = mean of nodes within +/-10 mm
REF_MIN_MM, REF_MAX_MM = 120.0, 200.0
STEP_MM, STEP_GUARD_MM = 500.0, 60.0
CUBOID_LINE_HALF_MM = 60.0
DUCT_BAND_MM = (100.0, 700.0)        # central band, excludes edge-rebar zones
WIN_BEFORE_T, WIN_AFTER_T = 0.5, 1.0
WAVELET_HALF_T = 0.6
BACKWALL_HALF_T = 0.5
F8_FRACTION = 0.5
LATE_OFFSET_T = 3.0                  # specimen-identity control window centre
OFF_LINES_PK401 = ((100.0, 250.0), (620.0, 700.0))
CONTROL_AUC_BAND = (0.30, 0.70)
PRIMARY = "1_5_GHz"
F_NOMINAL = {"1_5_GHz": 1.5, "2_6_GHz": 2.6}   # GHz -> T in ns = 1/f


# --- truth and calibration (no radar picks) ---------------------------------------

def objects(specimen: str) -> list[dict]:
    rows = list(csv.DictReader(GT_CSV.open(encoding="utf-8")))
    out = []
    for r in rows:
        if r["specimen_id"] != specimen or r["role"] != "target":
            continue
        out.append({"id": r["object_id"], "type": r["object_type"], "material": r["material"],
                    "x": float(r["x_mm"]), "y": float(r["y_mm"]) if r["y_mm"] else None,
                    "z_top": float(r["z_top_mm"])})
    return out


def phantoms_pk050() -> list[dict]:
    """The 8 object (x, z_top, y) positions placed in Pk050, which has no embedded objects."""
    return [{**o, "id": o["id"].replace("Pk266", "Pk050-phantom").replace("Pk401", "Pk050-phantom"),
             "type": "phantom_" + o["type"]} for o in objects("Pk266") + objects("Pk401")]


def calibration(specimen: str, scan: str) -> dict | None:
    s = json.loads(CAL_JSON.read_text())["scans"][f"{specimen}_3D_Dataset_{scan}"]
    c = s.get("calibration_backwall_peak")
    if not c or c.get("v_m_per_ns") is None:
        return None
    return {"v": c["v_m_per_ns"], "t0": c["t0_ns"], "backwall_t_ns": [b["t_ns"] for b in s["backwall"]],
            "residual_rms_ns": c["residual_rms_ns"]}


def step_of(x_mm: float) -> int:
    return min(int(x_mm // STEP_MM), 3)


def ref_nodes(grid_x: np.ndarray, x_obj: float) -> list[int]:
    k = step_of(x_obj)
    lo, hi = k * STEP_MM + STEP_GUARD_MM, (k + 1) * STEP_MM - STEP_GUARD_MM
    return [i for i, x in enumerate(grid_x) if REF_MIN_MM <= abs(x - x_obj) <= REF_MAX_MM and lo <= x <= hi]


def obj_nodes(grid_x: np.ndarray, x_obj: float) -> list[int]:
    return [i for i, x in enumerate(grid_x) if abs(x - x_obj) <= OBJECT_HALF_WIDTH_MM]


def lines_for(grid_y: np.ndarray, obj: dict) -> list[int]:
    if obj["y"] is None:
        return [j for j, y in enumerate(grid_y) if DUCT_BAND_MM[0] <= y <= DUCT_BAND_MM[1]]
    return [j for j, y in enumerate(grid_y) if abs(y - obj["y"]) <= CUBOID_LINE_HALF_MM]


def band_lines(grid_y: np.ndarray, bands) -> list[int]:
    return [j for j, y in enumerate(grid_y) if any(lo <= y <= hi for lo, hi in bands)]


def expected_time(cal: dict, z_top_mm: float) -> float:
    return cal["t0"] + 2 * (z_top_mm / 1000.0) / cal["v"]


# --- per-line measurements (protocol §C1, §C2) ---------------------------------------

def envelope(x: np.ndarray) -> np.ndarray:
    return np.abs(hilbert(x))


def _window(t_ns: np.ndarray, centre: float, before: float, after: float) -> np.ndarray:
    return np.nonzero((t_ns >= centre - before) & (t_ns <= centre + after))[0]


def object_response(vol, j, onodes, rnodes, t_ns, t_centre, T):
    """(r_j, p_j index, A_j) on line j: object minus reference, peak in W."""
    r = vol[onodes, j, :].mean(axis=0) - vol[rnodes, j, :].mean(axis=0)
    e = envelope(r)
    w = _window(t_ns, t_centre, WIN_BEFORE_T * T, WIN_AFTER_T * T)
    p = int(w[np.argmax(e[w])])
    return r, p, float(e[p])


def backwall_response(vol, j, rnodes, t_ns, t_bw, T):
    b = vol[rnodes, j, :].mean(axis=0)
    e = envelope(b - b.mean())
    w = _window(t_ns, t_bw, BACKWALL_HALF_T * T, BACKWALL_HALF_T * T)
    q = int(w[np.argmax(e[w])])
    return b - b.mean(), q, float(e[q])


def polarity(r, p, b, q, half: int) -> float:
    """Normalised zero-lag correlation of two peak-centred wavelets, in [-1, 1]."""
    n = min(half, p, q, len(r) - 1 - p, len(b) - 1 - q)
    u, w = r[p - n:p + n + 1], b[q - n:q + n + 1]
    den = float(np.linalg.norm(u) * np.linalg.norm(w))
    return float(np.dot(u, w) / den) if den > 0 else 0.0


def continuity_run(amplitudes: np.ndarray, line_step_mm: float) -> dict:
    """Half-maximum contiguous run through the line of maximum response (F8)."""
    jstar = int(np.argmax(amplitudes))
    thr = F8_FRACTION * amplitudes[jstar]
    lo = jstar
    while lo - 1 >= 0 and amplitudes[lo - 1] >= thr:
        lo -= 1
    hi = jstar
    while hi + 1 < len(amplitudes) and amplitudes[hi + 1] >= thr:
        hi += 1
    return {"argmax_index": jstar, "run_lines": hi - lo + 1, "run_mm": (hi - lo) * line_step_mm,
            "run_index_range": [lo, hi]}


# --- volume access -------------------------------------------------------------------

_VOL_CACHE: dict = {}


def scan_data(specimen: str, scan: str):
    from benchmark.bam_ingest import load_scan, load_volume
    key = (specimen, scan)
    if key not in _VOL_CACHE:
        s = load_scan(specimen, f"{specimen}_3D_Dataset_{scan}")
        _VOL_CACHE.clear()                       # one volume (~0.26 GB) in memory at a time
        _VOL_CACHE[key] = (s, load_volume(s).astype(np.float64))
    return _VOL_CACHE[key]


def per_line_measures(specimen: str, scan: str, obj: dict, lines: list[int], t_offset_T: float = 0.0):
    """Per-line A, polarity c, BW for one object/position in one scan. None if uncalibrated."""
    cal = calibration(specimen, scan)
    if cal is None:
        return None
    s, vol = scan_data(specimen, scan)
    g = s.grid
    T = 1.0 / F_NOMINAL[scan[:7]]
    dt = float(g.z[1] - g.z[0])
    t_ns = np.asarray(g.z, float)
    on, rn = obj_nodes(g.x, obj["x"]), ref_nodes(g.x, obj["x"])
    t_e = expected_time(cal, obj["z_top"]) + t_offset_T * T
    t_bw = cal["backwall_t_ns"][step_of(obj["x"])]
    half = int(round(WAVELET_HALF_T * T / dt))
    rows = []
    for j in lines:
        r, p, a = object_response(vol, j, on, rn, t_ns, t_e, T)
        b, q, bw = backwall_response(vol, j, rn, t_ns, t_bw, T)
        rows.append({"line": j, "y_mm": float(g.y[j]), "A": a, "t_peak_ns": float(t_ns[p]),
                     "BW": bw, "c": polarity(r, p, b, q, half)})
    return {"t_expected_ns": t_e, "t_backwall_ns": t_bw, "obj_nodes": on, "ref_nodes": rn,
            "T_ns": T, "rows": rows, "line_step_mm": float(np.median(np.diff(g.y)))}


def object_features(specimen: str, freq: str, obj: dict, lines: list[int], f8_lines: list[int] | None,
                    t_offset_T: float = 0.0) -> dict:
    m00 = per_line_measures(specimen, f"{freq}_Rot00", obj, lines, t_offset_T)
    m90 = per_line_measures(specimen, f"{freq}_Rot90", obj, lines, t_offset_T)
    out = {"object": obj["id"], "type": obj["type"], "specimen": specimen, "frequency": freq,
           "n_lines": len(lines), "t_offset_T": t_offset_T}
    if m00 is None:
        out["status"] = "uncalibrated"
        return out
    c = np.array([r["c"] for r in m00["rows"]])
    out["F1_polarity_median_c"] = float(np.median(c))
    out["F1_line_fraction_negative"] = float(np.mean(c < 0))
    out["t_expected_ns"] = m00["t_expected_ns"]
    out["median_t_peak_minus_expected_ns"] = float(np.median([r["t_peak_ns"] for r in m00["rows"]])
                                                   - m00["t_expected_ns"])
    if m90 is not None:
        rho = np.array([math.log(a["A"] / b["A"]) - math.log(a["BW"] / b["BW"])
                        for a, b in zip(m00["rows"], m90["rows"])])
        out["F7_signed_median_rho"] = float(np.median(rho))
        out["F7_P_abs_median_rho"] = abs(float(np.median(rho)))
        out["F7_rho_iqr"] = [float(np.percentile(rho, 25)), float(np.percentile(rho, 75))]
    if f8_lines is not None:
        m8 = per_line_measures(specimen, f"{freq}_Rot00", obj, f8_lines, t_offset_T)
        amps = np.array([r["A"] for r in m8["rows"]])
        run = continuity_run(amps, m8["line_step_mm"])
        run["run_y_mm"] = [m8["rows"][run["run_index_range"][0]]["y_mm"], m8["rows"][run["run_index_range"][1]]["y_mm"]]
        out["F8_run_mm"] = run["run_mm"]
        out["F8_detail"] = run
    return out


# --- stages ------------------------------------------------------------------------

def footprints() -> dict:
    from benchmark.bam_ingest import load_scan
    out = {"scans": {}, "dzt_headers": {}}
    for spec in ("Pk266", "Pk401", "Pk050"):
        objs = objects(spec) if spec != "Pk050" else phantoms_pk050()
        for scan in ("1_5_GHz_Rot00", "1_5_GHz_Rot90", "2_6_GHz_Rot00", "2_6_GHz_Rot90"):
            s = load_scan(spec, f"{spec}_3D_Dataset_{scan}")
            out["dzt_headers"][f"{spec}_{scan}"] = s.dzt_header
            cal = calibration(spec, scan)
            rows = []
            for o in objs:
                rows.append({"object": o["id"], "x_mm": o["x"], "y_mm": o["y"], "z_top_mm": o["z_top"],
                             "obj_nodes": obj_nodes(s.grid.x, o["x"]), "ref_nodes": ref_nodes(s.grid.x, o["x"]),
                             "n_lines": len(lines_for(s.grid.y, o)),
                             "t_expected_ns": None if cal is None else expected_time(cal, o["z_top"]),
                             "t_backwall_ns": None if cal is None else cal["backwall_t_ns"][step_of(o["x"])]})
            out["scans"][f"{spec}_{scan}"] = {"calibration": cal, "objects": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stage0e_bam_footprints.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def _test_block(ducts: list[dict], cuboids: list[dict], key: str, alternative: str) -> dict:
    a = [d[key] for d in ducts if key in d]
    b = [c[key] for c in cuboids if key in c]
    if len(a) < 2 or len(b) < 2:
        return {"status": "not_testable", "n_ducts": len(a), "n_cuboids": len(b)}
    return exact_mann_whitney(a, b, alternative)


def features() -> dict:
    from benchmark.bam_ingest import load_scan
    gy = {spec: load_scan(spec, f"{spec}_3D_Dataset_1_5_GHz_Rot00").grid.y for spec in ("Pk266", "Pk401", "Pk050")}
    res = {"label": "EXPLORATORY -- every BAM specimen/scan was used in earlier research; CONCRETE NDT ONLY; "
                    "units are objects (n = 4 vs 4)", "objects": {}, "controls": {}, "tests": {}}

    def feats(spec, obj, freq=PRIMARY, lines=None, f8=True, t_off=0.0):
        g = gy[spec]
        ls = lines if lines is not None else lines_for(g, obj)
        f8_lines = [j for j, y in enumerate(g) if DUCT_BAND_MM[0] <= y <= DUCT_BAND_MM[1]] if f8 else None
        return object_features(spec, freq, obj, ls, f8_lines, t_off)

    ducts = [feats("Pk266", o) for o in objects("Pk266")]
    cuboids = [feats("Pk401", o) for o in objects("Pk401")]
    res["objects"]["ducts_1_5_GHz"] = ducts
    res["objects"]["cuboids_1_5_GHz"] = cuboids
    res["objects"]["ducts_2_6_GHz_descriptive"] = [feats("Pk266", o, freq="2_6_GHz") for o in objects("Pk266")]
    res["objects"]["cuboids_2_6_GHz"] = "not computed: Pk401 2.6 GHz calibration REFUSED (protocol A4)"

    # independent tests (protocol §C3)
    res["tests"]["H5_F7_polarisation_magnitude"] = _test_block(ducts, cuboids, "F7_P_abs_median_rho", "greater")
    res["tests"]["H6_F8_continuity_sanity"] = _test_block(ducts, cuboids, "F8_run_mm", "greater")
    k = sum(c["F1_polarity_median_c"] < 0 for c in cuboids)
    res["tests"]["H7a_cuboid_polarity_opposite_backwall"] = {
        "k_negative": k, "n": len(cuboids), "p_exact_binomial_ge_k": exact_binomial_upper(k, len(cuboids)),
        "clopper_pearson_95": clopper_pearson(k, len(cuboids)), "min_attainable_p": 0.5 ** len(cuboids)}
    res["tests"]["H7b_polarity_ducts_vs_cuboids_two_sided"] = _test_block(ducts, cuboids, "F1_polarity_median_c",
                                                                          "two-sided")
    res["tests"]["duct_polarity_descriptive"] = {
        "k_negative": sum(d["F1_polarity_median_c"] < 0 for d in ducts), "n": len(ducts),
        "note": "duct material is NOT STATED in the truth; no material is inferred (protocol A3)"}

    # controls (protocol §C4)
    ph = [feats("Pk050", o) for o in phantoms_pk050()]
    res["controls"]["C4_1_pk050_phantoms"] = ph
    off = band_lines(gy["Pk401"], OFF_LINES_PK401)
    res["controls"]["C4_2_pk401_off_object_lines"] = [feats("Pk401", o, lines=off, f8=False) for o in objects("Pk401")]
    late_d = [feats("Pk266", o, f8=False, t_off=LATE_OFFSET_T) for o in objects("Pk266")]
    late_c = [feats("Pk401", o, f8=False, t_off=LATE_OFFSET_T) for o in objects("Pk401")]
    ctl = {}
    for key in ("F7_P_abs_median_rho", "F1_polarity_median_c"):
        t = exact_mann_whitney([d[key] for d in late_d], [c[key] for c in late_c], "two-sided")
        t["passes"] = CONTROL_AUC_BAND[0] <= t["auc"] <= CONTROL_AUC_BAND[1]
        ctl[key] = t
    res["controls"]["C4_3_specimen_identity_late_window"] = {"pk266": late_d, "pk401": late_c, "tests": ctl}
    # combination (protocol §C6): table only, no test
    table = []
    for o in ducts + cuboids:
        table.append({"object": o["object"], "type": o["type"], "F7_P": o.get("F7_P_abs_median_rho"),
                      "F8_run_mm": o.get("F8_run_mm"), "F1_c": o.get("F1_polarity_median_c")})
    res["combination_table"] = table
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stage1_features.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# --- Arm D (protocol §C5): descriptive -----------------------------------------------

def _armd_line(args):
    spec, j, freeze = args
    from benchmark.hyperbola_v2 import detect_v2
    s, vol = scan_data(spec, "1_5_GHz_Rot00")
    g = s.grid
    dt, toff = (g.z[1] - g.z[0]) * 1e-9, g.z[0] * 1e-9
    r = detect_v2(vol[:, j, :].astype(float), np.asarray(g.x, float) / 1000.0, dt, toff, 1.5e9,
                  f"bam:{spec}_1_5_GHz_Rot00:L{j}", freeze["grouping"], freeze["lambda0"])
    return [{"spec": spec, "line": j, "y_mm": float(g.y[j]), "x_mm": d["x"] * 1000.0, "t_ns": d["t"] * 1e9,
             "abs_z": d["abs_z"]} for d in r["detections"]]


def _classify(d, objs, cal, T):
    for o in objs:
        if abs(d["x_mm"] - o["x"]) <= 100 and (o["y"] is None or abs(d["y_mm"] - o["y"]) <= 60) \
                and abs(d["t_ns"] - expected_time(cal, o["z_top"])) <= T:
            return "object", o["id"]
    t_bw = cal["backwall_t_ns"][step_of(d["x_mm"])]
    if abs(d["t_ns"] - t_bw) <= T:
        return "back_wall", None
    if d["t_ns"] > t_bw + T:
        return "below_back_wall", None
    if d["t_ns"] < cal["t0"] + 2 * T:
        return "direct", None
    if any(abs(d["x_mm"] - e) <= 60 for e in (500, 1000, 1500)):
        return "step_edge", None
    if d["y_mm"] < 100 or d["y_mm"] > 700:
        return "edge_rebar_zone", None
    return "other", None


def armd(workers: int) -> dict:
    from scripts.hyperbola_v2_realdata import _freeze
    freeze = _freeze()
    res = {"label": "DESCRIPTIVE ONLY; non-object detections are not statistical units", "scans": {}}
    for spec in ("Pk266", "Pk401", "Pk050"):
        s, _ = scan_data(spec, "1_5_GHz_Rot00")
        with Pool(workers) as pool:
            dets = [d for part in pool.map(_armd_line, [(spec, j, freeze) for j in range(len(s.grid.y))])
                    for d in part]
        cal00, cal90 = calibration(spec, "1_5_GHz_Rot00"), calibration(spec, "1_5_GHz_Rot90")
        T = 1 / 1.5
        objs = objects(spec) if spec != "Pk050" else []
        s, vol00 = scan_data(spec, "1_5_GHz_Rot00")
        g = s.grid
        t_ns = np.asarray(g.z, float)
        dt = float(g.z[1] - g.z[0])
        half = int(round(WAVELET_HALF_T * T / dt))
        bydx = {}
        for d in dets:
            bydx.setdefault(d["line"], []).append(d)
        for d in dets:
            d["class"], d["object"] = _classify(d, objs, cal00, T)
            xi = int(np.argmin(np.abs(g.x - d["x_mm"])))
            on, rn = obj_nodes(g.x, g.x[xi]), ref_nodes(g.x, g.x[xi])
            if not rn:
                d["F1_c"] = None
                continue
            r, p, a = object_response(vol00, d["line"], on, rn, t_ns, d["t_ns"], T)
            b, q, bw = backwall_response(vol00, d["line"], rn, t_ns, cal00["backwall_t_ns"][step_of(g.x[xi])], T)
            d["F1_c"], d["_A00"], d["_BW00"] = polarity(r, p, b, q, half), a, bw
            run = 1
            for direction in (-1, 1):
                jj = d["line"] + direction
                while any(abs(e["x_mm"] - d["x_mm"]) <= 10 and abs(e["t_ns"] - d["t_ns"]) <= 0.5 * T
                          for e in bydx.get(jj, [])):
                    run += 1
                    jj += direction
            d["F8_run_mm"] = (run - 1) * float(np.median(np.diff(g.y)))
        s, vol90 = scan_data(spec, "1_5_GHz_Rot90")
        for d in dets:
            if d.get("F1_c") is None:
                continue
            xi = int(np.argmin(np.abs(g.x - d["x_mm"])))
            on, rn = obj_nodes(g.x, g.x[xi]), ref_nodes(g.x, g.x[xi])
            t90 = d["t_ns"] - cal00["t0"] + cal90["t0"]
            _, _, a90 = object_response(vol90, d["line"], on, rn, t_ns, t90, T)
            _, _, bw90 = backwall_response(vol90, d["line"], rn, t_ns, cal90["backwall_t_ns"][step_of(g.x[xi])], T)
            d["F7_rho"] = math.log(d.pop("_A00") / a90) - math.log(d.pop("_BW00") / bw90)
        summary = {}
        for cls in sorted({d["class"] for d in dets}):
            sub = [d for d in dets if d["class"] == cls and d.get("F1_c") is not None]
            if not sub:
                continue
            q = lambda key: [float(np.percentile([x[key] for x in sub if x.get(key) is not None], p))  # noqa: E731
                             for p in (25, 50, 75)]
            summary[cls] = {"n_detections": len(sub), "F1_c_q25_50_75": q("F1_c"),
                            "F7_abs_rho_q25_50_75": [float(np.percentile([abs(x["F7_rho"]) for x in sub], p))
                                                     for p in (25, 50, 75)],
                            "F8_run_mm_q25_50_75": q("F8_run_mm")}
        per_object = {}
        for o in objs:
            sub = [d for d in dets if d["object"] == o["id"]]
            per_object[o["id"]] = {"n_detections": len(sub), "n_lines": len({d["line"] for d in sub}),
                                   "F1_c_median": float(np.median([d["F1_c"] for d in sub])) if sub else None,
                                   "F7_abs_median_rho": abs(float(np.median([d["F7_rho"] for d in sub]))) if sub else None,
                                   "F8_run_mm_median": float(np.median([d["F8_run_mm"] for d in sub])) if sub else None}
        res["scans"][spec] = {"n_detections": len(dets), "by_class": summary, "per_object": per_object}
        (OUT / f"stage1_armd_{spec}_detections.json").write_text(json.dumps(dets, default=str))
    (OUT / "stage1_armd.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("footprints", "features", "armd"))
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    r = footprints() if a.stage == "footprints" else features() if a.stage == "features" else armd(a.workers)
    print(json.dumps(r.get("tests", r.get("scans", {})) if a.stage != "footprints" else
                     {k: v["calibration"] for k, v in r["scans"].items()}, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
