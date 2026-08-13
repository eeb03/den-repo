"""
Ground truth: what may count as evidence, and what may never.

WHY THESE TESTS ARE THE POINT OF STAGE 14. A benchmark is the instrument every
future claim about the detector will be measured with. If it can be nudged --
an unknown quietly counted as an absence, one trench counted twice, a detector's
silence promoted to evidence of empty ground -- then every number downstream
inherits the nudge, and no later care recovers it. Each test below corresponds
to one specific way that could happen.

The costliest failure has a name here: 4TU activity 09.7 is attested empty and
shares a byte-identical radargram with 09.6, which is positive. Those same bytes
cannot be evidence both that something is present and that nothing is.
"""
import ast
from pathlib import Path

import pytest

from benchmark.ground_truth import (
    DuplicateStatus, EvaluationUnit, EvidenceBasis, LabelEvidence,
    TargetInformation, TruthLabel, apply_duplicate_audit, bam_units,
    duplicate_counts, evaluable, fourtu_units, independent_negatives,
    independent_positives, label_counts,
)
from benchmark.leakage import find_duplicates


def evidence(basis=EvidenceBasis.TRENCH_EXCAVATION, **kwargs) -> LabelEvidence:
    defaults = dict(
        source="a published record", established_by="the publisher",
        coverage="the trench", independent_of_subterra=True,
        verified_by_subterra=False)
    return LabelEvidence(basis=basis, **{**defaults, **kwargs})


def unit(unit_id="u1", label=TruthLabel.NEGATIVE,
         status=DuplicateStatus.INDEPENDENT, basis=EvidenceBasis.TRENCH_EXCAVATION,
         **kwargs) -> EvaluationUnit:
    return EvaluationUnit(
        unit_id=unit_id, benchmark="test", label=label,
        evidence=evidence(basis), duplicate_status=status, **kwargs)


# ---------------------------------------------------------------------------
# unknown is not negative -- the rule this module exists for
# ---------------------------------------------------------------------------

def test_unknown_never_counts_as_a_negative():
    units = [unit("a", TruthLabel.UNKNOWN, basis=EvidenceBasis.NOT_RECORDED)]
    assert independent_negatives(units) == []
    assert evaluable(units) == []


def test_a_hand_relabelled_unknown_still_fails_without_an_observation():
    """
    The protection is the EVIDENCE, not the label.

    Somebody editing a label to NEGATIVE while the basis stays `not_recorded`
    has not dug a trench, and the unit must still not count. This is what stops
    the vocabulary from being a formality.
    """
    forged = unit("a", TruthLabel.NEGATIVE, basis=EvidenceBasis.NOT_RECORDED)
    assert forged.evidence.is_an_observation is False
    assert forged.contributes_independent_evidence is False
    assert independent_negatives([forged]) == []


def test_an_observed_absence_does_count():
    assert len(independent_negatives([unit("a", TruthLabel.NEGATIVE)])) == 1


def test_ambiguous_and_excluded_carry_no_evaluative_weight():
    units = [unit("a", TruthLabel.AMBIGUOUS), unit("b", TruthLabel.EXCLUDED)]
    assert evaluable(units) == []


def test_the_evaluable_label_set_cannot_widen_by_accident():
    from benchmark.ground_truth import EVALUABLE_LABELS
    assert EVALUABLE_LABELS == frozenset({TruthLabel.POSITIVE, TruthLabel.NEGATIVE})


# ---------------------------------------------------------------------------
# no detector may create ground truth
# ---------------------------------------------------------------------------

