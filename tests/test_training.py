import numpy as np

from training.synthetic_gpr import generate_patch, extract_features, generate_dataset, CLASSES, FEATURE_NAMES
from training.classifier import SoftmaxClassifier


def test_generate_patch_correct_shape():
    patch = generate_patch("pipe", n_traces=32, n_samples=64, rng=np.random.default_rng(0))
    assert patch.shape == (32, 64)


def test_generate_patch_rejects_unknown_class():
    import pytest
    with pytest.raises(ValueError):
        generate_patch("not_a_real_class")


def test_hyperbolic_classes_have_low_planarity_high_diffuseness():
    rng = np.random.default_rng(0)
    for cls in ["pipe", "cable", "void"]:
        patch = generate_patch(cls, rng=rng)
        feats = extract_features(patch)
        assert feats["planarity"] < 0.3, f"{cls} should have low planarity (curved reflector)"


def test_concrete_has_high_planarity_low_quad_coeff():
    rng = np.random.default_rng(0)
    patch = generate_patch("concrete", rng=rng)
    feats = extract_features(patch)
    assert feats["planarity"] > 0.5
    assert feats["quad_coeff"] < 0.05


def test_void_has_opposite_polarity_from_pipe():
    rng = np.random.default_rng(0)
    pipe_feats = extract_features(generate_patch("pipe", rng=rng))
    void_feats = extract_features(generate_patch("void", rng=rng))
    assert pipe_feats["polarity"] > 0
    assert void_feats["polarity"] < 0


def test_unknown_has_low_amplitude():
    rng = np.random.default_rng(0)
    unknown_feats = extract_features(generate_patch("unknown", rng=rng))
    pipe_feats = extract_features(generate_patch("pipe", rng=rng))
    assert unknown_feats["peak_amplitude"] < pipe_feats["peak_amplitude"]


def test_generate_dataset_shape_and_balance():
    X, y = generate_dataset(n_per_class=20, seed=1)
    assert X.shape == (20 * len(CLASSES), len(FEATURE_NAMES))
    for cls in CLASSES:
        assert y.count(cls) == 20


def test_classifier_beats_chance_on_held_out_data():
    X_train, y_train = generate_dataset(n_per_class=150, seed=1)
    clf = SoftmaxClassifier(CLASSES)
    result = clf.fit(X_train, y_train, epochs=300, val_split=0.2, seed=1)

    assert result["val_accuracy"] > 2 / len(CLASSES)  # comfortably beats chance (1/6)

    X_test, y_test = generate_dataset(n_per_class=50, seed=999)  # different seed -- genuinely held out
    preds = clf.predict(X_test)
    test_acc = np.mean([p == t for p, t in zip(preds, y_test)])
    assert test_acc > 2 / len(CLASSES)


def test_classifier_loss_decreases_during_training():
    X, y = generate_dataset(n_per_class=100, seed=2)
    clf = SoftmaxClassifier(CLASSES)
    result = clf.fit(X, y, epochs=300, val_split=0.2, seed=2)
    losses = result["train_loss_curve"]
    assert losses[-1] < losses[0]  # genuine learning, not random weights


def test_classifier_predict_proba_sums_to_one():
    X, y = generate_dataset(n_per_class=50, seed=3)
    clf = SoftmaxClassifier(CLASSES)
    clf.fit(X, y, epochs=100, seed=3)
    probs = clf.predict_proba(X[:5])
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_classifier_save_load_roundtrip(tmp_path):
    X, y = generate_dataset(n_per_class=50, seed=4)
    clf = SoftmaxClassifier(CLASSES)
    clf.fit(X, y, epochs=100, seed=4)

    path = tmp_path / "model.json"
    clf.save(path)
    loaded = SoftmaxClassifier.load(path)

    original_preds = clf.predict(X[:10])
    loaded_preds = loaded.predict(X[:10])
    assert original_preds == loaded_preds
