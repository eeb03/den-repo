"""
Associating observations that may be the same subsurface thing.

THIS PROPOSES; IT DOES NOT CONCLUDE. Every function here returns
`AssociationRecord`s -- hypotheses carrying the measurements that motivated
them and the caller's criteria -- and never a `SubsurfaceObject`. Resolving
associations into objects is a separate, reversible step.

NO THRESHOLD HAS A DEFAULT. `max_trace_gap`, `max_distance_m` and the rest are
required arguments. They are choices about what counts as "the same thing",
not properties of the subsurface, and a default would present a choice as
science. Same contract as velocity and CRS elsewhere in the platform.

THE THREE SCALES, AND WHAT EACH NEEDS:

    adjacent trace     within ONE acquisition. Compares trace index and depth
                       overlap -- both of which every candidate carries, so
                       this works on any GPR line.
    adjacent profile   BETWEEN acquisitions in one survey. Compares real-world
                       distance, so it requires both candidates to be placeable
                       on Earth. A line with odometry-only positions cannot be
                       associated this way, and the function says so rather
                       than falling back to trace indices, which are not
                       comparable between acquisitions.
    cross survey       between surveys separated in time. Requires repeat
                       coverage of the same ground AND acquisition timestamps.
                       See `cross_survey_readiness`: no dataset currently held
                       provides both, so this path is implemented but has never
                       been validated against real repeat-survey data, and it
                       reports that rather than implying otherwise.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from fusion.sensor_fusion import haversine_m
from schemas.associations import (
    AssociationCriteria, AssociationEvidence, AssociationMethod, AssociationRecord,
)
from schemas.objects import ObservationKind, ObservationRef
from schemas.spatial import GeographicPosition, NoPosition
from utils.logger import get_logger

logger = get_logger(__name__)


def observation_from_candidate(candidate, dataset_id: str) -> ObservationRef:
    """
    An observation pointer for one anomaly candidate.

    Position comes from the candidate's own centroid when it has one, and is
    `NoPosition` with a reason when it does not -- which is the honest state
    for a line whose traces carry odometry only.
    """
    ch = candidate.characteristics
    if ch.centroid_lat is not None and ch.centroid_lon is not None:
        pos = GeographicPosition(lat=ch.centroid_lat, lon=ch.centroid_lon)
    else:
        pos = NoPosition(reason=(
            "the candidate's supporting traces carry no geographic position, so it "
            "has no centroid on Earth"))
    return ObservationRef(
        kind=ObservationKind.CANDIDATE, dataset_id=dataset_id,
        observation_id=candidate.id, frame_id=f"{dataset_id}:{candidate.evidence.source_file}",
        source_file=candidate.evidence.source_file,
        trace_index=int(sum(candidate.evidence.trace_range) / 2),
        position=pos)


def _depth_overlap(a, b) -> tuple[float, float]:
    """Overlap in metres, and as a fraction of the SHORTER candidate's extent."""
    a0, a1 = a.evidence.depth_range
    b0, b1 = b.evidence.depth_range
    lo, hi = max(a0, b0), min(a1, b1)
    overlap = max(0.0, hi - lo)
    shortest = min(a1 - a0, b1 - b0)
    return overlap, (overlap / shortest if shortest > 0 else 0.0)


def _trace_gap(a, b) -> int:
    """Index distance between two trace ranges; 0 when they overlap."""
    a0, a1 = a.evidence.trace_range
    b0, b1 = b.evidence.trace_range
    if a1 >= b0 and b1 >= a0:
        return 0
    return b0 - a1 if b0 > a1 else a0 - b1


def _record(dataset_id, method, oa, ob, criteria, evidence, satisfied, failed, notes=None):
    total = len(satisfied) + len(failed)
    return AssociationRecord(
        dataset_id=dataset_id, method=method, observation_a=oa, observation_b=ob,
        criteria=criteria, evidence=evidence,
        criteria_satisfied=satisfied, criteria_failed=failed,
        score=(len(satisfied) / total) if total else 0.0, notes=notes)


