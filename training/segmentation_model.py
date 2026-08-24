"""
Learned Detector V1: the model architecture, loss, and training loop.

DELIBERATELY SEPARATE FROM `training/segmentation.py`. That module (dataset
construction, splitting, metrics, baseline comparison) runs on numpy alone
and stays usable with no ML framework installed. Everything in THIS module
needs `torch` -- an OPTIONAL dependency (`requirements.txt`, CPU-only
wheel), imported lazily and raising `MissingDependencyError` if absent,
exactly like `segyio`/`rasterio`/`laspy`/`obspy` already do in
`converters/`. Nothing elsewhere in this codebase is required to have
torch installed for anything else to work.

============================================================================
WHAT THIS MODULE DOES NOT CLAIM
============================================================================

This milestone's own data audit (see `training/segmentation.py`'s module
docstring) found exactly 4 real, trace-associated labelled targets in the
entire held GPR corpus, all in one BAM specimen -- not enough to define a
genuine held-out SITE split, and nowhere near enough for a statistically
meaningful segmentation-training claim. Per the milestone brief's own
Section 32, NO training run against this architecture is presented here as
validated evidence, and none is run "for real" in this codebase. What
exists here is the REUSABLE architecture/loss/training-loop code itself --
inspectable, and exercised only by fast, deterministic SANITY tests
(`tests/test_segmentation_model.py`: does gradient flow, does loss
decrease, can the model overfit a tiny synthetic fixture) that test the
CODE's correctness, not any claim about real GPR. See that test file's own
docstring for why a synthetic overfit test is legitimate software
verification and NOT scientific validation, and never presented as the
latter.

============================================================================
ARCHITECTURE CHOICE
============================================================================

A small U-Net, 3 encoder/decoder levels, base width 8 channels (121,385
parameters at these settings, confirmed by direct construction -- see
`TinyUNet.parameter_count`, and never restated as an approximation
somewhere else that could drift from it). Chosen over anything larger for
the reason the brief
itself states: with a labelled corpus this small, a bigger model can only
memorise, not learn -- there is no amount of regularisation that turns 4
targets into evidence a deep network's capacity would be justified by.
SegFormer/U-Net++/any transformer are explicitly NOT used: none is
justified by data this scarce, and choosing one anyway would be exactly
the "fashion, not evidence" the brief warns against.

============================================================================
LOSS
============================================================================

BCE + Dice, summed unweighted-but-named (`bce_dice_loss`). Segmentation
targets here are extremely imbalanced (this milestone's own real data: 73
positive cells out of 512*73 = 37,376 total, ~0.2%) -- plain BCE alone is
dominated by the negative class and Dice alone is unstable when a batch
has zero true positives (undefined gradient direction), so the sum uses
each loss where it is strong. Focal loss was considered and set aside: it
adds two more hyperparameters (gamma, alpha) that nothing in the real,
tiny corpus available here could be tuned against without overfitting the
tuning itself to 4 targets -- exactly the kind of unjustified precision
this project's own conventions refuse elsewhere.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

import numpy as np

from converters.base import MissingDependencyError

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


def _require_torch():
    if not _TORCH_AVAILABLE:
        raise MissingDependencyError(
            "torch is required for training.segmentation_model. Install with: "
            "pip install torch --extra-index-url https://download.pytorch.org/whl/cpu"
        )


def set_seed(seed: int) -> None:
    """Every source of randomness this module touches, in one place, so a caller need not hunt for a second one."""
    _require_torch()
    torch.manual_seed(seed)
    np.random.seed(seed)


if _TORCH_AVAILABLE:

    class _ConvBlock(nn.Module):
        def __init__(self, in_ch: int, out_ch: int):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, 3, padding=1), nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
                nn.Conv2d(out_ch, out_ch, 3, padding=1), nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
            )

        def forward(self, x):
            return self.net(x)

    class TinyUNet(nn.Module):
        """
        3-level U-Net, base width `base_channels` (default 8). Input:
        (batch, in_channels, H, W) -- H is the sample/depth axis, W the
        trace axis, matching `MaskRegion`'s (trace, sample) convention
        transposed to image orientation. Output: (batch, 1, H, W) LOGITS
        (not probabilities) -- callers apply `torch.sigmoid` themselves,
        so a loss function that expects logits (`bce_dice_loss` below) is
        never accidentally handed an already-squashed value.
        """
        def __init__(self, in_channels: int = 1, base_channels: int = 8):
            super().__init__()
            c = base_channels
            self.enc1 = _ConvBlock(in_channels, c)
            self.enc2 = _ConvBlock(c, c * 2)
            self.enc3 = _ConvBlock(c * 2, c * 4)
            self.pool = nn.MaxPool2d(2)
            self.bottleneck = _ConvBlock(c * 4, c * 8)
            self.up3 = nn.ConvTranspose2d(c * 8, c * 4, 2, stride=2)
            self.dec3 = _ConvBlock(c * 8, c * 4)
            self.up2 = nn.ConvTranspose2d(c * 4, c * 2, 2, stride=2)
            self.dec2 = _ConvBlock(c * 4, c * 2)
            self.up1 = nn.ConvTranspose2d(c * 2, c, 2, stride=2)
            self.dec1 = _ConvBlock(c * 2, c)
            self.out_conv = nn.Conv2d(c, 1, 1)

        def forward(self, x):
            e1 = self.enc1(x)
            e2 = self.enc2(self.pool(e1))
            e3 = self.enc3(self.pool(e2))
            b = self.bottleneck(self.pool(e3))
            d3 = self.dec3(torch.cat([self.up3(b), e3], dim=1))
            d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
            d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))
            return self.out_conv(d1)

        @property
        def parameter_count(self) -> int:
            return sum(p.numel() for p in self.parameters())

else:
    TinyUNet = None  # type: ignore[assignment,misc]


def bce_dice_loss(logits, target, eps: float = 1e-6):
    """BCE(logits, target) + (1 - soft Dice), both computed from the same logits -- see module docstring for why."""
    _require_torch()
    bce = F.binary_cross_entropy_with_logits(logits, target)
    probs = torch.sigmoid(logits)
    intersection = (probs * target).sum()
    dice = (2 * intersection + eps) / (probs.sum() + target.sum() + eps)
    return bce + (1 - dice)


@dataclass
class ConfidenceBucket:
    """
    Abstention support (milestone Section 18): a probability alone cannot
    tell a caller "high confidence" from "low but real" from "the model
    has no basis to say anything here" without a stated policy. This is
    that policy, as data, not a threshold buried in a UI.
    """
    low: float = 0.3
    high: float = 0.7

    def classify(self, probability: float) -> str:
        if probability >= self.high:
            return "high_confidence_evidence"
        if probability <= self.low:
            return "high_confidence_absence"
        return "low_confidence_unknown"


def predict_probabilities(model, signal: np.ndarray) -> np.ndarray:
    """
    Inference: (n_samples, n_traces) real amplitude in, (n_samples,
    n_traces) probabilities in [0, 1] out. Always `model.eval()` +
    `torch.no_grad()` -- inference must never update batch-norm running
    stats or accumulate a gradient graph.
    """
    _require_torch()
    model.eval()
    with torch.no_grad():
        x = torch.tensor(signal, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
        logits = model(x)
        probs = torch.sigmoid(logits).squeeze(0).squeeze(0).numpy()
    return probs


def train_one_epoch(model, optimizer, signal: np.ndarray, target: np.ndarray) -> float:
    """
    ONE gradient step on ONE (signal, target) pair -- deliberately this
    small and explicit, so `tests/test_segmentation_model.py`'s sanity
    tests (loss decreases; the model can overfit a tiny fixture) call
    exactly the same function a real training loop would, not a
    test-only shortcut that could drift from it.
    """
    _require_torch()
    model.train()
    x = torch.tensor(signal, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
    y = torch.tensor(target, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
    optimizer.zero_grad()
    logits = model(x)
    loss = bce_dice_loss(logits, y)
    loss.backward()
    optimizer.step()
    return float(loss.item())


def model_checksum(model) -> str:
    """SHA-256 over the model's own state_dict, byte-stable for a given set of weights -- what `ModelArtifactProvenance.model_checksum_sha256` records."""
    _require_torch()
    state = model.state_dict()
    h = hashlib.sha256()
    for key in sorted(state.keys()):
        h.update(key.encode())
        h.update(state[key].numpy().tobytes())
    return h.hexdigest()
