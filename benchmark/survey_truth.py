"""
Controlled-survey ground truth: the `subterra.targets.v1` manifest plus what a
controlled multi-line survey must additionally prove before it can be scored.

WHY THIS EXISTS. `benchmark.targets` already models what is physically in
the ground: frames, objects, physical depths, independent evidence, attested
empty locations. A controlled survey (docs/post-pr17-acquisition-strategy-brief.md
§1.6) needs four things that manifest shape does not carry:

  * a linear object's AXIS as a surveyed polyline (vertices every <= 1 m),
    not only its two end points;
  * VERIFIED-EMPTY AREAS as polygons with an area, so false alarms can be
    reported per square metre;
  * the survey CONTROL the coordinates rest on;
  * CUSTODY: a digest of the truth, recorded before any radar file is
    processed, so a later edit cannot pass unnoticed.

This module wraps a targets manifest rather than changing it. The embedded
manifest is loaded by `benchmark.targets.load_manifest_dict` unchanged, so
every existing rule (no radar quantity, no operator interpretation at grade
A/B, named depth reference surfaces) still applies.

VALID IS NOT ELIGIBLE. `load_survey_truth` refuses a document that is
malformed or self-contradictory (an "empty" area containing a target, an axis
that disagrees with the target's own end points). `eligibility` then reports,
per object and per area, whether it meets the brief's scoring requirements
and every reason it does not. A valid object can be ineligible; it is listed,
never dropped silently.

NOTHING HERE READS A DETECTOR. No import of `interpretation`,
`preprocessing`, `benchmark.detection` or `benchmark.predictions`.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from benchmark.ground_truth import EvidenceBasis
from benchmark.targets import (
    FrameKind, ManifestError, MeasuredTo, PhysicalDepth, PointLocation, SegmentLocation,
    TargetEvidence, TargetManifest, _check_keys, _build, _DEPTH_KEYS, _EVIDENCE_KEYS,
    load_manifest_dict,
)
from schemas.segmentation import EvidenceGrade

SCHEMA = "subterra.survey_truth.v1"

UNIT_TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001}

CLASS_GROUPS = ("linear", "compact")


@dataclass(frozen=True)
class Requirements:
    """
    The scoring requirements of the brief (§1.4, §1.6), in metres. They are
    a parameter, not a property of the data: a protocol may tighten them, and
    the report records which were applied.
    """
    max_vertex_spacing_m: float = 1.0
    max_position_uncertainty_m: float = 0.02
    min_empty_excavation_depth_m: float = 1.5
    min_control_points: int = 3
    max_control_uncertainty_m: float = 0.02

    def as_dict(self) -> dict:
        return dict(self.__dict__)


BRIEF_REQUIREMENTS = Requirements()

#: Bases that can establish that ground is EMPTY: somebody dug it, or placed
#: (nothing) in it under record. A survey instrument or a record cannot.
_EMPTINESS_BASES = frozenset({EvidenceBasis.TRENCH_EXCAVATION, EvidenceBasis.SEEDED_PLACEMENT})


# ---------------------------------------------------------------------------
# geometry (2-D, frame units)
# ---------------------------------------------------------------------------

def polygon_area(poly) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(p1, p2, q1, q2) -> bool:
    """True when the closed segments share a point."""
    d1, d2, d3, d4 = _orient(q1, q2, p1), _orient(q1, q2, p2), _orient(p1, p2, q1), _orient(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4):
        return True

    def on(a, b, c):
        return (_orient(a, b, c) == 0 and min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))
    return on(q1, q2, p1) or on(q1, q2, p2) or on(p1, p2, q1) or on(p1, p2, q2)


def point_in_polygon(pt, poly) -> bool:
    """Ray casting; a point on the boundary counts as inside."""
    n = len(poly)
    for i in range(n):
        if _segments_cross(poly[i], poly[(i + 1) % n], pt, pt):
            return True
    x, y = pt
    inside = False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def polyline_touches_polygon(vertices, poly) -> bool:
    if any(point_in_polygon(v, poly) for v in vertices):
        return True
    edges = list(zip(poly, poly[1:] + poly[:1]))
    return any(_segments_cross(a, b, e1, e2)
               for a, b in zip(vertices, vertices[1:]) for e1, e2 in edges)


def _is_simple(poly) -> bool:
    n = len(poly)
    edges = [(poly[i], poly[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue          # adjacent edges share a vertex by construction
            if _segments_cross(*edges[i], *edges[j]):
                return False
    return True


# ---------------------------------------------------------------------------
# document parts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ControlPoint:
    point_id: str
    frame_id: str
    coordinates: tuple
    uncertainty: Optional[float]
    method: str
    source: str


@dataclass(frozen=True)
class LinearAxis:
    frame_id: str
    vertices: tuple
    vertex_uncertainty: Optional[float]

    def max_spacing(self) -> float:
        return max(math.dist(a, b) for a, b in zip(self.vertices, self.vertices[1:]))

    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.vertices, self.vertices[1:]))


@dataclass(frozen=True)
class SurveyObject:
    target_id: str
    class_group: str
    axis: Optional[LinearAxis] = None


@dataclass(frozen=True)
class VerifiedEmptyArea:
    """Ground dug and documented to hold no object, as a polygon with an area."""
    area_id: str
    frame_id: str
    polygon: tuple
    excavation_depth: PhysicalDepth
    evidence: TargetEvidence
    notes: str = ""

    def area(self) -> float:
        return polygon_area(list(self.polygon))


@dataclass(frozen=True)
class Custody:
    sealed_utc: str
    sealed_by: str
    statement: str


@dataclass(frozen=True)
class SurveyTruth:
    survey_id: str
    site_id: str
    manifest: TargetManifest
    objects: tuple
    control_points: tuple
    verified_empty_areas: tuple
    custody: Custody
    digest: str

    def object(self, target_id: str) -> SurveyObject:
        return next(o for o in self.objects if o.target_id == target_id)


# ---------------------------------------------------------------------------
# custody digest
# ---------------------------------------------------------------------------

def canonical_bytes(doc: dict) -> bytes:
    """One byte string per document content, independent of key order and whitespace."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def truth_digest(doc: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(doc)).hexdigest()


