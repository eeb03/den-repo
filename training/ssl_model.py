"""
Self-Supervised GPR Encoder V1: the encoder/decoder architecture, the
reconstruction loss, and device selection.

DELIBERATELY torch-OPTIONAL, exactly like `training/segmentation_model.py`:
lazily imported, raises `MissingDependencyError` if absent, nothing else in
this codebase requires torch to import successfully.

============================================================================
WHY THE DECODER HAS NO SKIP CONNECTIONS (Section 12's own requirement)
============================================================================

`training/segmentation_model.py`'s `TinyUNet` is a full U-Net: encoder
feature maps are concatenated directly into the decoder at every level, so
a masked region's information could reach the output through a SKIP PATH
that never passes through the bottleneck -- exactly the identity-copying
risk Section 12 names. `GPREncoder` below extracts ONLY that model's
encoder TOWER (same conv blocks, same channel widths, so weights transfer),
but `SSLReconstructionDecoder` takes ONLY the bottleneck output -- no
encoder feature map ever reaches the decoder directly. Combined with
zero-filling the masked region BEFORE it ever reaches the encoder
(`training.ssl_masking.apply_mask`), the masked region's true values are
never available to the network by any path except "infer them from the
compressed bottleneck representation of the whole window" -- which is
exactly the representation-learning task this milestone wants to force.

============================================================================
WHY THE ENCODER TAKES ONE CHANNEL, NOT A SIGNAL+MASK PAIR
============================================================================

A second "where is the mask" input channel is common in masked-autoencoder
literature and would make the reconstruction task slightly easier to pose.
It was NOT used here: Section 10 requires this exact encoder to become
Detector V1's initialisation later, and a future detector runs on ordinary,
unmasked real signal with no "which cells are masked" concept at all -- a
2-channel encoder could not be loaded there without discarding or
re-deriving its first conv layer's weights. Keeping `in_channels=1`
throughout means the encoder's weights are directly loadable by a
1-channel detector with no surgery. The network still has a real,
learnable signal for "where was this masked": zero is a value normal
dewow'd amplitude essentially never holds continuously across a whole
block (see `training.ssl_masking.apply_mask`'s own fill value), so the
network is not deprived of the information, only of an explicit channel
for it.
"""
from __future__ import annotations

import hashlib
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
            "torch is required for training.ssl_model. Install with: "
            "pip install torch --extra-index-url https://download.pytorch.org/whl/cpu"
        )


def set_seed(seed: int) -> None:
    _require_torch()
    torch.manual_seed(seed)
    np.random.seed(seed)


def select_device(prefer: Optional[str] = None) -> "torch.device":
    """
    Explicit `cuda` -> `mps` -> `cpu` fallback (Section 21). `prefer`
    forces one choice (raises if unavailable) -- used by tests to pin `cpu`
    deterministically; production code calls this with no argument.
    """
    _require_torch()
    if prefer is not None:
        if prefer == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("cuda requested but not available")
        if prefer == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            raise RuntimeError("mps requested but not available")
        return torch.device(prefer)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


