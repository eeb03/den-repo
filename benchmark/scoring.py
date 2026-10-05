"""
Detection and false-alarm scoring for the BAM benchmark.

Two questions only:

  1. On a specimen with targets, does the detector find them, and what does it
     find that is not a target?
  2. On the attested-empty control specimen, how much does it fire anyway?

Localisation and depth became SCOREABLE on 2026-10-05 (`benchmark.gates`):
the appendix construction drawings supply a declared millimetre frame and
independent object coordinates. Scoreable is not validated -- measured
capability lives in `benchmark.gates.CAPABILITY_STATUS` and is never changed
by scoring. See `score_localization` and `score_depth` at the end of this file.

THE MATCHING RULE, stated rather than assumed. A detection matches a target
when its PEAK trace node falls inside that target's footprint -- the grid nodes
within one published outer radius of the published target X. No extra
tolerance is added. The peak is used rather than "any overlapping node"
because a component can straddle a footprint edge, and crediting a target for a
detection whose evidence is mostly elsewhere would inflate recall. Both counts
are reported (`matched_by_peak`, `overlapping_any_node`) so the choice is
visible instead of buried.

UNITS. Detection and false-alarm counts are in grid nodes and lines (unchanged).
Localisation and depth errors are in millimetres, the unit the drawings declare
(`benchmark.gates` open question `coordinate-units`, now RESOLVED).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from benchmark.association import target_for_trace
from benchmark.bam_truth import BenchmarkTarget, ControlRegion
from benchmark.gates import SCOPE_STATEMENT

MATCH_RULE = (
    "a detection matches a target when its peak trace node lies within the "
    "target's footprint (grid nodes within one published outer radius of the "
    "published target X); no additional tolerance"
)

#: A target counts as detected on a line if at least one detection on that line
#: matches it. Stated explicitly because "detected" is otherwise ambiguous
#: between per-line and per-scan.
DETECTION_UNIT = "target x line"


@dataclass(frozen=True)
class DetectionScore:
    scan_id: str
    specimen_id: str
    lines_processed: int
    n_targets: int
    true_positives: int
    false_negatives: int
    false_positives: int
    recall: Optional[float]
    precision: Optional[float]
    f1: Optional[float]
    per_target: dict = field(default_factory=dict)
    overlapping_any_node: int = 0
    match_rule: str = MATCH_RULE
    detection_unit: str = DETECTION_UNIT
    threshold: float = 0.0
    min_cells: int = 0
    scope: str = SCOPE_STATEMENT
    localization_scored: bool = False

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "scan_id", "specimen_id", "lines_processed", "n_targets",
            "true_positives", "false_negatives", "false_positives",
            "recall", "precision", "f1", "per_target", "overlapping_any_node",
            "match_rule", "detection_unit", "threshold", "min_cells",
            "scope", "localization_scored")}


@dataclass(frozen=True)
class FalseAlarmScore:
    """
    Firing on ground attested to hold no embedded elements.

    `sufficient_for_a_rate` is the honest part. A rate implies a population
    large enough to estimate one; when it is not, the measurable counts are
    reported and the limitation is stated rather than dressed up.
    """
    scan_id: str
    specimen_id: str
    lines_processed: int
    n_detections: int
    detections_per_line: Optional[float]
    false_alarm_rate: Optional[float]
    rate_basis: str
    sufficient_for_a_rate: bool
    limitation: str
    control_attested: bool
    control_caveat: str
    per_area_rate: None = None
    per_area_note: str = (
        "not computed: the archives declare no physical unit for X/Y, so an "
        "area cannot be stated without assuming one"
    )
    threshold: float = 0.0
    min_cells: int = 0
    scope: str = SCOPE_STATEMENT

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "scan_id", "specimen_id", "lines_processed", "n_detections",
            "detections_per_line", "false_alarm_rate", "rate_basis",
            "sufficient_for_a_rate", "limitation", "control_attested",
            "control_caveat", "per_area_rate", "per_area_note",
            "threshold", "min_cells", "scope")}


#: Below this many lines, a "rate" would be a number without a population.
MIN_LINES_FOR_A_RATE = 10


def score_detection(run, targets: list[BenchmarkTarget]) -> DetectionScore:
    """
    True/false positives and negatives for one scan against its targets.

    Counted per (target, line): with four targets over 161 lines there are 644
    opportunities to detect, and a target missed on one line but found on
    another is neither a clean hit nor a clean miss at scan level. Per-line
    counting says exactly how consistent the detector is.
    """
    lines = sorted({d.line_index for d in run.detections}) or []
    n_lines = run.lines_processed

    hits: dict[str, set] = {t.target_id: set() for t in targets}
    tp = fp = 0
    overlapping = 0

    for d in run.detections:
        matched = target_for_trace(targets, d.peak_trace)
        if any(n in t.footprint for t in targets for n in d.trace_indices):
            overlapping += 1
        if matched is not None:
            tp += 1
            hits[matched.target_id].add(d.line_index)
        else:
            fp += 1

    # A false negative is a (target, line) pair with no matching detection.
    fn = sum(n_lines - len(seen) for seen in hits.values()) if n_lines else 0

    opportunities = len(targets) * n_lines
    recall = (sum(len(s) for s in hits.values()) / opportunities) if opportunities else None
    precision = (tp / (tp + fp)) if (tp + fp) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and (precision + recall) else None)

    return DetectionScore(
        scan_id=run.scan_id,
        specimen_id=run.specimen_id,
        lines_processed=n_lines,
        n_targets=len(targets),
        true_positives=tp,
        false_negatives=fn,
        false_positives=fp,
        recall=recall,
        precision=precision,
        f1=f1,
        per_target={t.target_id: {
            "lines_with_a_match": len(hits[t.target_id]),
            "lines_processed": n_lines,
            "grid_index": t.x_node,
            "footprint": [t.footprint.first_node, t.footprint.last_node],
            "target_type": t.target_type,
            "position_provenance": t.provenance,
        } for t in targets},
        overlapping_any_node=overlapping,
        threshold=run.threshold,
        min_cells=run.min_cells,
    )


def score_false_alarms(run, control: ControlRegion) -> FalseAlarmScore:
    """
    Detector output on the attested-empty specimen.

    Every detection here is a false alarm with respect to EMBEDDED OBJECTS,
    which is the only thing the specimen is attested empty of. Its step back
    walls are genuine reflectors, so this is not a "no reflector" control and
    the caveat travels with the number.
    """
    if run.specimen_id != control.specimen_id:
        raise ValueError(
            f"false-alarm scoring needs the control specimen; got run on "
            f"{run.specimen_id!r}, control is {control.specimen_id!r}"
        )

    n = len(run.detections)
    lines = run.lines_processed
    enough = lines >= MIN_LINES_FOR_A_RATE and control.attested

    return FalseAlarmScore(
        scan_id=run.scan_id,
        specimen_id=run.specimen_id,
        lines_processed=lines,
        n_detections=n,
        detections_per_line=(n / lines) if lines else None,
        false_alarm_rate=(n / lines) if enough else None,
        rate_basis="detections per line on attested-empty ground" if enough else "not computed",
        sufficient_for_a_rate=enough,
        limitation=(
            "" if enough else
            f"fewer than {MIN_LINES_FOR_A_RATE} lines scored, or the control is "
            f"not attested empty; the raw detection count is reported instead of "
            f"a rate"
        ),
        control_attested=control.attested,
        control_caveat=control.caveat,
        threshold=run.threshold,
        min_cells=run.min_cells,
    )


# --------------------------------------------------------------------------
# localisation and depth: SCOREABLE against the drawings, never "validated" here
# --------------------------------------------------------------------------

#: Pre-registered in scripts/bam_quantitative_validation.py before any result was
#: computed, and reproduced here unchanged. A hit needs BOTH conditions: an
#: X-only coincidence at the wrong depth is a false positive, not a detection.
LOCALIZATION_RADIUS_MM = 100.0
LOCALIZATION_DEPTH_TOLERANCE_MM = 60.0
LOCALIZATION_RULE = (
    "pre-registered L-XZ: per scan line crossing a target, take the highest-|z| detection "
    f"whose peak X is within {LOCALIZATION_RADIUS_MM:g} mm of the drawn target X; it is a "
    "hit only if its depth (under a provenance-labelled calibration) is within "
    f"{LOCALIZATION_DEPTH_TOLERANCE_MM:g} mm of the drawn target top. Other detections in "
    "the X window that are also within the depth tolerance are duplicates; every other "
    "detection -- including X-window detections at the wrong depth -- is a false positive")


@dataclass(frozen=True)
class DepthCalibration:
    """Time zero and velocity for converting two-way time to depth, with provenance."""
    t0_ns: float
    v_m_per_ns: float
    provenance: str
    source: str

    def __post_init__(self):
        from benchmark.gates import DEPTH_PROVENANCES
        if self.provenance not in DEPTH_PROVENANCES:
            raise ValueError(f"depth provenance {self.provenance!r}; one of {DEPTH_PROVENANCES}")
        if not self.source.strip():
            raise ValueError("a depth calibration must name its source")
        if not self.v_m_per_ns > 0:
            raise ValueError("velocity must be positive")

    def depth_mm(self, t_ns: float) -> float:
        return (t_ns - self.t0_ns) * self.v_m_per_ns / 2.0 * 1000.0


@dataclass(frozen=True)
class ScoringTarget:
    """A target in the drawing frame, mm. `y_mm` None = spans every scan line."""
    target_id: str
    x_mm: float
    z_top_mm: float
    y_mm: Optional[float] = None
    y_half_extent_mm: Optional[float] = None


def bam_scoring_targets(specimen_id: str) -> list[ScoringTarget]:
    """
    Targets from the declared BAM manifest. z_top = drawn centre depth minus the
    half-height that faces the antenna (duct: outer radius; cuboid: half its Z size).
    """
    from benchmark.targets import MANIFEST_DIR, MeasuredTo, load_manifest
    m = load_manifest(MANIFEST_DIR / f"bam-{specimen_id.lower()}.targets.json")
    out = []
    for t in m.targets:
        centre = next(d for d in t.depths if d.measured_to is MeasuredTo.CENTRE)
        dims = t.dimensions
        half = (dims.outer_diameter / 2.0) if dims.outer_diameter else dims.height / 2.0
        loc = t.locations[0]
        if loc.geometry == "segment":            # a duct along Y: crosses every line
            out.append(ScoringTarget(t.target_id, loc.start[0], centre.value - half))
        else:
            out.append(ScoringTarget(t.target_id, loc.coordinates[0], centre.value - half,
                                     y_mm=loc.coordinates[1], y_half_extent_mm=dims.width / 2.0))
    return out


def _err_stats(errs):
    import numpy as np
    a = np.asarray(errs, float)
    if a.size == 0:
        return None
    ab = np.abs(a)
    return {"n": int(a.size), "mean_signed": float(a.mean()), "mean_abs": float(ab.mean()),
            "median_abs": float(np.median(ab)), "rmse": float(np.sqrt((a ** 2).mean())),
            "p95_abs": float(np.percentile(ab, 95))}


def score_localization(run, grid, targets: list[ScoringTarget],
                       calibration: DepthCalibration) -> dict:
    """
    Localisation against the drawing geometry under the pre-registered rule.

    Requires a depth calibration: there is deliberately no X-only mode. Returns
    errors in mm, recall/precision of the X-and-depth rule, duplicates and false
    positives. It reports a measurement; it never sets a capability status.
    """
    from benchmark.gates import CAPABILITY_STATUS, REFERENCE_FRAME_SOURCE, require_localization_evidence
    require_localization_evidence("localisation scoring")
    if calibration is None:
        raise ValueError("localisation scoring needs a DepthCalibration; X-only matching is refused")

    dets = [{"line": d.line_index, "y": float(grid.y[d.line_index]), "x": float(grid.x[d.peak_trace]),
             "depth": calibration.depth_mm(float(grid.z[d.peak_sample])), "z": abs(d.peak_z),
             "id": d.detection_id} for d in run.detections]
    by_line: dict[int, list] = {}
    for d in dets:
        by_line.setdefault(d["line"], []).append(d)
    lines_all = sorted({int(i) for i in range(len(grid.y))}) if run.lines_processed == len(grid.y) \
        else sorted(by_line)
    used, dx, dz, dup, per_target, opportunities, hits = set(), [], [], 0, {}, 0, 0
    for t in targets:
        lines = [j for j in lines_all if t.y_mm is None
                 or abs(float(grid.y[j]) - t.y_mm) <= t.y_half_extent_mm]
        matched = 0
        for j in lines:
            window = [d for d in by_line.get(j, []) if abs(d["x"] - t.x_mm) <= LOCALIZATION_RADIUS_MM]
            if not window:
                continue
            best = max(window, key=lambda d: d["z"])
            if abs(best["depth"] - t.z_top_mm) > LOCALIZATION_DEPTH_TOLERANCE_MM:
                continue                          # X coincidence at the wrong depth: not a hit
            in_depth = [d for d in window if abs(d["depth"] - t.z_top_mm) <= LOCALIZATION_DEPTH_TOLERANCE_MM]
            used.update(d["id"] for d in in_depth)
            dup += len(in_depth) - 1
            dx.append(best["x"] - t.x_mm)
            dz.append(best["depth"] - t.z_top_mm)
            matched += 1
        opportunities += len(lines)
        hits += matched
        per_target[t.target_id] = {"lines": len(lines), "lines_matched": matched}
    fps = [d for d in dets if d["id"] not in used]
    n_lines = len(lines_all) or 1
    return {
        "rule": LOCALIZATION_RULE,
        "reference_frame": REFERENCE_FRAME_SOURCE,
        "depth_provenance": calibration.provenance,
        "depth_calibration_source": calibration.source,
        "opportunities": opportunities,
        "recall": (hits / opportunities) if opportunities else None,
        "precision": (hits / (hits + len(fps))) if (hits + len(fps)) else None,
        "false_positives": len(fps),
        "false_positives_per_line": len(fps) / n_lines,
        "duplicates": dup,
        "longitudinal_error_mm": _err_stats(dx),
        "depth_error_mm": _err_stats(dz),
        "per_target": per_target,
        "scoreable_not_validated": (
            "this is a measurement; capability status is benchmark.gates.CAPABILITY_STATUS "
            f"(current_detector_localisation = {CAPABILITY_STATUS['current_detector_localisation']})"),
    }


def score_depth(measurements: list[tuple[str, float, float]], calibration: DepthCalibration,
                position_source: str) -> dict:
    """
    Depth error for (target_id, measured_depth_mm, true_depth_mm) measured under ONE
    calibration provenance. Scores of different provenance are never combined:
    call once per provenance. `position_source` must say how the position at which
    depth was measured was obtained (e.g. 'independently known from drawing' vs
    'detector output'), so a known-position depth can never read as a detection result.
    """
    from benchmark.gates import require_localization_evidence
    require_localization_evidence("depth scoring")
    if not position_source.strip():
        raise ValueError("position_source is required")
    errs = [m - t for _, m, t in measurements]
    return {"depth_provenance": calibration.provenance,
            "depth_calibration_source": calibration.source,
            "position_source": position_source,
            "per_target": {tid: m - t for tid, m, t in measurements},
            "error_mm": _err_stats(errs)}