def verify_digest(doc: dict, expected: str) -> None:
    """Refuse a truth document whose content is not the one sealed."""
    actual = truth_digest(doc)
    if actual != expected:
        raise ManifestError(
            f"truth digest {actual} does not match the sealed digest {expected}; the truth "
            f"changed after custody was recorded")


# ---------------------------------------------------------------------------
# strict loading
# ---------------------------------------------------------------------------

_DOC_KEYS = {"schema", "survey_id", "site_id", "targets_manifest", "objects", "control_points",
             "verified_empty_areas", "custody", "$comment"}
_OBJECT_KEYS = {"target_id", "class_group", "axis"}
_AXIS_KEYS = {"frame_id", "vertices", "vertex_uncertainty"}
_CONTROL_KEYS = {"point_id", "frame_id", "coordinates", "uncertainty", "method", "source"}
_AREA_KEYS = {"area_id", "frame_id", "polygon", "excavation_depth", "evidence", "notes"}
_CUSTODY_KEYS = {"sealed_utc", "sealed_by", "statement"}


def _coords(seq, where) -> tuple:
    try:
        out = tuple(tuple(float(c) for c in p) for p in seq)
    except (TypeError, ValueError):
        raise ManifestError(f"{where}: coordinates must be lists of numbers") from None
    if not all(len(p) == 2 and all(math.isfinite(c) for c in p) for p in out):
        raise ManifestError(f"{where}: every vertex needs two finite coordinates")
    return out


def _planar_frame(manifest: TargetManifest, frame_id, where):
    frame = manifest.frame(frame_id)
    if frame.kind not in (FrameKind.LOCAL_CARTESIAN, FrameKind.PROJECTED):
        raise ManifestError(
            f"{where}: frame {frame_id} is {frame.kind.value}; survey truth needs a planar "
            f"local_cartesian or projected frame")
    return frame


