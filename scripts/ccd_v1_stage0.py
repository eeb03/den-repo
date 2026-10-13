"""
CCD-V1 Stage 0 diagnostics (docs/ccd-v1-stage0-1-protocol.md §B). Descriptive;
spent data only; nothing here is validation.

    python -m scripts.ccd_v1_stage0 attribution --workers 6   # B0a, B0a', B0b
    python -m scripts.ccd_v1_stage0 fourtu-amplitude            # B0c
    python -m scripts.ccd_v1_stage0 fourtu-geometry             # B0d

Outputs: artifacts/ccd_v1/stage0_*.json. The stored PR #13 outputs are read,
never rewritten; A3 is re-run into new files and checked against them.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import re
import struct
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.signal import hilbert

OUT = Path("artifacts/ccd_v1")
V2_EVAL = Path("artifacts/simulation/hyperbola_v2/evaluate.jsonl")
FOURTU = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")

# frozen (protocol §B0a)
LATE_LATERAL_WL = 3.0
LATE_MAX_T = 6.0
DIRECT_TAIL_T = 2.0
NOISE_FREE_K = 3.0
TARGET_FIELD_SHARE = 0.5
KINDS = {
    "duplicate": "scoring_policy", "limb": "scoring_policy",
    "early": "system_or_processing", "direct_tail": "system_or_processing",
    "unexplained_imprint": "system_or_processing",
    "clutter_object": "generator_object", "layer": "generator_object",
    "stone_limb": "generator_object", "layer_multiple": "generator_object",
    "target_multiple": "scored_target_physics", "target_late": "scored_target_physics",
    "unexplained_noise": "noise_induced",
    "unexplained_target_field": "genuinely_unexplained_wavefield",
    "unexplained_twin_field": "genuinely_unexplained_wavefield",
}


def _events(tg) -> list[np.ndarray]:
    ev = tg.get("predicted_events") or {"top": tg["predicted"]}
    return [np.array([np.nan if v is None else v for v in e["two_way_time_s"]], float) for e in ev.values()]


def attribute(det: dict, base_class: str, line, nf_full, nf_twin) -> str:
    """Protocol §B0a rules 6-11 and §B0a' for one unmatched detection."""
    from simulation.scenario import CLUTTER_PREFIX
    if base_class not in ("clutter",):
        return base_class
    truth = line.truth
    f = truth["wavelet"]["centre_frequency_hz"]
    T, chi = 1.0 / f, truth["wavelet"]["peak_delay_s"]
    lam = line.soil_velocity_m_per_s / f
    tr, t = det["trace"], det["t"]
    stones = [tg for tg in truth["targets"] if tg["target_id"].startswith(CLUTTER_PREFIX)]
    scored = [tg for tg in truth["targets"] if not tg["target_id"].startswith(CLUTTER_PREFIX)]
    # 6 stone limbs
    for tg in stones:
        if any(np.isfinite(e[tr]) and abs(t - e[tr]) <= T for e in _events(tg)):
            return "stone_limb"
    # 7 layer multiple
    layer = truth.get("layer")
    if layer is not None and abs(t - (2 * layer["predicted_two_way_time_s"][tr] - chi)) <= T:
        return "layer_multiple"
    # 8 target multiple
    for tg in scored:
        if any(np.isfinite(e[tr]) and abs(t - (2 * e[tr] - chi)) <= T for e in _events(tg)):
            return "target_multiple"
    # 9 target late events
    for tg in scored:
        ev = _events(tg)
        last = max(float(np.nanmin(e)) for e in ev)
        if abs(det["x"] - tg["geometry"]["centre_x_m"]) <= LATE_LATERAL_WL * lam and \
                last + T < t <= last + T + LATE_MAX_T * T:
            return "target_late"
    # 10 direct-wave tail
    tx, rx = np.asarray(truth["antennas"]["tx_x_m"]), np.asarray(truth["antennas"]["rx_x_m"])
    direct_end = 2 * (float(rx[0] - tx[0]) / 2) / line.soil_velocity_m_per_s + chi + 2 * T
    if t <= direct_end + DIRECT_TAIL_T * T:
        return "direct_tail"
    # 11 noise-free attribution
    k = int(np.clip(round((t - nf_full.time_offset_s) / nf_full.dt_s), 0, nf_full.traces.shape[1] - 1))
    full = nf_full.traces
    F = full - full.mean(axis=0)
    eF_line = np.abs(hilbert(F, axis=1))
    after = nf_full.sample_times_s > direct_end
    s_F = float(np.median(eF_line[:, after]))
    e_F = float(eF_line[tr, k])
    scat = full - nf_full.background
    a = float(np.abs(hilbert(scat[tr]))[k])
    m = float(np.abs(hilbert(scat.mean(axis=0)))[k])
    if e_F < NOISE_FREE_K * s_F:
        return "unexplained_noise"
    if m > a:
        return "unexplained_imprint"
    if a >= TARGET_FIELD_SHARE * e_F:
        return "unexplained_target_field"
    return "unexplained_twin_field"


