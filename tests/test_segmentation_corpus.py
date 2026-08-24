"""
Tests for the Real GPR Annotation Corpus V1 infrastructure
(`training.segmentation`'s annotation export, QA, manifest, and visual QA).

Real BAM data for anything that needs genuine examples; synthetic
fixtures for anything testing the CHECKING logic itself against a
deliberately broken case.
"""
from __future__ import annotations

import os

import pytest

from schemas.segmentation import EvidenceGrade, GPRTrainingExample, LabelLevel, MaskRegion
from training.segmentation import (
    annotation_record,
    build_bam_pk050_negative_examples,
    build_bam_pk266_examples,
    build_corpus_manifest,
    render_annotation_overlay,
    validate_corpus,
)


def _labelled_example(**overrides) -> GPRTrainingExample:
    defaults = dict(
        dataset_id="d", site_id="A", survey_id="s", source_file="f.sgy",
        trace_range=(0, 9), sample_range=(0, 9),
        signal=[[0.0] * 10 for _ in range(10)],
        mask=MaskRegion(trace_indices=[5], sample_indices=[5], rule="test fixture"),
        label_level=LabelLevel.A_MASK, label_source=None,
        evidence_grade=EvidenceGrade.B_MEASUREMENT_ASSOCIATED,
        label_basis="a real fact", preprocessing_version="test-v1",
    )
    defaults.update(overrides)
    return GPRTrainingExample(**defaults)


class TestAnnotationRecord:
    def test_produces_the_documented_json_shape(self):
        ex = build_bam_pk266_examples()[0]
        rec = annotation_record(ex, "ann-0001")
        for key in ("annotation_id", "dataset_id", "site_id", "source_file", "target_id",
                   "trace_range", "sample_range", "label", "evidence_grade", "label_source",
                   "ground_truth_status", "source", "license"):
            assert key in rec

    def test_excludes_the_large_signal_array(self):
        """The whole point of a portable annotation record: cheap to list thousands of."""
        ex = build_bam_pk266_examples()[0]
        rec = annotation_record(ex, "ann-0001")
        assert "signal" not in rec

    def test_a_real_positive_is_labelled_anomaly_event(self):
        ex = build_bam_pk266_examples()[0]
        rec = annotation_record(ex, "a")
        assert rec["label"] == "anomaly_event"

    def test_a_real_negative_is_labelled_attested_negative(self):
        ex = build_bam_pk050_negative_examples()[0]
        rec = annotation_record(ex, "a")
        assert rec["label"] == "attested_negative"

    def test_only_grade_a_is_reported_as_independently_validated(self):
        pos = annotation_record(build_bam_pk266_examples()[0], "a")  # Grade B
        neg = annotation_record(build_bam_pk050_negative_examples()[0], "b")  # Grade A
        assert pos["ground_truth_status"] == "not_independently_validated"
        assert neg["ground_truth_status"] == "independently_validated"


