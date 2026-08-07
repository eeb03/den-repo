"""
Null models for the GPR anomaly detector.

A null model answers: what does this detector produce from data whose
structure of interest has been destroyed, but which is otherwise identical?
Anything the detector reports at or below its null rate is consistent with
chance.

Both nulls preserve the line's exact dimensions and the exact multiset of
processed sample values; they differ in what they destroy.

TRACE-ORDER PERMUTATION (`trace_permutation`)
    Permutes whole traces. Every trace keeps its internal depth structure;
    only trace-to-trace ADJACENCY is destroyed. This is the appropriate null
    for statistics about lateral extent, because it changes which traces are
    neighbours without changing what a trace contains.

    It is exactly equivalent to permuting the RAW traces and re-running the
    entire pipeline: background removal subtracts a mean trace that is
    invariant under permutation, and dewow and gain are strictly per-trace.
    `assert_trace_permutation_equivalence` proves that rather than assuming
    it, so the cheap form can be used with confidence.

PER-DEPTH LATERAL PERMUTATION (`lateral_permutation`)
    Independently permutes values across traces within each depth row,
    preserving each row's marginal exactly and destroying ALL lateral
    coherence.

    CAUTION, measured: this null is NOT usable for width statistics. Removing
    lateral coherence RAISES z-scores, because the ring background stops
    resembling its centre cell. On real INGV lines the scrambled null put a
    supra-threshold cell in a median of ~80% of trace columns versus ~2%
    observed, so component width and contiguous-run statistics measure
    supra-threshold DENSITY under this null, not coherence. Use it for
    cell-clustering questions only.

This module MEASURES the detector. It never modifies it.
"""
from __future__ import annotations

import numpy as np

from validation.synthetic_targets import anomaly_grid, processed_stages


def trace_permutation(processed: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """One draw: permute whole traces of a processed (n_traces, n_samples) array."""
    arr = np.asarray(processed, dtype=float)
    return arr[rng.permutation(arr.shape[0])]


def lateral_permutation(processed: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """One draw: independently permute values across traces within each depth row."""
    return rng.permuted(np.asarray(processed, dtype=float), axis=0)


NULL_MODELS = {
    "trace_permutation": trace_permutation,
    "lateral_permutation": lateral_permutation,
}


def assert_trace_permutation_equivalence(raw: np.ndarray, rng: np.random.Generator) -> float:
    """
    Verifies that permuting raw traces then processing equals processing then
    permuting columns. Returns the max absolute difference, which must be at
    machine-precision level for the cheap null to be valid.
    """
    arr = np.asarray(raw, dtype=float)
    perm = rng.permutation(arr.shape[0])
    full = processed_stages(arr[perm])["gained"]
    shortcut = processed_stages(arr)["gained"][perm]
    return float(np.max(np.abs(full - shortcut)))


def null_distribution(
    processed: np.ndarray, statistic, n_draws: int, rng: np.random.Generator,
    null_model: str = "trace_permutation",
) -> np.ndarray:
    """
    Draws `n_draws` samples of `statistic(anomaly_grid)` under a null model.

    `statistic` takes the (n_depths, n_traces) anomaly grid and returns a
    float, so callers choose what to test without this module knowing about
    candidates, widths, or thresholds.
    """
    try:
        draw = NULL_MODELS[null_model]
    except KeyError:
        raise ValueError(f"Unknown null model {null_model!r}; options: {sorted(NULL_MODELS)}")
    arr = np.asarray(processed, dtype=float)
    return np.array([float(statistic(anomaly_grid(draw(arr, rng)))) for _ in range(n_draws)])


def empirical_p_value(observed: float, null_draws: np.ndarray) -> float:
    """
    One-sided p: the fraction of null draws at least as extreme as observed.

    Uses the (1 + count) / (1 + n) estimator, which never returns exactly
    zero -- a finite number of draws cannot establish that something is
    impossible, and reporting p = 0 would overstate the evidence.
    """
    draws = np.asarray(null_draws, dtype=float)
    return float((1 + int((draws >= observed).sum())) / (1 + draws.size))


def benjamini_hochberg(p_values, alpha: float = 0.05) -> list[int]:
    """
    Indices surviving Benjamini-Hochberg control of the false discovery rate.

    Necessary whenever many survey lines are tested at once: at alpha=0.05,
    50 independent lines produce ~2.5 nominally significant results by
    chance alone, so an uncorrected p-value is not evidence of anything.
    """
    ps = np.asarray(p_values, dtype=float)
    if ps.size == 0:
        return []
    order = np.argsort(ps)
    m = ps.size
    passing = [i for rank, i in enumerate(order, start=1) if ps[i] <= alpha * rank / m]
    if not passing:
        return []
    cutoff = max(rank for rank, i in enumerate(order, start=1) if ps[i] <= alpha * rank / m)
    return sorted(order[:cutoff].tolist())