def job(args):
    sid, meta, freeze, stored = args
    from benchmark.hyperbola_stack import estimate_time_zero  # noqa: F401  (import parity with the runner)
    from simulation.background_benchmark import digitise, score_located
    from simulation.detector_comparison import PRIMARY_CONDITION, SAMPLINGS, condition_line
    from simulation.hyperbola_v2_runner import CORPORA, _a3, score_v2
    from simulation.interface import load_line
    base = load_line(CORPORA["s1v2"] / sid)
    line = condition_line(base, PRIMARY_CONDITION)
    f = float(meta["centre_frequency_hz"])
    a3, _, _ = _a3(line, f, f"s1v2:{sid}:{PRIMARY_CONDITION}", freeze["grouping"], [freeze["lambda0"]])
    thr, located = a3[freeze["lambda0"]]
    sc = score_v2(line, located)
    repro = (sc["n_det"] == stored["n_det"] and sc["classes"] == stored["classes"]
             and sc["matched"] == stored["matched"])
    # per-detection base classes in score_v2's own order
    from simulation.hyperbola_v2_runner import scored_view
    base_classes = score_located(scored_view(line), located)["detection_classes"]
    v2_classes = []
    from simulation.scenario import CLUTTER_PREFIX
    stones = []
    f0 = line.truth["wavelet"]["centre_frequency_hz"]
    period, lam = 1 / f0, line.soil_velocity_m_per_s / f0
    for tg in line.truth["targets"]:
        if tg["target_id"].startswith(CLUTTER_PREFIX):
            ev = _events(tg)
            stones.append((tg["geometry"]["centre_x_m"], float(np.nanmin(ev[0])) - period,
                           max(float(np.nanmin(e)) for e in ev) + period))
    layer = line.truth.get("layer")
    for d, c in zip(located, base_classes):
        if c in ("early", "clutter"):
            if any(abs(d["x"] - x) <= lam and lo <= d["t"] <= hi for x, lo, hi in stones):
                c = "clutter_object"
            elif layer is not None and abs(d["t"] - layer["predicted_two_way_time_s"][d["trace"]]) <= period:
                c = "layer"
        v2_classes.append(c)
    nf = digitise(base, SAMPLINGS["instrument_20spp"])
    final = [attribute(d, c, line, nf, None) if c != "matched" else "matched" for d, c in zip(located, v2_classes)]
    # Task A (B0b): full truth, stones are objects
    task_a = score_located(line, located)
    n_stones = sum(t["target_id"].startswith(CLUTTER_PREFIX) for t in line.truth["targets"])
    return {"sid": sid, "family": meta["family"], "reproduced": repro, "threshold": thr,
            "n_det": len(located), "final_classes": dict(collections.Counter(c for c in final if c != "matched")),
            "task_a": {"n_objects": len(task_a["targets"]), "n_stones": n_stones,
                       "objects_detected": sum(t["detected"] for t in task_a["targets"]),
                       "stones_detected": sum(t["detected"] for t in task_a["targets"]
                                              if t["target_id"].startswith(CLUTTER_PREFIX)),
                       "matched_detections": sum(t["detected"] for t in task_a["targets"]),
                       "physically_empty": len(line.truth["targets"]) == 0,
                       "empty_and_no_layer": len(line.truth["targets"]) == 0 and layer is None},
            "v2_class_replica_matches": dict(collections.Counter(c for c in v2_classes if c != "matched"))
            == sc["classes"]}


