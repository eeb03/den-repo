"""
Tests for the exploratory BAM probe (`training.ssl_probe`).

Real BAM data throughout -- the probe's entire point is real target
evidence; a synthetic fixture would not test anything this module claims.
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from training.ssl_model import GPREncoder, set_seed
from training.ssl_probe import _pad_to_multiple_of_8, run_probe


class TestPadding:
    def test_pads_up_to_the_next_multiple_of_8(self):
        arr = np.ones((512, 73))
        padded, (n_s, n_t) = _pad_to_multiple_of_8(arr)
        assert padded.shape == (512, 80)
        assert (n_s, n_t) == (512, 73)

    def test_already_aligned_shape_is_unpadded(self):
        arr = np.ones((64, 64))
        padded, (n_s, n_t) = _pad_to_multiple_of_8(arr)
        assert padded.shape == (64, 64)

    def test_padded_region_is_zero(self):
        arr = np.ones((512, 73))
        padded, _ = _pad_to_multiple_of_8(arr)
        assert (padded[:, 73:] == 0).all()


class TestRunProbe:
    def test_returns_the_required_exploratory_caveat(self):
        set_seed(0)
        encoder = GPREncoder(in_channels=1, base_channels=4)
        result = run_probe(encoder, epochs=2)
        assert "EXPLORATORY" in result["caveat"]
        assert "not" in result["caveat"].lower()

    def test_runs_against_all_five_real_bam_examples(self):
        set_seed(0)
        encoder = GPREncoder(in_channels=1, base_channels=4)
        result = run_probe(encoder, epochs=2)
        assert result["n_examples"] == 5
        assert len(result["per_example"]) == 5

    def test_loss_history_has_one_entry_per_epoch(self):
        set_seed(0)
        encoder = GPREncoder(in_channels=1, base_channels=4)
        result = run_probe(encoder, epochs=4)
        assert len(result["losses"]) == 4

    def test_encoder_weights_are_unchanged_after_probing(self):
        set_seed(0)
        encoder = GPREncoder(in_channels=1, base_channels=4)
        before = [p.clone() for p in encoder.parameters()]
        run_probe(encoder, epochs=3)
        after = list(encoder.parameters())
        for b, a in zip(before, after):
            assert torch.allclose(b, a), "the frozen encoder's weights changed during probing"
