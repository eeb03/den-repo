"""
SSL Encoder V1 Robustness / Ablation milestone: the shared experiment
runner and result-aggregation helpers used by the seed-replication
(Experiment A), training-duration (Experiment B), and masking-comparison
(Experiment C) experiments.

Deliberately thin: every experiment still calls
`training.ssl_train.run_ssl_training` directly (never a second training
loop) -- this module only adds what running SEVERAL of those and comparing
them needs: seed aggregation, and a small provenance record per experiment
so a result is traceable back to its exact configuration.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Optional

from schemas.ssl_gpr import SSLWindowRef
from training.ssl_masking import MaskConfig


@dataclass(frozen=True)
class SeedRunResult:
    seed: int
    best_epoch: int
    best_validation_loss: float
    reserved_loss: float
    train_losses: list[float]
    validation_losses: list[float]


@dataclass(frozen=True)
class SeedAggregate:
    """Mean/std across a set of `SeedRunResult`s -- exactly Experiment A's own required report."""
    n_seeds: int
    seeds: list[int]
    mean_best_validation_loss: float
    std_best_validation_loss: float
    mean_reserved_loss: float
    std_reserved_loss: float
    mean_best_epoch: float
    std_best_epoch: float


def _std(values: list[float]) -> float:
    """Population-agnostic: 0.0 for a single value (never an undefined-sample-stdev error), sample stdev otherwise."""
    return statistics.stdev(values) if len(values) > 1 else 0.0


def aggregate_seed_results(results: list[SeedRunResult]) -> SeedAggregate:
    """Section 3 Experiment A's required report: mean/std of best validation loss, reserved loss, and best epoch across seeds. Never touches anything but the per-seed results already computed -- no new evaluation happens here."""
    if not results:
        raise ValueError("cannot aggregate an empty list of seed results")
    val_losses = [r.best_validation_loss for r in results]
    reserved_losses = [r.reserved_loss for r in results]
    epochs = [float(r.best_epoch) for r in results]
    return SeedAggregate(
        n_seeds=len(results),
        seeds=[r.seed for r in results],
        mean_best_validation_loss=statistics.mean(val_losses),
        std_best_validation_loss=_std(val_losses),
        mean_reserved_loss=statistics.mean(reserved_losses),
        std_reserved_loss=_std(reserved_losses),
        mean_best_epoch=statistics.mean(epochs),
        std_best_epoch=_std(epochs),
    )


@dataclass
class ExperimentConfig:
    """
    What varies between one ablation run and V1's own configuration --
    recorded as data so every experiment's result is traceable to exactly
    what was held constant and what changed (Section 3's own "keep constant
    / only X changes" requirement, enforced by construction: every field
    not explicitly overridden equals the V1 default).
    """
    name: str
    seed: int = 0
    base_channels: int = 8
    epochs: int = 3
    learning_rate: float = 1e-3
    mask_config: Optional[MaskConfig] = None  # None -> caller uses SSL_V1_DEFAULT_MASK_CONFIG
    loss_kind: str = "l1"
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def run_seed_replication(
    train_refs: list[SSLWindowRef],
    validation_refs: list[SSLWindowRef],
    reserved_refs: list[SSLWindowRef],
    seeds: list[int],
    *,
    base_channels: int = 8,
    epochs: int = 3,
    learning_rate: float = 1e-3,
    mask_config: Optional[MaskConfig] = None,
) -> tuple[list[SeedRunResult], SeedAggregate]:
    """
    Experiment A: the exact V1 configuration, repeated once per seed.
    `reserved_refs` is used ONLY to compute the reported `reserved_loss`
    AFTER each run's best-validation checkpoint is already selected --
    never fed into `run_ssl_training`, which has no reserved-set parameter
    at all (Section 5's own holdout-integrity rule, enforced structurally:
    there is no argument here a caller could even accidentally wire it
    through).
    """
    from training.ssl_masking import SSL_V1_DEFAULT_MASK_CONFIG
    from training.ssl_model import select_device
    from training.ssl_train import evaluate, run_ssl_training

    cfg = mask_config or SSL_V1_DEFAULT_MASK_CONFIG
    device = select_device()
    results = []
    for seed in seeds:
        model, result, _provenance = run_ssl_training(
            train_refs, validation_refs, base_channels=base_channels,
            mask_config=cfg, epochs=epochs, learning_rate=learning_rate, seed=seed,
        )
        reserved_loss = evaluate(model, reserved_refs, cfg, device, loss_kind="l1")
        results.append(SeedRunResult(
            seed=seed, best_epoch=result.best_epoch, best_validation_loss=result.best_validation_loss,
            reserved_loss=reserved_loss, train_losses=result.train_losses,
            validation_losses=result.validation_losses,
        ))
    return results, aggregate_seed_results(results)