def attribution(workers: int) -> dict:
    from simulation.hyperbola_v2_runner import CORPORA, load_committed_freeze, FREEZE
    from simulation.detector_comparison import PRIMARY_CONDITION
    freeze = load_committed_freeze(FREEZE)
    meta = json.loads((CORPORA["s1v2"] / "index.json").read_text())["scenes"]
    stored = {}
    for ln in V2_EVAL.open():
        r = json.loads(ln)
        if r["condition"] == PRIMARY_CONDITION:
            stored[r["sid"]] = r["res"]["A3"]
    sids = sorted(s for s, m in meta.items() if m["split"] == "eval")
    with Pool(workers) as pool:
        rows = pool.map(job, [(s, meta[s], freeze, stored[s]) for s in sids])
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "stage0a_attribution_rows.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    total = collections.Counter()
    by_family = collections.defaultdict(collections.Counter)
    for r in rows:
        total.update(r["final_classes"])
        by_family[r["family"]].update(r["final_classes"])
    kinds = collections.Counter()
    for c, n in total.items():
        kinds[KINDS[c]] += n
    ta = [r["task_a"] for r in rows]
    n_det = sum(r["n_det"] for r in rows)
    empty = [r for r in rows if r["task_a"]["physically_empty"]]
    summary = {
        "label": "DESCRIPTIVE; corpus_s1_v2 eval is spent (PR #13); SIMULATION ONLY",
        "scenes": len(rows), "reproduced_all": all(r["reproduced"] for r in rows),
        "class_replica_matches_all": all(r["v2_class_replica_matches"] for r in rows),
        "not_reproduced": [r["sid"] for r in rows if not r["reproduced"]],
        "n_detections": n_det, "n_unmatched": sum(total.values()),
        "by_category": dict(total.most_common()), "by_kind": dict(kinds.most_common()),
        "by_family": {k: dict(v.most_common()) for k, v in sorted(by_family.items())},
        "task_a": {
            "objects": sum(t["n_objects"] for t in ta), "stones": sum(t["n_stones"] for t in ta),
            "objects_detected": sum(t["objects_detected"] for t in ta),
            "stones_detected": sum(t["stones_detected"] for t in ta),
            "recall_all_objects": sum(t["objects_detected"] for t in ta) / max(1, sum(t["n_objects"] for t in ta)),
            "recall_stones": sum(t["stones_detected"] for t in ta) / max(1, sum(t["n_stones"] for t in ta)),
            "precision": sum(t["matched_detections"] for t in ta) / max(1, n_det),
            "physically_empty_scenes": len(empty),
            "fp_per_physically_empty_scene": (sum(r["n_det"] for r in empty) / len(empty)) if empty else None,
            "physically_empty_scenes_without_layer": sum(r["task_a"]["empty_and_no_layer"] for r in rows),
        },
    }
    (OUT / "stage0a_attribution.json").write_text(json.dumps(summary, indent=1))
    return summary


# --- B0c / B0d: 4TU audits -------------------------------------------------------------

GAIN_WORDS = re.compile(r"\b(gain|agc|agc\w*|sec|automatic gain|exponential|processing|processed|filter\w*|dewow)\b",
                        re.IGNORECASE)


def _segy_headers(path: Path):
    """(textual header text, format code, trace header ints for traces, traces array)."""
    from converters.segy_endian import detect_endianness, LITTLE
    from scripts.real_data_detector_saturation import read_line
    raw = path.read_bytes()
    text = raw[:3200]
    try:
        txt = text.decode("cp500") if text[:1] == b"\xc3" else text.decode("ascii", "replace")
    except Exception:  # noqa: BLE001
        txt = text.decode("latin-1", "replace")
    order, _ = detect_endianness(path)
    end = "<" if order == LITTLE else ">"
    fmt = struct.unpack(end + "h", raw[3224:3226])[0]
    ns = struct.unpack(end + "H", raw[3220:3222])[0]
    tr, dt_s, x, _ = read_line(path)
    bps = {1: 4, 2: 4, 3: 2, 5: 4, 8: 1}.get(fmt, 4)
    th = []
    for i in range(min(tr.shape[0], 50)):
        off = 3600 + i * (240 + ns * bps)
        h = raw[off:off + 240]
        th.append({"gain_type": struct.unpack(end + "h", h[118:120])[0],
                   "gain_constant": struct.unpack(end + "h", h[120:122])[0],
                   "initial_gain": struct.unpack(end + "h", h[122:124])[0],
                   "sx": struct.unpack(end + "i", h[72:76])[0], "sy": struct.unpack(end + "i", h[76:80])[0]})
    return txt, fmt, th, tr, raw, end, ns, bps