def associate_adjacent_traces(
    candidates: list, dataset_id: str, *,
    max_trace_gap: int, require_depth_overlap: bool,
    min_depth_overlap_fraction: Optional[float] = None,
    supplied_by: str,
) -> list[AssociationRecord]:
    """
    Associates candidates WITHIN each acquisition by trace proximity.

    Only pairs from the same `source_file` are considered: a trace index is
    unique within one acquisition, so comparing indices across files would be
    comparing unrelated numbering.

    Returns only records whose criteria were ALL satisfied. Near-misses are not
    returned, because a stored hypothesis nobody believes is noise -- lower the
    thresholds to see more.
    """
    criteria = AssociationCriteria(
        max_trace_gap=max_trace_gap, require_depth_overlap=require_depth_overlap,
        min_depth_overlap_fraction=min_depth_overlap_fraction,
        supplied_by=supplied_by)
    by_file: dict[str, list] = {}
    for c in candidates:
        by_file.setdefault(c.evidence.source_file, []).append(c)

    out: list[AssociationRecord] = []
    for source_file, group in by_file.items():
        group = sorted(group, key=lambda c: c.evidence.trace_range[0])
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                gap = _trace_gap(a, b)
                if gap > max_trace_gap:
                    break            # sorted by trace start: no later b is closer
                overlap_m, overlap_frac = _depth_overlap(a, b)
                satisfied, failed = [], []
                (satisfied if gap <= max_trace_gap else failed).append("max_trace_gap")
                if require_depth_overlap:
                    (satisfied if overlap_m > 0 else failed).append("require_depth_overlap")
                if min_depth_overlap_fraction is not None:
                    (satisfied if overlap_frac >= min_depth_overlap_fraction
                     else failed).append("min_depth_overlap_fraction")
                if failed:
                    continue
                out.append(_record(
                    dataset_id, AssociationMethod.ADJACENT_TRACE,
                    observation_from_candidate(a, dataset_id),
                    observation_from_candidate(b, dataset_id),
                    criteria,
                    AssociationEvidence(trace_gap=gap, depth_overlap_m=overlap_m,
                                        depth_overlap_fraction=overlap_frac),
                    satisfied, failed,
                    notes=(f"same acquisition ({source_file}); not independent "
                           f"evidence of one object")))
    logger.info(f"associate_adjacent_traces: {len(out)} association(s) from "
                f"{len(candidates)} candidate(s) across {len(by_file)} acquisition(s)")
    return out


def associate_adjacent_profiles(
    candidates: list, dataset_id: str, *, max_distance_m: float, supplied_by: str,
    require_depth_overlap: bool = False,
) -> tuple[list[AssociationRecord], dict]:
    """
    Associates candidates ACROSS acquisitions by real-world distance.

    Returns (records, coverage) where `coverage` reports how many candidates
    could not participate because they carry no position. That number is the
    point: on a corpus where most lines have no usable centroid, a small
    association count means "not comparable", not "nothing matched".
    """
    criteria = AssociationCriteria(max_distance_m=max_distance_m,
                                   require_depth_overlap=require_depth_overlap or None,
                                   supplied_by=supplied_by)
    placed, unplaced = [], []
    for c in candidates:
        ref = observation_from_candidate(c, dataset_id)
        (placed if ref.position.kind == "geographic" else unplaced).append((c, ref))

    out: list[AssociationRecord] = []
    for i, (a, ra) in enumerate(placed):
        for b, rb in placed[i + 1:]:
            if ra.acquisition_id == rb.acquisition_id:
                continue                     # that is adjacent_trace's job
            d = haversine_m(ra.position.lat, ra.position.lon,
                            rb.position.lat, rb.position.lon)
            satisfied, failed = [], []
            (satisfied if d <= max_distance_m else failed).append("max_distance_m")
            overlap_m, overlap_frac = _depth_overlap(a, b)
            if require_depth_overlap:
                (satisfied if overlap_m > 0 else failed).append("require_depth_overlap")
            if failed:
                continue
            out.append(_record(
                dataset_id, AssociationMethod.ADJACENT_PROFILE, ra, rb, criteria,
                AssociationEvidence(
                    distance_m=d,
                    distance_basis="haversine between candidate centroids (WGS84)",
                    depth_overlap_m=overlap_m, depth_overlap_fraction=overlap_frac),
                satisfied, failed,
                notes="different acquisitions: this IS independent evidence"))
    coverage = {
        "candidates_total": len(candidates),
        "candidates_placeable": len(placed),
        "candidates_unplaceable": len(unplaced),
        "note": ("unplaceable candidates cannot be associated across acquisitions at "
                 "all: trace indices are not comparable between files, and nothing "
                 "here substitutes one for a distance"),
    }
    logger.info(f"associate_adjacent_profiles: {len(out)} association(s); "
                f"{len(unplaced)}/{len(candidates)} candidates unplaceable")
    return out, coverage