def _target_geometry(target, frame_id):
    """The target's own planar geometry in a frame, as vertex lists."""
    out = []
    for loc in target.locations:
        if loc.frame_id != frame_id:
            continue
        if isinstance(loc, PointLocation):
            out.append([loc.coordinates])
        elif isinstance(loc, SegmentLocation):
            out.append([loc.start, loc.end])
    return out


def load_survey_truth_dict(doc: dict, sealed_digest: Optional[str] = None) -> SurveyTruth:
    _check_keys(doc, _DOC_KEYS, "survey truth")
    if doc.get("schema") != SCHEMA:
        raise ManifestError(f"survey truth schema {doc.get('schema')!r}; expected {SCHEMA!r}")
    for key in ("survey_id", "site_id"):
        if not str(doc.get(key) or "").strip():
            raise ManifestError(f"survey truth {key} is required")
    if sealed_digest is not None:
        verify_digest(doc, sealed_digest)
    manifest = load_manifest_dict(doc.get("targets_manifest") or {})
    surfaces = {s.surface_id for s in manifest.depth_reference_surfaces}
    targets = {t.target_id: t for t in manifest.targets}

    objects = []
    for i, o in enumerate(doc.get("objects") or []):
        where = f"object {o.get('target_id', i)}"
        _check_keys(o, _OBJECT_KEYS, where)
        tid = o.get("target_id")
        if tid not in targets:
            raise ManifestError(f"{where}: no target {tid!r} in the embedded manifest")
        group = o.get("class_group")
        if group not in CLASS_GROUPS:
            raise ManifestError(f"{where}: class_group {group!r}; one of {list(CLASS_GROUPS)} "
                                f"(declared, never inferred from the class name)")
        axis = None
        if o.get("axis") is not None:
            _check_keys(o["axis"], _AXIS_KEYS, f"{where} axis")
            frame = _planar_frame(manifest, o["axis"].get("frame_id"), f"{where} axis")
            verts = _coords(o["axis"].get("vertices") or [], f"{where} axis")
            if len(verts) < 2:
                raise ManifestError(f"{where} axis: a polyline needs at least two vertices")
            unc = o["axis"].get("vertex_uncertainty")
            if unc is not None and (not math.isfinite(unc) or unc < 0):
                raise ManifestError(f"{where} axis: vertex_uncertainty must be non-negative")
            axis = LinearAxis(frame_id=frame.frame_id, vertices=verts, vertex_uncertainty=unc)
            for loc in targets[tid].locations:
                if isinstance(loc, SegmentLocation) and loc.frame_id == frame.frame_id:
                    tol = (loc.uncertainty or 0.0) + (unc or 0.0)
                    ends = {verts[0], verts[-1]}
                    for e in (loc.start, loc.end):
                        if min(math.dist(e, v) for v in ends) > tol:
                            raise ManifestError(
                                f"{where} axis: end point {e} of the target's segment is not an "
                                f"end vertex of the axis (beyond the combined uncertainty)")
        if group == "linear" and axis is None:
            raise ManifestError(f"{where}: a linear object must give its surveyed axis polyline")
        objects.append(SurveyObject(target_id=tid, class_group=group, axis=axis))
    missing = sorted(set(targets) - {o.target_id for o in objects})
    if missing:
        raise ManifestError(f"targets without a survey object entry: {missing}")
    if len({o.target_id for o in objects}) != len(objects):
        raise ManifestError("a target has more than one survey object entry")

    controls = []
    for i, c in enumerate(doc.get("control_points") or []):
        where = f"control point {c.get('point_id', i)}"
        _check_keys(c, _CONTROL_KEYS, where)
        frame = _planar_frame(manifest, c.get("frame_id"), where)
        if not c.get("point_id") or not c.get("method") or not c.get("source"):
            raise ManifestError(f"{where}: point_id, method and source are required")
        (xy,) = _coords([c.get("coordinates") or []], where)
        unc = c.get("uncertainty")
        if unc is not None and (not math.isfinite(unc) or unc < 0):
            raise ManifestError(f"{where}: uncertainty must be non-negative")
        controls.append(ControlPoint(point_id=c["point_id"], frame_id=frame.frame_id,
                                     coordinates=xy, uncertainty=unc, method=c["method"],
                                     source=c["source"]))
    if len({c.point_id for c in controls}) != len(controls):
        raise ManifestError("control point ids must be unique")

    areas = []
    used_ids = set(targets) | {e.location_id for e in manifest.attested_empty_locations}
    for i, a in enumerate(doc.get("verified_empty_areas") or []):
        where = f"verified-empty area {a.get('area_id', i)}"
        _check_keys(a, _AREA_KEYS, where)
        aid = a.get("area_id")
        if not aid or aid in used_ids:
            raise ManifestError(f"{where}: area_id is required and must be unique")
        used_ids.add(aid)
        frame = _planar_frame(manifest, a.get("frame_id"), where)
        poly = _coords(a.get("polygon") or [], where)
        if len(poly) < 3 or polygon_area(list(poly)) <= 0 or not _is_simple(list(poly)):
            raise ManifestError(f"{where}: the polygon must be simple, with >= 3 vertices "
                                f"and a positive area")
        if a.get("excavation_depth") is None or a.get("evidence") is None:
            raise ManifestError(f"{where}: excavation_depth and evidence are required")
        _check_keys(a["excavation_depth"], _DEPTH_KEYS, f"{where} excavation_depth")
        depth = _build(PhysicalDepth, a["excavation_depth"], f"{where} excavation_depth")
        if depth.reference_surface not in surfaces:
            raise ManifestError(f"{where}: excavation_depth reference_surface "
                                f"{depth.reference_surface!r} is not declared")
        _check_keys(a["evidence"], _EVIDENCE_KEYS, f"{where} evidence")
        ev = _build(TargetEvidence, a["evidence"], f"{where} evidence")
        if not ev.independent_of_gpr or ev.basis not in _EMPTINESS_BASES:
            raise ManifestError(
                f"{where}: emptiness must be established by excavation or recorded placement, "
                f"independently of the radar; basis {ev.basis.value!r} cannot establish it")
        for t in targets.values():
            for verts in _target_geometry(t, frame.frame_id):
                if polyline_touches_polygon(verts, list(poly)):
                    raise ManifestError(
                        f"{where}: target {t.target_id} lies in or crosses the area; an area "
                        f"cannot be both empty and occupied")
        for o in objects:
            if o.axis and o.axis.frame_id == frame.frame_id and \
                    polyline_touches_polygon(list(o.axis.vertices), list(poly)):
                raise ManifestError(f"{where}: the axis of {o.target_id} crosses the area")
        areas.append(VerifiedEmptyArea(area_id=aid, frame_id=frame.frame_id, polygon=poly,
                                       excavation_depth=depth, evidence=ev,
                                       notes=a.get("notes", "")))

    c = doc.get("custody") or {}
    _check_keys(c, _CUSTODY_KEYS, "custody")
    if not all(str(c.get(k) or "").strip() for k in _CUSTODY_KEYS):
        raise ManifestError("custody needs sealed_utc, sealed_by and a statement that the truth "
                            "was recorded before any radar file was processed")
    return SurveyTruth(survey_id=doc["survey_id"], site_id=doc["site_id"], manifest=manifest,
                       objects=tuple(objects), control_points=tuple(controls),
                       verified_empty_areas=tuple(areas), custody=Custody(**c),
                       digest=truth_digest(doc))


