"""
Candidate intelligence: what a candidate is, what is known about where it is,
and under what method it was produced.

WHAT THIS ADDS, AND WHAT IT DELIBERATELY DOES NOT. `anomaly_candidates` already
produces candidates and already refuses to describe them as objects. What it
does not produce is the surrounding record that makes a candidate set
TRUSTWORTHY rather than merely computed: which method and version made it, under
which parameters, over which inputs, when, and whether any of that has since
changed. This module supplies exactly that, plus a statement of how much is
genuinely known about a candidate's position and depth. It adds no new detector
and no new science.

CANDIDATE IS NOT DETECTION. This is the invariant the whole module exists to
protect, and it is enforced structurally rather than by convention:

  * `CLASSIFICATION_STATUS` is BLOCKED and there is no code path that sets it to
    anything else. No validated classifier exists in this repository, so no
    candidate may carry an object identity.
  * The only score is `candidate_score`, and `CANDIDATE_SCORE_MEANING` says in
    words what it is -- a peak local-anomaly z magnitude, ordinal WITHIN one
    dataset under one parameter set. It is not a probability, it is not a
    confidence, and it is not comparable between datasets.
  * `CandidateIntelligence` carries `BenchmarkContext` so that no consumer can
    display a candidate list without also being handed the measured performance
    of the method that produced it.

WHY THE BENCHMARK CONTEXT TRAVELS WITH THE DATA. The detector is at chance on
both benchmarks (see `BENCHMARK_CONTEXT` for the measured numbers and the
artifacts they come from). A candidate list rendered without that fact reads as
a finding. Attaching it to the payload rather than to a paragraph of
documentation means the honest framing cannot be dropped by a consumer that
forgets to look it up.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from interpretation.anomaly_candidates import (
    DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS, AnomalyCandidate,
)

#: The candidate-generation method, named once. Bump the version when the RULE
#: changes -- not when a parameter changes, which `GenerationParameters` already
#: records. A version bump makes every previously stored set stale.
CANDIDATE_METHOD = "ring_local_anomaly_connected_components"
CANDIDATE_METHOD_VERSION = "1.0.0"

#: Structurally constant. Setting this to anything else is a deliberate edit
#: that `tests/test_candidate_intelligence.py` fails on.
CLASSIFICATION_STATUS = "BLOCKED"
CLASSIFICATION_BLOCKED_REASON = (
    "no validated classifier exists in this repository, and no benchmark here "
    "supports mapping a candidate to an object identity"
)

CANDIDATE_SCORE_MEANING = (
    "peak local-anomaly z magnitude for the region. It orders candidates WITHIN "
    "one dataset under one parameter set and nothing more: it is not a "
    "probability, not a confidence, not calibrated against any ground truth, and "
    "not comparable between datasets."
)

#: What a candidate is allowed to mean, in the platform's own words. Carried in
#: the payload so an API consumer receives the definition, not just the data.
CANDIDATE_DEFINITION = (
    "a region of the processed signal whose measured characteristics satisfy a "
    "candidate-generation rule. It is not a detected object, not a validated "
    "detection, and not evidence that anything is buried at this location."
)


class LocalisationCertainty(str, Enum):
    """
    How well a candidate's position is actually known.

    These are levels of EVIDENCE, not of precision. `TRACE_RELATIVE` is not a
    worse measurement of the same thing as `SPATIALLY_REGISTERED` -- it is a
    different and weaker claim, and the difference is why a candidate may never
    be plotted on a map merely because it exists.
    """
    SPATIALLY_REGISTERED = "spatially_registered"
    FRAME_RELATIVE = "frame_relative"
    TRACE_RELATIVE = "trace_relative"
    UNKNOWN = "unknown"


class DepthCertainty(str, Enum):
    """
    What kind of depth, if any, the candidate has.

    DERIVED is the honest answer whenever a propagation velocity produced the
    number: velocity is an assumption about this ground, so the depth is an
    assumption's consequence. Stage 12 established that relating the depth-axis
    origin to the ground does NOT by itself create a physical depth, and this
    enum has no value that would let it.
    """
    MEASURED = "measured"
    DERIVED = "derived"
    UNAVAILABLE = "unavailable"


class CandidateStatus(str, Enum):
    """
    A candidate's place in the review workflow.

    ACCEPTED means a reviewer decided this candidate is worth retaining. It does
    NOT mean the candidate became ground truth, a detection, or an object, and
    nothing downstream may treat it as any of those.
    """
    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class BenchmarkContext(BaseModel):
    """
    Measured performance of the generating method, carried with its output.

    Every number here is reproduced from the committed artifacts by
    `scripts/score_bam_benchmark.py` and `scripts/score_4tu_benchmark.py`.
    """
    method: str = CANDIDATE_METHOD
    method_version: str = CANDIDATE_METHOD_VERSION
    summary: str = (
        "This method performs at approximately chance on both benchmarks it has "
        "been scored against. Candidates are worth inspecting; they are not "
        "evidence that something is there."
    )
    measurements: list[dict] = Field(default_factory=lambda: [
        {"benchmark": "bam-concrete-gpr", "arm": "1.5 GHz", "precision": 0.1351,
         "recall": 0.0652, "f1": 0.0880, "chance_precision": 0.1297,
         "times_chance": 1.04, "source": "artifacts/bam/score_1_5_GHz_Rot00.json"},
        {"benchmark": "bam-concrete-gpr", "arm": "2.6 GHz", "precision": 0.1465,
         "recall": 0.0932, "f1": 0.1139, "chance_precision": 0.1297,
         "times_chance": 1.13, "source": "artifacts/bam/score_2_6_GHz_Rot00.json"},
        {"benchmark": "4tu-nl-utility", "arm": "activity-level separation",
         "auc": 0.4452, "ci95": [0.2219, 0.6607], "contains_chance": True,
         "n_negative": 7, "source": "artifacts/4tu/leakage.json"},
    ])
    caveat: str = (
        "The 4TU separation rests on seven attested-empty trenches. Its 95% "
        "interval spans chance in both directions, so that benchmark cannot "
        "currently distinguish this method from chance -- in either direction."
    )


class GenerationParameters(BaseModel):
    """
    Everything that changes which candidates come out.

    A parameter change does not bump the method version; it makes previously
    stored sets stale, which is a different and weaker statement than "the rule
    changed". `fingerprint` is what staleness is actually decided on.
    """
    threshold: float = DEFAULT_ANOMALY_THRESHOLD
    min_cells: int = DEFAULT_MIN_CELLS
    #: Minimum number of trace columns a candidate must span. 1 reproduces the
    #: baseline exactly. See docs/candidate-intelligence.md for the evaluation.
    min_trace_span: int = 1

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(), sort_keys=True).encode()
        ).hexdigest()[:16]


class CandidateGeneration(BaseModel):
    """
    The provenance of one candidate set: who computed it, how, over what.

    `input_fingerprint` is what makes staleness detectable without recomputing
    anything. It summarises the INPUTS -- which source files, how many records,
    which preprocessing mode -- so that reprocessing a dataset, or declaring a
    new spatial reference, is visible as a change rather than silently
    producing a set that no longer matches the data it claims to describe.
    """
    method: str = CANDIDATE_METHOD
    method_version: str = CANDIDATE_METHOD_VERSION
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)
    generated_at: datetime
    dataset_id: str
    input_fingerprint: str
    #: The dataset's newest spatial declaration AT GENERATION TIME, kept
    #: separate from the input fingerprint because the two are checkable in
    #: different places: the records are readable from disk, the declarations
    #: need the database. Folding them into one hash would force every consumer
    #: to have both, and a consumer that had only one would report a dataset
    #: stale merely because it could not see the other half.
    declared_reference_at: Optional[datetime] = None
    n_source_files: int = 0
    n_records: int = 0

    #: This method uses no randomness. The field exists so that a method which
    #: does can record its seed rather than quietly claim reproducibility.
    seed: Optional[int] = None
    deterministic: bool = True
    determinism_note: str = (
        "same records, same preprocessing, same parameters and same method "
        "version reproduce this candidate set exactly; no randomness is used"
    )


def input_fingerprint(dataset_id: str, source_files: list[str], n_records: int,
                      preprocessing_mode: Optional[str] = None) -> str:
    """A stable summary of the RECORDS a candidate set was computed from."""
    payload = {
        "dataset_id": dataset_id,
        "source_files": sorted(source_files),
        "n_records": n_records,
        "preprocessing_mode": preprocessing_mode,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class CandidateStaleness(BaseModel):
    """
    Why a stored candidate set no longer describes the current dataset.

    `checks_performed` matters as much as the verdict. A caller that could not
    see the spatial declarations has not established that the set is current --
    it has established that the records did not change. Saying which is the
    difference between "not stale" and "not known to be stale".
    """
    is_stale: bool = False
    reasons: list[str] = Field(default_factory=list)
    checks_performed: list[str] = Field(default_factory=list)
    checks_skipped: list[str] = Field(default_factory=list)
    note: str = (
        "nothing is recomputed automatically: regenerating is a decision for "
        "somebody who can see why the old set no longer applies"
    )


def assess_staleness(generation: CandidateGeneration, *,
                     current_fingerprint: Optional[str] = None,
                     newest_declaration_at: Optional[datetime] = None,
                     check_declarations: bool = False,
                     current_method_version: str = CANDIDATE_METHOD_VERSION,
                     current_parameters: Optional[GenerationParameters] = None,
                     ) -> CandidateStaleness:
    """
    Compare a stored generation against the dataset as it is now.

    Mirrors `api/spatial.py::stale_products`: it states the fact and recomputes
    nothing, because silently re-running the detector would hide the very change
    being reported.

    A declaration made AFTER generation makes the set stale, because Stage 8
    established that a CRS, datum, tie or velocity changes what the data means.
    Pass `check_declarations=True` only when `newest_declaration_at` genuinely
    reflects the database; otherwise the check is recorded as skipped rather
    than silently counted as passed.
    """
    reasons: list[str] = []
    performed: list[str] = ["method version"]
    skipped: list[str] = []

    if generation.method_version != current_method_version:
        reasons.append(
            f"generated by method version {generation.method_version}, "
            f"current version is {current_method_version}"
        )

    if current_fingerprint is None:
        skipped.append("records")
    else:
        performed.append("records")
        if generation.input_fingerprint != current_fingerprint:
            reasons.append(
                "the dataset's records have changed since generation (record "
                "count, source files, or preprocessing)"
            )

    if not check_declarations:
        skipped.append("spatial declarations")
    else:
        performed.append("spatial declarations")
        before = generation.declared_reference_at
        if newest_declaration_at is not None and (
                before is None or newest_declaration_at > before):
            reasons.append(
                "a spatial declaration has been recorded since generation, so the "
                "data means something different from when the candidates were computed"
            )

    if current_parameters is not None:
        performed.append("parameters")
        if generation.parameters.fingerprint() != current_parameters.fingerprint():
            reasons.append(
                f"generated with parameters {generation.parameters.model_dump()}, "
                f"current request asks for {current_parameters.model_dump()}"
            )

    return CandidateStaleness(is_stale=bool(reasons), reasons=reasons,
                              checks_performed=performed, checks_skipped=skipped)


def localisation_of(candidate: AnomalyCandidate) -> tuple[LocalisationCertainty, str]:
    """
    What is genuinely known about where this candidate is.

    Nothing is fabricated here and nothing is estimated: the answer is read off
    measurements that either exist or do not. A candidate with no geographic
    centroid is TRACE_RELATIVE, which is a real and useful location -- it names
    the file and the traces a person can open -- and it is not a coordinate.
    """
    c = candidate.characteristics
    if c.centroid_lat is not None and c.centroid_lon is not None:
        return (LocalisationCertainty.SPATIALLY_REGISTERED,
                "the supporting traces carry geographic positions")
    if c.lateral_extent_source == "odometry":
        return (LocalisationCertainty.FRAME_RELATIVE,
                "along-track distance is measured, but no geographic position is available")
    if candidate.evidence.source_file:
        return (LocalisationCertainty.TRACE_RELATIVE,
                f"locatable as traces {candidate.evidence.trace_range[0]}"
                f"-{candidate.evidence.trace_range[1]} of {candidate.evidence.source_file}")
    return (LocalisationCertainty.UNKNOWN, "no defensible location exists for this candidate")


def depth_of(candidate: AnomalyCandidate) -> tuple[DepthCertainty, str]:
    """
    What kind of depth this candidate has, if any.

    A velocity makes depth DERIVED, never measured: it is an assumption about
    this ground and the number inherits that status. With no velocity there is
    no physical depth at all -- the candidate still has a position on the
    instrument's own axis, which is not a depth and must not be shown as one.
    """
    v = candidate.confidence.velocity_m_per_ns
    if v is None:
        return (DepthCertainty.UNAVAILABLE,
                "no propagation velocity has been declared for this dataset, so the "
                "candidate's position on the instrument axis is not a physical depth")
    return (DepthCertainty.DERIVED,
            f"converted from the time axis using a declared velocity of {v} m/ns, "
            "which is an assumption about this ground and not a measurement")


class InspectableCandidate(BaseModel):
    """
    One candidate, with everything a person needs to judge it themselves.

    The evidence chain is the point: `source_file` plus `trace_range` plus
    `depth_range` addresses the exact measurements behind the proposal, so a
    reviewer can go and look instead of trusting the platform.
    """
    candidate: AnomalyCandidate
    candidate_score: float
    candidate_score_meaning: str = CANDIDATE_SCORE_MEANING
    localisation: LocalisationCertainty
    localisation_basis: str
    depth: DepthCertainty
    depth_basis: str
    status: CandidateStatus = CandidateStatus.PROPOSED
    classification_status: str = CLASSIFICATION_STATUS
    classification_blocked_reason: str = CLASSIFICATION_BLOCKED_REASON


def inspectable(candidate: AnomalyCandidate,
                status: CandidateStatus = CandidateStatus.PROPOSED) -> InspectableCandidate:
    loc, loc_why = localisation_of(candidate)
    depth, depth_why = depth_of(candidate)
    return InspectableCandidate(
        candidate=candidate,
        candidate_score=abs(candidate.evidence.peak_value),
        localisation=loc, localisation_basis=loc_why,
        depth=depth, depth_basis=depth_why,
        status=status,
    )


class CandidateIntelligence(BaseModel):
    """
    The whole candidate picture for one dataset.

    `status` describes whether candidate generation is possible, NOT whether
    anything was found: AVAILABLE with zero candidates is a real and meaningful
    result, and it is not the same as BLOCKED.
    """
    dataset_id: str
    #: AVAILABLE | LIMITED | BLOCKED
    status: str
    status_reason: str
    missing: list[str] = Field(default_factory=list)

    definition: str = CANDIDATE_DEFINITION
    generation: Optional[CandidateGeneration] = None
    staleness: CandidateStaleness = Field(default_factory=CandidateStaleness)

    candidate_count: int = 0
    #: Ranked by `candidate_score`, descending. The ranking is ordinal within
    #: this dataset only -- see CANDIDATE_SCORE_MEANING.
    candidates: list[InspectableCandidate] = Field(default_factory=list)
    ranking_basis: str = CANDIDATE_SCORE_MEANING

    #: §23: how many candidates a person would have to look at.
    candidate_burden: Optional[float] = None
    candidate_burden_basis: str = "candidates per 1000 traces examined"

    #: Counts by certainty, so a consumer can see at a glance how much of this
    #: set is actually placeable.
    localisation_breakdown: dict[str, int] = Field(default_factory=dict)
    depth_breakdown: dict[str, int] = Field(default_factory=dict)
    shape_classes: dict[str, int] = Field(default_factory=dict)

    classification_status: str = CLASSIFICATION_STATUS
    classification_blocked_reason: str = CLASSIFICATION_BLOCKED_REASON
    classified_object_count: int = 0

    benchmark: BenchmarkContext = Field(default_factory=BenchmarkContext)


def build_intelligence(dataset_id: str, candidates: list[InspectableCandidate], *,
                       generation: Optional[CandidateGeneration] = None,
                       staleness: Optional[CandidateStaleness] = None,
                       status: str = "available",
                       status_reason: str = "",
                       missing: Optional[list[str]] = None,
                       n_traces: Optional[int] = None) -> CandidateIntelligence:
    """Assemble the view. Counts only; nothing here computes new science."""
    def tally(values) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in values:
            out[v] = out.get(v, 0) + 1
        return dict(sorted(out.items()))

    ranked = sorted(candidates, key=lambda c: c.candidate_score, reverse=True)
    burden = (1000.0 * len(ranked) / n_traces) if n_traces else None

    return CandidateIntelligence(
        dataset_id=dataset_id,
        status=status,
        status_reason=status_reason,
        missing=list(missing or []),
        generation=generation,
        staleness=staleness or CandidateStaleness(),
        candidate_count=len(ranked),
        candidates=ranked,
        candidate_burden=burden,
        localisation_breakdown=tally(c.localisation.value for c in ranked),
        depth_breakdown=tally(c.depth.value for c in ranked),
        shape_classes=tally(c.candidate.interpretation.anomaly_class for c in ranked),
    )


def blocked(dataset_id: str, reason: str, missing: list[str]) -> CandidateIntelligence:
    """
    Candidate generation is not possible for this dataset.

    `missing` is never empty: a blocked state nobody can act on is the one
    failure every other assessment in this platform is built to avoid.
    """
    if not missing:
        raise ValueError("a blocked candidate state must name what is missing")
    return CandidateIntelligence(
        dataset_id=dataset_id, status="blocked", status_reason=reason, missing=missing,
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
