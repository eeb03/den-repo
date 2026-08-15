"""
How much ground truth is needed before a detector improvement can be believed?

THE QUESTION STAGE 14 ASKS. Not "is the detector good" but "if it got better,
would this benchmark notice?" Those are different questions, and the second has
an answer that does not depend on any detector: it depends on how many
independent units the benchmark holds and how they are split between present and
absent.

WHY AUC AND NOT PRECISION/RECALL. The 4TU truth is a per-activity count with no
coordinates, so no candidate can be matched to a utility and precision has no
denominator that means what it usually means (`benchmark.gates` blocks
object-level scoring for exactly this reason). What the corpus does support is
whether candidate DENSITY separates trench-occupied from trench-empty ground,
which is a rank comparison -- and the Mann-Whitney statistic behind that is the
AUC. So the power question is a power question about AUC.

THE VARIANCE MODEL. Hanley & McNeil (1982) give the standard error of an AUC
estimated from n_p positive and n_n negative units, using the exponential
approximation for the two conditional variance terms:

    Q1 = A / (2 - A)              Q2 = 2A^2 / (1 + A)
    SE = sqrt( [A(1-A) + (n_p - 1)(Q1 - A^2) + (n_n - 1)(Q2 - A^2)] / (n_p n_n) )

It is an approximation and this module says so rather than presenting its output
as exact. Two properties make it the right tool anyway: it is standard,
publicly checkable, and it depends on the sample sizes in the way that matters
here -- SE is dominated by the SMALLER group, which is precisely the situation a
corpus with 112 positives and 7 negatives is in.

A BOOTSTRAP CROSS-CHECK IS ALSO PROVIDED, because an approximation used to
decide "we need more data" should be verified against the data actually held.
`artifacts/benchmark/power.json` reports both.

WHAT THIS DOES NOT DO. It does not choose what improvement is worth detecting.
That is a judgement about the application -- how much better a detector must be
before anybody should care -- and it is an argument, not a computation. The
module takes it as an input and records the value used, so a reader can disagree
with the premise instead of having to reverse-engineer it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

#: Two-sided alpha and the power convention this analysis reports at. Stated as
#: constants so the numbers cannot drift between the code and the write-up.
DEFAULT_ALPHA = 0.05
DEFAULT_POWER = 0.80

#: The improvements the readiness report asks about. 0.60 is a detector that is
#: noticeably better than chance; 0.70 is one that is clearly useful. Neither is
#: a target Subterra has committed to -- they are reference points chosen to
#: bracket "worth caring about", and the report states them as such.
REFERENCE_AUCS = (0.60, 0.65, 0.70, 0.75)


def _z(p: float) -> float:
    """
    Inverse standard normal CDF (Acklam's rational approximation).

    Implemented here rather than pulled from scipy.stats because `benchmark`
    currently depends on scipy only for `ndimage`, and a one-function
    dependency on the stats subpackage is not worth the coupling. Accurate to
    better than 1.15e-9 over the range, which is far past what a sample-size
    recommendation can use.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"probability out of range: {p}")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5])*q / \
           (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)


#: Below this, the Hanley-McNeil formula is degenerate rather than merely
#: imprecise: both conditional-variance terms are multiplied by (n - 1), so a
#: group of one contributes NO variance and the formula reports a confidently
#: small error from a single observation. With 1 positive and 1 negative it
#: claims an AUC of 0.97 is distinguishable from chance, which is nonsense. Two
#: per group is the minimum at which the expression means anything.
MIN_GROUP_FOR_VARIANCE = 2


def auc_standard_error(auc: float, n_positive: int, n_negative: int) -> Optional[float]:
    """
    Hanley-McNeil standard error.

    None when either group is too small for the formula to carry meaning --
    which is an answer ("this cannot be estimated"), not a failure. Returning a
    number here would be worse than returning nothing.
    """
    if n_positive < MIN_GROUP_FOR_VARIANCE or n_negative < MIN_GROUP_FOR_VARIANCE:
        return None
    a = auc
    q1 = a / (2.0 - a)
    q2 = 2.0 * a * a / (1.0 + a)
    numerator = (a * (1 - a)
                 + (n_positive - 1) * (q1 - a * a)
                 + (n_negative - 1) * (q2 - a * a))
    return math.sqrt(max(numerator, 0.0) / (n_positive * n_negative))


