"""
Self-Supervised GPR Encoder V1: masking strategies over a real GPR window.

WHY NOT RANDOM INDEPENDENT PIXEL MASKING (Section 5's own instruction). A
radargram's information lives in REFLECTION CONTINUITY across neighbouring
traces and in the local temporal/depth structure of one trace -- randomly
scattered single-pixel holes are each trivially fillable by interpolating
their immediate neighbours (which survive independent-pixel masking with
near certainty), so the task would not force the network to use distant
context at all. Every strategy here masks a CONTIGUOUS region instead, so a
masked cell's nearest visible evidence is always at least one full block
away.

TWO STRATEGIES, ONE DEFAULT. `TRACE_BLOCK` (mask K contiguous traces, full
depth) is the V1 default: it forces reconstruction of an entire missing
trace from lateral reflection continuity in its NEIGHBOURING traces, the
strongest form of the "use neighbouring traces" instruction. `PATCH`
(a contiguous trace x time rectangle) is implemented as a configurable
alternative for future comparison, not the primary V1 run -- see
`SSL_V1_DEFAULT_MASK_CONFIG`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class MaskKind(str, Enum):
    #: K contiguous trace columns, every sample (full depth) masked.
    TRACE_BLOCK = "trace_block"
    #: K contiguous sample rows (a time/depth band), every trace masked.
    TIME_BAND = "time_band"
    #: One contiguous (traces x samples) rectangle.
    PATCH = "patch"


@dataclass(frozen=True)
class MaskConfig:
    """
    Every masking parameter this milestone uses, recorded as data (Section
    5's own "must be configurable and recorded in experiment provenance")
    rather than a magic number buried in a training loop.
    """
    kind: MaskKind = MaskKind.TRACE_BLOCK
    #: Fraction of the window's masked AXIS covered by masked block(s).
    #: Bounded to (0.05, 0.6): below 5% the task is too easy to be a useful
    #: pretraining signal (module docstring); above 60% too little visible
    #: context remains for reconstruction to be well-posed at all (Section
    #: 5's own "not so much that reconstruction becomes impossible").
    ratio: float = 0.3
    seed: int = 0

    def __post_init__(self):
        if not (0.05 <= self.ratio <= 0.6):
            raise ValueError(
                f"mask ratio {self.ratio} is outside the defensible (0.05, 0.6) band -- "
                f"too low and the model can win by copying visible neighbours; too high "
                f"and reconstruction is not well-posed"
            )


#: The V1 real training run's own configuration -- named so a caller (and
#: `SSLArtifactProvenance.masking_strategy`) can cite it directly rather
#: than restate the parameters.
SSL_V1_DEFAULT_MASK_CONFIG = MaskConfig(kind=MaskKind.TRACE_BLOCK, ratio=0.3, seed=0)


def generate_mask(shape: tuple[int, int], config: MaskConfig, window_seed: int) -> np.ndarray:
    """
    A boolean mask, `True` = masked (reconstruction target), shape
    `(n_samples, n_traces)`. Deterministic given `(config.seed,
    window_seed)` -- Section 29's "augmentation reproducibility with seed"
    test depends on this, and so does being able to re-derive exactly which
    cells any past experiment masked from its recorded seed alone.
    """
    n_samples, n_traces = shape
    rng = np.random.default_rng((config.seed, window_seed))
    mask = np.zeros(shape, dtype=bool)

    if config.kind == MaskKind.TRACE_BLOCK:
        block = max(1, round(n_traces * config.ratio))
        block = min(block, n_traces)
        start = int(rng.integers(0, n_traces - block + 1))
        mask[:, start:start + block] = True
    elif config.kind == MaskKind.TIME_BAND:
        block = max(1, round(n_samples * config.ratio))
        block = min(block, n_samples)
        start = int(rng.integers(0, n_samples - block + 1))
        mask[start:start + block, :] = True
    elif config.kind == MaskKind.PATCH:
        t_block = max(1, round(n_traces * (config.ratio ** 0.5)))
        s_block = max(1, round(n_samples * (config.ratio ** 0.5)))
        t_block, s_block = min(t_block, n_traces), min(s_block, n_samples)
        t0 = int(rng.integers(0, n_traces - t_block + 1))
        s0 = int(rng.integers(0, n_samples - s_block + 1))
        mask[s0:s0 + s_block, t0:t0 + t_block] = True
    else:
        raise ValueError(f"unknown mask kind {config.kind!r}")

    return mask


def apply_mask(signal: np.ndarray, mask: np.ndarray, fill_value: float = 0.0) -> np.ndarray:
    """
    The masked INPUT: real values outside `mask`, `fill_value` inside it.
    Never returns the original array in place -- a caller must not be able
    to accidentally mutate the real signal through this function's output.
    """
    out = signal.copy()
    out[mask] = fill_value
    return out
