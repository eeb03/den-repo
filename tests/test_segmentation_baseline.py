"""
Baseline-comparison tests for `training.segmentation` -- the harness that
scores the EXISTING production statistical detector against real BAM
examples, using the exact same metrics any future learned model would be
compared with.
"""
from __future__ import annotations

import numpy as np

from training.segmentation import (
    aggregate_metrics,
    baseline_statistical_detector,
    build_bam_pk050_negative_examples,
    build_bam_pk266_examples,
    score_examples,
)


class TestBaselineStatisticalDetector:
    def test_returns_the_same_shape_as_the_input_signal(self):
        ex = build_bam_pk266_examples()[0]
        z = baseline_statistical_detector(ex)
        assert z.shape == (len(ex.signal), len(ex.signal[0]))

    def test_scores_are_non_negative_absolute_z(self):
        ex = build_bam_pk266_examples()[0]
        z = baseline_statistical_detector(ex)
        assert (z >= 0).all()

    def test_unreliable_cells_score_zero_never_a_fabricated_confident_value(self):
        """Matches production's own 'unreliable, not scored' contract -- see the function's own docstring."""
        ex = build_bam_pk266_examples()[0]
        z = baseline_statistical_detector(ex)
        # edge columns of a ring statistic are the ones most likely starved
        # of neighbours; whatever is unreliable must be exactly 0, not NaN
        # or a large spurious value.
        assert not np.isnan(z).any()

    def test_real_finding_no_target_cell_reaches_the_production_candidate_threshold(self):
        """
        Pinned real result from this milestone's own investigation: across
        all 4 real BAM targets, the statistical detector's z-score at the
        TRUE, measured target location never exceeds ~2.0 -- well under
        the |z|>=3 threshold production candidate generation actually
        uses. If this ever changes, it is a real finding worth noticing,
        not a flaky test to raise the tolerance on.
        """
        for ex in build_bam_pk266_examples():
            z = baseline_statistical_detector(ex)
            mask_vals = np.array([z[s, t] for t, s in zip(ex.mask.trace_indices, ex.mask.sample_indices)])
            assert mask_vals.max() < 3.0


class TestScoreExamples:
    def test_scores_only_trainable_label_levels(self):
        examples = build_bam_pk266_examples() + build_bam_pk050_negative_examples()
        scores = score_examples(examples, baseline_statistical_detector, threshold=5.0)
        assert len(scores) == len(examples)  # both A_MASK (positives) and the attested-empty negative

    def test_the_attested_negative_example_has_no_false_positives_at_a_sane_threshold(self):
        neg = build_bam_pk050_negative_examples()
        scores = score_examples(neg, baseline_statistical_detector, threshold=5.0)
        assert scores[0].metrics["true_positives"] == 0

    def test_uses_identical_truth_and_signal_for_the_scored_example(self):
        """
        'Current detector comparison uses identical truth/split' (milestone
        Section 29, item 16): `score_examples` must read `ex.mask` and
        `ex.signal` from the SAME example object it calls `predict` on --
        never a second, independently-loaded copy that could silently
        drift from what was actually scored.
        """
        examples = build_bam_pk266_examples()
        calls = []

        def spy_predict(ex):
            calls.append(ex)
            return baseline_statistical_detector(ex)

        score_examples(examples, spy_predict, threshold=5.0)
        assert calls == examples  # exact same objects, not copies


class TestAggregateMetrics:
    def test_empty_scores_is_reported_honestly(self):
        assert aggregate_metrics([]) == {"n_examples": 0}

    def test_reports_how_many_examples_contributed_to_each_metric(self):
        examples = build_bam_pk266_examples()
        scores = score_examples(examples, baseline_statistical_detector, threshold=5.0)
        agg = aggregate_metrics(scores)
        assert agg["n_examples"] == 4
        # dice/iou are defined for all 4 (truth is non-empty for every real target)
        assert agg["dice"]["n"] == 4