def fourtu_amplitude() -> dict:
    files = sorted(glob.glob(str(FOURTU / "**/*.sgy"), recursive=True))
    rows = []
    for p in files:
        try:
            txt, fmt, th, tr, *_ = _segy_headers(Path(p))
        except Exception as e:  # noqa: BLE001
            rows.append({"path": p, "error": str(e)[:120]})
            continue
        env = np.median(np.abs(hilbert(tr - tr.mean(axis=0), axis=1)), axis=0)
        n = env.size
        early = env[int(0.20 * n):int(0.35 * n)]
        late = env[int(0.70 * n):]
        rows.append({"path": p, "format_code": fmt, "n_traces": int(tr.shape[0]), "n_samples": int(n),
                     "text_gain_words": sorted({w.lower() for w in GAIN_WORDS.findall(txt)}),
                     "gain_fields_nonzero": any(h["gain_type"] or h["gain_constant"] or h["initial_gain"] for h in th),
                     "late_over_early_rms": float(np.sqrt(np.mean(late ** 2)) / max(1e-12, np.sqrt(np.mean(early ** 2))))})
    ok = [r for r in rows if "error" not in r]
    ratio = np.array([r["late_over_early_rms"] for r in ok])
    summary = {
        "files": len(rows), "read_ok": len(ok), "errors": len(rows) - len(ok),
        "format_codes": dict(collections.Counter(r["format_code"] for r in ok)),
        "files_with_gain_words_in_textual_header": sum(bool(r["text_gain_words"]) for r in ok),
        "gain_words_seen": dict(collections.Counter(w for r in ok for w in r["text_gain_words"])),
        "files_with_nonzero_trace_gain_fields": sum(r["gain_fields_nonzero"] for r in ok),
        "late_over_early_rms_quantiles": {q: float(np.percentile(ratio, q)) for q in (5, 25, 50, 75, 95)},
        "rule": "not_preserved only if a header/documentation states gain; preserved only if documentation "
                "states raw export; otherwise unknown. The indicator is circumstantial only.",
    }
    summary["outcome"] = ("not_preserved" if summary["files_with_nonzero_trace_gain_fields"] else "unknown")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stage0c_fourtu_amplitude.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    return summary


def _decode_positions(th_all, end) -> np.ndarray | None:
    xs, ys = [], []
    for sx, sy in th_all:
        fx = struct.unpack(end + "f", struct.pack(end + "i", sx))[0]
        fy = struct.unpack(end + "f", struct.pack(end + "i", sy))[0]
        xs.append(fx)
        ys.append(fy)
    xs, ys = np.array(xs), np.array(ys)
    ok = np.isfinite(xs) & np.isfinite(ys) & (np.abs(xs) > 1) & (np.abs(ys) > 1) & (np.abs(xs) < 18000) & (np.abs(ys) < 9000)
    if ok.mean() < 0.5:
        return None
    # NMEA ddmm.mmmm: one of them is latitude (~52 deg N), the other longitude (~4-7 deg E)
    lat_raw, lon_raw = (ys, xs) if np.nanmedian(np.abs(ys)) > np.nanmedian(np.abs(xs)) else (xs, ys)
    from converters.segy_endian import nmea_to_degrees
    lat = np.array([nmea_to_degrees(v) for v in lat_raw])
    lon = np.array([nmea_to_degrees(v) for v in lon_raw])
    lat0 = np.nanmedian(lat[ok])
    e = (lon - np.nanmedian(lon[ok])) * 111320 * math.cos(math.radians(lat0))
    n = (lat - lat0) * 110540
    pts = np.column_stack([e, n])
    pts[~ok] = np.nan
    return pts, float(ok.mean()), float(lat0), float(np.nanmedian(lon[ok]))


