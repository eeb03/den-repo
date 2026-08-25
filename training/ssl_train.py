"""
Self-Supervised GPR Encoder V1: the dataset wrapper, normalization,
training loop, and artifact provenance builder.

============================================================================
INPUT REPRESENTATION (Section 6)
============================================================================

DEWOW-ONLY real amplitude. `preprocessing.trace_processing.dewow` (reused,
not reimplemented) is applied per-trace before windowing. Considered and
rejected:

  raw amplitude          Every held vendor's raw DC/low-frequency wander
                          differs enough (BAM's controlled lab rig vs. 4TU's
                          air-launched field antenna) that the network's
                          very first signal would be dominated by an
                          acquisition-system artefact, not radar structure.
  background_removal     Assumes coherent noise shared across NEIGHBOURING
                          traces within one survey line -- a real, useful
                          assumption for detection, but one this SSL window
                          (a fixed-size crop that may not span a whole
                          survey) cannot always support consistently, and
                          Section 6 explicitly warns against building on
                          the existing detector's own assumptions.
  gain                   Reshapes the true amplitude-vs-depth relationship
                          to make deep, weak signal easier to SEE -- exactly
                          the "amplitude relationship the future detector
                          may need" Section 8 warns not to remove before a
                          representation is learned from it.

Dewow alone removes a near-universal instrument artefact (slow drift/DC
wander) with no assumption about neighbouring traces or target depth, and
is already used unmodified by both the existing statistical detector
(`training.segmentation.baseline_statistical_detector`) and this project's
own signal chain -- reusing it, not inventing a new preprocessing step.

============================================================================
NORMALIZATION (Section 8)
============================================================================

PER-WINDOW ROBUST NORMALIZATION: subtract the window's own median, divide
by 1.4826 x the window's own median absolute deviation (a robust,
outlier-resistant z-score), computed from the DEWOW'D signal BEFORE
masking (masking must never influence the statistic a window is normalized
by, or a caller could distinguish masked windows from unmasked ones by
their normalization alone -- a leakage channel independent of the model
architecture). Chosen over:

  per-trace normalization    Would remove the very lateral amplitude
                              relationship (how one trace's reflection
                              compares to its neighbours) TRACE_BLOCK
                              masking is designed to force the network to
                              reconstruct FROM.
  dataset-level normalization  A single global scale factor is not
                              physically meaningful across this corpus:
                              GSSI 32-bit lab data, MALA field data and
                              little-endian SEG-Y field data have
                              different, vendor-specific raw amplitude
                              scales with no shared physical unit recorded
                              anywhere in this codebase.

STATED RISK, not hidden: per-window normalization discards each window's
ABSOLUTE amplitude scale relative to every other window -- a real
limitation for any future task that needs cross-window amplitude
comparison (Section 8's own warning). SSL's objective here is STRUCTURE
(reflection continuity, local temporal pattern), not absolute-amplitude
calibration, so this is a defensible V1 trade, stated rather than assumed
away. The exact method/parameters are recorded on every artifact
(`SSLArtifactProvenance.normalization`) and reproduced identically at
inference (`normalize_window` is the one function both training and any
future encoder use ever call).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from converters.base import MissingDependencyError
from preprocessing.trace_processing import dewow
from schemas.ssl_gpr import LicensePool, SSLArtifactProvenance, SSLWindowRef
from training import ssl_corpus
from training.ssl_masking import MaskConfig, SSL_V1_DEFAULT_MASK_CONFIG, apply_mask, generate_mask

try:
    import torch
    from torch.utils.data import Dataset
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    Dataset = object  # type: ignore[assignment,misc]

NORMALIZATION_METHOD = "per_window_robust_zscore_median_mad_1.4826_clip50"
PREPROCESSING_VERSION = ssl_corpus.PREPROCESSING_VERSION


def _require_torch():
    if not _TORCH_AVAILABLE:
        raise MissingDependencyError(
            "torch is required for training.ssl_train. Install with: "
            "pip install torch --extra-index-url https://download.pytorch.org/whl/cpu"
        )


def dewow_window(raw: np.ndarray) -> np.ndarray:
    """`raw`: (n_samples, n_traces). Applies `preprocessing.trace_processing.dewow` PER TRACE (each column)."""
    out = np.empty_like(raw, dtype=float)
    for i in range(raw.shape[1]):
        out[:, i] = dewow(raw[:, i].tolist())
    return out


#: A robust z-score beyond this magnitude is not real reflectivity structure
#: by construction (see this constant's own use below) -- discovered as a
#: REAL finding during the V1 training run, not chosen a priori: certain
#: TestUM crosshole files' very first window (trace 0, sample 0) has a
#: near-zero MAD (a documented instrument artifact -- the file's own
#: leading samples are genuinely near-constant, `docs/testum-raw-data-
#: validation.md`'s "the first two samples are genuinely 0"), and dividing
#: by a near-zero scale sent that window's normalized values into the
#: millions, which then dominated a mean L1 loss over hundreds of
#: otherwise well-behaved windows (median max-|value| across a real sample:
#: ~33; the degenerate windows: ~3-4 MILLION). Clipping is a defensive
#: floor on a real, observed failure mode, not an arbitrary hyperparameter.
NORMALIZED_CLIP_MAGNITUDE = 50.0


def normalize_window(dewowed: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Per-window robust z-score -- see module docstring. Clipped at +/-`NORMALIZED_CLIP_MAGNITUDE` -- see that constant's own docstring."""
    median = float(np.median(dewowed))
    mad = float(np.median(np.abs(dewowed - median)))
    scale = 1.4826 * mad + eps
    normalized = (dewowed - median) / scale
    return np.clip(normalized, -NORMALIZED_CLIP_MAGNITUDE, NORMALIZED_CLIP_MAGNITUDE)


