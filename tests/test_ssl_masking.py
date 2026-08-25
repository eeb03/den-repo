"""
Tests for Self-Supervised GPR Encoder V1's masking (`training.ssl_masking`).

Synthetic fixtures throughout: this module tests the CHECKING/construction
logic itself against deliberately simple, known shapes -- real signal
content is irrelevant to whether a mask is contiguous, reproducible, or the
right size.
"""
from __future__ import annotations

import numpy as np
import pytest

from training.ssl_masking import MaskConfig, MaskKind, apply_mask, generate_mask


class TestMaskConfig:
    def test_ratio_below_the_defensible_band_is_rejected(self):
        with pytest.raises(ValueError):
            MaskConfig(ratio=0.01)

    def test_ratio_above_the_defensible_band_is_rejected(self):
        with pytest.raises(ValueError):
            MaskConfig(ratio=0.9)

    def test_ratio_within_the_band_is_accepted(self):
        MaskConfig(ratio=0.3)  # must not raise


class TestMaskConstruction:
    def test_trace_block_masks_a_contiguous_column_range_full_depth(self):
        mask = generate_mask((20, 40), MaskConfig(kind=MaskKind.TRACE_BLOCK, ratio=0.25), window_seed=1)
        assert mask.shape == (20, 40)
        cols_masked = np.where(mask.any(axis=0))[0]
        assert len(cols_masked) == round(40 * 0.25)
        assert (cols_masked == np.arange(cols_masked.min(), cols_masked.max() + 1)).all()
        # full depth masked in every masked column
        assert mask[:, cols_masked].all()

    def test_time_band_masks_a_contiguous_row_range_full_width(self):
        mask = generate_mask((20, 40), MaskConfig(kind=MaskKind.TIME_BAND, ratio=0.25), window_seed=1)
        rows_masked = np.where(mask.any(axis=1))[0]
        assert len(rows_masked) == round(20 * 0.25)
        assert (rows_masked == np.arange(rows_masked.min(), rows_masked.max() + 1)).all()
        assert mask[rows_masked, :].all()

    def test_patch_masks_a_bounded_contiguous_rectangle(self):
        mask = generate_mask((32, 64), MaskConfig(kind=MaskKind.PATCH, ratio=0.25), window_seed=1)
        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]
        assert (rows == np.arange(rows.min(), rows.max() + 1)).all()
        assert (cols == np.arange(cols.min(), cols.max() + 1)).all()

    def test_mask_ratio_is_never_zero_or_total(self):
        for kind in MaskKind:
            mask = generate_mask((16, 16), MaskConfig(kind=kind, ratio=0.3), window_seed=0)
            assert 0 < mask.sum() < mask.size


class TestReproducibility:
    def test_same_seeds_produce_identical_masks(self):
        cfg = MaskConfig(kind=MaskKind.TRACE_BLOCK, ratio=0.3, seed=7)
        m1 = generate_mask((16, 32), cfg, window_seed=3)
        m2 = generate_mask((16, 32), cfg, window_seed=3)
        assert np.array_equal(m1, m2)

    def test_different_window_seeds_can_produce_different_masks(self):
        cfg = MaskConfig(kind=MaskKind.TRACE_BLOCK, ratio=0.3, seed=7)
        masks = {tuple(np.where(generate_mask((16, 32), cfg, window_seed=s).any(axis=0))[0])
                  for s in range(10)}
        assert len(masks) > 1, "10 different window seeds produced the exact same mask position every time"

    def test_different_config_seeds_produce_different_masks(self):
        m1 = generate_mask((16, 32), MaskConfig(kind=MaskKind.TRACE_BLOCK, ratio=0.3, seed=1), window_seed=0)
        m2 = generate_mask((16, 32), MaskConfig(kind=MaskKind.TRACE_BLOCK, ratio=0.3, seed=2), window_seed=0)
        assert not np.array_equal(m1, m2)


class TestApplyMask:
    def test_masked_cells_are_overwritten_with_the_fill_value(self):
        signal = np.arange(16.0).reshape(4, 4)
        mask = np.zeros((4, 4), dtype=bool)
        mask[1:3, 1:3] = True
        out = apply_mask(signal, mask, fill_value=-99.0)
        assert (out[mask] == -99.0).all()

    def test_unmasked_cells_are_untouched(self):
        signal = np.arange(16.0).reshape(4, 4)
        mask = np.zeros((4, 4), dtype=bool)
        mask[1:3, 1:3] = True
        out = apply_mask(signal, mask, fill_value=-99.0)
        assert np.array_equal(out[~mask], signal[~mask])

    def test_does_not_mutate_the_input_array(self):
        signal = np.arange(16.0).reshape(4, 4)
        original = signal.copy()
        mask = np.ones((4, 4), dtype=bool)
        apply_mask(signal, mask, fill_value=0.0)
        assert np.array_equal(signal, original)

    def test_masked_values_cannot_leak_into_the_model_input(self):
        """The real value at every masked cell must be gone from the input the encoder sees."""
        rng = np.random.default_rng(0)
        signal = rng.normal(size=(20, 40)) * 1000 + 500  # values far from the fill value
        mask = generate_mask(signal.shape, MaskConfig(ratio=0.3), window_seed=0)
        out = apply_mask(signal, mask, fill_value=0.0)
        assert (out[mask] == 0.0).all()
        assert not np.array_equal(out[mask], signal[mask])
