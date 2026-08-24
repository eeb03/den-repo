"""
Split-integrity tests for `training.segmentation.split_by_site`.

SYNTHETIC MULTI-SITE FIXTURES, deliberately -- the real held corpus has
exactly ONE real site with any usable label (see `training/segmentation.py`'s
own audit), which cannot exercise a genuine multi-site split at all. These
tests verify the SPLITTING CODE's correctness (does it assign what it says,
does it refuse ambiguity, does it never leak) using fixtures built
specifically to have several distinct "sites" -- never a claim about real
cross-site generalisation, which `assess_split_adequacy` (tested separately
below) is what actually gates that claim.
"""
from __future__ import annotations

import pytest

from schemas.segmentation import GPRTrainingExample, LabelLevel
from training.segmentation import assess_split_adequacy, split_by_site


def _example(site_id: str, dataset_id: str = "synthetic") -> GPRTrainingExample:
    return GPRTrainingExample(
        dataset_id=dataset_id, site_id=site_id, survey_id="s1", source_file="f.sgy",
        trace_range=(0, 1), sample_range=(0, 1), signal=[[0.0, 0.0], [0.0, 0.0]],
        mask=None, label_level=LabelLevel.D_EXISTENCE,
        preprocessing_version="test-fixture-v1",
    )


class TestSplitBySite:
    def test_assigns_split_by_site_membership(self):
        examples = [_example("A"), _example("B"), _example("C")]
        out = split_by_site(examples, train_sites={"A"}, validation_sites={"B"}, test_sites={"C"})
        assert [e.split for e in out] == ["train", "validation", "test"]

    def test_a_site_with_multiple_examples_stays_together(self):
        examples = [_example("A"), _example("A"), _example("B")]
        out = split_by_site(examples, train_sites={"A"}, validation_sites=set(), test_sites={"B"})
        assert [e.split for e in out] == ["train", "train", "test"]

    def test_an_unassigned_site_is_refused_not_defaulted(self):
        examples = [_example("A"), _example("UNKNOWN_SITE")]
        with pytest.raises(ValueError, match="not assigned"):
            split_by_site(examples, train_sites={"A"}, validation_sites=set(), test_sites=set())

    def test_overlapping_site_sets_are_refused(self):
        examples = [_example("A")]
        with pytest.raises(ValueError, match="not disjoint"):
            split_by_site(examples, train_sites={"A"}, validation_sites={"A"}, test_sites=set())

    def test_original_examples_are_not_mutated(self):
        """`split_by_site` must return copies -- the input list's own examples keep split=None."""
        examples = [_example("A")]
        out = split_by_site(examples, train_sites={"A"}, validation_sites=set(), test_sites=set())
        assert examples[0].split is None
        assert out[0].split == "train"

    def test_no_trace_level_leakage_is_possible_by_construction(self):
        """
        Every example from the SAME site must land in the SAME split --
        the split function has no code path that could put two examples
        sharing a site_id on both sides, since assignment is a single
        membership lookup per site, not per example.
        """
        examples = [_example("A") for _ in range(20)]
        out = split_by_site(examples, train_sites={"A"}, validation_sites=set(), test_sites=set())
        assert {e.split for e in out} == {"train"}


class TestSplitAdequacy:
    def test_at_least_two_sites_per_split_is_adequate(self):
        result = assess_split_adequacy({"A", "B"}, {"C", "D"}, {"E", "F"})
        assert result.adequate is True

    def test_a_single_site_in_any_split_is_inadequate(self):
        result = assess_split_adequacy({"A", "B"}, {"C", "D"}, {"E"})
        assert result.adequate is False
        assert "memorising the one site" in result.reason

    def test_reports_the_real_counts_not_a_summary_only(self):
        result = assess_split_adequacy({"A"}, set(), {"B"})
        assert result.n_train_sites == 1
        assert result.n_validation_sites == 0
        assert result.n_test_sites == 1

    def test_the_real_bam_corpus_is_correctly_flagged_inadequate(self):
        """
        The one live, real-data case this milestone actually has: 1 site
        with usable targets (Pk266), 1 attested-negative site (Pk050), 0
        validation sites. This must NOT be reported as evidence of
        generalisation -- pinned here so a future change to the threshold
        cannot silently start claiming otherwise for this exact real case.
        """
        result = assess_split_adequacy({"Pk266"}, set(), {"Pk050"})
        assert result.adequate is False