def materialize_window(ref: SSLWindowRef) -> np.ndarray:
    """Real amplitude -> dewow -> per-window robust normalization. The one function every caller (training, evaluation, a future probe) uses, so no two call sites can silently diverge."""
    raw = ssl_corpus.read_window(ref)
    return normalize_window(dewow_window(raw))


class SSLWindowDataset(Dataset):
    """
    Wraps a list of `SSLWindowRef` into `(masked_input, target, mask)`
    torch tensors, each shape `(1, n_samples, n_traces)`
    (`masked_input`/`target`) or `(1, n_samples, n_traces)` bool (`mask`).
    `window_seed` for `generate_mask` is the window's own index in the
    list -- deterministic and reproducible given the same `refs` ordering.
    """
    def __init__(self, refs: list[SSLWindowRef], mask_config: MaskConfig = SSL_V1_DEFAULT_MASK_CONFIG):
        _require_torch()
        self.refs = refs
        self.mask_config = mask_config

    def __len__(self):
        return len(self.refs)

    def __getitem__(self, idx: int):
        ref = self.refs[idx]
        target = materialize_window(ref)
        mask = generate_mask(target.shape, self.mask_config, window_seed=idx)
        masked_input = apply_mask(target, mask, fill_value=0.0)
        return (
            torch.tensor(masked_input, dtype=torch.float32).unsqueeze(0),
            torch.tensor(target, dtype=torch.float32).unsqueeze(0),
            torch.tensor(mask, dtype=torch.bool).unsqueeze(0),
        )


@dataclass
class TrainingResult:
    train_losses: list[float] = field(default_factory=list)
    validation_losses: list[float] = field(default_factory=list)
    n_train_windows: int = 0
    n_validation_windows: int = 0


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ssl_corpus.REPO_ROOT, text=True,
        ).strip()
    except Exception:
        return "unknown"


def evaluate(model, refs: list[SSLWindowRef], mask_config: MaskConfig, device, loss_kind: str = "l1") -> float:
    """Mean masked reconstruction loss over `refs`, no gradient, `model.eval()`."""
    _require_torch()
    from training.ssl_model import masked_reconstruction_loss

    if not refs:
        return float("nan")
    model.eval()
    dataset = SSLWindowDataset(refs, mask_config)
    total, n = 0.0, 0
    with torch.no_grad():
        for i in range(len(dataset)):
            x, y, m = dataset[i]
            x, y, m = x.unsqueeze(0).to(device), y.unsqueeze(0).to(device), m.unsqueeze(0).to(device)
            pred = model(x)
            loss = masked_reconstruction_loss(pred, y, m, kind=loss_kind)
            total += float(loss.item())
            n += 1
    return total / n


