"""
Statistical power, and the benchmark version that pins what was measured.

WHAT THESE PROTECT. Stage 14's central claim is a number: this corpus could only
distinguish a detector of AUC 0.74 or better from chance, so a moderate genuine
improvement would go unrecognised. That claim decides whether detector work is
worth starting, so the arithmetic behind it is tested against closed-form
identities and against the resampling it is meant to approximate -- not merely
executed.

The version tests protect a different failure: ground truth changing without the
benchmark's identity changing, which would make two incomparable numbers look
comparable.
"""
import json
from pathlib import Path

import pytest

from benchmark.definition import (
    USELESS_ABOVE_AUC, BenchmarkDefinition, assess_readiness, build,
)
from benchmark.ground_truth import (
    DuplicateStatus, EvaluationUnit, EvidenceBasis, LabelEvidence, TruthLabel,
)
from benchmark.power import (
    DEFAULT_ALPHA, DEFAULT_POWER, assess, auc_standard_error, detectable_auc,
    negatives_required, _z,
)


def unit(unit_id, label, basis=EvidenceBasis.TRENCH_EXCAVATION) -> EvaluationUnit:
    return EvaluationUnit(
        unit_id=unit_id, benchmark="test", label=label,
        evidence=LabelEvidence(
            basis=basis, source="s", established_by="e", coverage="c",
            independent_of_subterra=True),
        duplicate_status=DuplicateStatus.INDEPENDENT)


def population(n_pos: int, n_neg: int) -> list[EvaluationUnit]:
    return ([unit(f"p{i}", TruthLabel.POSITIVE) for i in range(n_pos)]
            + [unit(f"n{i}", TruthLabel.NEGATIVE) for i in range(n_neg)])


# ---------------------------------------------------------------------------
# the arithmetic
# ---------------------------------------------------------------------------

def test_the_normal_quantile_matches_known_values():
    assert _z(0.975) == pytest.approx(1.959964, abs=1e-5)
    assert _z(0.80) == pytest.approx(0.841621, abs=1e-5)
    assert _z(0.5) == pytest.approx(0.0, abs=1e-9)


def test_the_standard_error_shrinks_as_the_smaller_group_grows():
    """
    The property that makes this the right tool for a 112-vs-7 corpus:
    the error is dominated by the smaller group, so adding positives to a
    corpus starved of negatives buys almost nothing.
    """
    adding_negatives = (auc_standard_error(0.7, 112, 7)
                        - auc_standard_error(0.7, 112, 14))
    adding_positives = (auc_standard_error(0.7, 112, 7)
                        - auc_standard_error(0.7, 224, 7))
    assert adding_negatives > adding_positives > 0


def test_an_empty_group_has_no_standard_error():
    """None, not zero. A zero error would claim perfect precision from nothing."""
    assert auc_standard_error(0.7, 0, 7) is None
    assert auc_standard_error(0.7, 112, 0) is None


def test_more_negatives_lower_the_smallest_detectable_improvement():
    assert detectable_auc(112, 50) < detectable_auc(112, 7)


def test_a_single_unit_per_group_yields_no_estimate_at_all():
    """
    None, not a number.

    The Hanley-McNeil variance terms are multiplied by (n - 1), so a group of
    one contributes no variance and the formula reports a confidently tiny
    error from a single observation -- it called AUC 0.97 distinguishable from
    chance on BAM's two specimens. Refusing to estimate is the honest answer.
    """
    assert auc_standard_error(0.7, 1, 1) is None
    assert detectable_auc(1, 1) is None
    assert negatives_required(0.70, 1) is None


def test_negatives_required_rises_as_the_target_improvement_shrinks():
    """A subtler improvement needs more evidence, not less."""
    modest = negatives_required(0.60, 112)
    clear = negatives_required(0.70, 112)
    assert modest > clear > 0


def test_required_negatives_actually_achieve_the_target():
    """Round-trip: the recommended n must clear the threshold, and n-1 must not."""
    target, n_pos = 0.70, 112
    n = negatives_required(target, n_pos)
    threshold = _z(1 - DEFAULT_ALPHA / 2) + _z(DEFAULT_POWER)

    assert (target - 0.5) / auc_standard_error(target, n_pos, n) >= threshold
    assert (target - 0.5) / auc_standard_error(target, n_pos, n - 1) < threshold


# ---------------------------------------------------------------------------
# the measured verdict on the corpus actually held
# ---------------------------------------------------------------------------

def test_the_4tu_corpus_cannot_resolve_a_useful_detector():
    """
    The Stage 14 headline, as arithmetic.

    107 independent positives and 6 independent negatives survive the duplicate
    audit. That population could only distinguish a detector well above 0.70.
    """
    a = assess("4tu-nl-utility", n_positive=107, n_negative=6)
    assert a.smallest_detectable_auc > 0.70
    assert a.adequate is False


def test_the_shortfall_is_quantified_rather_than_asserted():
    a = assess("4tu-nl-utility", n_positive=107, n_negative=6)
    needed = a.negatives_required[0.70]
    assert needed is not None and needed > 6, "must say how many more are needed"


def test_removing_the_contaminated_negative_costs_resolving_power():
    """Excluding 09.7 is correct AND costly. Both are worth stating."""
    before = assess("4tu", 112, 7).smallest_detectable_auc
    after = assess("4tu", 107, 6).smallest_detectable_auc
    assert after > before


def test_the_method_and_its_caveat_travel_with_the_numbers():
    a = assess("4tu", 107, 6)
    assert "Hanley" in a.method
    assert "approximation" in a.caveat
    assert "independent" in a.caveat


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------