if _TORCH_AVAILABLE:

    class _ConvBlock(nn.Module):
        """Identical shape to `training.segmentation_model._ConvBlock` -- kept separate so neither module depends on the other's internals changing."""
        def __init__(self, in_ch: int, out_ch: int):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, 3, padding=1), nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
                nn.Conv2d(out_ch, out_ch, 3, padding=1), nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
            )

        def forward(self, x):
            return self.net(x)

    class GPREncoder(nn.Module):
        """
        The reusable encoder tower: 3 conv-block/pool stages down to a
        bottleneck, structurally identical to `TinyUNet`'s own encoder half
        (same widths, same blocks) so a Detector V1 built later as a
        `TinyUNet`-shaped model can load these exact weights into its own
        `enc1`/`enc2`/`enc3`/`bottleneck` by name. Input: `(batch, 1, H, W)`.
        Output: `(batch, base_channels * 8, H/8, W/8)` -- the latent GPR
        representation Section 9's diagram names.
        """
        def __init__(self, in_channels: int = 1, base_channels: int = 8):
            super().__init__()
            c = base_channels
            self.enc1 = _ConvBlock(in_channels, c)
            self.enc2 = _ConvBlock(c, c * 2)
            self.enc3 = _ConvBlock(c * 2, c * 4)
            self.pool = nn.MaxPool2d(2)
            self.bottleneck = _ConvBlock(c * 4, c * 8)
            self.base_channels = base_channels

        def forward(self, x):
            e1 = self.enc1(x)
            e2 = self.enc2(self.pool(e1))
            e3 = self.enc3(self.pool(e2))
            return self.bottleneck(self.pool(e3))

        @property
        def parameter_count(self) -> int:
            return sum(p.numel() for p in self.parameters())

    class SSLReconstructionDecoder(nn.Module):
        """
        NO skip connections -- see module docstring. Three transpose-conv
        upsamples (mirroring the encoder's three poolings) back to the
        input's (H, W), ending in a single-channel LINEAR output (this is
        regression, not classification -- no sigmoid/softmax).
        """
        def __init__(self, base_channels: int = 8):
            super().__init__()
            c = base_channels
            self.up3 = nn.ConvTranspose2d(c * 8, c * 4, 2, stride=2)
            self.dec3 = _ConvBlock(c * 4, c * 4)
            self.up2 = nn.ConvTranspose2d(c * 4, c * 2, 2, stride=2)
            self.dec2 = _ConvBlock(c * 2, c * 2)
            self.up1 = nn.ConvTranspose2d(c * 2, c, 2, stride=2)
            self.dec1 = _ConvBlock(c, c)
            self.out_conv = nn.Conv2d(c, 1, 1)

        def forward(self, z):
            d3 = self.dec3(self.up3(z))
            d2 = self.dec2(self.up2(d3))
            d1 = self.dec1(self.up1(d2))
            return self.out_conv(d1)

    class SSLAutoencoder(nn.Module):
        """
        `encoder` + `decoder`, kept as separate named submodules (never
        merged into one sequential) so `save_encoder_only`/`load_ssl_encoder`
        below can address `self.encoder`'s state dict alone -- Section 10's
        "encoder separate from pretraining head" requirement, enforced by
        the module structure itself, not just a naming convention.
        """
        def __init__(self, base_channels: int = 8):
            super().__init__()
            self.encoder = GPREncoder(in_channels=1, base_channels=base_channels)
            self.decoder = SSLReconstructionDecoder(base_channels=base_channels)

        def forward(self, masked_input):
            z = self.encoder(masked_input)
            return self.decoder(z)

        @property
        def parameter_count(self) -> int:
            return sum(p.numel() for p in self.parameters())

else:
    GPREncoder = None  # type: ignore[assignment,misc]
    SSLReconstructionDecoder = None  # type: ignore[assignment,misc]
    SSLAutoencoder = None  # type: ignore[assignment,misc]


def masked_reconstruction_loss(pred, target, mask, kind: str = "l1"):
    """
    Scored ONLY on masked cells (Section 11: "prefer scoring masked regions
    so the network cannot win by copying visible inputs") -- unmasked cells
    never contribute to the gradient at all. `mask`: bool tensor, same
    (batch, 1, H, W) shape as `pred`/`target`, `True` = masked = scored.
    """
    _require_torch()
    mask_f = mask.float()
    n = mask_f.sum().clamp(min=1.0)
    diff = pred - target
    if kind == "l1":
        loss = (diff.abs() * mask_f).sum() / n
    elif kind == "mse":
        loss = ((diff ** 2) * mask_f).sum() / n
    elif kind == "huber":
        loss = (F.huber_loss(pred, target, reduction="none") * mask_f).sum() / n
    else:
        raise ValueError(f"unknown loss kind {kind!r}")
    return loss


def save_encoder_only(encoder, path: str) -> str:
    """Persists ONLY the encoder's state dict -- never the decoder's, so a downstream loader cannot accidentally depend on pretraining-only weights."""
    _require_torch()
    torch.save(encoder.state_dict(), path)
    return path


def load_ssl_encoder(path: str, base_channels: int = 8, map_location: str = "cpu"):
    """The stable interface Section 10 requires: `encoder = load_ssl_encoder(path)`, importable with no reference to `SSLReconstructionDecoder` at all."""
    _require_torch()
    encoder = GPREncoder(in_channels=1, base_channels=base_channels)
    state = torch.load(path, map_location=map_location, weights_only=True)
    encoder.load_state_dict(state)
    return encoder


def model_checksum(model) -> str:
    _require_torch()
    state = model.state_dict()
    h = hashlib.sha256()
    for key in sorted(state.keys()):
        h.update(key.encode())
        h.update(state[key].detach().cpu().numpy().tobytes())
    return h.hexdigest()