def test_ground_truth_imports_nothing_that_could_detect_anything():
    """
    Structural, not stylistic.

    "The detector found nothing here" becoming "this place is empty" is the
    single most damaging thing a benchmark can do, and the cheapest way to
    prevent it is to keep the module unable to ask a detector anything. Checked
    by parsing the imports rather than by grep, so a name appearing in prose
    cannot fail it and a real import cannot hide from it.
    """
    tree = ast.parse(Path("benchmark/ground_truth.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = ("interpretation", "preprocessing", "training", "models",
                 "benchmark.detection", "api")
    for name in imported:
        assert not name.startswith(forbidden), \
            f"ground truth must not be able to consult {name}"


def test_no_truth_label_is_derived_from_a_candidate_count():
    """
    4TU labels come from the trench count, which is an excavation record.

    `target.count` carries what the trench found; nothing reads a detector.
    """
    from benchmark.fourtu_truth import load_truth

    units = fourtu_units(load_truth())
    for u in units:
        assert u.evidence.basis in (EvidenceBasis.TRENCH_EXCAVATION,
                                    EvidenceBasis.NOT_RECORDED)
        assert u.evidence.established_by.startswith("the corpus publisher")


# ---------------------------------------------------------------------------
# duplicates cannot inflate evidence
# ---------------------------------------------------------------------------

def test_contradictory_duplicates_disqualify_both_units():
    """
    The 09.6 / 09.7 case, in miniature.

    Neither becomes a weaker version of itself: a benchmark that half-counts
    contradictory evidence is worse than one that admits it holds less.
    """
    manifest = {"pos": {"a.sgy": "same"}, "neg": {"b.sgy": "same"}}
    units = [unit("pos", TruthLabel.POSITIVE), unit("neg", TruthLabel.NEGATIVE)]

    audited = apply_duplicate_audit(units, find_duplicates(manifest))

    assert all(u.duplicate_status is DuplicateStatus.CONTAMINATED for u in audited)
    assert evaluable(audited) == []
    for u in audited:
        assert u.exclusion_reason, "an excluded unit must say why"


def test_same_label_duplicates_are_counted_once():
    manifest = {"n1": {"a.sgy": "same"}, "n2": {"b.sgy": "same"}}
    units = [unit("n1", TruthLabel.NEGATIVE), unit("n2", TruthLabel.NEGATIVE)]

    audited = apply_duplicate_audit(units, find_duplicates(manifest),
                                    owner_of_unit={"n1": "n1", "n2": "n1"})
    assert len(independent_negatives(audited)) == 1


def test_an_unaudited_unit_is_not_silently_promoted():
    """A unit the audit never saw keeps a status, not a guess about one."""
    audited = apply_duplicate_audit(
        [unit("solo", TruthLabel.NEGATIVE, status=DuplicateStatus.UNKNOWN)],
        find_duplicates({"solo": {"a.sgy": "h"}}))
    assert audited[0].duplicate_status is DuplicateStatus.INDEPENDENT


def test_duplicate_status_is_reported_not_hidden():
    manifest = {"pos": {"a.sgy": "same"}, "neg": {"b.sgy": "same"}}
    audited = apply_duplicate_audit(
        [unit("pos", TruthLabel.POSITIVE), unit("neg", TruthLabel.NEGATIVE)],
        find_duplicates(manifest))
    assert duplicate_counts(audited)["contaminated"] == 2
    assert all(u.shares_with for u in audited)


# ---------------------------------------------------------------------------
# evidence provenance
# ---------------------------------------------------------------------------

def test_every_label_carries_a_traceable_basis():
    from benchmark.fourtu_truth import load_truth

    for u in fourtu_units(load_truth()):
        assert u.evidence.source
        assert u.evidence.established_by
        assert u.evidence.coverage

def test_nothing_claims_subterra_verified_it():
    """
    Subterra has excavated nothing and fabricated nothing.

    `verified_by_subterra` means Subterra checked -- not that the source sounds
    reliable. Every label currently held must say False.
    """
    from benchmark.fourtu_truth import load_truth

    for u in fourtu_units(load_truth()):
        assert u.evidence.verified_by_subterra is False


def test_coverage_states_the_trench_is_not_the_survey():
    from benchmark.fourtu_truth import load_truth

    sample = fourtu_units(load_truth())[0]
    assert "trench" in sample.evidence.coverage
    assert "larger surveyed area" in sample.evidence.coverage


def test_there_is_no_single_confidence_number():
    """
    Evidence dimensions, not a score.

    "confidence = 0.92" with no calibration behind it looks like a measurement
    and is not one.
    """
    assert "confidence" not in LabelEvidence.__dataclass_fields__


# ---------------------------------------------------------------------------
# nothing about targets is fabricated
# ---------------------------------------------------------------------------

def test_4tu_units_claim_no_location_footprint_or_depth():
    """The publisher withheld geospatial information deliberately."""
    from benchmark.fourtu_truth import load_truth

    for u in fourtu_units(load_truth()):
        assert u.target.location_known is False
        assert u.target.footprint_known is False
        assert u.target.depth_known is False


def test_target_information_defaults_to_knowing_nothing():
    t = TargetInformation()
    assert t.count is None
    assert not (t.footprint_known or t.location_known
                or t.depth_known or t.class_known)


# ---------------------------------------------------------------------------
# the real corpora
# ---------------------------------------------------------------------------

def test_the_4tu_inventory_matches_the_published_source():
    from benchmark.fourtu_truth import load_truth

    counts = label_counts(fourtu_units(load_truth()))
    assert counts == {"negative": 7, "positive": 112, "unknown": 6}


def test_the_six_blank_activities_are_unknown_not_negative():
    from benchmark.fourtu_truth import load_truth

    unknown = [u.unit_id for u in fourtu_units(load_truth())
               if u.label is TruthLabel.UNKNOWN]
    assert sorted(unknown) == ["010.1", "010.2", "010.3", "010.6", "010.8", "010.9"]


def test_the_activity_is_the_4tu_evaluation_unit():
    """
    Not the radargram.

    One activity holds many radargrams of one trench, and the truth is stated
    once for the trench. A per-radargram label would be the same observation
    counted a dozen times -- which is exactly the inflation Stage 13's audit of
    759 files against 721 checksums warned about.
    """
    from benchmark.fourtu_truth import load_truth

    units = fourtu_units(load_truth())
    assert len(units) == 125
    assert len({u.unit_id for u in units}) == 125


def test_bam_units_are_specimens_not_survey_lines():
    """
    Pk266's 161 lines are 161 passes over the SAME four ducts.

    Counting them as independent samples would multiply one fabrication record
    into a population.
    """
    class _Target:
        target_type = "duct"

    class _Control:
        specimen_id = "Pk050"
        attested = True
        caveat = "step back walls are real reflectors"

    units = bam_units([_Target()] * 4, _Control())
    assert len(units) == 2
    assert {u.unit_id for u in units} == {"Pk266", "Pk050"}
    assert units[0].target.count == 4


def test_an_unattested_control_is_unknown_not_negative():
    class _Control:
        specimen_id = "Pk050"
        attested = False
        caveat = ""

    control = bam_units([], _Control())[1]
    assert control.label is TruthLabel.UNKNOWN
    assert control.contributes_independent_evidence is False
