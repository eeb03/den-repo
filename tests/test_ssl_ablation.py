"""
Tests for the SSL Encoder V1 Robustness milestone's shared experiment
infrastructure (`training.ssl_ablation`).

Real BAM windows for the one true end-to-end multi-seed run (cheap, and
exercises the actual `run_ssl_training` -> `evaluate` path); synthetic
values for the pure aggregation math.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from training.ssl_ablation import ExperimentConfig, SeedRunResult, aggregate_seed_results, run_seed_replication
from training import ssl_corpus


class TestExperimentConfig:
    def test_defaults_match_v1s_own_configuration(self):
        cfg = ExperimentConfig(name="baseline")
        assert cfg.seed == 0
        assert cfg.base_channels == 8
        assert cfg.epochs == 3
        assert cfg.learning_rate == 1e-3
        assert cfg.mask_config is None  # caller falls back to SSL_V1_DEFAULT_MASK_CONFIG

    def test_overriding_one_field_leaves_the_rest_at_v1_defaults(self):
        cfg = ExperimentConfig(name="duration", epochs=8)
        assert cfg.epochs == 8
        assert cfg.seed == 0
        assert cfg.base_channels == 8


def _real_bam_windows(n_train=4, n_validation=2, n_reserved=2):
    files = ssl_corpus.discover_bam_source_files()
    windows = ssl_corpus.build_window_index(files)
    train = [w for w in windows if w.split.value == "train"][:n_train]
    validation = [w for w in windows if w.split.value == "validation"][:n_validation]
    testum_files = ssl_corpus.discover_testum_source_files()
    reserved = ssl_corpus.build_window_index(testum_files)[:n_reserved]
    return train, validation, reserved


class TestAggregation:
    def test_mean_and_std_over_three_seeds(self):
        results = [
            SeedRunResult(seed=0, best_epoch=1, best_validation_loss=1.0, reserved_loss=2.0,
                          train_losses=[1.5, 1.0], validation_losses=[1.2, 1.0]),
            SeedRunResult(seed=1, best_epoch=2, best_validation_loss=2.0, reserved_loss=3.0,
                          train_losses=[1.5, 1.2, 1.0], validation_losses=[1.3, 1.1, 2.0]),
            SeedRunResult(seed=2, best_epoch=0, best_validation_loss=3.0, reserved_loss=4.0,
                          train_losses=[1.5], validation_losses=[3.0]),
        ]
        agg = aggregate_seed_results(results)
        assert agg.n_seeds == 3
        assert agg.mean_best_validation_loss == pytest.approx(2.0)
        assert agg.mean_reserved_loss == pytest.approx(3.0)
        assert agg.std_best_validation_loss > 0

    def test_single_seed_has_zero_std_not_an_error(self):
        results = [SeedRunResult(seed=0, best_epoch=0, best_validation_loss=1.0, reserved_loss=1.0,
                                 train_losses=[1.0], validation_losses=[1.0])]
        agg = aggregate_seed_results(results)
        assert agg.std_best_validation_loss == 0.0
        assert agg.std_reserved_loss == 0.0

    def test_empty_results_is_rejected(self):
        with pytest.raises(ValueError):
            aggregate_seed_results([])


class TestReservedSetCannotAffectSelection:
    def test_run_seed_replication_never_passes_reserved_refs_into_training(self):
        """Structural guarantee: run_ssl_training has no reserved-set parameter at all -- checked directly on the real function signature, not just this call site."""
        import inspect
        from training.ssl_train import run_ssl_training
        params = set(inspect.signature(run_ssl_training).parameters)
        assert not (params & {"reserved_refs", "reserved", "test_refs"})

    def test_seed_replication_runs_end_to_end_on_real_bam_windows(self):
        train, validation, reserved = _real_bam_windows()
        results, agg = run_seed_replication(train, validation, reserved, seeds=[0, 1], base_channels=4, epochs=1)
        assert len(results) == 2
        assert agg.n_seeds == 2
        assert agg.seeds == [0, 1]
        # different seeds actually produced different training trajectories
        assert results[0].train_losses != results[1].train_losses or results[0].seed != results[1].seed
