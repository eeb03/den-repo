"""
Activity-level scoring of the detector against 4TU trial-trench truth.

THE RESOLUTION IS THE ACTIVITY, and that is forced by the source rather than
chosen: 4TU withholds trench coordinates, so nothing here matches a candidate
to a utility. Every metric is a per-activity count or a comparison between
groups of activities.

WHAT IS DELIBERATELY NOT COMPUTED, because the truth cannot support it:
per-object precision and recall, IoU, detection distance, depth accuracy,
positional F1. `benchmark.gates.require_object_level_evidence` raises for any
of them.

WHY "FALSE POSITIVE" IS NOT USED HERE. On a controlled specimen an unmatched
detection is wrong. On 4TU it may be a real utility that the trial trench --
a small excavation inside a much larger surveyed area -- never reached. The
measure reported for zero-utility activities is therefore an *unexplained
response rate*, not a false-alarm rate, and the distinction is in the field
names, not only in the prose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from benchmark.fourtu_truth import TRENCH_SCOPE_CAVEAT, ActivityTruth, FourTuTruth

SCOPE_STATEMENT = (
    "4TU results measure detector response on real-world utility surveys "
    "against trial-trench counts. They are activity-level only: no candidate "
    "is matched to a utility, and no positional or depth accuracy is measured."
)


@dataclass(frozen=True)
class ActivityObservation:
    """What the detector produced for one activity."""
    location_id: str
    candidates: int
    traces: int

    @property
    def per_1k_traces(self) -> Optional[float]:
        return (1000.0 * self.candidates / self.traces) if self.traces else None


@dataclass(frozen=True)
class GroupSummary:
    n_activities: int
    n_candidates: int
    median_per_1k: Optional[float]
    mean_per_1k: Optional[float]
    min_per_1k: Optional[float]
    max_per_1k: Optional[float]
    activities_with_zero_candidates: int


@dataclass(frozen=True)
class FourTuScore:
    n_activities_scored: int
    n_positive: int
    n_attested_zero: int
    n_unrecorded: int

    #: Activity-level "did it respond at all" -- reported, and labelled with
    #: why it carries almost no information on this corpus.
    activities_with_utilities_and_a_candidate: int
    activity_level_response_rate: Optional[float]
    activity_level_note: str

    positive_group: GroupSummary
    attested_zero_group: GroupSummary

    #: Does candidate density separate trench-empty from trench-occupied ground?
    density_separation: dict

    #: Does the number of candidates track the number of utilities found?
    count_agreement: dict

    unexplained_response_rate: Optional[float]
    unexplained_response_basis: str
    sufficient_for_a_rate: bool
    limitation: str

    trench_scope_caveat: str = TRENCH_SCOPE_CAVEAT
    scope: str = SCOPE_STATEMENT
    object_level_scored: bool = False
    positional_accuracy_scored: bool = False
    depth_accuracy_scored: bool = False
    provenance: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {}
        for k, v in self.__dict__.items():
            out[k] = v.__dict__ if isinstance(v, GroupSummary) else v
        return out


#: Below this many activities in a group, a "rate" would be a number without a
#: population behind it. 4TU publishes only a handful of zero-utility trenches.
MIN_ACTIVITIES_FOR_A_RATE = 10


def _median(xs: list[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _summarise(obs: list[ActivityObservation]) -> GroupSummary:
    dens = [o.per_1k_traces for o in obs if o.per_1k_traces is not None]
    return GroupSummary(
        n_activities=len(obs),
        n_candidates=sum(o.candidates for o in obs),
        median_per_1k=_median(dens),
        mean_per_1k=(sum(dens) / len(dens)) if dens else None,
        min_per_1k=min(dens) if dens else None,
        max_per_1k=max(dens) if dens else None,
        activities_with_zero_candidates=sum(1 for o in obs if o.candidates == 0),
    )


def _spearman(pairs: list[tuple[float, float]]) -> Optional[float]:
    """Rank correlation, with average ranks for ties. None if degenerate."""
    n = len(pairs)
    if n < 3:
        return None

    def ranks(vals):
        order = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return (num / den) if den else None


def _rank_sum_separation(a: list[float], b: list[float]) -> dict:
    """
    Probability that a random member of `a` exceeds a random member of `b`
    (the Mann-Whitney common-language effect size). 0.5 means no separation.

    Reported instead of a p-value because with a handful of zero-utility
    activities a p-value would imply a power this design does not have.
    """
    if not a or not b:
        return {"auc": None, "n_a": len(a), "n_b": len(b),
                "interpretation": "not computable: a group is empty"}
    wins = sum((1.0 if x > y else 0.5 if x == y else 0.0) for x in a for y in b)
    auc = wins / (len(a) * len(b))
    return {
        "auc": auc,
        "n_a": len(a),
        "n_b": len(b),
        "interpretation": (
            "probability that a utility-bearing activity shows a higher candidate "
            "density than a trench-empty one; 0.5 is no separation"
        ),
    }


def score_activities(truth: FourTuTruth,
                     observations: dict[str, ActivityObservation]) -> FourTuScore:
    """
    Compare detector output per activity with the trial-trench counts.

    `observations` is keyed by LocationID. Activities present in one source and
    not the other are excluded from the comparison and counted, so a partial
    overlap can never masquerade as full coverage.
    """
    shared = sorted(set(truth.activities) & set(observations))

    pos_obs, zero_obs = [], []
    pairs: list[tuple[float, float]] = []
    responded = 0

    for loc in shared:
        t: ActivityTruth = truth.activities[loc]
        o = observations[loc]
        if t.has_utilities:
            pos_obs.append(o)
            if o.candidates > 0:
                responded += 1
            if o.per_1k_traces is not None:
                pairs.append((float(t.n_utilities), o.per_1k_traces))
        elif t.attested_zero:
            zero_obs.append(o)

    pos_sum, zero_sum = _summarise(pos_obs), _summarise(zero_obs)
    enough = len(zero_obs) >= MIN_ACTIVITIES_FOR_A_RATE

    pos_dens = [o.per_1k_traces for o in pos_obs if o.per_1k_traces is not None]
    zero_dens = [o.per_1k_traces for o in zero_obs if o.per_1k_traces is not None]

    rho = _spearman(pairs)

    return FourTuScore(
        n_activities_scored=len(shared),
        n_positive=len(pos_obs),
        n_attested_zero=len(zero_obs),
        n_unrecorded=len([1 for loc in shared if truth.activities[loc].unrecorded]),
        activities_with_utilities_and_a_candidate=responded,
        activity_level_response_rate=(responded / len(pos_obs)) if pos_obs else None,
        activity_level_note=(
            "This is 'did the detector produce any candidate in an activity where "
            "the trench found a utility'. It is reported for completeness and "
            "carries almost no information on this corpus, because the detector "
            "produces candidates in essentially every activity -- including the "
            "trench-empty ones. A near-1.0 value here is not evidence of skill."
        ),
        positive_group=pos_sum,
        attested_zero_group=zero_sum,
        density_separation=_rank_sum_separation(pos_dens, zero_dens),
        count_agreement={
            "spearman_rho": rho,
            "n_pairs": len(pairs),
            "x": "utilities found in the trial trench (declared_by_source)",
            "y": "candidates per 1,000 traces (derived)",
            "interpretation": (
                "whether activities where the trench found more utilities also "
                "produce more detector candidates"
            ),
            "caveat": (
                "a trench count is not a count of what lies under the survey "
                "lines; see trench_scope_caveat"
            ),
        },
        unexplained_response_rate=(
            (zero_sum.n_candidates / zero_sum.n_activities) if enough and zero_sum.n_activities else None
        ),
        unexplained_response_basis=(
            "candidates per activity on ground whose trench found no utilities"
            if enough else "not computed"
        ),
        sufficient_for_a_rate=enough,
        limitation=(
            "" if enough else
            f"only {len(zero_obs)} activities have an attested zero count, below "
            f"the {MIN_ACTIVITIES_FOR_A_RATE} needed before a rate is reported; "
            f"the raw counts are given instead"
        ),
        provenance={
            "truth": truth.source,
            "truth_field": "Amount of utilities",
            "truth_definition": truth.count_definition,
            "truth_provenance": truth.count_provenance,
            "coordinates_available": truth.coordinates_available,
        },
    )


def score_object_level(*_args, **_kwargs):
    """Refuses. 4TU publishes no coordinates, so there is nothing to match."""
    from benchmark.gates import require_object_level_evidence
    require_object_level_evidence("object-level 4TU scoring")
