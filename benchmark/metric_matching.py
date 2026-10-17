"""
Object-level matching of candidates to buried objects in METRIC planar
coordinates, with declared tolerances.

    match_objects(manifest, frame_id, candidates, groups, tolerance, ...) -> dict

WHY THIS EXISTS. `benchmark.target_scoring` matches per (target, line) in a
frame's own units, which suits BAM. The controlled survey
(docs/post-pr17-acquisition-strategy-brief.md §6) scores OBJECTS: one unit
per buried object, lines as repeated measures, tolerances in metres that may
grow with depth, a detected-length fraction for linear objects, and false
alarms counted only inside independently verified-empty AREAS. This module
does that. It reuses the targets manifest, its frames and its capability
gates unchanged, and applies no transform between frames.

FAIL CLOSED. Matching needs the frame to support LOCALIZATION_ERROR in the
manifest (declared origin, units and registration to the radar): a metric
distance in a frame nobody has registered is not a measurement. Every
tolerance is declared by the caller and echoed in the result; nothing is
defaulted to unlock a number.

THE RULES (all deterministic; ties broken by identifier):
  1. A candidate is FEASIBLE for a target when its horizontal distance to the
     target's geometry (point, segment or surveyed polyline) is within the
     target's horizontal tolerance.
  2. Each candidate is assigned to at most ONE target: the nearest feasible
     one, ties by target_id. A candidate is never counted twice.
  3. COMPACT targets: the nearest assigned candidate is the detection (ties
     by candidate_id); the others assigned to the same target are
     `duplicates`. Because rule 2 fixes each candidate's target first, a
     candidate between two objects serves only the nearer one -- a
     deliberate, conservative choice, not a global optimum.
  4. LINEAR targets: every assigned candidate covers the axis within
     `coverage_radius_m` of its projection onto the axis. The DETECTED
     LENGTH FRACTION is the covered share of the axis length, and the target
     counts as detected when it reaches `min_length_fraction`.
  5. An unassigned candidate inside a VERIFIED-EMPTY AREA is a FALSE ALARM.
     Anywhere else it is UNVERIFIED: not known to be false (brief §6.5).
  6. Depth is scored separately and never gates detection.

NOTHING HERE READS A DETECTOR, and the result holds no statistic beyond
counts; intervals belong to the validation protocol.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

from benchmark.targets import (
    Capability, FrameKind, GroundTruthTarget, MeasuredTo, PointLocation, SegmentLocation,
    TargetManifest,
)

UNIT_TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001}
CLASS_GROUPS = ("linear", "compact")


class MatchingBlocked(RuntimeError):
    """The requested matching is not supported by the declared evidence."""


@dataclass(frozen=True)
class Tolerance:
    """
    Horizontal: max(horizontal_m, horizontal_depth_fraction * depth_to_top).
    For a compact target, half its largest declared dimension is added when
    `add_half_size` is set, since the reference point is its centre.
    Depth: max(depth_floor_m, depth_fraction * true depth).
    """
    name: str
    horizontal_m: float
    horizontal_depth_fraction: float = 0.0
    add_half_size: bool = False
    depth_fraction: Optional[float] = None
    depth_floor_m: float = 0.0
    source: str = ""

    def __post_init__(self):
        for k in ("horizontal_m", "horizontal_depth_fraction", "depth_floor_m"):
            v = getattr(self, k)
            if not math.isfinite(v) or v < 0:
                raise MatchingBlocked(f"tolerance {self.name}: {k} must be finite and >= 0")
        if self.depth_fraction is not None and not (0 <= self.depth_fraction < 10):
            raise MatchingBlocked(f"tolerance {self.name}: depth_fraction out of range")


@dataclass(frozen=True)
class Candidate:
    """A detector output in the same metric frame, never carrying truth."""
    candidate_id: str
    x: float
    y: float
    depth_m: Optional[float] = None

    def __post_init__(self):
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise MatchingBlocked(f"candidate {self.candidate_id}: non-finite position")


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

def _project(p, a, b):
    """(distance, along-segment position from a) of p onto segment ab."""
    ab = (b[0] - a[0], b[1] - a[1])
    L2 = ab[0] ** 2 + ab[1] ** 2
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / L2))
    q = (a[0] + t * ab[0], a[1] + t * ab[1])
    return math.dist(p, q), t * math.sqrt(L2)


def project_onto_polyline(p, vertices):
    """(horizontal distance, chainage along the polyline) of the nearest point."""
    best, chain, acc = math.inf, 0.0, 0.0
    for a, b in zip(vertices, vertices[1:]):
        d, s = _project(p, a, b)
        if d < best:
            best, chain = d, acc + s
        acc += math.dist(a, b)
    return best, chain


def polyline_length(vertices) -> float:
    return sum(math.dist(a, b) for a, b in zip(vertices, vertices[1:]))


def _point_in_polygon(pt, poly) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)
                and (x2 - x1) * (y - y1) == (y2 - y1) * (x - x1)):
            return True
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _polygon_area(poly) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]))) / 2


def _union_length(intervals) -> float:
    total, cur = 0.0, None
    for lo, hi in sorted(intervals):
        if cur is None or lo > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [lo, hi]
        else:
            cur[1] = max(cur[1], hi)
    return total + (cur[1] - cur[0] if cur else 0.0)


# ---------------------------------------------------------------------------
# truth side, in metres
# ---------------------------------------------------------------------------

def _top_depth_m(t: GroundTruthTarget) -> Optional[float]:
    tops = [d for d in t.depths if d.measured_to is MeasuredTo.TOP]
    return tops[0].value * UNIT_TO_M[tops[0].units] if tops else None


def _half_size_m(t: GroundTruthTarget) -> float:
    d = t.dimensions
    if d is None or d.units is None:
        return 0.0
    vals = [v for v in (d.length, d.width, d.height, d.outer_diameter) if v is not None]
    return max(vals) * UNIT_TO_M[d.units] / 2.0 if vals else 0.0


def _geometry_m(t: GroundTruthTarget, frame_id: str, scale: float, axes: dict):
    if t.target_id in axes:
        return [tuple(c * scale for c in v) for v in axes[t.target_id]]
    for loc in t.locations:
        if loc.frame_id != frame_id:
            continue
        if isinstance(loc, SegmentLocation):
            return [tuple(c * scale for c in loc.start), tuple(c * scale for c in loc.end)]
        if isinstance(loc, PointLocation):
            return [tuple(c * scale for c in loc.coordinates)]
    return None


def horizontal_tolerance_m(t: GroundTruthTarget, group: str, tol: Tolerance) -> float:
    depth = _top_depth_m(t)
    if tol.horizontal_depth_fraction > 0 and depth is None:
        raise MatchingBlocked(
            f"tolerance {tol.name} grows with depth, but target {t.target_id} has no depth to "
            f"its top")
    h = max(tol.horizontal_m, tol.horizontal_depth_fraction * (depth or 0.0))
    if tol.add_half_size and group == "compact":
        h += _half_size_m(t)
    return h


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

def match_objects(manifest: TargetManifest, frame_id: str, candidates, groups: dict,
                  tolerance: Tolerance, *, coverage_radius_m: float,
                  min_length_fraction: float, empty_areas=(), axes: Optional[dict] = None,
                  include_ids: Optional[set] = None) -> dict:
    """
    `groups`: target_id -> "linear" | "compact", declared for every scored target.
    `empty_areas`: (area_id, polygon in frame units) for independently
    verified-empty ground. `axes`: optional target_id -> surveyed polyline
    (frame units) that replaces a linear target's segment.
    `include_ids`: score only these targets (e.g. the eligible ones);
    excluded targets still absorb candidates near them, so a candidate on an
    ineligible object is never called a false alarm.
    """
    frame = manifest.frame(frame_id)
    if frame.kind not in (FrameKind.LOCAL_CARTESIAN, FrameKind.PROJECTED):
        raise MatchingBlocked(f"frame {frame_id} is {frame.kind.value}; metric matching needs a "
                              f"planar frame")
    ok, reasons = manifest.capability(Capability.LOCALIZATION_ERROR, frame_id)
    if not ok:
        raise MatchingBlocked("metric matching is not supported: " + "; ".join(reasons))
    if not (coverage_radius_m > 0 and 0 < min_length_fraction <= 1):
        raise MatchingBlocked("coverage_radius_m must be > 0 and min_length_fraction in (0, 1]")
    scale = UNIT_TO_M[frame.units]
    axes = axes or {}
    cands = sorted(candidates, key=lambda c: c.candidate_id)
    if len({c.candidate_id for c in cands}) != len(cands):
        raise MatchingBlocked("candidate ids must be unique")

    targets = sorted(manifest.targets, key=lambda t: t.target_id)
    info = {}
    for t in targets:
        group = groups.get(t.target_id)
        if group not in CLASS_GROUPS:
            raise MatchingBlocked(f"target {t.target_id}: class group {group!r} not declared")
        geom = _geometry_m(t, frame_id, scale, axes)
        if geom is None:
            raise MatchingBlocked(f"target {t.target_id} has no location in frame {frame_id}")
        if group == "linear" and len(geom) < 2:
            raise MatchingBlocked(f"linear target {t.target_id} needs an axis, not a point")
        info[t.target_id] = {"t": t, "group": group, "geom": geom,
                             "h_tol": horizontal_tolerance_m(t, group, tolerance),
                             "scored": include_ids is None or t.target_id in include_ids}

    # rules 1-2: each candidate to its nearest feasible target
    assigned, dist_to, chain_of = {}, {}, {}
    for c in cands:
        p = (c.x * scale, c.y * scale)
        best = None
        for tid, inf in info.items():
            d, s = project_onto_polyline(p, inf["geom"]) if len(inf["geom"]) > 1 \
                else (math.dist(p, inf["geom"][0]), 0.0)
            if d <= inf["h_tol"] and (best is None or (d, tid) < (best[0], best[1])):
                best = (d, tid, s)
        if best:
            assigned[c.candidate_id], dist_to[c.candidate_id], chain_of[c.candidate_id] = \
                best[1], best[0], best[2]

    per_target = {}
    by_target = {tid: [c for c in cands if assigned.get(c.candidate_id) == tid] for tid in info}

    # rule 3: compact -- the nearest assigned candidate, ties by id
    compact = [tid for tid, inf in info.items() if inf["group"] == "compact"]
    for tid in compact:
        inf = info[tid]
        tp = min(by_target[tid], key=lambda c: (dist_to[c.candidate_id], c.candidate_id),
                 default=None)
        per_target[tid] = {
            "class_group": "compact", "scored": inf["scored"], "detected": tp is not None,
            "horizontal_tolerance_m": inf["h_tol"],
            "matched_candidate": tp.candidate_id if tp else None,
            "horizontal_error_m": dist_to[tp.candidate_id] if tp else None,
            "duplicates": sorted(c.candidate_id for c in by_target[tid] if c is not tp),
            "depth": _depth(inf["t"], tp, tolerance) if tp else None}

    # rule 4: linear -- covered share of the axis
    for tid, inf in info.items():
        if inf["group"] != "linear":
            continue
        L = polyline_length(inf["geom"])
        cs = by_target[tid]
        covered = _union_length([(max(0.0, chain_of[c.candidate_id] - coverage_radius_m),
                                  min(L, chain_of[c.candidate_id] + coverage_radius_m)) for c in cs])
        frac = covered / L if L > 0 else 0.0
        errs = sorted(dist_to[c.candidate_id] for c in cs)
        per_target[tid] = {
            "class_group": "linear", "scored": inf["scored"],
            "detected": frac >= min_length_fraction,
            "horizontal_tolerance_m": inf["h_tol"], "axis_length_m": L,
            "detected_length_fraction": frac, "n_candidates": len(cs),
            "matched_candidates": [c.candidate_id for c in cs],
            "median_horizontal_error_m": float(np.median(errs)) if errs else None,
            "depth": [_depth(inf["t"], c, tolerance) for c in cs if c.depth_m is not None] or None}

    # rule 5: false alarms only in verified-empty areas
    unassigned = [c for c in cands if c.candidate_id not in assigned]
    in_area, area_m2 = {}, 0.0
    for aid, poly in empty_areas:
        poly_m = [(x * scale, y * scale) for x, y in poly]
        area_m2 += _polygon_area(poly_m)
        in_area[aid] = sorted(c.candidate_id for c in unassigned
                              if _point_in_polygon((c.x * scale, c.y * scale), poly_m))
    false_alarms = sorted({cid for v in in_area.values() for cid in v})

    scored = {tid: v for tid, v in per_target.items() if v["scored"]}
    counts = {g: {"n": sum(1 for v in scored.values() if v["class_group"] == g),
                  "detected": sum(1 for v in scored.values()
                                  if v["class_group"] == g and v["detected"])}
              for g in CLASS_GROUPS}
    return {
        "frame_id": frame_id, "frame_units": frame.units,
        "tolerance": asdict(tolerance), "coverage_radius_m": coverage_radius_m,
        "min_length_fraction": min_length_fraction,
        "rules": "nearest-feasible assignment per candidate; compact one-to-one by linear-sum "
                 "assignment; linear by covered axis fraction; false alarms only inside "
                 "verified-empty areas; ties by identifier",
        "per_target": per_target, "counts": counts,
        "excluded_targets": sorted(tid for tid, v in per_target.items() if not v["scored"]),
        "false_alarms": {"n": len(false_alarms), "candidates": false_alarms,
                         "verified_empty_area_m2": area_m2, "by_area": in_area},
        "unverified_candidates": sorted(c.candidate_id for c in unassigned
                                        if c.candidate_id not in false_alarms),
        "n_candidates": len(cands),
    }


def _depth(t: GroundTruthTarget, c: Candidate, tol: Tolerance):
    """Depth error against the top depth; reported, never gating detection."""
    true = _top_depth_m(t)
    if c is None or c.depth_m is None or true is None:
        return None
    err = c.depth_m - true
    out = {"candidate": c.candidate_id, "true_top_m": true, "error_m": err}
    if tol.depth_fraction is not None:
        lim = max(tol.depth_floor_m, tol.depth_fraction * true)
        out.update(tolerance_m=lim, within=abs(err) <= lim)
    return out


def candidates_from_artifact(artifact, manifest: TargetManifest) -> list:
    """
    Object-level candidates from a `benchmark.predictions.PredictionArtifact`,
    refusing a frame, CRS or unit mismatch exactly as `target_scoring` does.
    A radar depth is carried only when the artifact declares the velocity it
    rests on and the surface it is measured from; otherwise it stays None.
    """
    from benchmark.predictions import PredictionArtifact
    if not isinstance(artifact, PredictionArtifact):
        raise MatchingBlocked("candidates must come from a PredictionArtifact")
    if artifact.dataset_id != manifest.dataset_id:
        raise MatchingBlocked(f"artifact dataset {artifact.dataset_id!r} is not manifest "
                              f"dataset {manifest.dataset_id!r}")
    frame = manifest.frame(artifact.frame_id)
    if artifact.frame_units != frame.units:
        raise MatchingBlocked(f"units mismatch: {artifact.frame_units!r} vs {frame.units!r}")
    if frame.kind is FrameKind.PROJECTED and artifact.frame_crs != frame.crs:
        raise MatchingBlocked(f"CRS mismatch: {artifact.frame_crs!r} vs {frame.crs!r}")
    t = artifact.timing
    depth_ok = (t.velocity_source in ("declared", "measured") and t.depth_reference_surface
                and t.depth_units in UNIT_TO_M)
    out = []
    for p in artifact.predictions:
        if len(p.position) != 2:
            raise MatchingBlocked(f"prediction {p.prediction_id}: a planar position is required")
        depth = (p.radar_depth * UNIT_TO_M[t.depth_units]
                 if depth_ok and p.radar_depth is not None else None)
        out.append(Candidate(candidate_id=p.prediction_id, x=p.position[0], y=p.position[1],
                             depth_m=depth))
    return out