def fourtu_geometry() -> dict:
    files = sorted(glob.glob(str(FOURTU / "**/*.sgy"), recursive=True))
    by_act = collections.defaultdict(list)
    for p in files:
        parts = Path(p).relative_to(FOURTU).parts
        by_act[parts[2] if len(parts) > 3 else parts[0]].append(p)
    acts = {}
    for act, paths in sorted(by_act.items()):
        geo = []
        for p in paths:
            try:
                txt, fmt, _, tr, raw, end, ns, bps = _segy_headers(Path(p))
            except Exception as e:  # noqa: BLE001
                geo.append({"path": p, "error": str(e)[:100]})
                continue
            th_all = []
            for i in range(tr.shape[0]):
                off = 3600 + i * (240 + ns * bps)
                th_all.append(struct.unpack(end + "ii", raw[off + 72:off + 80]))
            dec = _decode_positions(th_all, end)
            if dec is None:
                geo.append({"path": p, "valid_fix_fraction": 0.0})
                continue
            pts, frac, lat0, lon0 = dec
            good = pts[np.isfinite(pts[:, 0])]
            seg = np.diff(good, axis=0)
            length = float(np.sum(np.hypot(seg[:, 0], seg[:, 1])))
            d = good[-1] - good[0]
            heading = float(math.degrees(math.atan2(d[1], d[0])) % 180.0)
            jumps = int(np.sum(np.hypot(seg[:, 0], seg[:, 1]) > 1.0))
            geo.append({"path": p, "valid_fix_fraction": frac, "length_m": length, "chord_m": float(np.hypot(*d)),
                        "heading_deg_mod180": heading, "jumps_gt_1m": jumps,
                        "lat0": lat0, "lon0": lon0, "_pts": good})
        pairs = []
        usable = [g for g in geo if g.get("_pts") is not None and g.get("chord_m", 0) > 1]
        # common local frame per activity
        if usable:
            lat_ref, lon_ref = usable[0]["lat0"], usable[0]["lon0"]
            for g in usable:
                shift = np.array([(g["lon0"] - lon_ref) * 111320 * math.cos(math.radians(lat_ref)),
                                  (g["lat0"] - lat_ref) * 110540])
                g["_abs"] = g["_pts"] + shift
        for i in range(len(usable)):
            for j in range(i + 1, len(usable)):
                a, b = usable[i], usable[j]
                dh = abs(a["heading_deg_mod180"] - b["heading_deg_mod180"])
                dh = min(dh, 180 - dh)
                if dh > 15:
                    continue
                u = np.array([math.cos(math.radians(a["heading_deg_mod180"])), math.sin(math.radians(a["heading_deg_mod180"]))])
                nrm = np.array([-u[1], u[0]])
                pa, pb = a["_abs"], b["_abs"]
                sep = float(np.median(np.abs((pb - pa[0]) @ nrm)))
                ta, tb = pa @ u, pb @ u
                overlap = float(min(ta.max(), tb.max()) - max(ta.min(), tb.min()))
                if sep <= 2.0 and overlap >= 5.0:
                    pairs.append({"a": Path(a["path"]).name, "b": Path(b["path"]).name, "heading_diff_deg": dh,
                                  "separation_m": sep, "overlap_m": overlap})
        for g in geo:
            g.pop("_pts", None)
            g.pop("_abs", None)
        acts[act] = {"n_paths": len(paths), "paths": geo, "parallel_pairs": pairs}
    measurable = sorted(a for a, v in acts.items() if v["parallel_pairs"])
    summary = {"activities": len(acts), "paths": len(files),
               "activities_with_ge2_paths": sum(v["n_paths"] >= 2 for v in acts.values()),
               "activities_with_parallel_pair": len(measurable), "measurable_in_principle": measurable,
               "registration_accuracy": "UNVERIFIED: no GNSS quality field or documentation states it",
               "encoding_assumed": "ieee_nmea (the corpus's declared encoding; caller-declared)"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stage0d_fourtu_geometry.json").write_text(json.dumps({"summary": summary, "activities": acts},
                                                                  indent=1, default=str))
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("attribution", "fourtu-amplitude", "fourtu-geometry"))
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args(argv)
    r = {"attribution": lambda: attribution(a.workers), "fourtu-amplitude": fourtu_amplitude,
         "fourtu-geometry": fourtu_geometry}[a.stage]()
    print(json.dumps(r, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
