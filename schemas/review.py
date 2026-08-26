"""
Human-in-the-Loop Anomaly Verification V1: a reviewer's judgement about real
Subterra evidence, kept strictly separate from the detector's own output, from
semantic interpretation, and from independently verified physical truth.

============================================================================
THE FOUR THINGS THIS MODULE NEVER COLLAPSES INTO ONE FIELD
============================================================================

    DETECTOR OUTPUT        z_score = 4.2, candidate_class = "elongated"
                            -- `DetectorSnapshot` below. Frozen at review
                            time, never edited by a review.
    HUMAN ANOMALY JUDGEMENT review_status = CONFIRMED -- `ReviewStatus`.
                            Whether the reviewer believes real evidence is
                            present. Establishes NO identity.
    HUMAN INTERPRETATION   operator_label = "pipe" -- optional, free text
                            constrained to a small vocabulary, always
                            human-supplied, never model output.
    INDEPENDENT TRUTH      ground_truth_status -- this module can only ever
                            report `not_independently_validated` for
                            anything it produces (mirrors
                            `training.segmentation.annotation_record`'s own
                            field of the same name). A human saying "this
                            looks like a pipe" is not, and cannot become,
                            "Subterra detected a pipe".

============================================================================
WHY THIS IS A NEW SCHEMA, NOT A REUSE OF `CandidateStatus` OR `SemanticLabel`
============================================================================

`interpretation.candidate_intelligence.CandidateStatus` (proposed / reviewed
/ accepted / rejected) already exists and is NOT duplicated here -- it
answers a different question, "is this candidate worth retaining in the
list", and this module leaves it alone. `CONFIRMED` here answers "does this
represent genuine radar evidence of a real anomaly/structure", which is a
scientific judgement `CandidateStatus` was never built to carry, and forcing
the two together would mean either inventing a `CandidateStatus.CONFIRMED`
that isn't about retention, or silently narrowing this module's own
UNCERTAIN state out of existence (only four `CandidateStatus` values exist
and none of them means "insufficient evidence to say").

`schemas.labels.SemanticLabel` (`LabelKind.HUMAN_INTERPRETATION`) is exactly
the mechanism this module DOES reuse for `operator_label` -- see
`training.review_corpus`, which writes it there, not a new field. This
module's `operator_label` is a convenience mirror for display; the label
system of record for "what a human called it" stays `schemas.labels`.

============================================================================
WHY EVERY REVIEW THIS MODULE PRODUCES IS EVIDENCE GRADE C
============================================================================

`schemas.segmentation.EvidenceGrade.C_OPERATOR_REVIEWED`, always -- "a
knowledgeable reviewer selected a radar event by visual/technical judgment.
Useful for training research; not independent ground truth." Nothing in
this module has a path to Grade A or B: those require an independent
physical observation (an excavation, a survey, a controlled placement) that
a screen-based review structurally cannot supply. `PRIMARY_TRAINING_
EVIDENCE_GRADES` in `schemas.segmentation` already excludes Grade C from the
primary corpus, so this module inherits that gate for free -- it does not
re-implement or weaken it (Section 17's own rule).

============================================================================
WHY A REJECTED CANDIDATE IS NOT A VERIFIED-EMPTY NEGATIVE
============================================================================

`training.segmentation.build_bam_pk050_negative_examples` grades its empty
specimen `EvidenceGrade.A_INDEPENDENTLY_VERIFIED` because the FABRICATOR's
own construction record independently attests nothing was placed there. A
human here deciding "this candidate is clutter" attests only that one
person did not find the DETECTOR's proposal convincing -- real evidence
about the detector's false-positive behaviour, but not an independent
statement about the ground. A `REJECTED` review is therefore graded
`C_OPERATOR_REVIEWED` like every other review this module produces, never
promoted to `A_INDEPENDENTLY_VERIFIED` (Section 11's own distinction).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from schemas.segmentation import EvidenceGrade, LabelSource as SegmentationLabelSource

#: The small, inspected-before-defining vocabulary Section 4 asks for.
#: "unknown"/"other" are first-class, not fallbacks -- a reviewer who is
#: confident an anomaly is real but cannot name it is a valid, expected,
#: important state (Section 4's own "critical valid state").
OPERATOR_LABEL_VOCABULARY = (
    "pipe", "cable", "void", "layer_interface", "geological_feature",
    "buried_object", "unknown", "other",
)


class ReviewStatus(str, Enum):
    """
    Section 3's smallest useful vocabulary. Deliberately NOT binary --
    `UNCERTAIN` is a first-class outcome, not a missing value, because
    forcing a reviewer to pick Confirmed or Rejected when the evidence is
    genuinely ambiguous would manufacture a judgement nobody made.
    """
    #: No human judgement has been recorded.
    UNREVIEWED = "unreviewed"
    #: The reviewer believes the radar evidence represents a genuine
    #: anomaly/structure. Establishes no identity -- see `operator_label`.
    CONFIRMED = "confirmed"
    #: The reviewer believes the candidate is clutter/noise/not meaningful.
    #: See module docstring for why this never becomes a verified negative.
    REJECTED = "rejected"
    #: The evidence is insufficient to say either way.
    UNCERTAIN = "uncertain"


class AnnotationGeometryKind(str, Enum):
    #: (trace_start, trace_end) x (sample_start, sample_end), inclusive --
    #: Section 6 Option A. Every cell in the box is the marked region; the
    #: reviewer drew the whole extent, so this is not an invented width.
    RECTANGLE = "rectangle"
    #: A sequence of (trace, sample) points tracing a visible event --
    #: Section 6 Option B, preferred where an event is visually traceable.
    #: One point per traced column, mirroring `training.segmentation`'s own
    #: "no invented width around the pick" doctrine for BAM's real ridge
    #: annotations.
    RIDGE_PATH = "ridge_path"


class AnnotationGeometry(BaseModel):
    """
    Section 7: the reviewer's ACTUAL marked geometry, preserved as drawn --
    never collapsed into a generated mask at write time, so a future,
    better mask-generation rule can be re-applied without losing what the
    human actually pointed at. `training.review_corpus.geometry_to_mask`
    is the one place the deterministic-width rule this converts into a
    training mask lives.
    """
    kind: AnnotationGeometryKind
    #: RECTANGLE only.
    trace_start: Optional[int] = None
    trace_end: Optional[int] = None
    sample_start: Optional[int] = None
    sample_end: Optional[int] = None
    #: RIDGE_PATH only -- parallel arrays, one traced point per entry,
    #: matching `schemas.segmentation.MaskRegion`'s own convention exactly.
    trace_indices: list[int] = Field(default_factory=list)
    sample_indices: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape_matches_kind(self):
        if self.kind == AnnotationGeometryKind.RECTANGLE:
            missing = [f for f in ("trace_start", "trace_end", "sample_start", "sample_end")
                       if getattr(self, f) is None]
            if missing:
                raise ValueError(f"a rectangle annotation is missing {missing}")
            if self.trace_end < self.trace_start:
                raise ValueError(f"trace_end {self.trace_end} is before trace_start {self.trace_start}")
            if self.sample_end < self.sample_start:
                raise ValueError(f"sample_end {self.sample_end} is before sample_start {self.sample_start}")
        elif self.kind == AnnotationGeometryKind.RIDGE_PATH:
            if not self.trace_indices:
                raise ValueError("a ridge_path annotation needs at least one traced point")
            if len(self.trace_indices) != len(self.sample_indices):
                raise ValueError(
                    f"trace_indices ({len(self.trace_indices)}) and sample_indices "
                    f"({len(self.sample_indices)}) must be the same length"
                )
        return self


class ReviewRevision(BaseModel):
    """
    Section 10's audit history: one snapshot of what changed, appended, never
    overwritten. The smallest mechanism that satisfies "do not silently erase
    the prior state" without a separate event-sourcing store -- history lives
    inline on the record it describes.
    """
    reviewer_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    review_status: ReviewStatus
    operator_label: Optional[str] = None
    notes: Optional[str] = None


class DetectorSnapshot(BaseModel):
    """
    Section 9: the detector's output AT REVIEW TIME, frozen. A review must
    never be able to alter these fields -- they exist so a later evaluation
    can ask "was the detector correct", which requires knowing what the
    detector actually said, not what it says now after a possible
    regeneration.
    """
    candidate_score: Optional[float] = None
    candidate_class: Optional[str] = None
    detector_method: Optional[str] = None
    detector_version: Optional[str] = None
    localisation: Optional[str] = None
    depth_certainty: Optional[str] = None


def make_review_id(dataset_id: str, candidate_id: Optional[str],
                   source_file: str, trace_range: tuple[int, int]) -> str:
    """
    Deterministic identity, mirroring `schemas.labels.make_label_id`'s own
    reasoning: one candidate has one review record, so re-reviewing UPDATES
    it (with history preserved -- see `ReviewRevision`) instead of
    accumulating duplicates. A missed-event annotation (no `candidate_id`)
    is identified by its own geometry instead, since there is no candidate
    id to anchor to.
    """
    raw = "|".join([dataset_id, candidate_id or "missed_event",
                    source_file, str(trace_range[0]), str(trace_range[1])])
    return "rev_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


class CandidateReview(BaseModel):
    """
    One reviewer's judgement about one piece of real Subterra evidence --
    either an existing detector candidate, or a candidate-independent
    "missed event" the detector never proposed (Section 12).
    """
    id: Optional[str] = None
    dataset_id: str = Field(..., min_length=1)
    #: None for a missed-event annotation (Section 12) -- candidate-
    #: independent, so the future corpus is not limited to the detector's
    #: own blind spots.
    candidate_id: Optional[str] = None
    site_id: Optional[str] = None
    source_file: str = Field(..., min_length=1)
    #: (min, max) real trace indices this review addresses.
    trace_range: tuple[int, int]

    reviewer_id: str = Field(..., min_length=1)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    #: Constrained to `OPERATOR_LABEL_VOCABULARY`, or `None` -- Section 4's
    #: own "critical valid state": CONFIRMED with no label is first-class.
    operator_label: Optional[str] = None
    annotation_geometry: Optional[AnnotationGeometry] = None
    notes: Optional[str] = None

    #: Always `C_OPERATOR_REVIEWED` -- see module docstring.
    evidence_grade: EvidenceGrade = EvidenceGrade.C_OPERATOR_REVIEWED
    #: Always `OPERATOR_REVIEWED` -- reuses `schemas.segmentation.LabelSource`,
    #: the milestone brief's own instruction (Section 8).
    label_source: SegmentationLabelSource = SegmentationLabelSource.OPERATOR_REVIEWED
    #: Always this literal string -- see module docstring on why a review can
    #: never become independently validated ground truth.
    ground_truth_status: Literal["not_independently_validated"] = "not_independently_validated"

    #: Frozen at first review; a review can never edit these (Section 9).
    detector_snapshot: Optional[DetectorSnapshot] = None

    history: list[ReviewRevision] = Field(default_factory=list)
    created_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def _rules(self):
        if self.operator_label is not None and self.operator_label not in OPERATOR_LABEL_VOCABULARY:
            raise ValueError(
                f"operator_label {self.operator_label!r} is not in the reviewed vocabulary "
                f"{OPERATOR_LABEL_VOCABULARY}"
            )
        if self.trace_range[0] > self.trace_range[1]:
            raise ValueError(f"trace_range {self.trace_range} is inverted")
        if self.id is None:
            self.id = make_review_id(self.dataset_id, self.candidate_id,
                                     self.source_file, self.trace_range)
        return self

    @property
    def is_missed_event(self) -> bool:
        return self.candidate_id is None

    @property
    def eligible_for_corpus(self) -> bool:
        """A review carries usable evidence only once a human has actually looked -- UNREVIEWED never exports."""
        return self.review_status != ReviewStatus.UNREVIEWED

    @property
    def distinct_reviewer_ids(self) -> list[str]:
        """
        Every reviewer who has ever recorded a judgement on this candidate,
        current reviewer first -- the audit trail Section 16 asks a future
        multi-reviewer feature to be able to read. `make_review_id` keys one
        review per candidate, so a second expert re-reviewing the same
        candidate does not create a second record; `upsert_review` instead
        pushes the prior `reviewer_id`/`review_status` into `history` before
        replacing it (Section 10), which is exactly what this property reads.
        """
        ids = [self.reviewer_id]
        for revision in self.history:
            if revision.reviewer_id not in ids:
                ids.append(revision.reviewer_id)
        return ids

    @property
    def review_kind(self) -> Literal["single_review", "consensus_review"]:
        """
        Section 16's quality-control distinction. Computed, not a stored
        field or a workflow this module drives -- "do not require multiple
        reviewers yet" -- but the schema already supports it for free: once
        `distinct_reviewer_ids` shows more than one expert has looked at this
        candidate, this becomes `consensus_review` without any new mechanism
        or any loss of the original reviewer's judgement.
        """
        return "consensus_review" if len(self.distinct_reviewer_ids) > 1 else "single_review"


class ReviewSet(BaseModel):
    """All reviews for one dataset, as stored -- mirrors `schemas.labels.LabelSet`."""
    dataset_id: str
    reviews: list[CandidateReview] = Field(default_factory=list)

    def for_candidate(self, candidate_id: str) -> Optional[CandidateReview]:
        return next((r for r in self.reviews if r.candidate_id == candidate_id), None)

    def summary(self) -> dict:
        """Section 13's dataset-level progress report, computed rather than hand-maintained."""
        counts = {s.value: 0 for s in ReviewStatus}
        missed_events = 0
        consensus_reviews = 0
        for r in self.reviews:
            counts[r.review_status.value] += 1
            if r.is_missed_event:
                missed_events += 1
            if r.review_kind == "consensus_review":
                consensus_reviews += 1
        return {
            "total_reviews": len(self.reviews),
            "by_status": counts,
            "missed_events": missed_events,
            "eligible_for_corpus": sum(1 for r in self.reviews if r.eligible_for_corpus),
            #: Section 16 -- reviewed by more than one distinct reviewer_id, never
            #: required, always computed from `history` (see `review_kind`).
            "consensus_reviews": consensus_reviews,
        }
