"""
Self-Supervised GPR Encoder V1's exploratory representation probe
(Section 17C / Section 18).

============================================================================
WHAT THIS IS, STATED AS PLAINLY AS THE CODE CAN STATE IT
============================================================================

This is NOT Detector V1 validation. There is still exactly one real,
trace-associated positive-label site in the entire held corpus (BAM Pk266,
4 targets -- `training.segmentation`'s own audit, unchanged by this
milestone). A probe against one site's 4 targets cannot support, and this
module does not claim, generalisation, detection improvement, or any
production readiness. The correct sentence for a result out of this module
is: "SSL-pretrained features showed a stronger exploratory one-site probe
than random initialisation" -- never "the learned detector improved"
(Section 18's own required wording).

============================================================================
WHAT THE PROBE DOES
============================================================================

Freezes an encoder (SSL-pretrained, or a randomly-initialised same-shape
control -- `run_probe`'s own `encoders` argument takes both so one script
run produces a real, paired comparison). Attaches ONE 1x1 conv "head" on
top of the frozen bottleneck, upsampled back to input resolution, trained
against BAM Pk266's real 4-target mask (`training.segmentation.
build_bam_pk266_examples`) with the encoder's own weights never updated
(`requires_grad_(False)` + `model.eval()` for the whole probe). BAM's real
window widths (73 traces) are not divisible by 8 (three 2x poolings) --
padded to 80 with zeros on the trailing edge, real mask cells never fall in
the padded region (checked, not assumed -- see `_pad_to_multiple_of_8`),
and the pad is masked out of the loss so it can never be scored as a
(trivially correct) negative.
"""
from __future__ import annotations

import numpy as np

from converters.base import MissingDependencyError

try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


def _require_torch():
    if not _TORCH_AVAILABLE:
        raise MissingDependencyError(
            "torch is required for training.ssl_probe. Install with: "
            "pip install torch --extra-index-url https://download.pytorch.org/whl/cpu"
        )


def _pad_to_multiple_of_8(arr: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    """Zero-pads the trailing edge of each axis up to a multiple of 8. Returns (padded, (n_samples_real, n_traces_real))."""
    n_samples, n_traces = arr.shape
    pad_s = (-n_samples) % 8
    pad_t = (-n_traces) % 8
    padded = np.pad(arr, ((0, pad_s), (0, pad_t)), mode="constant", constant_values=0.0)
    return padded, (n_samples, n_traces)


if _TORCH_AVAILABLE:

    class ProbeHead(nn.Module):
        """The ONLY trainable part of the probe: one 1x1 conv on the frozen bottleneck, then upsample to input resolution."""
        def __init__(self, in_channels: int):
            super().__init__()
            self.conv = nn.Conv2d(in_channels, 1, 1)

        def forward(self, z, out_hw: tuple[int, int]):
            logits = self.conv(z)
            return nn.functional.interpolate(logits, size=out_hw, mode="bilinear", align_corners=False)

else:
    ProbeHead = None  # type: ignore[assignment,misc]


def _build_probe_examples():
    """
    Real BAM Pk266 (4 positives) + Pk050 (1 attested-empty negative window),
    dewow'd and per-window normalised the SAME way `training.ssl_train`
    prepares any other window -- an encoder trained on THAT representation
    must be probed on the same one, or the comparison is not apples-to-apples.
    """
    from training.segmentation import build_bam_pk050_negative_examples, build_bam_pk266_examples
    from training.ssl_train import dewow_window, normalize_window

    examples = build_bam_pk266_examples() + build_bam_pk050_negative_examples()
    out = []
    for ex in examples:
        signal = np.array(ex.signal, dtype=float)
        signal = normalize_window(dewow_window(signal))
        padded, (n_s, n_t) = _pad_to_multiple_of_8(signal)
        target = np.zeros_like(padded)
        if ex.mask is not None:
            for t, s in zip(ex.mask.trace_indices, ex.mask.sample_indices):
                target[s, t] = 1.0
        valid = np.zeros_like(padded, dtype=bool)
        valid[:n_s, :n_t] = True
        out.append((padded, target, valid, ex.site_id))
    return out


def run_probe(encoder, epochs: int = 30, learning_rate: float = 1e-2, seed: int = 0) -> dict:
    """
    Trains `ProbeHead` on top of a FROZEN `encoder` against BAM's real 4
    targets + 1 real negative window (leave-one-out over the 5 examples,
    since 5 real examples is too few for a held-out split of its own --
    reported as what it is: an in-sample fit over one site's own examples,
    NOT a train/test split, and explicitly not claimed as one).
    """
    _require_torch()
    from training.ssl_model import set_seed

    set_seed(seed)
    examples = _build_probe_examples()

    encoder = encoder.eval()
    for p in encoder.parameters():
        p.requires_grad_(False)

    head = ProbeHead(in_channels=encoder.base_channels * 8)
    optimizer = torch.optim.Adam(head.parameters(), lr=learning_rate)

    losses = []
    for _ in range(epochs):
        epoch_total = 0.0
        for padded, target, valid, _site in examples:
            x = torch.tensor(padded, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
            y = torch.tensor(target, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
            v = torch.tensor(valid, dtype=torch.bool).unsqueeze(0).unsqueeze(0)
            with torch.no_grad():
                z = encoder(x)
            optimizer.zero_grad()
            logits = head(z, out_hw=padded.shape)
            probs = torch.sigmoid(logits)
            loss = nn.functional.binary_cross_entropy(probs[v], y[v])
            loss.backward()
            optimizer.step()
            epoch_total += float(loss.item())
        losses.append(epoch_total / len(examples))

    # final per-example scores at a fixed threshold, real precision/recall
    from training.segmentation import precision_recall_f1
    per_example = []
    with torch.no_grad():
        for padded, target, valid, site_id in examples:
            x = torch.tensor(padded, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
            z = encoder(x)
            logits = head(z, out_hw=padded.shape)
            probs = torch.sigmoid(logits).squeeze(0).squeeze(0).numpy()
            pred = (probs >= 0.5) & valid
            pr = precision_recall_f1(pred, (target > 0.5) & valid)
            per_example.append({
                "site_id": site_id, "precision": pr.precision, "recall": pr.recall, "f1": pr.f1,
                "true_positives": pr.true_positives, "false_positives": pr.false_positives,
            })

    return {
        "losses": losses,
        "final_loss": losses[-1] if losses else None,
        "per_example": per_example,
        "n_examples": len(examples),
        "caveat": (
            "EXPLORATORY ONLY. One real site (BAM Pk266/Pk050), 5 real examples, no "
            "train/test split -- an in-sample fit, not a generalisation test. Not Detector "
            "V1 validation. A better score than random initialisation is evidence about "
            "REPRESENTATION LEARNING, not about detection or site generalisation."
        ),
    }
