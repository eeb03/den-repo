"""
Self-Supervised GPR Encoder V1: data augmentation (Section 13).

SCOPE DECISION, recorded rather than silently applied or silently skipped.
Of the "potentially valid" list (amplitude scaling, additive noise, trace
dropout, controlled cropping, small global time shift), V1 implements ONLY
modest amplitude scaling:

  amplitude scaling   IMPLEMENTED. A real acquisition's coupling to the
                       ground/antenna contact varies survey to survey,
                       which really does rescale amplitude without
                       changing structure -- a defensible, minimal,
                       single-parameter augmentation.
  additive noise       NOT implemented. Would need a real, evidence-based
                       noise-floor estimate per vendor/instrument to avoid
                       inventing a noise characteristic this codebase has
                       not measured -- deferred, not fabricated.
  trace dropout        NOT implemented for V1: overlaps materially with
                       TRACE_BLOCK masking's own effect; adding both at
                       once in V1 would confound which one caused any
                       observed effect.
  cropping / time shift  NOT implemented: `training.ssl_corpus.
                       build_window_index`'s fixed-size, non-overlapping
                       windows already vary each window's absolute
                       position; a further per-epoch crop/shift is a
                       reasonable V2 addition, not required to ship V1.

This is a deliberately small module so the scope decision above stays
visible in one place, not spread across the training loop.
"""
from __future__ import annotations

import numpy as np


def amplitude_scale(signal: np.ndarray, window_seed: int, config_seed: int = 0,
                     low: float = 0.9, high: float = 1.1) -> np.ndarray:
    """
    Multiplies the whole window by one real scalar in `[low, high]`,
    deterministic given `(config_seed, window_seed)` -- same reproducibility
    contract as `training.ssl_masking.generate_mask`.
    """
    # 0x0A5CA1E ("amplitude scale") as a fixed integer tag distinguishing this
    # RNG stream from `ssl_masking.generate_mask`'s -- `default_rng` accepts
    # only integers/sequences of integers as a seed, not mixed-type tuples.
    rng = np.random.default_rng((config_seed, window_seed, 0x0A5CA1E))
    factor = rng.uniform(low, high)
    return signal * factor