def run_ssl_training(
    train_refs: list[SSLWindowRef],
    validation_refs: list[SSLWindowRef],
    *,
    base_channels: int = 8,
    mask_config: MaskConfig = SSL_V1_DEFAULT_MASK_CONFIG,
    epochs: int = 3,
    learning_rate: float = 1e-3,
    seed: int = 0,
    loss_kind: str = "l1",
    device_prefer: Optional[str] = None,
    max_train_windows: Optional[int] = None,
) -> tuple["torch.nn.Module", TrainingResult, SSLArtifactProvenance]:
    """
    The complete V1 training driver: one gradient step per window (batch
    size 1, matching `training.segmentation_model.train_one_epoch`'s own
    convention for real, variable-shape GPR windows -- avoids padding
    windows of equal size into a batch tensor when Section 7 already
    guarantees every window is `(sample_window, trace_window)`-uniform by
    construction, kept simple rather than adding a batching layer this
    corpus does not need at V1 scale). Returns the trained model, the loss
    history, and a complete `SSLArtifactProvenance`.
    """
    _require_torch()
    from training.ssl_model import (
        SSLAutoencoder, masked_reconstruction_loss, model_checksum, select_device, set_seed,
    )

    set_seed(seed)
    device = select_device(device_prefer)

    if max_train_windows is not None:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(train_refs), size=min(max_train_windows, len(train_refs)), replace=False)
        train_refs = [train_refs[i] for i in sorted(idx)]

    model = SSLAutoencoder(base_channels=base_channels).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    dataset = SSLWindowDataset(train_refs, mask_config)

    result = TrainingResult(n_train_windows=len(train_refs), n_validation_windows=len(validation_refs))
    for epoch in range(epochs):
        model.train()
        epoch_total, n = 0.0, 0
        order = np.random.default_rng(seed + epoch).permutation(len(dataset))
        for i in order:
            x, y, m = dataset[int(i)]
            x, y, m = x.unsqueeze(0).to(device), y.unsqueeze(0).to(device), m.unsqueeze(0).to(device)
            optimizer.zero_grad()
            pred = model(x)
            loss = masked_reconstruction_loss(pred, y, m, kind=loss_kind)
            loss.backward()
            optimizer.step()
            epoch_total += float(loss.item())
            n += 1
        result.train_losses.append(epoch_total / max(n, 1))
        result.validation_losses.append(evaluate(model, validation_refs, mask_config, device, loss_kind))

    all_refs = train_refs + validation_refs
    licenses = {r.dataset_id: (r.license or "unrecorded") for r in all_refs}
    commercial = all(r.license_pool == LicensePool.COMMERCIAL_COMPATIBLE for r in all_refs)

    provenance = SSLArtifactProvenance(
        architecture="GPREncoder(base_channels={})+SSLReconstructionDecoder (no skip connections)".format(base_channels),
        parameter_count=model.parameter_count,
        training_commit=_git_commit(),
        training_sites=sorted({r.site_id for r in train_refs}),
        validation_sites=sorted({r.site_id for r in validation_refs}),
        reserved_sites=sorted(ssl_corpus.RESERVED_DATASETS),
        licenses=licenses,
        commercial_use_status=(
            LicensePool.COMMERCIAL_COMPATIBLE if commercial else LicensePool.RESEARCH_ONLY
        ),
        preprocessing_version=PREPROCESSING_VERSION,
        normalization=NORMALIZATION_METHOD,
        masking_strategy=f"{mask_config.kind.value} ratio={mask_config.ratio} seed={mask_config.seed}",
        mask_ratio=mask_config.ratio,
        seed=seed,
        optimizer="Adam",
        learning_rate=learning_rate,
        epochs=epochs,
        batch_size=1,
        hardware=str(device),
        metrics={
            "final_train_loss": result.train_losses[-1] if result.train_losses else float("nan"),
            "final_validation_loss": result.validation_losses[-1] if result.validation_losses else float("nan"),
        },
        model_checksum_sha256=model_checksum(model),
        trained_utc=datetime.now(timezone.utc).isoformat(),
        limitations=(
            "Masked reconstruction only -- NOT validated for anomaly detection, object "
            "classification, site generalisation, or autonomous interpretation. The "
            "encoder has not been evaluated as a Detector V1 initialisation; see the "
            "milestone's own exploratory BAM probe (single site, single specimen's 4 "
            "targets) for the only downstream signal collected, itself not a "
            "generalisation claim."
        ),
    )
    return model, result, provenance