def cross_survey_readiness(frames: Iterable) -> dict:
    """
    Whether the held data can support cross-survey association at all.

    Two things are required and neither can be manufactured: repeat coverage of
    the same ground, and acquisition timestamps to order the surveys. This
    reports what is present so a caller learns the answer instead of receiving
    an empty result that looks like "no matches".
    """
    frames = list(frames)
    with_time = [f for f in frames
                 if (f.source_metadata or {}).get("created")
                 or (f.source_metadata or {}).get("acquisition_date")]
    datasets = {f.dataset_id for f in frames}
    ready = len(with_time) >= 2 and len(datasets) >= 2
    return {
        "ready": ready,
        "frames_examined": len(frames),
        "frames_with_acquisition_time": len(with_time),
        "distinct_datasets": len(datasets),
        "missing": [] if ready else [
            m for m in [
                ("acquisition timestamps on at least two frames"
                 if len(with_time) < 2 else None),
                ("at least two distinct surveys of the same ground"
                 if len(datasets) < 2 else None),
            ] if m],
        "note": ("cross-survey association has NOT been validated against real "
                 "repeat-survey data: no dataset currently held provides repeat "
                 "coverage of the same ground with timestamps. The code path exists "
                 "and is unit-tested; it is not evidence-backed."),
    }


def associate_cross_survey(
    candidates_a: list, candidates_b: list, dataset_id: str, *,
    max_distance_m: float, max_time_separation_days: Optional[float],
    time_a_iso: Optional[str], time_b_iso: Optional[str], supplied_by: str,
) -> list[AssociationRecord]:
    """
    Associates candidates from two SEPARATE surveys.

    Requires both sets to be placeable and, when a time criterion is applied,
    both acquisition times. Unvalidated against real repeat surveys -- see
    `cross_survey_readiness`.
    """
    from datetime import datetime

    separation = None
    if max_time_separation_days is not None:
        if not (time_a_iso and time_b_iso):
            raise ValueError(
                "a time separation criterion was supplied but at least one survey has "
                "no acquisition time. Supply both times or drop the criterion; nothing "
                "here guesses when a survey happened."
            )
        separation = abs((datetime.fromisoformat(time_a_iso)
                          - datetime.fromisoformat(time_b_iso)).total_seconds()) / 86400.0

    criteria = AssociationCriteria(
        max_distance_m=max_distance_m,
        max_time_separation_days=max_time_separation_days, supplied_by=supplied_by)
    out: list[AssociationRecord] = []
    for a in candidates_a:
        ra = observation_from_candidate(a, dataset_id)
        if ra.position.kind != "geographic":
            continue
        for b in candidates_b:
            rb = observation_from_candidate(b, dataset_id)
            if rb.position.kind != "geographic":
                continue
            d = haversine_m(ra.position.lat, ra.position.lon,
                            rb.position.lat, rb.position.lon)
            satisfied, failed = [], []
            (satisfied if d <= max_distance_m else failed).append("max_distance_m")
            if max_time_separation_days is not None:
                (satisfied if separation <= max_time_separation_days
                 else failed).append("max_time_separation_days")
            if failed:
                continue
            out.append(_record(
                dataset_id, AssociationMethod.CROSS_SURVEY, ra, rb, criteria,
                AssociationEvidence(
                    distance_m=d,
                    distance_basis="haversine between candidate centroids (WGS84)",
                    time_separation_days=separation),
                satisfied, failed,
                notes=("cross-survey association: UNVALIDATED against real "
                       "repeat-survey data")))
    return out
