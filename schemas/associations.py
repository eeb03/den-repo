"""
Association records: "these two observations may be the same thing".

AN ASSOCIATION IS A HYPOTHESIS WITH ITS EVIDENCE ATTACHED. It is never a
finding that two observations ARE one object. The record therefore carries
the measurements that motivated it and the criteria that were applied, so a
reader can disagree with the criteria without re-running anything.

NO BUILT-IN HEURISTICS. Every threshold is supplied by the caller and stored
on the record. There is no default "traces within 5" or "depth overlap 50%",
because those numbers are not properties of the subsurface -- they are choices,
and a default would present a choice as science. This is the same contract the
platform already uses for velocity and CRS.

WHAT `score` IS AND IS NOT. It is the fraction of the applied criteria that
were satisfied, on [0, 1]. It is NOT a probability that the observations are
the same object, and `score_basis` says so on every record. Nothing multiplies
scores together or treats them as likelihoods.

INDEPENDENCE. `same_acquisition` records whether the two observations come
from one survey line. Two hyperbolae five traces apart on the same line are
weak evidence of one object; the same on two different lines is stronger. That
distinction is preserved here and consumed by `SubsurfaceObject`, which will
not call an object `corroborated` without independent acquisitions.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from schemas.objects import ObservationRef
from schemas.provenance import ProvenanceClass


class AssociationMethod(str, Enum):
    """
    How the association was proposed. Each names what it actually compares.
    """
    #: Same acquisition, nearby trace indices, overlapping depth.
    ADJACENT_TRACE = "adjacent_trace"
    #: Different acquisitions in one survey, compared by real-world distance.
    #: Requires both observations to be placeable on Earth.
    ADJACENT_PROFILE = "adjacent_profile"
    #: Different surveys of the same ground, separated in time.
    CROSS_SURVEY = "cross_survey"
    #: A human asserted it.
    MANUAL = "manual"


class AssociationCriteria(BaseModel):
    """
    The caller's thresholds, stored verbatim with the record.

    Every field is optional because different methods apply different criteria;
    what is NOT optional is that whatever was applied appears here. An
    association whose criteria are unknown cannot be argued with.
    """
    max_trace_gap: Optional[int] = None
    require_depth_overlap: Optional[bool] = None
    min_depth_overlap_fraction: Optional[float] = None
    max_distance_m: Optional[float] = None
    max_time_separation_days: Optional[float] = None
    supplied_by: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _something_must_have_been_applied(self):
        applied = [f for f in ("max_trace_gap", "require_depth_overlap",
                               "min_depth_overlap_fraction", "max_distance_m",
                               "max_time_separation_days")
                   if getattr(self, f) is not None]
        if not applied:
            raise ValueError(
                "association criteria must state at least one threshold that was "
                "actually applied; an association with no criteria is an assertion, "
                "not a hypothesis"
            )
        return self


class AssociationEvidence(BaseModel):
    """
    What was MEASURED about the pair. Numbers, not judgements.

    These are the quantities the criteria were tested against, kept so the
    same record can be re-judged under different criteria without recomputing.
    """
    trace_gap: Optional[int] = None
    depth_overlap_m: Optional[float] = None
    depth_overlap_fraction: Optional[float] = None
    distance_m: Optional[float] = None
    distance_basis: Optional[str] = None
    time_separation_days: Optional[float] = None
    extra: dict[str, Any] = Field(default_factory=dict)


def make_association_id(a: str, b: str, method: str) -> str:
    """Order-independent: associating A with B is the same claim as B with A."""
    lo, hi = sorted([a, b])
    return "asc_" + hashlib.sha256(f"{lo}|{hi}|{method}".encode()).hexdigest()[:16]


class AssociationRecord(BaseModel):
    """One hypothesis that two observations are the same thing."""
    id: Optional[str] = None
    dataset_id: str = Field(..., min_length=1)
    method: AssociationMethod
    observation_a: ObservationRef
    observation_b: ObservationRef

    criteria: AssociationCriteria
    evidence: AssociationEvidence
    criteria_satisfied: list[str] = Field(default_factory=list)
    criteria_failed: list[str] = Field(default_factory=list)

    score: float = Field(..., ge=0.0, le=1.0)
    score_basis: str = (
        "fraction of the applied criteria that were satisfied; NOT a probability "
        "that the observations are the same object")
    provenance: ProvenanceClass = ProvenanceClass.DERIVED
    created_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _rules(self):
        if self.observation_a.observation_id == self.observation_b.observation_id:
            raise ValueError("an observation cannot be associated with itself")
        if self.provenance in (ProvenanceClass.MEASURED,
                               ProvenanceClass.DECLARED_BY_SOURCE):
            raise ValueError(
                "an association is derived or asserted, never measured or declared: "
                "no instrument observes that two observations are one object"
            )
        if self.method == AssociationMethod.ADJACENT_PROFILE and \
                self.evidence.distance_m is None:
            raise ValueError(
                "an adjacent_profile association compares real-world distance, so it "
                "requires a measured distance_m. If the observations cannot be placed "
                "on Earth, they cannot be associated by this method."
            )
        if self.id is None:
            self.id = make_association_id(self.observation_a.observation_id,
                                          self.observation_b.observation_id,
                                          self.method.value)
        return self

    @property
    def same_acquisition(self) -> bool:
        return self.observation_a.acquisition_id == self.observation_b.acquisition_id

    @property
    def is_independent_evidence(self) -> bool:
        """Whether this association spans two acquisitions."""
        return not self.same_acquisition


class AssociationSet(BaseModel):
    """All associations for one dataset, as stored."""
    dataset_id: str
    associations: list[AssociationRecord] = Field(default_factory=list)

    def connected_components(self, min_score: float = 0.0) -> list[list[str]]:
        """
        Groups of observation ids linked by associations at or above `min_score`.

        Plain transitive closure, deliberately: A-B and B-C means {A, B, C}.
        That is a permissive grouping and it is stated as such -- the resulting
        object is a hypothesis, and a reviewer can raise `min_score` to split
        it. Nothing here weighs chains or decays scores along them, because any
        such rule would be invented.
        """
        parent: dict[str, str] = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        ids: set[str] = set()
        for a in self.associations:
            ids.add(a.observation_a.observation_id)
            ids.add(a.observation_b.observation_id)
            if a.score >= min_score:
                union(a.observation_a.observation_id, a.observation_b.observation_id)
        groups: dict[str, list[str]] = {}
        for i in sorted(ids):
            groups.setdefault(find(i), []).append(i)
        return [sorted(g) for g in groups.values()]
