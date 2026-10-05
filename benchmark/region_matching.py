"""
PRE-REGISTERED matching rule for scoring response regions (and, for
comparison, 2D point detections) against the BAM construction drawings.

Committed BEFORE any target-level region result was computed. Not to be
changed after seeing results; a change would be a new rule with a new name.

ALL COORDINATES IN METRES, depth below the calibrated surface. Only
depth-domain outputs are scoreable; a time-domain output is reported as not
scoreable.

TARGET FOOTPRINTS (from the drawings):
  duct  (runs along y): x in [x_d - r, x_d + r], r = 33.5 mm, any y;
        depth [z_top, z_top + 67 mm]
  cuboid: x in [x_c - 60, x_c + 60] mm, y in the drawn y extent;
        depth [z_top, z_top + 60 mm]

A REGION MATCHES A TARGET when ALL hold:
  1. its PEAK lies inside the target's lateral footprint expanded by
     LATERAL_TOL (50 mm) -- x for ducts, x and y for cuboids. (A peak rule,
     not an overlap rule, so one wide sheet cannot claim every target it
     touches.)
  2. its depth interval [z_min, z_max] intersects the target's depth interval
     expanded by DEPTH_TOL (60 mm) on both sides.
A 2D POINT DETECTION (x, line y, depth) matches under the same two rules,
with the point as both peak and interval.

ASSIGNMENT (deterministic): all (output, target) pairs that match, sorted by
the output's own score descending, then id. Walking that list: an output is
used at most once; the first output for a target CREDITS it (true positive);
every further output matching an already-credited target is a DUPLICATE
(neither a hit nor a false positive). An output matching no target is
checked against KNOWN NON-TARGET STRUCTURES (reported, excluded from
precision); otherwise it is a FALSE output.

KNOWN NON-TARGET STRUCTURES (from the drawings, categories fixed here):
  back_wall          depth interval within DEPTH_TOL of the step thickness at
                     the peak's x step (steps of 500 mm)
  edge_reinforcement peak y < 0.10 m or > 0.70 m and z_min <= 0.12 m
                     (bars near both long edges, 25-100 mm deep)
  grouted_borehole   peak within 60 mm laterally of a drawn borehole
FALSE categories (diagnostic only): below_back_wall (z_min more than
DEPTH_TOL below the back wall at its x), step_edge (peak within 60 mm of x =
0.5/1.0/1.5 m), other.

METRICS (per class -- ducts and foam cuboids are never pooled):
  recall      credited targets / targets
  precision   (TP + duplicates) / (TP + duplicates + false); known structures excluded
  strict_precision  TP / all outputs
  F1          from recall and precision
  false per scan, per line (161) and per m^2 of scanned area (2.0 x 0.8 m)
  duplicates per credited target
  centroid / peak lateral error (ducts: x only), depth error (region top
  z_min and peak depth vs drawn top), extent vs drawn extent where meaningful
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

LATERAL_TOL = 0.050
DEPTH_TOL = 0.060
DUCT_R = 0.0335
SCAN_AREA_M2 = 2.0 * 0.8
N_LINES = 161
RULE_NAME = "bam-region-match-v1"


@dataclass
class Target:
    id: str
    kind: str                     # duct | cuboid
    x_range: tuple[float, float]
    y_range: Optional[tuple[float, float]]
    z_top: float
    z_bottom: float


@dataclass
class Output:
    id: str
    score: float
    peak: tuple[float, float, float]
    z_range: tuple[float, float]
    centroid: Optional[tuple[float, float, float]] = None
    extent: Optional[tuple[float, float, float]] = None
    fwhm: Optional[tuple[float, float, float]] = None
    extra: dict = field(default_factory=dict)


def targets_from_csv(rows: list[dict], specimen: str) -> tuple[list[Target], dict]:
    mm = 1e-3
    targets, structures = [], {"back_wall": [], "boreholes": []}
    for r in rows:
        if r["specimen_id"] != specimen:
            continue
        t = r["object_type"]
        if t == "tendon_duct":
            x = float(r["x_mm"]) * mm
            zt = float(r["z_top_mm"]) * mm
            targets.append(Target(r["object_id"], "duct", (x - DUCT_R, x + DUCT_R), None, zt, zt + 2 * DUCT_R))
        elif t == "void_analogue_cuboid":
            x = float(r["x_mm"]) * mm
            y0, y1 = [float(v) * mm for v in re.findall(r"[\d.]+", r["y_extent_mm"])[:2]]
            zt = float(r["z_top_mm"]) * mm
            targets.append(Target(r["object_id"], "cuboid", (x - 0.06, x + 0.06), (y0, y1), zt, zt + 0.06))
        elif t == "step_back_wall":
            structures["back_wall"] = [float(v) * mm for v in re.findall(r"(\d+\.\d)", r["dimensions_mm"])[:4]]
        elif t == "grouted_borehole":
            structures["boreholes"].append((float(r["x_mm"]) * mm, float(r["y_mm"]) * mm))
    return targets, structures


def matches(o: Output, t: Target) -> bool:
    px, py, _ = o.peak
    if not (t.x_range[0] - LATERAL_TOL <= px <= t.x_range[1] + LATERAL_TOL):
        return False
    if t.y_range is not None and not (t.y_range[0] - LATERAL_TOL <= py <= t.y_range[1] + LATERAL_TOL):
        return False
    return o.z_range[0] <= t.z_bottom + DEPTH_TOL and o.z_range[1] >= t.z_top - DEPTH_TOL


def structure_of(o: Output, structures: dict) -> Optional[str]:
    px, py, _ = o.peak
    bw = structures.get("back_wall") or []
    if bw:
        step = min(int(px // 0.5), 3)
        z = bw[step]
        if o.z_range[0] <= z + DEPTH_TOL and o.z_range[1] >= z - DEPTH_TOL:
            return "back_wall"
    if (py < 0.10 or py > 0.70) and o.z_range[0] <= 0.12:
        return "edge_reinforcement"
    if any(abs(px - bx) <= 0.06 and abs(py - by) <= 0.06 for bx, by in structures.get("boreholes", [])):
        return "grouted_borehole"
    return None


def false_category(o: Output, structures: dict) -> str:
    px = o.peak[0]
    bw = structures.get("back_wall") or []
    if bw and o.z_range[0] > bw[min(int(px // 0.5), 3)] + DEPTH_TOL:
        return "below_back_wall"
    if any(abs(px - e) <= 0.06 for e in (0.5, 1.0, 1.5)):
        return "step_edge"
    return "other"


def score(outputs: list[Output], targets: list[Target], structures: dict) -> dict:
    pairs = sorted(((o, t) for o in outputs for t in targets if matches(o, t)),
                   key=lambda p: (-p[0].score, p[0].id, p[1].id))
    used, credited = set(), {}
    dups: dict[str, list[Output]] = {t.id: [] for t in targets}
    for o, t in pairs:
        if o.id in used:
            continue
        used.add(o.id)
        if t.id not in credited:
            credited[t.id] = o
        else:
            dups[t.id].append(o)
    known, false = {}, {}
    for o in outputs:
        if o.id in used:
            continue
        s = structure_of(o, structures)
        if s:
            known[s] = known.get(s, 0) + 1
        else:
            c = false_category(o, structures)
            false[c] = false.get(c, 0) + 1
    out = {"rule": RULE_NAME, "n_outputs": len(outputs), "known_structures": known, "false_categories": false,
           "per_class": {}}
    for kind in sorted({t.kind for t in targets}):
        ts = [t for t in targets if t.kind == kind]
        tp = [t for t in ts if t.id in credited]
        n_dup = sum(len(dups[t.id]) for t in ts)
        out["per_class"][kind] = {"targets": len(ts), "credited": len(tp), "recall": len(tp) / len(ts),
                                  "duplicates": n_dup,
                                  "duplicates_per_credited_target": (n_dup / len(tp)) if tp else None,
                                  "per_target": {t.id: _errors(credited.get(t.id), t, len(dups[t.id])) for t in ts}}
    n_tp = len(credited)
    n_dup = sum(len(v) for v in dups.values())
    n_false = sum(false.values())
    prec = (n_tp + n_dup) / (n_tp + n_dup + n_false) if (n_tp + n_dup + n_false) else None
    rec = n_tp / len(targets) if targets else None
    out.update({"targets": len(targets), "credited": n_tp, "duplicates": n_dup, "false": n_false,
                "recall": rec, "precision": prec,
                "strict_precision": n_tp / len(outputs) if outputs else None,
                "f1": (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if targets else None),
                "false_per_scan": n_false, "false_per_line": n_false / N_LINES,
                "false_per_m2": n_false / SCAN_AREA_M2})
    return out


def _errors(o: Optional[Output], t: Target, n_dup: int) -> dict:
    if o is None:
        return {"credited": False, "duplicates": n_dup}
    tx = (t.x_range[0] + t.x_range[1]) / 2
    ty = None if t.y_range is None else (t.y_range[0] + t.y_range[1]) / 2
    e = {"credited": True, "by": o.id, "duplicates": n_dup,
         "peak_dx_mm": round((o.peak[0] - tx) * 1000, 1),
         "peak_dy_mm": None if ty is None else round((o.peak[1] - ty) * 1000, 1),
         "peak_depth_error_mm": round((o.peak[2] - t.z_top) * 1000, 1),
         "top_depth_error_mm": round((o.z_range[0] - t.z_top) * 1000, 1)}
    if o.centroid is not None:
        e["centroid_dx_mm"] = round((o.centroid[0] - tx) * 1000, 1)
        e["centroid_dy_mm"] = None if ty is None else round((o.centroid[1] - ty) * 1000, 1)
        e["centroid_depth_error_mm"] = round((o.centroid[2] - t.z_top) * 1000, 1)
    if o.extent is not None:
        e["extent_mm"] = [round(v * 1000, 1) for v in o.extent]
        e["drawn_extent_mm"] = [round((t.x_range[1] - t.x_range[0]) * 1000, 1),
                                None if t.y_range is None else round((t.y_range[1] - t.y_range[0]) * 1000, 1),
                                round((t.z_bottom - t.z_top) * 1000, 1)]
    if o.fwhm is not None:
        e["fwhm_mm"] = [round(v * 1000, 1) for v in o.fwhm]
    return e