def test_a_corpus_that_resolves_only_a_near_perfect_detector_is_blocked():
    """
    Not "partial".

    A benchmark that would notice a detector at AUC 0.97 and nothing short of it
    has no ability to choose between candidate methods, which is what the
    dimension is about.
    """
    dims = {d.name: d for d in build("bam", population(1, 1)).readiness}
    assert dims["detector comparison"].readiness == "blocked"
    assert USELESS_ABOVE_AUC == 0.85


def test_a_sufficient_corpus_reports_ready():
    dims = {d.name: d for d in build("plenty", population(112, 60)).readiness}
    assert dims["detector comparison"].readiness == "ready"
    assert dims["negative evidence"].readiness == "ready"


def test_every_non_ready_dimension_names_what_is_missing():
    """The invariant this platform holds everywhere: a blocker must be actionable."""
    for units in (population(107, 6), population(1, 1), population(4, 0)):
        for d in build("b", units).readiness:
            if d.readiness != "ready":
                assert d.missing, f"{d.name} is {d.readiness} with nothing to act on"


def test_readiness_says_how_many_more_negatives_are_needed():
    dims = {d.name: d for d in build("4tu", population(107, 6)).readiness}
    assert any("further" in m for m in dims["negative evidence"].missing)


def test_unknown_units_are_reported_as_not_counted():
    units = population(10, 3) + [unit("x", TruthLabel.UNKNOWN,
                                      EvidenceBasis.NOT_RECORDED)]
    dims = {d.name: d for d in build("b", units).readiness}
    assert "not counted as absences" in dims["negative evidence"].reason


# ---------------------------------------------------------------------------
# versioning
# ---------------------------------------------------------------------------

def test_the_same_truth_produces_the_same_version():
    assert build("b", population(5, 5)).version == build("b", population(5, 5)).version


def test_changing_a_label_changes_the_version():
    before = build("b", population(5, 5)).version
    changed = population(5, 4) + [unit("n4", TruthLabel.UNKNOWN,
                                       EvidenceBasis.NOT_RECORDED)]
    assert build("b", changed).version != before


def test_changing_evidence_basis_changes_the_version():
    before = build("b", population(5, 5)).version
    swapped = population(5, 4) + [unit("n4", TruthLabel.NEGATIVE,
                                       EvidenceBasis.FABRICATION_RECORD)]
    assert build("b", swapped).version != before


def test_adding_a_unit_changes_the_version():
    assert build("b", population(5, 5)).version != build("b", population(5, 6)).version


def test_reordering_the_inventory_does_not_change_the_version():
    """Version tracks the truth, not the order it happened to be listed in."""
    units = population(5, 5)
    assert build("b", units).version == build("b", list(reversed(units))).version


def test_the_version_does_not_depend_on_any_detector_parameter():
    """
    A benchmark whose identity changed when the detector changed could not be
    used to compare detectors, which is its only purpose.
    """
    definition = build("b", population(5, 5))
    assert "threshold" not in definition.content_hash
    assert "not part of this benchmark" in definition.threshold_policy.lower()


# ---------------------------------------------------------------------------
# the committed artifact
# ---------------------------------------------------------------------------

ARTIFACT = Path("artifacts/benchmark/definition.json")
NEEDS_ARTIFACT = pytest.mark.skipif(
    not ARTIFACT.exists(),
    reason="benchmark definition not built; run scripts/build_benchmark_definition.py")


@NEEDS_ARTIFACT
def test_the_committed_definition_records_the_measured_population():
    payload = json.loads(ARTIFACT.read_text())["benchmarks"]["4tu-nl-utility"]
    counts = payload["counts"]
    assert counts["by_label"] == {"negative": 7, "positive": 112, "unknown": 6}
    assert counts["independent_positives"] == 107
    assert counts["independent_negatives"] == 6


@NEEDS_ARTIFACT
def test_the_committed_definition_excludes_both_contaminated_units():
    payload = json.loads(ARTIFACT.read_text())["benchmarks"]["4tu-nl-utility"]
    contaminated = {u["unit_id"] for u in payload["units"]
                    if u["duplicate_status"] == "contaminated"}
    assert contaminated == {"09.6", "09.7"}
    for u in payload["units"]:
        if u["unit_id"] in contaminated:
            assert u["contributes_independent_evidence"] is False
            assert u["exclusion_reason"]


@NEEDS_ARTIFACT
def test_the_bootstrap_agrees_with_the_analytic_standard_error():
    """
    A recommendation to go and collect more data should not rest on an
    approximation nobody checked.
    """
    payload = json.loads(ARTIFACT.read_text())
    bootstrap = payload["bootstrap_cross_check"]
    se = payload["benchmarks"]["4tu-nl-utility"]["power"]["se_at_chance"]
    assert bootstrap["half_width"] == pytest.approx(1.96 * se, rel=0.10)


@NEEDS_ARTIFACT
def test_the_definition_reads_no_detector_output():
    payload = json.loads(ARTIFACT.read_text())
    assert payload["reads_detector_output"] is False
    assert payload["corpus_unmodified"] is True


@NEEDS_ARTIFACT
def test_external_evidence_is_recorded_as_outstanding_not_requested():
    """
    The repository holds no correspondence with any dataset author. Claiming a
    request was sent would invent a fact about the outside world.
    """
    payload = json.loads(ARTIFACT.read_text())["benchmarks"]["4tu-nl-utility"]
    questions = {q["id"]: q for q in payload["open_questions"]}
    assert "attested-zero-population-is-small" in questions
    for q in questions.values():
        assert q["request_status"].startswith("OUTSTANDING")
        assert q["resolution_route"]
