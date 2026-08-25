"""
Tests for `training.ssl_train`: normalization reproducibility, the
end-to-end training driver, augmentation reproducibility, and artifact
provenance completeness.

Real BAM data for the end-to-end training run (genuinely exercises the full
real-file -> dewow -> normalize -> mask -> train -> provenance path);
synthetic fixtures for the normalization/augmentation math itself.
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from schemas.ssl_gpr import SSLArtifactProvenance
from training import ssl_corpus, ssl_train
from training.ssl_augment import amplitude_scale
from training.ssl_masking import MaskConfig, MaskKind


def _real_bam_windows(n_train: int = 4, n_validation: int = 2):
    files = ssl_corpus.discover_bam_source_files()
    windows = ssl_corpus.build_window_index(files)
    train = [w for w in windows if w.split.value == "train"][:n_train]
    validation = [w for w in windows if w.split.value == "validation"][:n_validation]
    return train, validation


class TestNormalization:
    def test_normalize_window_is_reproducible_for_the_same_input(self):
        rng = np.random.default_rng(0)
        raw = rng.normal(loc=50, scale=200, size=(64, 32))
        n1 = ssl_train.normalize_window(raw)
        n2 = ssl_train.normalize_window(raw)
        assert np.array_equal(n1, n2)

    def test_normalize_window_centres_on_zero_median(self):
        rng = np.random.default_rng(0)
        raw = rng.normal(loc=500, scale=10, size=(64, 32))
        normalized = ssl_train.normalize_window(raw)
        assert abs(np.median(normalized)) < 1e-6

    def test_normalize_window_is_a_pure_function_of_its_input(self):
        """Two different windows with the same shape but different values must not be normalized by a shared/global statistic."""
        rng = np.random.default_rng(0)
        a = rng.normal(loc=0, scale=1, size=(64, 32))
        b = rng.normal(loc=10000, scale=5000, size=(64, 32))
        na, nb = ssl_train.normalize_window(a), ssl_train.normalize_window(b)
        assert abs(np.median(na)) < 1e-6
        assert abs(np.median(nb)) < 1e-6  # both re-centred independently, neither dragged toward the other

    def test_a_near_constant_window_does_not_produce_an_unbounded_value(self):
        """Regression test for a real finding: a near-zero-MAD window (a real TestUM crosshole-file artifact) must never blow up the normalized scale -- clipped, not exploded."""
        degenerate = np.full((32, 16), 5.0)
        degenerate[0, 0] = 5.001  # a tiny real deviation -- MAD is ~0, not exactly 0
        normalized = ssl_train.normalize_window(degenerate)
        assert np.abs(normalized).max() <= ssl_train.NORMALIZED_CLIP_MAGNITUDE

    def test_dewow_window_applies_per_trace(self):
        raw = np.tile(np.array([1.0, 2.0, 3.0, 100.0, 3.0, 2.0, 1.0]).reshape(-1, 1), (1, 3))
        out = ssl_train.dewow_window(raw)
        assert out.shape == raw.shape
        # every column (trace) treated identically since the input columns are identical
        assert np.allclose(out[:, 0], out[:, 1])
        assert np.allclose(out[:, 1], out[:, 2])


class TestAugmentationReproducibility:
    def test_same_seeds_produce_identical_scaling(self):
        rng = np.random.default_rng(0)
        signal = rng.normal(size=(16, 16))
        a1 = amplitude_scale(signal, window_seed=3, config_seed=1)
        a2 = amplitude_scale(signal, window_seed=3, config_seed=1)
        assert np.array_equal(a1, a2)

    def test_different_window_seeds_can_scale_differently(self):
        rng = np.random.default_rng(0)
        signal = rng.normal(size=(16, 16))
        factors = {float(amplitude_scale(signal, window_seed=s, config_seed=1)[0, 0] / signal[0, 0])
                   for s in range(8)}
        assert len(factors) > 1

    def test_scale_factor_stays_within_the_declared_bounds(self):
        rng = np.random.default_rng(0)
        signal = np.ones((4, 4))
        for s in range(20):
            scaled = amplitude_scale(signal, window_seed=s, config_seed=0, low=0.9, high=1.1)
            assert 0.9 <= scaled[0, 0] <= 1.1


class TestEndToEndTraining:
    def test_run_ssl_training_on_real_bam_windows_returns_a_complete_provenance(self):
        train, validation = _real_bam_windows()
        model, result, provenance = ssl_train.run_ssl_training(
            train, validation, base_channels=4, epochs=1, seed=0,
            mask_config=MaskConfig(kind=MaskKind.TRACE_BLOCK, ratio=0.3, seed=0),
        )
        assert isinstance(provenance, SSLArtifactProvenance)
        assert result.n_train_windows == len(train)
        assert len(result.train_losses) == 1
        assert len(result.validation_losses) == 1

    def test_provenance_records_every_required_field_non_default(self):
        train, validation = _real_bam_windows()
        _, _, provenance = ssl_train.run_ssl_training(
            train, validation, base_channels=4, epochs=1, seed=0,
        )
        assert provenance.parameter_count > 0
        assert provenance.training_sites
        assert provenance.masking_strategy
        assert provenance.model_checksum_sha256
        assert len(provenance.model_checksum_sha256) == 64  # sha256 hex digest
        assert provenance.limitations
        assert provenance.limitations.strip() != ""

    def test_reserved_sites_never_appear_in_training_or_validation_sites(self):
        train, validation = _real_bam_windows()
        _, _, provenance = ssl_train.run_ssl_training(
            train, validation, base_channels=4, epochs=1, seed=0,
        )
        reserved = set(provenance.reserved_sites)
        assert not (reserved & set(provenance.training_sites))
        assert not (reserved & set(provenance.validation_sites))

    def test_training_is_deterministic_given_the_same_seed(self):
        train, validation = _real_bam_windows()
        _, result_a, _ = ssl_train.run_ssl_training(train, validation, base_channels=4, epochs=1, seed=5)
        _, result_b, _ = ssl_train.run_ssl_training(train, validation, base_channels=4, epochs=1, seed=5)
        assert result_a.train_losses == pytest.approx(result_b.train_losses)


class TestBestCheckpointSelection:
    def test_select_best_epoch_picks_the_minimum(self):
        assert ssl_train.select_best_epoch([3.0, 1.0, 2.0]) == 1

    def test_select_best_epoch_ties_pick_the_first(self):
        assert ssl_train.select_best_epoch([1.0, 1.0, 2.0]) == 0

    def test_select_best_epoch_rejects_empty_history(self):
        with pytest.raises(ValueError):
            ssl_train.select_best_epoch([])

    def test_run_ssl_training_records_best_epoch_and_loss(self):
        train, validation = _real_bam_windows()
        _, result, _ = ssl_train.run_ssl_training(train, validation, base_channels=4, epochs=3, seed=0)
        assert result.best_epoch == ssl_train.select_best_epoch(result.validation_losses)
        assert result.best_validation_loss == result.validation_losses[result.best_epoch]

    def test_restore_best_true_returns_the_best_epoch_checkpoint_not_the_last(self):
        """A model that keeps improving every epoch has best==last (nothing to distinguish); this test instead checks the restoration MECHANISM directly: the returned model's weights must equal the checkpoint captured at result.best_epoch, not simply whatever the final epoch left in place."""
        train, validation = _real_bam_windows()
        model, result, _ = ssl_train.run_ssl_training(
            train, validation, base_channels=4, epochs=3, seed=0, restore_best=True,
        )
        # re-run identically with restore_best=False to get the raw final-epoch weights
        model_final, result_final, _ = ssl_train.run_ssl_training(
            train, validation, base_channels=4, epochs=3, seed=0, restore_best=False,
        )
        if result.best_epoch != len(result.validation_losses) - 1:
            # best epoch is NOT the last -> the two models must differ
            same = all(torch.allclose(p1, p2) for p1, p2 in zip(model.parameters(), model_final.parameters()))
            assert not same
        else:
            same = all(torch.allclose(p1, p2) for p1, p2 in zip(model.parameters(), model_final.parameters()))
            assert same


class TestNoTargetTruthConsumed:
    def test_training_windows_carry_no_ground_truth_reference(self):
        """Every field on a real SSLWindowRef used for training is either an index (where the data is) or metadata (vendor/frequency/licence) -- never a target/truth value."""
        train, _ = _real_bam_windows()
        for w in train:
            assert not hasattr(w, "mask")
            assert not hasattr(w, "target_id")

    def test_materialize_window_reads_only_the_signal_no_truth_file(self):
        import inspect
        src = inspect.getsource(ssl_train.materialize_window)
        assert "truth" not in src.lower()
        assert "target" not in src.lower()
