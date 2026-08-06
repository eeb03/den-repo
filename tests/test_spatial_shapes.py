import numpy as np

from training.spatial_shapes import (
    generate_cluster_grid, extract_cluster_shape_features, generate_dataset, CLASSES, FEATURE_NAMES,
)
from training.classifier import SoftmaxClassifier


def test_elongation_is_bounded_even_for_degenerate_thin_line():
    """
    Regression test: the original unbounded elongation formula
    (eigvals[0]/eigvals[1]) produced a value of ~2.6 BILLION for a 1px-wide
    line due to floating-point near-degeneracy in the minor eigenvalue.
    The bounded formula (eigvals[0]/(eigvals[0]+eigvals[1])) must stay in
    (0, 1] no matter how thin the shape is.
    """
    grid_size = 30
    mask = np.zeros((grid_size, grid_size), dtype=bool)
    mask[5:25, 14:15] = True  # extremely thin, degenerate case that broke the old formula
    grid = np.where(mask, 5.0, 0.0)
    feats = extract_cluster_shape_features(mask, grid)
    assert feats is not None
    assert 0 < feats["elongation"] <= 1.0001


def test_elongated_shapes_score_higher_than_round_shapes():
    grid_size = 30
    mask_line = np.zeros((grid_size, grid_size), dtype=bool)
    mask_line[5:25, 14:16] = True
    grid_line = np.where(mask_line, 5.0, 0.0)
    line_feats = extract_cluster_shape_features(mask_line, grid_line)

    yy, xx = np.mgrid[0:grid_size, 0:grid_size]
    mask_round = (yy - 15) ** 2 + (xx - 15) ** 2 < 16
    grid_round = np.where(mask_round, 5.0, 0.0)
    round_feats = extract_cluster_shape_features(mask_round, grid_round)

    assert line_feats["elongation"] > round_feats["elongation"]


def test_extract_features_returns_none_for_empty_mask():
    grid = np.zeros((20, 20))
    mask = np.zeros((20, 20), dtype=bool)
    assert extract_cluster_shape_features(mask, grid) is None


def test_generate_cluster_grid_rejects_unknown_class():
    import pytest
    with pytest.raises(ValueError):
        generate_cluster_grid("not_a_real_class")


def test_generate_dataset_all_features_finite():
    X, y = generate_dataset(n_per_class=50, seed=1)
    assert np.all(np.isfinite(X)), "no NaN/Inf values should ever appear in the feature matrix"
    assert X[:, FEATURE_NAMES.index("elongation")].max() <= 1.0001


def test_spatial_classifier_beats_chance_on_held_out_data():
    X_train, y_train = generate_dataset(n_per_class=150, seed=1)
    clf = SoftmaxClassifier(CLASSES)
    result = clf.fit(X_train, y_train, epochs=300, val_split=0.2, seed=1)
    assert result["val_accuracy"] > 2 / len(CLASSES)

    X_test, y_test = generate_dataset(n_per_class=50, seed=888)
    preds = clf.predict(X_test)
    test_acc = np.mean([p == t for p, t in zip(preds, y_test)])
    assert test_acc > 2 / len(CLASSES)
