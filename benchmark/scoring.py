"""
Detection and false-alarm scoring for the BAM benchmark.

Two questions only:

  1. On a specimen with targets, does the detector find them, and what does it
     find that is not a target?
  2. On the attested-empty control specimen, how much does it fire anyway?

Localisation is not scored, and `benchmark.gates` raises if anything asks.

THE MATCHING RULE, stated rather than assumed. A detection matches a target
when its PEAK trace node falls inside that target's footprint -- the grid nodes
within one published outer radius of the published target X. No extra
tolerance is added. The peak is used rather than "any overlapping node"
because a component can straddle a footprint edge, and crediting a target for a
detection whose evidence is mostly elsewhere would inflate recall. Both counts
are reported (`matched_by_peak`, `overlapping_any_node`) so the choice is
visible instead of buried.

UNITS. Everything here is counted in grid nodes and lines. Nothing is reported
per physical area, because the archives declare no unit for X/Y -- see
`benchmark.gates` open question `coordinate-units`.
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


def score_localization(*_args, **_kwargs):
    """Refuses. Present so the refusal is discoverable where scoring lives."""
    from benchmark.gates import require_localization_evidence
    require_localization_evidence("localisation scoring")
