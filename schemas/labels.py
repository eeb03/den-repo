"""
Semantic labels: what something has been CALLED, and by whom.

WHY THIS IS NOT A CLASSIFICATION FIELD. The platform already refuses to let
a detector candidate become a confirmed object -- `AnomalyCandidate` carries
`evidence`, `characteristics` and a deliberately neutral `interpretation`,
and nothing else. A label is the mechanism for saying more than that WITHOUT
losing the distinction: it attaches a name to a target while recording who
attached it, on what evidence, at what pipeline stage, and how much they
claim to know.

    A label is an ASSERTION BY A LABELLER. It is never a property of the
    ground. Two labellers may disagree about the same target and both labels
    are stored; nothing here resolves them, because resolving them would be
    inventing an answer.

WHAT MAKES A LABEL GROUND TRUTH. Only `LabelKind.GROUND_TRUTH`, and only
with an `attestation` naming the independent observation that established it
(a trial trench, an excavation record, a survey). A label cannot be promoted
to ground truth by a detector agreeing with it, by confidence, or by
repetition -- the validator refuses a ground-truth label with no attestation,
so the promotion cannot happen silently.

CONFIDENCE IS NOT PROBABILITY. `confidence` is whatever the labeller reports
on its own scale, and `confidence_basis` is required with it. A detector
score, a human's five-point rating and a model's softmax output are not
comparable, and averaging them would be meaningless -- so nothing here
averages them.

POSITION. A label locates itself with the existing `Position` union, or not
at all. It never carries loose lat/lon, and `NoPosition` with a reason is a
legitimate, common answer: a label attached to a whole survey line has no
single coordinate.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from schemas.provenance import ProvenanceClass
from schemas.spatial import NoPosition, Position


class LabelKind(str, Enum):
    """
    What sort of claim this label is. The distinction is load-bearing: a
    viewer must be able to draw a machine guess differently from a trench.
    """
    #: A detector's own neutral geometric class, carried forward as a label.
    DETECTOR_CANDIDATE = "detector_candidate"
    #: A human's reading of the data. An opinion, recorded as one.
    HUMAN_INTERPRETATION = "human_interpretation"
    #: A model's output. Requires the model's identity and version.
    MODEL_PREDICTION = "model_prediction"
    #: Established by an independent observation. Requires an attestation.
    GROUND_TRUTH = "ground_truth"


class LabelTargetKind(str, Enum):
    """What the label is attached to. All four are things the platform already has."""
    CANDIDATE = "candidate"        # an AnomalyCandidate.id
    FRAME = "frame"                # a SurveyFrame.frame_id -- a whole survey line
    DATASET = "dataset"            # a whole dataset
    TRACE_RANGE = "trace_range"    # a span of traces within one frame


class LabelSource(BaseModel):
    """
    Who or what produced the label.

    `name` and `kind` are required because an unattributed label cannot be
    reproduced, disputed or superseded. `version` is required for models and
    detectors -- "the model said so" is not a provenance record unless it
    says which model.
    """
    kind: str = Field(..., min_length=1)     # "detector" | "human" | "model" | "survey"
    name: str = Field(..., min_length=1)
    version: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _machines_must_declare_a_version(self):
        if self.kind in ("detector", "model") and not self.version:
            raise ValueError(
                f"a {self.kind} label source must declare a version: '{self.name} said so' "
                f"is not reproducible without knowing which {self.name}"
            )
        return self


class LabelTarget(BaseModel):
    """What is being labelled, by the platform's own identifiers."""
    kind: LabelTargetKind
    dataset_id: str = Field(..., min_length=1)
    #: AnomalyCandidate.id, SurveyFrame.frame_id, or the dataset id itself.
    target_id: str = Field(..., min_length=1)
    frame_id: Optional[str] = None
    source_file: Optional[str] = None
    trace_range: Optional[tuple[int, int]] = None

    @model_validator(mode="after")
    def _trace_range_needs_a_frame(self):
        if self.kind == LabelTargetKind.TRACE_RANGE:
            if self.trace_range is None or self.frame_id is None:
                raise ValueError(
                    "a trace_range target must name both a frame_id and a trace_range; "
                    "a trace index is only meaningful within one acquisition"
                )
            if self.trace_range[0] > self.trace_range[1]:
                raise ValueError(f"trace_range {self.trace_range} is inverted")
        return self


