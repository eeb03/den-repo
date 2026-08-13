"""
A benchmark, pinned: which units, which labels, which policies, which version.

WHY A VERSION AT ALL. Ground truth is part of the scientific definition of a
result, not configuration around it. "AUC 0.4452" means nothing without knowing
which units were scored, what counted as a negative, and what was excluded --
and if any of those change, the number is no longer comparable with the one
before it. So the version is a HASH OF THE TRUTH ITSELF: labels, evidence bases,
duplicate statuses, exclusions and policies all feed it. Change any of them and
the version changes on its own, without anybody remembering to bump it.

WHAT THE VERSION DELIBERATELY EXCLUDES: anything about a detector. Thresholds,
estimators and parameters belong to the thing being measured, not to the
measuring instrument. A benchmark whose identity changed when the detector
changed could not be used to compare detectors, which is its only purpose.

READINESS REUSES THE PLATFORM'S EXISTING VOCABULARY -- READY / PARTIAL /
BLOCKED, from `schemas.dataset_report` -- rather than inventing a benchmark
quality score. There is no number here. A score would invite comparing two
benchmarks' fitness on one axis, and the whole finding of this stage is that
fitness is per-question: the 4TU corpus is fine for asking whether candidates
appear at all and unfit for asking whether one detector beats another.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from benchmark import gates
from benchmark.ground_truth import (
    EvaluationUnit, TruthLabel, duplicate_counts, independent_negatives,
    independent_positives, label_counts,
)
from benchmark.power import PowerAssessment, assess as assess_power

#: Bumped by hand ONLY when the meaning of a field changes -- not when truth
#: changes, which the content hash already covers.
SCHEMA_VERSION = "1"

#: How duplicate and contaminated units are handled. Recorded in the definition
#: so a version can be interpreted without reading this source file.
DUPLICATE_POLICY = (
    "Units are compared by file checksum (benchmark.leakage). Units sharing "
    "byte-identical measurements with a unit of the OPPOSITE label are marked "
    "contaminated and excluded from both populations. Units sharing with the "
    "same label are counted once, the retained one chosen by sort order. No "
    "file is ever deleted and no corpus is modified."
)

EXCLUSION_POLICY = (
    "A unit is excluded from the evaluable population when its label is not "
    "positive or negative, when no observation was made (a blank field is not "
    "an absence), or when the duplicate audit marks it contaminated or "
    "duplicate. Excluded units stay in the inventory with a stated reason."
)

METRIC_POLICY = (
    "4TU supports activity-level candidate DENSITY separation only, reported as "
    "an AUC with a bootstrap interval. BAM supports per-(target, line) detection "
    "counts on a controlled specimen. Object-level, localisation, depth and "
    "classification metrics are gated in benchmark.gates and are not computed."
)

THRESHOLD_POLICY = (
    "Detector thresholds are NOT part of this benchmark and are never chosen "
    "against it. A detector arrives with its parameters already fixed, and any "
    "calibration happens on a separate split (see docs/ground-truth-benchmarks.md)."
)


@dataclass(frozen=True)
class ReadinessDimension:
    """One thing the benchmark either supports or does not."""
    name: str
    #: ready | partial | blocked -- schemas.dataset_report.Readiness values.
    readiness: str
    reason: str
    #: Never empty unless readiness is `ready`.
    missing: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"name": self.name, "readiness": self.readiness,
                "reason": self.reason, "missing": list(self.missing)}


@dataclass(frozen=True)
class BenchmarkDefinition:
    """
    Everything needed to reproduce an evaluation, and its identity.

    `version` is derived, never supplied: `content_hash` over the truth content
    plus the policies. Two runs that produce the same version scored the same
    ground truth under the same rules.
    """
    benchmark: str
    units: tuple[EvaluationUnit, ...]
    duplicate_policy: str = DUPLICATE_POLICY
    exclusion_policy: str = EXCLUSION_POLICY
    metric_policy: str = METRIC_POLICY
    threshold_policy: str = THRESHOLD_POLICY
    schema_version: str = SCHEMA_VERSION
    power: Optional[PowerAssessment] = None
    readiness: tuple[ReadinessDimension, ...] = field(default_factory=tuple)
    open_questions: tuple[dict, ...] = ()

    @property
    def content_hash(self) -> str:
        """
        A hash over the TRUTH, not over this object's formatting.

        Only the fields that change what was evaluated are included, sorted, so
        that reordering the inventory or reformatting a docstring does not
        invent a new benchmark version.
        """
        payload = {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "policies": [self.duplicate_policy, self.exclusion_policy,
                         self.metric_policy, self.threshold_policy],
            "units": sorted(
                [
                    {
                        "unit_id": u.unit_id,
                        "label": u.label.value,
                        "basis": u.evidence.basis.value,
                        "source": u.evidence.source,
                        "verified_by_subterra": u.evidence.verified_by_subterra,
                        "duplicate_status": u.duplicate_status.value,
                        "shares_with": sorted(u.shares_with),
                        "contributes": u.contributes_independent_evidence,
                    }
                    for u in self.units
                ],
                key=lambda d: d["unit_id"],
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    @property
    def version(self) -> str:
        return f"{self.schema_version}.{self.content_hash}"

    def as_dict(self) -> dict:
        return {
            "benchmark": self.benchmark,
            "version": self.version,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
            "counts": {
                "units": len(self.units),
                "by_label": label_counts(list(self.units)),
                "by_duplicate_status": duplicate_counts(list(self.units)),
                "independent_positives": len(independent_positives(list(self.units))),
                "independent_negatives": len(independent_negatives(list(self.units))),
            },
            "policies": {
                "duplicate": self.duplicate_policy,
                "exclusion": self.exclusion_policy,
                "metric": self.metric_policy,
                "threshold": self.threshold_policy,
            },
            "power": self.power.as_dict() if self.power else None,
            "readiness": [d.as_dict() for d in self.readiness],
            "open_questions": list(self.open_questions),
            "units": [u.as_dict() for u in sorted(self.units, key=lambda u: u.unit_id)],
        }


#: Above this, a corpus would only notice a near-perfect detector, which is no
#: use for choosing between candidate methods.
USELESS_ABOVE_AUC = 0.85


def _comparison_readiness(power: Optional[PowerAssessment]) -> str:
    if power is None or power.smallest_detectable_auc is None:
        return "blocked"
    if power.adequate:
        return "ready"
    return "partial" if power.smallest_detectable_auc <= USELESS_ABOVE_AUC else "blocked"


def assess_readiness(units: list[EvaluationUnit],
                     power: Optional[PowerAssessment],
                     duplicate_audit_complete: bool) -> tuple[ReadinessDimension, ...]:
    """
    What this benchmark can currently answer, dimension by dimension.

    Every non-ready dimension names what is missing. That invariant is held
    across this platform for the same reason it matters here: a limitation
    nobody can act on is indistinguishable from a complaint.
    """
    positives = independent_positives(units)
    negatives = independent_negatives(units)
    contaminated = [u for u in units if u.duplicate_status.value == "contaminated"]
    unknown = [u for u in units if u.label is TruthLabel.UNKNOWN]

    dimensions = [
        ReadinessDimension(
            name="positive evidence",
            readiness="ready" if positives else "blocked",
            reason=f"{len(positives)} independent unit(s) with an established target",
            missing=() if positives else ("a unit with an independently established target",),
        ),
        ReadinessDimension(
            name="negative evidence",
            readiness=("ready" if len(negatives) >= 12
                       else "partial" if negatives else "blocked"),
            reason=(f"{len(negatives)} independent attested-empty unit(s); "
                    f"{len(unknown)} unit(s) are UNKNOWN and are not counted as absences"),
            missing=() if len(negatives) >= 12 else (
                f"more independently attested-empty units -- {max(0, 12 - len(negatives))} "
                f"further would allow a clearly useful detector (AUC 0.70) to be "
                f"distinguished from chance",),
        ),
        ReadinessDimension(
            name="duplicate audit",
            readiness="ready" if duplicate_audit_complete else "blocked",
            reason=("every unit's measurements were compared by checksum"
                    if duplicate_audit_complete else "no checksum audit has been run"),
            missing=() if duplicate_audit_complete else ("a corpus checksum audit",),
        ),
        ReadinessDimension(
            name="independent units",
            readiness="partial" if contaminated else (
                "ready" if positives and negatives else "blocked"),
            reason=(f"{len(contaminated)} unit(s) share measurements with a unit of the "
                    f"opposite label and are excluded from both populations"
                    if contaminated else
                    f"{len(positives) + len(negatives)} unit(s) contribute independent evidence"),
            # A contaminated unit needs replacement evidence; an EMPTY
            # population needs evidence of that kind to exist at all. Deriving
            # `missing` only from contamination left a corpus with no negatives
            # blocked with nothing to act on -- the one failure every assessment
            # in this platform is built to avoid.
            missing=tuple(
                f"replacement evidence for {u.unit_id}, which shares data with "
                f"{', '.join(u.shares_with)}" for u in contaminated
            ) or tuple(
                f"at least one independent {kind} unit"
                for kind, group in (("positive", positives), ("negative", negatives))
                if not group
            ),
        ),
        ReadinessDimension(
            name="localisation truth",
            readiness=("partial" if any(u.target.footprint_known for u in positives)
                       else "blocked"),
            reason=("footprints are published for the controlled specimen only; the "
                    "real-world corpus withholds coordinates"),
            missing=("trench coordinates, withheld by the publisher to preserve "
                     "utility-location confidentiality",),
        ),
        ReadinessDimension(
            name="depth truth",
            readiness="blocked",
            reason="no unit publishes a depth that survives its own reference-surface question",
            missing=("an unambiguous depth reference surface from the publisher",),
        ),
        ReadinessDimension(
            name="detection evaluation",
            readiness="partial" if positives and negatives else "blocked",
            reason=("candidate density can be compared between occupied and empty "
                    "ground, at activity level only"),
            missing=("a false-alarm RATE, which needs a larger attested-empty population",),
        ),
        ReadinessDimension(
            name="detector comparison",
            # Three bands, because "can distinguish something" and "can
            # distinguish something worth caring about" are different claims.
            # A corpus that resolves only AUC >= 0.85 would notice a detector
            # that is nearly perfect and nothing short of it, which is not a
            # partial capability -- for comparing candidate methods it is none.
            readiness=_comparison_readiness(power),
            reason=(
                f"the smallest improvement this corpus could distinguish from chance is "
                f"AUC {power.smallest_detectable_auc:.3f}"
                if power and power.smallest_detectable_auc is not None
                else "no improvement of any size could be distinguished at this size"),
            missing=() if (power and power.adequate) else (
                "more independent negatives; see the power assessment for how many "
                "each target improvement would need",),
        ),
    ]
    return tuple(dimensions)


def build(benchmark: str, units: list[EvaluationUnit],
          duplicate_audit_complete: bool = True,
          open_questions: tuple[dict, ...] = ()) -> BenchmarkDefinition:
    """Assemble a definition. Counts only -- nothing here scores a detector."""
    power = assess_power(
        benchmark,
        n_positive=len(independent_positives(units)),
        n_negative=len(independent_negatives(units)),
    )
    return BenchmarkDefinition(
        benchmark=benchmark,
        units=tuple(units),
        power=power,
        readiness=assess_readiness(units, power, duplicate_audit_complete),
        open_questions=open_questions,
    )


#: An external dependency has been RECORDED, not requested. The repository holds
#: no correspondence with any dataset author, so claiming a request was sent
#: would be inventing a fact about the outside world -- and inventing a reply
#: would be worse. `OUTSTANDING` means exactly "somebody must go and ask".
REQUEST_OUTSTANDING = "OUTSTANDING -- no request recorded in this repository"


def _questions(source) -> tuple[dict, ...]:
    """
    Open questions as data, with who must answer them.

    `benchmark.gates` already carried these with a `resolution_route`; this is
    the same content projected so a report or a UI can show what is blocked and
    what would unblock it, without a second tracker to fall out of step.
    """
    return tuple(
        {
            "id": q.id,
            "statement": q.statement,
            "blocks": q.blocks,
            "resolution_route": q.resolution_route,
            "status": q.status,
            "request_status": REQUEST_OUTSTANDING,
        }
        for q in source if q.status != gates.RESOLVED
    )


#: Where `scripts/build_benchmark_definition.py` writes its output.
DEFINITION_ARTIFACT = "artifacts/benchmark/definition.json"


def current_version(benchmark: str = "4tu-nl-utility") -> Optional[str]:
    """
    The version of the built definition, or None if none has been built.

    Read from the artifact rather than recomputed, because recomputing would
    hash the corpus on every call and -- worse -- could report a version that
    no scoring run was ever performed under. None is a legitimate answer and
    consumers render it as "unrecorded", not as a version of zero.
    """
    from pathlib import Path

    path = Path(DEFINITION_ARTIFACT)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        entry = payload.get("benchmarks", {}).get(benchmark, {})
        return entry.get("version")
    except Exception:  # noqa: BLE001 -- an unreadable artifact is "not built"
        return None


def fourtu_open_questions() -> tuple[dict, ...]:
    return _questions(gates.FOURTU_OPEN_QUESTIONS)


def bam_open_questions() -> tuple[dict, ...]:
    return _questions(gates.OPEN_QUESTIONS)