def load_survey_truth(path, sealed_digest: Optional[str] = None) -> SurveyTruth:
    return load_survey_truth_dict(json.loads(Path(path).read_text()), sealed_digest)


# ---------------------------------------------------------------------------
# eligibility (valid is not eligible)
# ---------------------------------------------------------------------------

def _to_m(value, units) -> Optional[float]:
    return None if value is None else value * UNIT_TO_M[units]


def eligibility(truth: SurveyTruth, req: Requirements = BRIEF_REQUIREMENTS) -> dict:
    """
    Per object and per area: scoring-eligible or not, with every reason. Also
    the totals the validation protocol's sample-size rules are applied to.
    """
    m = truth.manifest
    objects = {}
    for o in truth.objects:
        t = next(x for x in m.targets if x.target_id == o.target_id)
        reasons = []
        if not t.evidence.is_independent_physical_truth:
            reasons.append(f"evidence grade {t.evidence.grade.value}"
                           f"{'' if t.evidence.independent_of_gpr else ', not independent of GPR'}"
                           f": only independent grade A/B truth is scored")
        planar = [loc for loc in t.locations
                  if m.frame(loc.frame_id).kind in (FrameKind.LOCAL_CARTESIAN, FrameKind.PROJECTED)]
        if not planar:
            reasons.append("no location in a planar frame")
        for loc in planar:
            units = m.frame(loc.frame_id).units
            u = _to_m(loc.uncertainty, units)
            if u is None:
                reasons.append(f"position uncertainty in {loc.frame_id} is not stated")
            elif u > req.max_position_uncertainty_m:
                reasons.append(f"position uncertainty {u:.3f} m exceeds "
                               f"{req.max_position_uncertainty_m} m")
        if o.axis is not None:
            units = m.frame(o.axis.frame_id).units
            spacing = _to_m(o.axis.max_spacing(), units)
            if spacing > req.max_vertex_spacing_m:
                reasons.append(f"axis vertex spacing {spacing:.2f} m exceeds "
                               f"{req.max_vertex_spacing_m} m")
            vu = _to_m(o.axis.vertex_uncertainty, units)
            if vu is None:
                reasons.append("axis vertex uncertainty is not stated")
            elif vu > req.max_position_uncertainty_m:
                reasons.append(f"axis vertex uncertainty {vu:.3f} m exceeds "
                               f"{req.max_position_uncertainty_m} m")
        depth_ok = any(d.measured_to is not MeasuredTo.UNRESOLVED for d in t.depths)
        objects[o.target_id] = {"class_group": o.class_group, "eligible": not reasons,
                                "reasons": reasons, "depth_scorable": depth_ok and not reasons,
                                "grade": t.evidence.grade.value}

    areas = {}
    for a in truth.verified_empty_areas:
        units = m.frame(a.frame_id).units
        reasons = []
        if a.evidence.grade not in (EvidenceGrade.A_INDEPENDENTLY_VERIFIED,
                                    EvidenceGrade.B_MEASUREMENT_ASSOCIATED):
            reasons.append(f"evidence grade {a.evidence.grade.value}")
        dep = _to_m(a.excavation_depth.value, a.excavation_depth.units)
        if dep < req.min_empty_excavation_depth_m:
            reasons.append(f"excavated to {dep:.2f} m, less than "
                           f"{req.min_empty_excavation_depth_m} m")
        areas[a.area_id] = {"area_m2": a.area() * UNIT_TO_M[units] ** 2, "eligible": not reasons,
                            "reasons": reasons}

    good_controls = [c for c in truth.control_points
                     if (u := _to_m(c.uncertainty, m.frame(c.frame_id).units)) is not None
                     and u <= req.max_control_uncertainty_m]
    control_reasons = ([] if len(good_controls) >= req.min_control_points else
                       [f"{len(good_controls)} control point(s) within "
                        f"{req.max_control_uncertainty_m} m; {req.min_control_points} required"])
    totals = {g: sum(1 for v in objects.values() if v["class_group"] == g and v["eligible"])
              for g in CLASS_GROUPS}
    return {
        "survey_id": truth.survey_id, "site_id": truth.site_id, "digest": truth.digest,
        "requirements": req.as_dict(),
        "control": {"ok": not control_reasons, "reasons": control_reasons,
                    "n_within_tolerance": len(good_controls)},
        "objects": objects, "verified_empty_areas": areas,
        "eligible_objects": totals,
        "eligible_empty_area_m2": sum(v["area_m2"] for v in areas.values() if v["eligible"]),
        "ineligible": sorted([k for k, v in objects.items() if not v["eligible"]]
                             + [k for k, v in areas.items() if not v["eligible"]]),
    }