def make_label_id(target: LabelTarget, source: LabelSource, value: str) -> str:
    """
    Deterministic identity: the same labeller asserting the same value about
    the same target is the same label, not a duplicate. Re-running a detector
    therefore updates rather than accumulates.
    """
    raw = "|".join([target.dataset_id, target.kind.value, target.target_id,
                    source.kind, source.name, source.version or "", value])
    return "lbl_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


class SemanticLabel(BaseModel):
    """
    One assertion: this target has been called this, by this labeller.

    `provenance` is the class from `schemas.provenance`. A label is at best
    `supplied_by_caller` (a human said so) or `derived` (a detector computed
    it); it is never `measured`, because naming a thing is not measuring it.
    Only a ground-truth label with an attestation may claim
    `declared_by_source`.
    """
    id: Optional[str] = None
    kind: LabelKind
    target: LabelTarget
    source: LabelSource

    #: The label itself, e.g. "pipe-like hyperbola", "sewer", "diffuse".
    value: str = Field(..., min_length=1)
    #: Free-form vocabulary name, so two projects' "pipe" need not collide.
    vocabulary: Optional[str] = None

    confidence: Optional[float] = None
    confidence_basis: Optional[str] = None

    provenance: ProvenanceClass = ProvenanceClass.SUPPLIED_BY_CALLER
    #: Which pipeline stage produced it -- "ingest", "preprocessing",
    #: "detection", "interpretation", "review".
    processing_stage: str = Field(..., min_length=1)

    #: For GROUND_TRUTH only: the independent observation behind it.
    attestation: Optional[str] = None
    #: Free-form pointer to the evidence a reader could check.
    evidence_ref: Optional[str] = None
    notes: Optional[str] = None

    position: Position = Field(
        default_factory=lambda: NoPosition(
            reason="this label is attached to a target, not to a single coordinate"))
    created_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def _rules(self):
        if self.kind == LabelKind.GROUND_TRUTH and not (self.attestation or "").strip():
            raise ValueError(
                "a ground_truth label requires an `attestation` naming the independent "
                "observation that established it (a trial trench, an excavation record, a "
                "survey). Without one it is an opinion, and should be recorded as "
                "human_interpretation or model_prediction instead."
            )
        if self.kind != LabelKind.GROUND_TRUTH and self.attestation:
            raise ValueError(
                f"only a ground_truth label may carry an attestation; this is a "
                f"{self.kind.value}. Put the supporting detail in `notes` or `evidence_ref`."
            )
        if self.confidence is not None:
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError(
                    f"confidence {self.confidence} is outside [0, 1]. Normalise the "
                    f"labeller's own scale before recording it, and say which scale in "
                    f"`confidence_basis`."
                )
            if not (self.confidence_basis or "").strip():
                raise ValueError(
                    "a confidence requires a `confidence_basis` saying what it measures. "
                    "A detector score, a human rating and a model softmax are not "
                    "comparable, and an unlabelled number invites averaging them."
                )
        if self.provenance == ProvenanceClass.MEASURED:
            raise ValueError(
                "a label is never `measured`: naming a thing is not measuring it. Use "
                "`derived` for a detector, `supplied_by_caller` for a human, or "
                "`declared_by_source` for an attested ground-truth record."
            )
        if self.id is None:
            self.id = make_label_id(self.target, self.source, self.value)
        return self

    @property
    def is_ground_truth(self) -> bool:
        return self.kind == LabelKind.GROUND_TRUTH


class LabelSet(BaseModel):
    """All labels for one dataset, as stored."""
    dataset_id: str
    labels: list[SemanticLabel] = Field(default_factory=list)

    def for_target(self, target_id: str) -> list[SemanticLabel]:
        return [l for l in self.labels if l.target.target_id == target_id]

    def disagreements(self) -> dict[str, list[SemanticLabel]]:
        """
        Targets carrying more than one distinct value.

        Reported, never resolved. Two labellers disagreeing is information a
        reviewer needs; picking a winner here would be inventing an answer.
        """
        by_target: dict[str, list[SemanticLabel]] = {}
        for l in self.labels:
            by_target.setdefault(l.target.target_id, []).append(l)
        return {t: ls for t, ls in by_target.items()
                if len({l.value for l in ls}) > 1}
