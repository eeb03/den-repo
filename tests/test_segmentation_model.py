"""
Tests for `training.segmentation_model` -- the TinyUNet architecture, loss,
and training loop.

SYNTHETIC, TINY FIXTURES ONLY, AND DELIBERATELY SO. These tests verify the
TRAINING CODE ITSELF is correct (gradients flow, loss decreases, a trivial
pattern can be memorised) -- standard software verification for a training
loop, same as `tests/test_training.py`'s own synthetic-only sanity tests
elsewhere in this repo. NONE of this is presented as, or should be read as,
evidence about real GPR segmentation performance: this milestone's own data
audit (`training/segmentation.py`'s module docstring) found real labelled
GPR far too scarce to train or validate a real model, and no test here
claims otherwise. See that module and the milestone's final report for the
actual real-data findings.

Requires `torch`, an OPTIONAL dependency -- skipped entirely (not failed)
if it is not installed, matching how `tests/test_dem_alignment.py` already
skips its own optional-dependency (`rasterio`) tests.
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from training.segmentation_model import (  # noqa: E402
    ConfidenceBucket,
    TinyUNet,
    bce_dice_loss,
    model_checksum,
    predict_probabilities,
    set_seed,
    train_one_epoch,
)


def _tiny_signal(h: int = 16, w: int = 16, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0, 1, size=(h, w)).astype(np.float32)


def _tiny_target(h: int = 16, w: int = 16) -> np.ndarray:
    """A trivial pattern: a single positive cell at a known location -- easy enough for a tiny model to overfit."""
    target = np.zeros((h, w), dtype=np.float32)
    target[h // 2, w // 2] = 1.0
    return target


class TestArchitecture:
    def test_output_shape_matches_input_spatial_dims(self):
        model = TinyUNet(in_channels=1, base_channels=4)
        x = torch.zeros(1, 1, 16, 16)
        out = model(x)
        assert out.shape == (1, 1, 16, 16)

    def test_parameter_count_is_reported_and_small(self):
        model = TinyUNet(in_channels=1, base_channels=8)
        # "small enough to avoid massive overfitting" -- a real, checkable
        # ceiling, not a vague aspiration: under 1M params at these settings.
        assert 0 < model.parameter_count < 1_000_000

    def test_rejects_dimensions_that_do_not_survive_three_poolings(self):
        """A 3-level U-Net needs H/W divisible by 8 for the skip connections to line up -- confirmed here, not silently produced wrong."""
        model = TinyUNet(in_channels=1, base_channels=4)
        x = torch.zeros(1, 1, 15, 15)
        with pytest.raises((RuntimeError, ValueError)):
            model(x)


class TestLoss:
    def test_perfect_prediction_gives_a_smaller_loss_than_a_random_one(self):
        target = torch.tensor(_tiny_target()).unsqueeze(0).unsqueeze(0)
        perfect_logits = (target * 20) - 10  # confidently correct
        random_logits = torch.zeros_like(target)
        assert bce_dice_loss(perfect_logits, target).item() < bce_dice_loss(random_logits, target).item()

    def test_loss_is_a_finite_scalar(self):
        target = torch.zeros(1, 1, 8, 8)
        logits = torch.randn(1, 1, 8, 8)
        loss = bce_dice_loss(logits, target)
        assert torch.isfinite(loss)
        assert loss.dim() == 0


class TestTrainingSanity:
    """Milestone Section 29, items 8-10: reproducibility, tiny-fixture overfit, loss decreases."""

    def test_fixed_seed_is_reproducible(self):
        set_seed(42)
        m1 = TinyUNet(in_channels=1, base_channels=4)
        w1 = next(m1.parameters()).clone()
        set_seed(42)
        m2 = TinyUNet(in_channels=1, base_channels=4)
        w2 = next(m2.parameters()).clone()
        assert torch.allclose(w1, w2)

    def test_loss_decreases_over_a_few_steps_on_a_tiny_fixture(self):
        set_seed(0)
        model = TinyUNet(in_channels=1, base_channels=4)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
        signal, target = _tiny_signal(), _tiny_target()

        losses = [train_one_epoch(model, optimizer, signal, target) for _ in range(30)]
        assert losses[-1] < losses[0]

    def test_model_can_overfit_a_tiny_controlled_fixture(self):
        """Basic sanity: given enough steps on ONE fixed example, the model should predict it near-perfectly. Not a claim about generalisation -- see module docstring."""
        set_seed(0)
        model = TinyUNet(in_channels=1, base_channels=4)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
        signal, target = _tiny_signal(), _tiny_target()

        for _ in range(200):
            train_one_epoch(model, optimizer, signal, target)

        probs = predict_probabilities(model, signal)
        peak_r, peak_c = np.unravel_index(np.argmax(probs), probs.shape)
        assert (peak_r, peak_c) == (8, 8)  # matches _tiny_target's known positive cell


class TestInference:
    def test_probabilities_are_in_zero_one_range(self):
        model = TinyUNet(in_channels=1, base_channels=4)
        probs = predict_probabilities(model, _tiny_signal())
        assert probs.min() >= 0.0
        assert probs.max() <= 1.0

    def test_output_shape_matches_input(self):
        model = TinyUNet(in_channels=1, base_channels=4)
        signal = _tiny_signal(h=32, w=16)
        probs = predict_probabilities(model, signal)
        assert probs.shape == (32, 16)

    def test_a_flat_zero_signal_does_not_crash_and_stays_in_range(self):
        model = TinyUNet(in_channels=1, base_channels=4)
        probs = predict_probabilities(model, np.zeros((16, 16), dtype=np.float32))
        assert probs.shape == (16, 16)
        assert probs.min() >= 0.0 and probs.max() <= 1.0

    def test_inference_does_not_accumulate_gradients(self):
        model = TinyUNet(in_channels=1, base_channels=4)
        predict_probabilities(model, _tiny_signal())
        assert all(p.grad is None for p in model.parameters())


class TestModelChecksum:
    def test_is_deterministic_for_identical_weights(self):
        set_seed(1)
        m1 = TinyUNet(in_channels=1, base_channels=4)
        set_seed(1)
        m2 = TinyUNet(in_channels=1, base_channels=4)
        assert model_checksum(m1) == model_checksum(m2)

    def test_differs_after_a_training_step(self):
        set_seed(2)
        model = TinyUNet(in_channels=1, base_channels=4)
        before = model_checksum(model)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-1)
        train_one_epoch(model, optimizer, _tiny_signal(), _tiny_target())
        after = model_checksum(model)
        assert before != after


class TestConfidenceBucket:
    def test_classifies_high_low_and_unknown(self):
        bucket = ConfidenceBucket(low=0.3, high=0.7)
        assert bucket.classify(0.9) == "high_confidence_evidence"
        assert bucket.classify(0.05) == "high_confidence_absence"
        assert bucket.classify(0.5) == "low_confidence_unknown"

    def test_boundaries_are_inclusive_to_the_confident_side(self):
        bucket = ConfidenceBucket(low=0.3, high=0.7)
        assert bucket.classify(0.7) == "high_confidence_evidence"
        assert bucket.classify(0.3) == "high_confidence_absence"