class TestValidateCorpus:
    def test_the_real_bam_corpus_has_zero_qa_issues(self):
        examples = build_bam_pk266_examples() + build_bam_pk050_negative_examples()
        assert validate_corpus(examples) == []

    def test_distinct_real_targets_sharing_a_window_local_range_are_not_flagged_duplicate(self):
        """
        Regression test for a real bug this milestone's own development
        caught: BAM's 4 real targets are each re-indexed to their OWN
        local (0, 72) window, which a naive range-only duplicate key
        mistook for 3 duplicates. They are 4 genuinely different real
        ducts and must never be flagged.
        """
        examples = build_bam_pk266_examples()
        ranges = {ex.trace_range for ex in examples}
        assert len(ranges) == 1  # confirms the scenario this regression test guards actually occurs
        issues = validate_corpus(examples)
        assert not any(i.check == "duplicate_annotation" for i in issues)

    def test_a_genuine_duplicate_is_still_caught(self):
        examples = build_bam_pk266_examples()
        duplicated = examples + [examples[0]]
        issues = validate_corpus(duplicated)
        assert any(i.check == "duplicate_annotation" for i in issues)

    def test_an_invalid_trace_range_is_caught(self):
        ex = _labelled_example(trace_range=(9, 0))  # end before start
        issues = validate_corpus([ex])
        assert any(i.check == "trace_range_valid" for i in issues)

    def test_a_mask_cell_outside_the_window_is_caught(self):
        ex = _labelled_example(mask=MaskRegion(trace_indices=[99], sample_indices=[99], rule="bad fixture"))
        issues = validate_corpus([ex])
        assert any(i.check == "annotation_geometry_valid" for i in issues)

    def test_a_labelled_example_with_no_evidence_grade_is_caught(self):
        ex = _labelled_example(evidence_grade=None)
        issues = validate_corpus([ex])
        assert any(i.check == "evidence_grade_present" for i in issues)

    def test_a_labelled_example_with_no_basis_is_caught(self):
        ex = _labelled_example(label_basis=None)
        issues = validate_corpus([ex])
        assert any(i.check == "provenance_present" for i in issues)

    def test_a_primary_grade_example_with_no_license_is_caught(self):
        ex = _labelled_example(evidence_grade=EvidenceGrade.A_INDEPENDENTLY_VERIFIED, license=None)
        issues = validate_corpus([ex])
        assert any(i.check == "license_present" for i in issues)

    def test_a_grade_c_example_with_no_license_is_not_required_to_have_one(self):
        """Only PRIMARY_TRAINING_EVIDENCE_GRADES (A, B) require a license -- Grade C/D are research-only regardless."""
        ex = _labelled_example(evidence_grade=EvidenceGrade.C_OPERATOR_REVIEWED, license=None)
        issues = validate_corpus([ex])
        assert not any(i.check == "license_present" for i in issues)

    def test_mismatched_signal_dimensions_are_caught(self):
        ex = _labelled_example(signal=[[0.0] * 3 for _ in range(3)])  # ranges say 10x10
        issues = validate_corpus([ex])
        assert any(i.check == "mask_dimensions_correct" for i in issues)

    def test_overlapping_train_test_sites_are_caught(self):
        a = _labelled_example(site_id="X").model_copy(update={"split": "train"})
        b = _labelled_example(site_id="X").model_copy(update={"split": "test"})
        issues = validate_corpus([a, b])
        assert any(i.check == "no_train_test_site_overlap" for i in issues)

    def test_disjoint_splits_are_not_flagged(self):
        a = _labelled_example(site_id="X").model_copy(update={"split": "train"})
        b = _labelled_example(site_id="Y").model_copy(update={"split": "test"})
        issues = validate_corpus([a, b])
        assert not any(i.check == "no_train_test_site_overlap" for i in issues)


class TestCorpusManifest:
    def test_counts_match_the_real_bam_corpus_exactly(self):
        examples = build_bam_pk266_examples() + build_bam_pk050_negative_examples()
        manifest = build_corpus_manifest(examples, version="test-v1")
        assert manifest["n_examples"] == 5
        assert manifest["n_positive"] == 4
        assert manifest["n_negative"] == 1
        assert manifest["n_unlabelled"] == 0
        assert manifest["n_sites"] == 2
        assert set(manifest["sites"]) == {"Pk266", "Pk050"}

    def test_reports_zero_qa_issues_for_the_real_corpus(self):
        examples = build_bam_pk266_examples() + build_bam_pk050_negative_examples()
        manifest = build_corpus_manifest(examples, version="test-v1")
        assert manifest["qa_issues"] == 0

    def test_is_reproducible_from_the_same_examples(self):
        examples = build_bam_pk266_examples()
        m1 = build_corpus_manifest(examples, version="v1")
        m2 = build_corpus_manifest(examples, version="v1")
        assert m1 == m2

    def test_evidence_grade_distribution_matches_real_data(self):
        examples = build_bam_pk266_examples() + build_bam_pk050_negative_examples()
        manifest = build_corpus_manifest(examples, version="test-v1")
        assert manifest["evidence_grade_distribution"] == {
            "measurement_associated": 4, "independently_verified": 1,
        }


class TestVisualQA:
    def test_writes_a_real_nonempty_png(self, tmp_path):
        ex = build_bam_pk266_examples()[0]
        out = str(tmp_path / "overlay.png")
        result = render_annotation_overlay(ex, out)
        assert result == out
        assert os.path.exists(out)
        assert os.path.getsize(out) > 1000  # a real rendered image, not an empty/stub file

    def test_handles_an_unlabelled_example_without_crashing(self, tmp_path):
        ex = _labelled_example(mask=None, evidence_grade=None, label_basis=None)
        out = str(tmp_path / "overlay.png")
        render_annotation_overlay(ex, out)
        assert os.path.exists(out)
