"""
Metric-arithmetic tests for `training.segmentation` -- every value here is
hand-computable, so these pin the ARITHMETIC, never a real result.
"""
from __future__ import annotations

import numpy as np
import pytest

from training.segmentation import (
    chance_baseline_precision,
    dice_coefficient,
    false_positives_per_metre,
    iou,
    pr_auc,
    precision_recall_f1,
)


def _grid(rows: list[str]) -> np.ndarray:
    """'X' -> True, '.' -> False, one row of the string per grid row."""
    return np.array([[c == "X" for c in row] for row in rows])


class TestDiceAndIoU:
    def test_perfect_overlap_is_one(self):
        m = _grid(["XX", "XX"])
        assert dice_coefficient(m, m) == pytest.approx(1.0)
        assert iou(m, m) == pytest.approx(1.0)

    def test_no_overlap_is_zero(self):
        pred = _grid(["XX", ".."])
        truth = _grid(["..", "XX"])
        assert dice_coefficient(pred, truth) == pytest.approx(0.0)
        assert iou(pred, truth) == pytest.approx(0.0)

    def test_partial_overlap_matches_hand_computation(self):
        # pred: {(0,0),(0,1)}; truth: {(0,1),(1,1)} -> intersection 1, |pred|=2, |truth|=2
        pred = _grid(["XX", ".."])
        truth = _grid([".X", ".X"])
        assert dice_coefficient(pred, truth) == pytest.approx(2 * 1 / (2 + 2))
        assert iou(pred, truth) == pytest.approx(1 / 3)  # union = 3

    def test_both_empty_is_undefined_not_perfect(self):
        empty = _grid(["..", ".."])
        assert dice_coefficient(empty, empty) is None
        assert iou(empty, empty) is None


class TestPrecisionRecallF1:
    def test_hand_computable_case(self):
        pred = _grid(["XX.", "..."])
        truth = _grid(["X..", ".X."])
        # tp=1 (0,0), fp=1 (0,1), fn=1 (1,1), tn=3
        result = precision_recall_f1(pred, truth)
        assert result.true_positives == 1
        assert result.false_positives == 1
        assert result.false_negatives == 1
        assert result.true_negatives == 3
        assert result.precision == pytest.approx(0.5)
        assert result.recall == pytest.approx(0.5)
        assert result.f1 == pytest.approx(0.5)

    def test_no_predicted_positives_gives_undefined_precision(self):
        pred = _grid(["..", ".."])
        truth = _grid(["X.", ".."])
        result = precision_recall_f1(pred, truth)
        assert result.precision is None
        assert result.recall == pytest.approx(0.0)

    def test_no_true_positives_at_all_gives_undefined_recall(self):
        pred = _grid(["X.", ".."])
        truth = _grid(["..", ".."])
        result = precision_recall_f1(pred, truth)
        assert result.recall is None
        assert result.precision == pytest.approx(0.0)


class TestPrAuc:
    def test_perfect_ranking_gives_auc_one(self):
        # every true positive scores strictly higher than every negative
        scores = np.array([0.9, 0.8, 0.1, 0.2])
        truth = np.array([True, True, False, False])
        assert pr_auc(scores, truth) == pytest.approx(1.0, abs=1e-6)

    def test_no_positives_is_undefined(self):
        scores = np.array([0.9, 0.1])
        truth = np.array([False, False])
        assert pr_auc(scores, truth) is None

    def test_inverted_ranking_scores_worse_than_perfect(self):
        scores = np.array([0.1, 0.2, 0.8, 0.9])  # negatives score highest
        truth = np.array([True, True, False, False])
        result = pr_auc(scores, truth)
        assert result is not None
        assert result < 0.9  # materially worse than the perfect-ranking case


class TestChanceBaseline:
    def test_matches_hand_computed_fraction(self):
        truth = _grid(["XX.", "..."])  # 2 of 6 cells positive
        assert chance_baseline_precision(truth) == pytest.approx(2 / 6)

    def test_empty_grid_is_none(self):
        assert chance_baseline_precision(np.zeros((0, 0), dtype=bool)) is None


class TestFalsePositivesPerMetre:
    def test_hand_computable_case(self):
        # 2 traces, one has a false-positive column
        pred = _grid(["X.", "X."])
        truth = _grid([".."], ) if False else _grid(["..", ".."])
        result = false_positives_per_metre(pred, truth, trace_spacing_m=0.5)
        # 1 FP column, line length = 2 traces * 0.5 m = 1.0 m -> 1.0 FP/m
        assert result == pytest.approx(1.0)

    def test_no_spacing_is_none_not_a_fabricated_distance(self):
        pred = _grid(["X."])
        truth = _grid(["X."])
        assert false_positives_per_metre(pred, truth, trace_spacing_m=None) is None
        assert false_positives_per_metre(pred, truth, trace_spacing_m=0.0) is None
