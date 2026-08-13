"""
Duplicate evaluation units, and what they do to a benchmark score.

WHY THIS MATTERS HERE. The 4TU score compares candidate density between
activities whose trench found utilities and activities whose trench was
attested empty, and it rests on SEVEN negatives. Auditing the corpus found that
one of those seven -- activity 09.7 -- shares a byte-identical radargram with
09.6, which is a positive. Five further activity pairs are duplicated in full.
`artifacts/4tu/leakage.json` records the measurement.

These tests hold the audit's logic, not its result: they run on small synthetic
manifests so they state the rule exactly, and a separate test asserts the
committed artifact still reflects a real corpus scan.
"""
import json
from pathlib import Path

import pytest

from benchmark.leakage import find_duplicates, retained_files


def manifest(**units) -> dict[str, dict[str, str]]:
    return dict(units)


# ---------------------------------------------------------------------------
# finding duplicates
# ---------------------------------------------------------------------------

def test_a_corpus_with_no_repeats_is_clean():
    report = find_duplicates(manifest(a={"1.sgy": "h1"}, b={"2.sgy": "h2"}))
    assert report.clean
    assert report.n_files == 2
    assert report.n_unique_checksums == 2
    assert not report.affected_units


def test_two_units_sharing_a_file_are_not_independent():
    report = find_duplicates(manifest(a={"1.sgy": "same"}, b={"2.sgy": "same"}))
    assert not report.clean
    assert len(report.cross_unit_groups) == 1
    assert report.cross_unit_groups[0].units == ("a", "b")


def test_repetition_inside_one_unit_is_redundancy_not_leakage():
    """
    A unit holding the same file twice is a catalogue problem. It does not make
    two evaluation units one, which is the thing that damages a score.
    """
    report = find_duplicates(manifest(a={"1.sgy": "same", "copy.sgy": "same"}))
    assert report.clean
    assert not report.cross_unit_groups


def test_a_unit_whose_every_file_belongs_elsewhere_is_fully_duplicated():
    report = find_duplicates(manifest(
        a={"1.sgy": "h1", "2.sgy": "h2"},
        b={"1.sgy": "h1", "2.sgy": "h2"}))
    assert {u.unit_id for u in report.fully_duplicated_units} == {"a", "b"}
    assert all(u.shared_fraction == 1.0 for u in report.fully_duplicated_units)


def test_partial_overlap_is_reported_with_its_fraction():
    report = find_duplicates(manifest(
        a={"1.sgy": "shared", "2.sgy": "own"},
        b={"1.sgy": "shared"}))
    a = next(u for u in report.units if u.unit_id == "a")
    assert a.n_shared == 1 and a.n_files == 2
    assert a.shared_fraction == 0.5
    assert not a.fully_duplicated
    assert a.shares_with == ("b",)


# ---------------------------------------------------------------------------
# the assignment rule
# ---------------------------------------------------------------------------

def test_each_shared_measurement_is_owned_by_exactly_one_unit():
    m = manifest(b={"1.sgy": "same"}, a={"2.sgy": "same"})
    kept = retained_files(m, find_duplicates(m))
    owners = [unit for unit, files in kept.items() if files]
    assert owners == ["a"], "sort order decides, so the choice cannot be steered by data"


def test_a_fully_duplicated_unit_retains_nothing():
    m = manifest(a={"1.sgy": "h"}, b={"1.sgy": "h"})
    kept = retained_files(m, find_duplicates(m))
    assert kept["a"] == ("1.sgy",)
    assert kept["b"] == ()


def test_a_unit_keeps_the_files_only_it_has():
    m = manifest(a={"shared.sgy": "s"}, b={"shared.sgy": "s", "own.sgy": "o"})
    kept = retained_files(m, find_duplicates(m))
    assert kept["b"] == ("own.sgy",)


def test_the_assignment_is_reproducible():
    m = manifest(a={"1.sgy": "h"}, b={"1.sgy": "h"}, c={"1.sgy": "h"})
    first = retained_files(m, find_duplicates(m))
    second = retained_files(m, find_duplicates(m))
    assert first == second


def test_the_report_states_that_it_finds_exact_duplicates_only():
    """
    A clean report is not evidence that units are independent -- only that they
    are not byte-identical. Overclaiming here would be the exact error the audit
    exists to prevent.
    """
    payload = find_duplicates(manifest(a={"1.sgy": "h"})).as_dict()
    assert "near-duplicates are not detectable" in payload["detects"]
    assert "independent of the data" in payload["assignment_rule"]


# ---------------------------------------------------------------------------
# the measured 4TU result
# ---------------------------------------------------------------------------

ARTIFACT = Path("artifacts/4tu/leakage.json")

#: `artifacts/` is gitignored and regenerable, so "not generated yet" is a
#: legitimate state rather than a failure -- the same convention
#: `tests/test_4tu_benchmark.py` uses for the characterisation artifact.
#: Regenerate with `python scripts/audit_benchmark_leakage.py`.
NEEDS_ARTIFACT = pytest.mark.skipif(
    not ARTIFACT.exists(),
    reason="4TU leakage artifact not present; run scripts/audit_benchmark_leakage.py",
)


@NEEDS_ARTIFACT
def test_the_committed_4tu_audit_records_a_real_corpus_scan():
    payload = json.loads(ARTIFACT.read_text())
    leakage = payload["leakage"]
    assert leakage["n_files"] == 759
    assert leakage["n_unique_checksums"] == 721
    assert leakage["n_cross_unit_groups"] == 34
    assert not leakage["clean"]


@NEEDS_ARTIFACT
def test_one_of_the_seven_negatives_shares_data_with_a_positive():
    """
    The finding that matters. With seven negatives, one contaminated unit is
    14% of the population the separation AUC rests on.
    """
    payload = json.loads(ARTIFACT.read_text())
    assert payload["negatives_sharing_data_with_another_activity"] == ["09.7"]


@NEEDS_ARTIFACT
def test_deduplication_drops_the_fully_duplicated_activities():
    payload = json.loads(ARTIFACT.read_text())
    assert payload["published"]["n_activities_scored"] == 125
    assert payload["deduplicated"]["n_activities_scored"] == 121
    assert len(payload["deduplicated"]["activities_dropped"]) == 4


@NEEDS_ARTIFACT
def test_removing_the_duplicates_does_not_rescue_the_score():
    """
    The honest outcome: the leakage is real, and it is not the explanation. Both
    intervals span chance, so neither supports a claim of skill -- nor a claim
    of below-chance performance.
    """
    payload = json.loads(ARTIFACT.read_text())
    published = payload["published"]["separation"]
    deduped = payload["deduplicated"]["separation"]
    assert published["contains_chance"] is True
    assert deduped["contains_chance"] is True
    assert abs(deduped["auc"] - published["auc"]) < 0.05


@NEEDS_ARTIFACT
def test_the_corpus_is_never_modified_by_the_audit():
    payload = json.loads(ARTIFACT.read_text())
    assert payload["corpus_unmodified"] is True
