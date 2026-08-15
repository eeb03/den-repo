"""
What the benchmarks actually know, in one vocabulary.

WHY THIS EXISTS. Both benchmarks already model their own truth honestly, and
neither is replaced here. 4TU separates a trench count of zero (`attested_zero`)
from a blank field (`unrecorded`); BAM separates transcribed target geometry from
a fabricator's attestation that a specimen is empty. What did not exist was a
COMMON way to say what those mean, so nothing could ask the question this stage
exists to answer: how much independent evidence does Subterra actually hold?

THE RULE THIS MODULE EXISTS TO ENFORCE. `UNKNOWN` is not `NEGATIVE`. A blank
field, an unsurveyed area, or a trench nobody dug says nothing about what is in
the ground. Treating it as absence would manufacture negative evidence out of
missing evidence -- which is the cheapest possible way to make a benchmark look
adequate, and the reason this file is structured to make it impossible rather
than merely discouraged: `TruthLabel.UNKNOWN` has no path to `NEGATIVE`, and
`independent_negatives()` counts only labels whose evidence says a real
observation was made.

NOTHING HERE READS A DETECTOR. Every label is built from a published truth
source. There is no import of `interpretation`, `preprocessing` or any model in
this module, and `tests/test_ground_truth.py` asserts that by inspecting the
module's imports -- because "the detector found nothing here" becoming "this
place is empty" is the single most damaging thing a benchmark can do.

VERIFIED MEANS SUBTERRA CHECKED IT. Not that the source was confident. Every
label in this repository is currently `verified_by_subterra=False`, because
Subterra has excavated nothing and fabricated nothing. That field exists to stop
somebody later reading "published by a university" as "independently confirmed".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TruthLabel(str, Enum):
    """
    What is known about the presence of a target in one evaluation unit.

    POSITIVE and NEGATIVE are the only labels that carry evaluative weight.
    The rest exist so that a unit which cannot support a binary judgement is
    excluded honestly rather than silently rounded into one that can.
    """
    #: A target was independently established to be present.
    POSITIVE = "positive"
    #: An absence was independently established -- somebody looked and found
    #: nothing. NOT "no detector response" and NOT "no record".
    NEGATIVE = "negative"
    #: Insufficient evidence to say either way. The default for missing data.
    UNKNOWN = "unknown"
    #: Evidence exists but cannot support a binary label.
    AMBIGUOUS = "ambiguous"
    #: Unsuitable for evaluation for a stated reason.
    EXCLUDED = "excluded"


#: Labels that may contribute to a detection metric. Deliberately a frozen set
#: rather than a test on the enum, so adding a label cannot silently widen it.
EVALUABLE_LABELS = frozenset({TruthLabel.POSITIVE, TruthLabel.NEGATIVE})


class EvidenceBasis(str, Enum):
    """
    How the label was established. Not how confident anybody is.

    These are kinds of observation, and they are not interchangeable: a trench
    excavation is a direct physical check of a small volume, while a
    publication transcription is somebody reading a number out of a paper.
    """
    #: A trial trench was excavated and its contents recorded (4TU).
    TRENCH_EXCAVATION = "trench_excavation"
    #: The specimen's fabricator states what was cast into it (BAM Pk050).
    FABRICATION_RECORD = "fabrication_record"
    #: Geometry read out of a publication by hand (BAM Pk266 targets).
    PUBLICATION_TRANSCRIPTION = "publication_transcription"
    #: The source published a field and left it blank.
    NOT_RECORDED = "not_recorded"


class DuplicateStatus(str, Enum):
    """
    Whether a unit is its own evidence.

    CONTAMINATED is the state Stage 13 found: 4TU activity 09.7 is attested
    empty and shares a byte-identical radargram with 09.6, which is positive.
    The same measurements cannot be evidence both that something is there and
    that nothing is. Such a unit is not "a slightly weaker negative" -- it is
    not usable as either, and it is excluded from both counts.
    """
    INDEPENDENT = "independent"
    #: Byte-identical to another unit carrying the SAME label. Counted once.
    DUPLICATE_OF = "duplicate_of"
    #: Shares measurements with a unit carrying the OPPOSITE label.
    CONTAMINATED = "contaminated"
    #: Not audited.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LabelEvidence:
    """
    Why a label is what it is, in dimensions rather than in a score.

    THERE IS NO CONFIDENCE NUMBER HERE, deliberately. "confidence = 0.92" with
    no calibration method behind it is a number that looks like a measurement
    and is not one. These fields say what a reader would need to judge the
    label themselves, and each can be checked.
    """
    basis: EvidenceBasis
    #: The document, file or record a reader could go and consult.
    source: str
    #: Who established it. A publisher, a fabricator, a survey operator.
    established_by: str
    #: What ground the evidence actually covers -- rarely the whole survey.
    coverage: str
    #: Was the evidence produced without reference to Subterra? Published
    #: corpora are; anything Subterra derived would not be.
    independent_of_subterra: bool
    #: Has SUBTERRA checked it? Not "does the source sound reliable".
    verified_by_subterra: bool = False
    #: What remains unresolved even granting the evidence.
    uncertainty: str = ""
    established_at: Optional[str] = None

    @property
    def is_an_observation(self) -> bool:
        """
        Did somebody actually look?

        NOT_RECORDED is the absence of an observation, and this is the property
        that stops it from ever being counted as one.
        """
        return self.basis != EvidenceBasis.NOT_RECORDED


@dataclass(frozen=True)
class TargetInformation:
    """
    What is known about the targets in a POSITIVE unit.

    Every field is optional because most are genuinely unknown, and a benchmark
    can evaluate DETECTION without any of them. Localisation and depth truth
    are separate capabilities (see `benchmark.gates`), and their absence must
    block those metrics rather than produce a guess.
    """
    count: Optional[int] = None
    #: Grid nodes or trace ranges, where a source publishes them. Never derived
    #: from a coarse verbal description.
    footprint_known: bool = False
    location_known: bool = False
    depth_known: bool = False
    class_known: bool = False
    #: Free-text kinds as the source states them, for reporting only.
    described_as: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationUnit:
    """
    One thing the benchmark can score, and everything known about it.

    `unit_id` is the source's own identifier -- a 4TU LocationID, a BAM
    specimen -- so that any claim here can be traced back to a published row.
    """
    unit_id: str
    benchmark: str
    label: TruthLabel
    evidence: LabelEvidence
    duplicate_status: DuplicateStatus = DuplicateStatus.UNKNOWN
    #: Which units this one shares measurements with, if any.
    shares_with: tuple[str, ...] = ()
    target: TargetInformation = field(default_factory=TargetInformation)
    #: Set when the unit is EXCLUDED, or when a duplicate/contamination rule
    #: removes it from the evaluable population. Never empty in those states.
    exclusion_reason: str = ""

    @property
    def contributes_independent_evidence(self) -> bool:
        """
        May this unit count toward a metric, once and on its own?

        Four conditions, each of which has a failure it prevents: the label must
        be evaluable (no UNKNOWN-as-negative), somebody must actually have
        looked (no blank field as absence), the unit must be independent (no
        duplicate counted twice), and it must not be contaminated (no unit
        serving as evidence for both answers).
        """
        return (
            self.label in EVALUABLE_LABELS
            and self.evidence.is_an_observation
            and self.duplicate_status is DuplicateStatus.INDEPENDENT
        )

    def as_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "benchmark": self.benchmark,
            "label": self.label.value,
            "duplicate_status": self.duplicate_status.value,
            "shares_with": list(self.shares_with),
            "contributes_independent_evidence": self.contributes_independent_evidence,
            "exclusion_reason": self.exclusion_reason,
            "evidence": {
                "basis": self.evidence.basis.value,
                "source": self.evidence.source,
                "established_by": self.evidence.established_by,
                "coverage": self.evidence.coverage,
                "independent_of_subterra": self.evidence.independent_of_subterra,
                "verified_by_subterra": self.evidence.verified_by_subterra,
                "uncertainty": self.evidence.uncertainty,
            },
            "target": {
                "count": self.target.count,
                "footprint_known": self.target.footprint_known,
                "location_known": self.target.location_known,
                "depth_known": self.target.depth_known,
                "class_known": self.target.class_known,
                "described_as": list(self.target.described_as),
            },
        }


# ---------------------------------------------------------------------------
# building units from the published truth sources
# ---------------------------------------------------------------------------

FOURTU_SOURCE = "4TU Metadata.csv, field 'Amount of utilities'"
FOURTU_ESTABLISHED_BY = "the corpus publisher (trial-trench excavation records)"
FOURTU_COVERAGE = (
    "the trial trench only -- a small excavation inside a much larger surveyed "
    "area, so a utility outside the trench is absent from the truth and present "
    "in the ground"
)


def fourtu_units(truth) -> list[EvaluationUnit]:
    """
    One evaluation unit per 4TU activity.

    THE ACTIVITY IS THE UNIT, not the radargram. A single activity holds many
    radargrams of one trench, and the truth is stated once for the trench: a
    per-radargram label would be the same observation counted a dozen times.

    A blank count becomes UNKNOWN with basis NOT_RECORDED. It never becomes
    NEGATIVE, and `is_an_observation` is what keeps it out of the negative
    population even if somebody later relabels it by hand.
    """
    units = []
    for location_id in sorted(truth.activities):
        activity = truth.activities[location_id]
        if activity.unrecorded:
            label = TruthLabel.UNKNOWN
            basis = EvidenceBasis.NOT_RECORDED
            uncertainty = "the publisher left the count blank; nobody has said what is there"
        elif activity.attested_zero:
            label = TruthLabel.NEGATIVE
            basis = EvidenceBasis.TRENCH_EXCAVATION
            uncertainty = (
                "the trench found nothing; ground outside the trench is unobserved"
            )
        else:
            label = TruthLabel.POSITIVE
            basis = EvidenceBasis.TRENCH_EXCAVATION
            uncertainty = (
                "the count is what the trench found; utilities outside it are not counted"
            )

        units.append(EvaluationUnit(
            unit_id=location_id,
            benchmark="4tu-nl-utility",
            label=label,
            evidence=LabelEvidence(
                basis=basis, source=FOURTU_SOURCE,
                established_by=FOURTU_ESTABLISHED_BY, coverage=FOURTU_COVERAGE,
                independent_of_subterra=True, verified_by_subterra=False,
                uncertainty=uncertainty),
            target=TargetInformation(
                count=activity.n_utilities,
                # The publisher withheld geospatial information deliberately.
                footprint_known=False, location_known=False, depth_known=False,
                class_known=bool(activity.disciplines),
                described_as=activity.disciplines),
        ))
    return units


def bam_units(targets, control, specimen_id: str = "Pk266") -> list[EvaluationUnit]:
    """
    Two evaluation units for BAM: the target specimen and the control.

    THE SPECIMEN IS THE UNIT. Pk266's 161 survey lines are 161 passes over the
    SAME four ducts -- one physical arrangement, observed repeatedly. Counting
    them as 161 independent samples would multiply one fabrication record into
    a population, which is precisely the inflation this stage exists to stop.
    Lines remain the unit that DETECTION SCORING iterates over; they are not
    units of independent ground-truth evidence.
    """
    return [
        EvaluationUnit(
            unit_id=specimen_id,
            benchmark="bam-concrete-gpr",
            label=TruthLabel.POSITIVE,
            evidence=LabelEvidence(
                basis=EvidenceBasis.PUBLICATION_TRANSCRIPTION,
                source="benchmark/bam_pk266_targets.json, transcribed from publications",
                established_by="the specimen's fabricator, via published tables",
                coverage="the fabricated specimen",
                independent_of_subterra=True, verified_by_subterra=False,
                uncertainty=("the repository ships no geometry file; the numbers were "
                             "transcribed by hand and the absolute origin is unverified")),
            duplicate_status=DuplicateStatus.INDEPENDENT,
            target=TargetInformation(
                count=len(targets), footprint_known=True, location_known=False,
                depth_known=False, class_known=True,
                described_as=tuple(sorted({t.target_type for t in targets}))),
        ),
        EvaluationUnit(
            unit_id=control.specimen_id,
            benchmark="bam-concrete-gpr",
            label=TruthLabel.NEGATIVE if control.attested else TruthLabel.UNKNOWN,
            evidence=LabelEvidence(
                basis=EvidenceBasis.FABRICATION_RECORD if control.attested
                else EvidenceBasis.NOT_RECORDED,
                source="benchmark/bam_pk266_targets.json, specimen attestation",
                established_by="the data repository, stating what was cast in",
                coverage="the fabricated specimen",
                independent_of_subterra=True, verified_by_subterra=False,
                uncertainty=control.caveat),
            duplicate_status=DuplicateStatus.INDEPENDENT,
            target=TargetInformation(count=0),
        ),
    ]


# ---------------------------------------------------------------------------
# applying the duplicate audit
# ---------------------------------------------------------------------------

def apply_duplicate_audit(units: list[EvaluationUnit],
                          report,
                          owner_of_unit: Optional[dict[str, str]] = None,
                          ) -> list[EvaluationUnit]:
    """
    Fold a `benchmark.leakage` report into the units' independence.

    THE CONTAMINATION RULE. If two units share measurements and carry DIFFERENT
    labels, both are marked CONTAMINATED: the same bytes cannot be evidence that
    something is present and that nothing is. Neither is downgraded to a weaker
    version of itself -- they are removed from the evaluable population, because
    a benchmark that half-counts contradictory evidence is worse than one that
    admits it has less.

    THE DUPLICATE RULE. Units sharing measurements with the SAME label are the
    same observation recorded twice. One retains the evidence -- chosen by sort
    order, which is arbitrary but cannot be steered by the data -- and the rest
    are DUPLICATE_OF, present in the inventory and absent from the counts.

    Units the audit did not see keep whatever status they already had.
    """
    by_id = {u.unit_id: u for u in units}
    affected = {u.unit_id: u for u in report.affected_units}
    owner_of_unit = owner_of_unit or {}

    out = []
    for unit in units:
        leak = affected.get(unit.unit_id)
        if leak is None:
            status = (unit.duplicate_status
                      if unit.duplicate_status is not DuplicateStatus.UNKNOWN
                      else DuplicateStatus.INDEPENDENT)
            out.append(EvaluationUnit(**{**unit.__dict__, "duplicate_status": status}))
            continue

        partners = tuple(leak.shares_with)
        opposite = [p for p in partners
                    if p in by_id and by_id[p].label != unit.label
                    and {by_id[p].label, unit.label} <= EVALUABLE_LABELS]

        if opposite:
            status = DuplicateStatus.CONTAMINATED
            reason = (
                f"shares byte-identical measurements with {', '.join(opposite)}, "
                f"which carry the opposite label; the same data cannot be evidence "
                f"for both answers"
            )
        elif owner_of_unit.get(unit.unit_id, unit.unit_id) != unit.unit_id:
            status = DuplicateStatus.DUPLICATE_OF
            reason = (
                f"the same measurements are already counted under "
                f"{owner_of_unit[unit.unit_id]}"
            )
        else:
            status = DuplicateStatus.INDEPENDENT
            reason = ""

        out.append(EvaluationUnit(**{
            **unit.__dict__,
            "duplicate_status": status,
            "shares_with": partners,
            "exclusion_reason": reason,
        }))
    return out


# ---------------------------------------------------------------------------
# counting
# ---------------------------------------------------------------------------

def evaluable(units: list[EvaluationUnit]) -> list[EvaluationUnit]:
    return [u for u in units if u.contributes_independent_evidence]


def independent_positives(units: list[EvaluationUnit]) -> list[EvaluationUnit]:
    return [u for u in evaluable(units) if u.label is TruthLabel.POSITIVE]


def independent_negatives(units: list[EvaluationUnit]) -> list[EvaluationUnit]:
    """
    The population every claim about false alarms rests on.

    This is the number Stage 14 exists to establish honestly, and the reason
    `is_an_observation` is checked: an UNKNOWN unit relabelled by hand would
    still fail here, because nobody dug the trench.
    """
    return [u for u in evaluable(units) if u.label is TruthLabel.NEGATIVE]


def label_counts(units: list[EvaluationUnit]) -> dict[str, int]:
    out: dict[str, int] = {}
    for unit in units:
        out[unit.label.value] = out.get(unit.label.value, 0) + 1
    return dict(sorted(out.items()))


def duplicate_counts(units: list[EvaluationUnit]) -> dict[str, int]:
    out: dict[str, int] = {}
    for unit in units:
        out[unit.duplicate_status.value] = out.get(unit.duplicate_status.value, 0) + 1
    return dict(sorted(out.items()))