def detectable_auc(n_positive: int, n_negative: int,
                   alpha: float = DEFAULT_ALPHA,
                   power: float = DEFAULT_POWER) -> Optional[float]:
    """
    The smallest AUC this many units could distinguish from chance.

    Solved by bisection rather than in closed form because the standard error
    itself depends on the AUC being tested, so there is no clean inversion.
    Returns None if even a perfect detector could not clear the bar -- which is
    a real and important answer for a very small corpus, not an error.
    """
    if n_positive < MIN_GROUP_FOR_VARIANCE or n_negative < MIN_GROUP_FOR_VARIANCE:
        return None
    threshold = _z(1 - alpha / 2.0) + _z(power)

    def clears(a: float) -> bool:
        se = auc_standard_error(a, n_positive, n_negative)
        return se is not None and se > 0 and (a - 0.5) / se >= threshold

    if not clears(0.999):
        return None
    lo, hi = 0.5, 0.999
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if clears(mid):
            hi = mid
        else:
            lo = mid
    return hi


def negatives_required(target_auc: float, n_positive: int,
                       alpha: float = DEFAULT_ALPHA,
                       power: float = DEFAULT_POWER,
                       limit: int = 100_000) -> Optional[int]:
    """
    How many independent NEGATIVE units are needed to detect `target_auc`.

    Negatives rather than positives because that is the binding constraint
    here: the corpus holds 112 of one and a handful of the other, and adding
    positives to a corpus starved of negatives buys almost nothing. Returns
    None if the target is unreachable within `limit`.
    """
    if n_positive < MIN_GROUP_FOR_VARIANCE:
        return None
    threshold = _z(1 - alpha / 2.0) + _z(power)
    for n_negative in range(MIN_GROUP_FOR_VARIANCE, limit + 1):
        se = auc_standard_error(target_auc, n_positive, n_negative)
        if se and (target_auc - 0.5) / se >= threshold:
            return n_negative
    return None


@dataclass(frozen=True)
class PowerAssessment:
    """What the benchmark can and cannot resolve, at its current size."""
    benchmark: str
    n_positive: int
    n_negative: int
    alpha: float
    power: float
    #: The smallest true AUC that would be distinguishable from chance here.
    smallest_detectable_auc: Optional[float]
    #: target AUC -> negatives needed (None where unreachable).
    negatives_required: dict[float, Optional[int]]
    #: Half-width of the interval around a chance-level observation.
    se_at_chance: Optional[float]
    method: str = ("Hanley & McNeil (1982) exponential approximation to the "
                   "variance of an AUC; two-sided test against 0.5")
    caveat: str = ("An approximation, and a sample-size recommendation is not a "
                   "guarantee. It also assumes the units are independent -- which "
                   "is why the duplicate audit runs first and contaminated units "
                   "are removed before these counts are taken.")

    @property
    def adequate(self) -> bool:
        """
        Can this benchmark recognise an improvement worth caring about?

        Anchored at 0.70 -- a detector that is clearly useful rather than
        marginally above chance. If a corpus cannot resolve even that, it cannot
        resolve anything subtler, and the honest report is that detector work
        cannot yet be evaluated.
        """
        smallest = self.smallest_detectable_auc
        return smallest is not None and smallest <= 0.70

    def as_dict(self) -> dict:
        return {
            "benchmark": self.benchmark,
            "n_positive": self.n_positive,
            "n_negative": self.n_negative,
            "alpha": self.alpha,
            "power": self.power,
            "smallest_detectable_auc": self.smallest_detectable_auc,
            "negatives_required": {str(k): v for k, v in self.negatives_required.items()},
            "se_at_chance": self.se_at_chance,
            "adequate_for_a_useful_detector": self.adequate,
            "adequacy_anchor": "AUC 0.70, a clearly useful detector rather than a marginal one",
            "method": self.method,
            "caveat": self.caveat,
        }


def assess(benchmark: str, n_positive: int, n_negative: int,
           alpha: float = DEFAULT_ALPHA,
           power: float = DEFAULT_POWER,
           reference_aucs: Sequence[float] = REFERENCE_AUCS) -> PowerAssessment:
    return PowerAssessment(
        benchmark=benchmark,
        n_positive=n_positive,
        n_negative=n_negative,
        alpha=alpha,
        power=power,
        smallest_detectable_auc=detectable_auc(n_positive, n_negative, alpha, power),
        negatives_required={
            auc: negatives_required(auc, n_positive, alpha, power)
            for auc in reference_aucs
        },
        se_at_chance=auc_standard_error(0.5, n_positive, n_negative),
    )
