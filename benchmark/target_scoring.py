"""
Scoring a prediction artifact against target truth -- the only module that
sees both.

    score(artifact, manifest, rule) -> dict

FAIL CLOSED. Every metric passes a gate first. Matching itself needs the
predictions and the truth in the SAME declared frame, with the radar
registered to it; there is no coordinate transform here, and a mismatch is a
refusal, not a best effort. Metrics beyond matching (false positives,
per-metre rates, localisation error, depth error) each need more, and each is
reported as `null` with its reasons when that is absent. No default velocity,
time-zero or origin is ever supplied to unlock a number.

MATCHING (deterministic, one-to-one). On each survey line, a prediction and a
target are a candidate pair when the prediction's position lies within the
target's match radius of the target's geometry (a point or a linear axis).
Pairs are taken in order of (distance, prediction_id, target_id) and accepted
when neither side is already matched. So:
  * one prediction never counts for two targets -- it goes to the nearest,
    ties broken by target_id;
  * one target is never counted twice on a line -- the nearest prediction
    wins, ties broken by prediction_id; the others are reported as
    `duplicate_detections` and counted as false positives, since they are not
    the detection of anything new;
  * manifest and artifact ORDER cannot change the result, because every tie
    is broken by identifier.

THE UNIT OF OPPORTUNITY is (target, line): a target counts on a line when
the line passes within the target's match radius of its geometry. A linear
object crossed by many lines is many opportunities, as in the legacy BAM
scorer (`benchmark.scoring.DETECTION_UNIT`).
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Optional

from benchmark.predictions import AcquisitionLine, PredictionArtifact
from benchmark.targets import (
    Capability, FrameKind, GroundTruthTarget, MeasuredTo, PointLocation, SegmentLocation,
    TargetManifest,
)


class ScoringBlocked(RuntimeError):
    """The requested scoring is not supported by the declared evidence."""


@dataclass(frozen=True)
class MatchRule:
    """
    How close is close enough, stated rather than assumed.

    `radius_kind`:
      * "fixed": `radius` in the frame's units for every target;
      * "half_dimension": half of the target's `dimension` (e.g. the outer
        diameter), for which the target must carry that dimension.
    `extra_tolerance` is added on top; 0 unless deliberately chosen.
    """
    name: str
    radius_kind: str
    radius: Optional[float] = None
    dimension: Optional[str] = None
    extra_tolerance: float = 0.0
    position: str = "the prediction's peak position"
    #: Radius around an attested-empty location within which an unmatched
    #: prediction counts as a control response. Declared, never defaulted:
    #: without it the control analysis is reported as unavailable.
    control_radius: Optional[float] = None

    def radius_for(self, target: GroundTruthTarget) -> float:
        if self.radius_kind == "fixed":
            if self.radius is None or self.radius < 0:
                raise ScoringBlocked(f"match rule {self.name}: a fixed radius is required")
            return self.radius + self.extra_tolerance
        if self.radius_kind == "half_dimension":
            value = getattr(target.dimensions, self.dimension, None) if target.dimensions else None
            if value is None:
                raise ScoringBlocked(
                    f"match rule {self.name} needs target {target.target_id}'s "
                    f"{self.dimension}, which is not known")
            return value / 2.0 + self.extra_tolerance
        raise ScoringBlocked(f"match rule {self.name}: unknown radius_kind {self.radius_kind!r}")

    def describe(self) -> str:
        base = (f"fixed radius {self.radius}" if self.radius_kind == "fixed"
                else f"half the target's {self.dimension}")
        return (f"{self.name}: a prediction ({self.position}) matches a target when it lies "
                f"within {base}{' + ' + str(self.extra_tolerance) if self.extra_tolerance else ''}"
                f" of the target's geometry, in frame units; one-to-one, nearest first, ties "
                f"broken by prediction_id then target_id")


#: The legacy BAM footprint rule, expressed generically: within one published
#: outer radius of the target axis, no added tolerance.
BAM_FOOTPRINT_RULE = MatchRule(name="bam-footprint", radius_kind="half_dimension",
                               dimension="outer_diameter")


def _line_distance(line: AcquisitionLine, loc) -> float:
    """Shortest distance between a survey line segment and a target geometry."""
    seg = SegmentLocation(frame_id="", start=line.start, end=line.end)
    if isinstance(loc, PointLocation):
        return seg.distance_to(loc.coordinates)
    ends = [seg.distance_to(loc.start), seg.distance_to(loc.end),
            loc.distance_to(line.start), loc.distance_to(line.end)]
    if len(line.start) == 2 and _segments_intersect(line.start, line.end, loc.start, loc.end):
        return 0.0
    return min(ends)


def _segments_intersect(p1, p2, q1, q2) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 * d2 <= 0) and (d3 * d4 <= 0)


def _check_frame(artifact: PredictionArtifact, manifest: TargetManifest):
    if not isinstance(artifact, PredictionArtifact):
        raise ScoringBlocked("predictions must be a PredictionArtifact")
    if not isinstance(manifest, TargetManifest):
        raise ScoringBlocked("truth must be a TargetManifest")
    if artifact.dataset_id != manifest.dataset_id:
        raise ScoringBlocked(
            f"artifact dataset {artifact.dataset_id!r} is not manifest dataset "
            f"{manifest.dataset_id!r}")
    try:
        frame = manifest.frame(artifact.frame_id)
    except Exception:
        raise ScoringBlocked(
            f"predictions are in frame {artifact.frame_id!r}, which the truth does not "
            f"declare; Subterra applies no transform between frames") from None
    if frame.kind in (FrameKind.PROJECTED, FrameKind.GEOGRAPHIC) and artifact.frame_crs != frame.crs:
        raise ScoringBlocked(
            f"CRS mismatch: predictions in {artifact.frame_crs!r}, truth in {frame.crs!r}; "
            f"no declared transform is applied")
    if artifact.frame_units != frame.units:
        raise ScoringBlocked(
            f"units mismatch: predictions in {artifact.frame_units!r}, truth frame "
            f"{frame.frame_id} in {frame.units!r}")
    if frame.kind == FrameKind.SURVEY_LINE:
        other = sorted({ln.line_id for ln in artifact.lines} - {frame.line_id})
        if other:
            raise ScoringBlocked(
                f"survey_line frame {frame.frame_id} is line {frame.line_id!r}; the artifact "
                f"carries other line(s) {other}, whose chainage origins are not this one")
    ok, reasons = manifest.capability(Capability.DETECTION_MATCHING, frame.frame_id)
    if not ok:
        raise ScoringBlocked("detection matching is not supported: " + "; ".join(reasons))
    return frame


def _depth_gate(artifact: PredictionArtifact, manifest: TargetManifest, frame_id: str):
    ok, reasons = manifest.capability(Capability.DEPTH_SCORING, frame_id)
    t = artifact.timing
    if t.time_zero_status not in ("declared", "measured"):
        reasons.append(f"radar time-zero is {t.time_zero_status!r}, not declared or measured")
    if t.velocity_source not in ("declared", "measured") or t.velocity_m_per_ns is None:
        reasons.append(f"propagation velocity is {t.velocity_source!r}, not declared or measured")
    # A "declared" label is not enough: the basis says what the number rests
    # on. The platform default is an assumption, and a velocity fitted to the
    # same radar data is not independent of the depths it would be judged on.
    if t.velocity_basis in ("assumed_default", "estimated_from_same_survey"):
        reasons.append(f"propagation velocity basis is {t.velocity_basis!r}; depth scoring "
                       f"needs a velocity independent of this survey's own reflections")
    if not t.depth_reference_surface:
        reasons.append("no declared relationship between the radar depth axis and a physical "
                       "reference surface")
    elif t.depth_reference_surface not in {s.surface_id for s in manifest.depth_reference_surfaces}:
        reasons.append(f"radar depth reference {t.depth_reference_surface!r} is not a surface "
                       f"the truth declares")
    return (not reasons, reasons)


def _ratio(a, b):
    return (a / b) if b else None


def _breakdown(targets, per_target, key, label):
    """Recall per group, only when every target carries the key."""
    values = {t.target_id: key(t) for t in targets}
    missing = sorted(tid for tid, v in values.items() if v in (None, ""))
    if missing:
        return {"available": False,
                "reason": f"{label} is unknown for target(s) {missing}; no subgroup statistic"}
    groups: dict = {}
    for t in targets:
        g = groups.setdefault(str(values[t.target_id]), {"opportunities": 0, "matched": 0,
                                                          "targets": []})
        g["opportunities"] += per_target[t.target_id]["opportunities"]
        g["matched"] += per_target[t.target_id]["matched"]
        g["targets"].append(t.target_id)
    for g in groups.values():
        g["recall"] = _ratio(g["matched"], g["opportunities"])
    def order(item):
        try:
            return (0, float(item[0]), item[0])
        except ValueError:
            return (1, 0.0, item[0])
    return {"available": True, "groups": dict(sorted(groups.items(), key=order))}


def _depth_key(frame_targets):
    """A physical depth group key, only when every target's depth shares one
    reference surface and one resolved point of the object."""
    def resolved(t):
        return [d for d in t.depths if d.measured_to is not MeasuredTo.UNRESOLVED]
    kinds = {(d.reference_surface, d.measured_to.value, d.units)
             for t in frame_targets for d in resolved(t)}
    if len(kinds) != 1:
        return lambda t: None, "targets do not share one resolved depth convention"
    (surface, point, units), = kinds
    label = f"physical depth to {point} below {surface} ({units})"
    return (lambda t: next((d.value for d in resolved(t)), None)), label


def score(artifact: PredictionArtifact, manifest: TargetManifest,
          rule: MatchRule) -> dict:
    frame = _check_frame(artifact, manifest)
    targets = sorted((t for t in manifest.targets if t.location_in(frame.frame_id)),
                     key=lambda t: t.target_id)
    not_in_frame = sorted(t.target_id for t in manifest.targets
                          if not t.location_in(frame.frame_id))
    radius = {t.target_id: rule.radius_for(t) for t in targets}
    lines = sorted(artifact.lines, key=lambda ln: ln.line_id)

    # --- opportunities: (target, line) where the line passes the target ---
    opportunities = {}
    for ln in lines:
        opportunities[ln.line_id] = [
            t for t in targets
            if frame.kind == FrameKind.SURVEY_LINE
            or _line_distance(ln, t.location_in(frame.frame_id)) <= radius[t.target_id]]

    # --- one-to-one matching per line ---
    by_line: dict[str, list] = {}
    for p in artifact.predictions:
        by_line.setdefault(p.line_id, []).append(p)
    matches, duplicates = [], []
    for ln in lines:
        cands = []
        for p in by_line.get(ln.line_id, []):
            for t in opportunities[ln.line_id]:
                d = t.location_in(frame.frame_id).distance_to(p.position)
                if d <= radius[t.target_id]:
                    cands.append((d, p.prediction_id, t.target_id, p, t))
        cands.sort(key=lambda c: c[:3])
        used_p, used_t = set(), set()
        for d, pid, tid, p, t in cands:
            if pid in used_p or tid in used_t:
                continue
            used_p.add(pid)
            used_t.add(tid)
            matches.append({"line_id": ln.line_id, "prediction_id": pid, "target_id": tid,
                            "distance": d, "prediction": p, "target": t})
        duplicates += [pid for _, pid, tid, _, _ in cands
                       if pid not in used_p and tid in used_t]
    duplicates = sorted(set(duplicates) - {m["prediction_id"] for m in matches})

    n_opp = sum(len(v) for v in opportunities.values())
    tp = len(matches)
    matched_ids = {m["prediction_id"] for m in matches}
    unmatched = [p for p in artifact.predictions if p.prediction_id not in matched_ids]
    recall = _ratio(tp, n_opp)

    per_target = {t.target_id: {"opportunities": sum(t in v for v in opportunities.values()),
                                "matched": sum(m["target_id"] == t.target_id for m in matches),
                                "match_radius": radius[t.target_id]} for t in targets}
    for tid, row in per_target.items():
        row["recall"] = _ratio(row["matched"], row["opportunities"])

    gates = {}
    fp_ok, fp_reasons = manifest.capability(Capability.FALSE_POSITIVES, frame.frame_id)
    gates["false_positives"] = {"available": fp_ok, "reasons": fp_reasons}
    fpm_ok, fpm_reasons = manifest.capability(Capability.FALSE_ALARMS_PER_METRE, frame.frame_id)
    gates["false_alarms_per_metre"] = {"available": fpm_ok, "reasons": fpm_reasons}
    loc_ok, loc_reasons = manifest.capability(Capability.LOCALIZATION_ERROR, frame.frame_id)
    gates["localization_error"] = {"available": loc_ok, "reasons": loc_reasons}
    depth_ok, depth_reasons = _depth_gate(artifact, manifest, frame.frame_id)
    gates["depth_scoring"] = {"available": depth_ok, "reasons": depth_reasons}

    fp = len(unmatched) if fp_ok else None
    precision = _ratio(tp, tp + fp) if fp is not None else None
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    total_length = sum(ln.length for ln in lines)
    metre = {"m": 1.0, "cm": 0.01, "mm": 0.001}[frame.units]
    controls = _controls(artifact, manifest, frame, lines, unmatched, rule)

    localization = None
    if loc_ok and matches:
        dist = [m["distance"] for m in matches]
        localization = {"units": frame.units, "mean_abs": statistics.fmean(dist),
                        "median_abs": statistics.median(dist), "max_abs": max(dist),
                        "note": "horizontal distance from the prediction to the target geometry",
                        "depth_checked": False,
                        "interpretation": (
                            "measurement on horizontally matched pairs only; a match here may sit "
                            "at the wrong depth. It is not the pre-registered depth-checked "
                            "localisation rule (benchmark.scoring.score_localization) and it is "
                            "not a capability claim: scoreable is not validated (see "
                            "benchmark.gates.CAPABILITY_STATUS)")}

    depth = None
    if depth_ok:
        errors = []
        for m in matches:
            truth = next((d for d in m["target"].depths
                          if d.reference_surface == artifact.timing.depth_reference_surface
                          and d.measured_to is MeasuredTo.TOP), None)
            if truth is not None and m["prediction"].radar_depth is not None:
                errors.append(m["prediction"].radar_depth - truth.value)
        depth = ({"n": len(errors), "mean_signed_error": statistics.fmean(errors),
                  "mean_abs_error": statistics.fmean(abs(e) for e in errors)}
                 if errors else {"n": 0, "note": "no matched pair carries both depths"})

    depth_key, depth_label = _depth_key(targets)
    depth_breakdown = (
        {**_breakdown(targets, per_target, depth_key, depth_label), "convention": depth_label}
        if targets and all(depth_key(t) is not None for t in targets)
        else {"available": False, "reason": depth_label if targets else "no targets"})
    breakdowns = {
        "object_class": _breakdown(targets, per_target, lambda t: t.object_class
                                   if t.object_class != "unknown" else None, "object class"),
        "material": _breakdown(targets, per_target, lambda t: t.material, "material"),
        "physical_depth": depth_breakdown,
    }

    return {
        "schema": "subterra.target_score.v1",
        "dataset_id": manifest.dataset_id,
        "acquisition_id": artifact.acquisition_id,
        "frame": {"frame_id": frame.frame_id, "kind": frame.kind.value, "units": frame.units,
                  "origin_status": frame.origin_status, "units_status": frame.units_status,
                  "registration_to_radar": frame.registration_to_radar},
        "evidence": manifest.evidence_summary(),
        "truth_source": manifest.truth_source,
        "notes": list(manifest.notes),
        "match_rule": rule.describe(),
        "antenna_frequency_mhz": artifact.antenna_frequency_mhz,
        "antenna_frequency_source": artifact.antenna_frequency_source,
        "detector": artifact.detector,
        "input_sha256": artifact.input_sha256,
        "code_version": artifact.code_version,
        "gates": gates,
        "counts": {
            "lines": len(lines), "predictions": len(artifact.predictions),
            "targets_in_frame": len(targets), "targets_not_in_frame": not_in_frame,
            "opportunities": n_opp, "true_positives": tp,
            "false_negatives": n_opp - tp,
            "false_positives": fp, "duplicate_detections": len(duplicates),
            "matched_detections_incl_duplicates": tp + len(duplicates),
            "false_positives_at_attested_empty": controls.get("predictions_at_controls"),
        },
        "metrics": {
            "recall": recall, "precision": precision, "f1": f1,
            "false_positives_per_line": _ratio(fp, len(lines)) if fp is not None else None,
            "false_alarms_per_metre": (fp / (total_length * metre)
                                       if fpm_ok and fp is not None and total_length else None),
            "localization_error": localization,
            "depth_error": depth,
        },
        "per_target": per_target,
        "controls": controls,
        "breakdowns": breakdowns,
        "matches": [{k: v for k, v in m.items() if k not in ("prediction", "target")}
                    for m in sorted(matches, key=lambda m: (m["line_id"], m["target_id"]))],
    }


def _controls(artifact, manifest, frame, lines, unmatched, rule) -> dict:
    """
    Responses at attested-empty locations: unmatched predictions within the
    rule's `control_radius` of a location the truth documents as holding no
    object. These are a subset of the false positives, never extra ones, and
    never false negatives. Reported even when precision itself is gated,
    because the emptiness of these specific locations IS attested.
    """
    empties = sorted((e for e in manifest.attested_empty_locations
                      if e.location_in(frame.frame_id)), key=lambda e: e.location_id)
    if rule.control_radius is None:
        return {"available": False, "locations_in_frame": len(empties),
                "reason": "the match rule declares no control_radius",
                "predictions_at_controls": None}
    r = rule.control_radius
    by_line: dict[str, list] = {}
    for p in unmatched:
        by_line.setdefault(p.line_id, []).append(p)
    responses, hit_preds, by_kind = [], set(), {}
    for e in empties:
        loc = e.location_in(frame.frame_id)
        on_lines = [ln for ln in lines if frame.kind == FrameKind.SURVEY_LINE
                    or _line_distance(ln, loc) <= r]
        preds = sorted(p.prediction_id for ln in on_lines for p in by_line.get(ln.line_id, [])
                       if loc.distance_to(p.position) <= r)
        k = by_kind.setdefault(e.kind.value, {"locations": 0, "with_a_response": 0})
        k["locations"] += 1
        if preds:
            k["with_a_response"] += 1
            hit_preds.update(preds)
            responses.append({"location_id": e.location_id, "kind": e.kind.value,
                              "prediction_ids": preds,
                              "lines_passing": len(on_lines)})
    return {"available": True, "control_radius": r, "locations_in_frame": len(empties),
            "locations_with_a_response": len(responses), "by_kind": by_kind,
            "responses": responses, "predictions_at_controls": len(hit_preds),
            "note": "a subset of the false positives, never counted twice and never a miss"}


def by_frequency(results: list[dict]) -> dict:
    """Detection vs antenna frequency across several scored artifacts. Only
    runs whose frequency is known are grouped; the rest are listed."""
    known = [r for r in results if r.get("antenna_frequency_mhz")]
    rows: dict = {}
    for r in known:
        row = rows.setdefault(str(r["antenna_frequency_mhz"]),
                              {"opportunities": 0, "true_positives": 0, "acquisitions": [],
                               "frequency_sources": set()})
        row["opportunities"] += r["counts"]["opportunities"]
        row["true_positives"] += r["counts"]["true_positives"]
        row["acquisitions"].append(r["acquisition_id"])
        row["frequency_sources"].add(r["antenna_frequency_source"])
    for row in rows.values():
        row["recall"] = _ratio(row["true_positives"], row["opportunities"])
        row["frequency_sources"] = sorted(row["frequency_sources"])
    return {"groups": dict(sorted(rows.items())),
            "unknown_frequency": [r["acquisition_id"] for r in results if r not in known]}
