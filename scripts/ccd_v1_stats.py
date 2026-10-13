"""
Exact small-sample statistics for CCD-V1 Stage 1 (docs/ccd-v1-stage0-1-protocol.md §C3).

Object-level units only: every function takes one value per object. With
4 vs 4 objects the exact null distribution of U is enumerated over all 70
splits; no normal approximation is used anywhere.
"""
from __future__ import annotations

import itertools
import math
from statistics import median


def mann_whitney_u(a: list[float], b: list[float]) -> float:
    """U for a over b: pairs with a > b, ties counting 1/2."""
    return sum(1.0 if x > y else 0.5 if x == y else 0.0 for x in a for y in b)


def exact_mann_whitney(a: list[float], b: list[float], alternative: str = "greater") -> dict:
    """Exact permutation p for U, enumerating every split of the pooled values.

    alternative: 'greater' (a tends to exceed b), 'less', or 'two-sided'
    (|U - n_a n_b / 2| at least as extreme)."""
    if alternative not in ("greater", "less", "two-sided"):
        raise ValueError(alternative)
    pooled, na, nb = list(a) + list(b), len(a), len(b)
    u_obs = mann_whitney_u(a, b)
    centre = na * nb / 2
    n_splits = extreme = 0
    for idx in itertools.combinations(range(na + nb), na):
        chosen = set(idx)
        u = mann_whitney_u([pooled[i] for i in idx], [pooled[i] for i in range(na + nb) if i not in chosen])
        n_splits += 1
        if alternative == "greater":
            extreme += u >= u_obs - 1e-12
        elif alternative == "less":
            extreme += u <= u_obs + 1e-12
        else:
            extreme += abs(u - centre) >= abs(u_obs - centre) - 1e-12
    diffs = sorted(x - y for x in a for y in b)
    return {"n_a": na, "n_b": nb, "U": u_obs, "auc": u_obs / (na * nb), "alternative": alternative,
            "p_exact": extreme / n_splits, "n_splits": n_splits,
            "min_attainable_p": (2 if alternative == "two-sided" else 1) / n_splits,
            "hodges_lehmann_shift": median(diffs),
            "pairwise_difference_range": [diffs[0], diffs[-1]],
            "range_confidence": 1 - 2 / n_splits}


def exact_binomial_upper(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Exact binomial interval by bisection on the binomial tails (no scipy needed)."""
    alpha = 1 - conf

    def tail_ge(p):
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))

    def tail_le(p):
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))

    def solve(f, target, increasing):
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if (f(mid) < target) == increasing:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(tail_ge, alpha / 2, True)
    upper = 1.0 if k == n else solve(tail_le, alpha / 2, False)
    return lower, upper
