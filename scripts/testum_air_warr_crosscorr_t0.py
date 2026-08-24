"""
Can waveform cross-correlation recover an independent TestUM t0 from the
published air-WARR calibration files, and if so, does fixing that t0 break
the t0/velocity confound found in the crosshole audit?

THIS IS A RESEARCH AUDIT, NOT A PRODUCT FEATURE. It reads the real archive
already on disk (`datasets/raw/pangaea/971978/`), reuses
`scripts.testum_air_warr_t0`'s DZT reader and file index (never rewriting
working code) and `scripts.testum_crosshole_velocity_audit`'s crosshole
picking and geometry (same reason), touches no `SubterraRecord`, no
converter, no provenance schema, no live dataset, and writes only a JSON
artifact under `artifacts/testum/`. Reproduce with:

    python -m scripts.testum_air_warr_crosscorr_t0 --out artifacts/testum/testum_air_warr_t0_velocity_audit.json

WHY THIS EXPERIMENT, AND WHAT IT BUILDS ON.
`docs/testum-air-warr-t0-experiment.md` fitted t0 from ABSOLUTE picks on
each of an air-WARR file's 11-16 traces independently: 25/26 files
analysed, only 2 passed the physics falsifier (fitted slope must equal
1/c_air = 3.336 ns/m), and the two survivors disagreed by 1.12 ns. Its own
"Recommended next experiment" section proposed exactly what this script
does: detrend, cross-correlate every trace against the X=3 m reference (the
authors' own near-field-avoidance rule), and anchor the resulting RELATIVE
alignment with a single absolute pick -- keeping the same slope falsifier.

WHAT WAS FOUND BEFORE WRITING THE ACCEPTANCE RULES, AND WHY THEY ARE WHAT
THEY ARE. Probing real files first (not assumed) showed the recommended
approach only partly works: traces within about 0.2-0.4 m of the X=3 m
reference correlate cleanly (positive peak, ncc 0.85-1.0, observed shift
close to the physically expected L/c_air). Traces farther from the
reference frequently lock onto the WRONG half-cycle of the oscillatory
air-coupling wavelet -- observed shifts near double the expected value, or
with the wrong sign, and correspondingly NEGATIVE peak correlation (an
anti-phase "match"). This is cycle-skipping, a known failure mode of
waveform cross-correlation on band-limited oscillatory signals, and it is
why the acceptance gate below rejects on peak-correlation SIGN AND
MAGNITUDE ALONE (data-intrinsic, never using the expected shift to decide
what to keep) before the slope check is ever applied -- exactly mirroring
the original script's median/MAD rejection, which is also data-intrinsic
and applied before its own falsifier.

WHAT THIS MEANS THE EXPERIMENT CAN AND CANNOT CLAIM. Cross-correlation
gives a genuinely more precise RELATIVE shift between two traces that are
both cleanly correlated -- typically only the closest 1-3 trace pairs per
file survive the gate, not all 10-15. An ABSOLUTE t0 still requires one
amplitude-based pick (on the reference trace, using the SAME global-peak-
deviation method `testum_crosshole_velocity_audit.py::pick_arrival` uses,
bounded to a search window that is physically necessary for AIR at 3 m --
about 10 ns -- never a subsurface assumption). If that combination does not
survive the slope falsifier across enough files, the honest conclusion is
that cross-correlation improves relative precision without resolving
absolute t0, and this script says so rather than reporting a number anyway.

WHAT THIS DOES NOT DO. It does not touch SubterraRecord, any converter, any
provenance schema, or the roadmap. It does not refit t0 jointly with
velocity in Phase 4 -- t0 is fixed from Phase 2-3's result (or reported
absent) and only v is estimated. It never calls a derived number "measured"
or "validated": TestUM still has no independently surveyed reflector/depth
truth, so even an identifiable fixed-t0 velocity is capped short of
verified=True (see `classify_overall`).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from scripts.testum_air_warr_t0 import (
    C_AIR,
    MARKER_SAMPLES,
    METADATA,
    RAW_DIR as CALIBRATION_RAW_DIR,
    load_index,
    parse_protocol,
    read_dzt as read_calibration_dzt,
)
from scripts.testum_crosshole_velocity_audit import (
    C_M_PER_NS,
    RAW_DIR as CROSSHOLE_RAW_DIR,
    AuditError,
    PairResult,
    analyse_pair,
    load_well_coordinates,
    relative_permittivity,
    surveyed_separation_m,
    PAIR_FILES,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Peak normalised cross-correlation below this is not accepted as a genuine
#: waveform match at all (weak/no coherent signal). Chosen from the real
#: data probed while writing this script: the clean, physically-consistent
#: observations (traces near the X=3 m reference) reached 0.85-1.0; the
#: cycle-skipped ones that disagreed with physics scored 0.4-0.68 or
#: negative. 0.75 sits between the two clusters, data-intrinsic -- it does
#: not reference the expected shift.
MIN_PEAK_NCC = 0.75
#: A negative peak correlation means the "best match" found is anti-phase
#: with the reference -- an oscillatory wavelet's OTHER half-cycle, not a
#: genuine alignment. Rejected unconditionally, independent of magnitude.
REQUIRE_POSITIVE_NCC = True
#: Cross-correlation search bound, in samples, generous relative to the
#: largest physically possible air-path shift at these separations
#: (<=6.7 ns) but small enough to avoid the trace's own far reverberation.
MAX_LAG_SAMPLES = 300
#: Detrending order for the smooth baseline documented in
#: docs/testum-air-warr-t0-experiment.md ("large, smoothly varying
#: baseline"). A cubic captures a slow RC-like curve without absorbing the
#: much faster wavelet oscillation itself (confirmed on real traces before
#: use: the wavelet's own period is a handful of samples, the baseline's is
#: hundreds).
DETREND_DEGREE = 3
#: Minimum points, spanning more than one separation, to attempt a slope
#: fit per file -- mirrors the original script's "at least 3" for a
#: meaningful regression, not a tuned threshold.
MIN_POINTS_FOR_SLOPE_FIT = 3
#: Mirrors testum_air_warr_t0.py exactly: the recovered slope must be
#: within this of 1/c_air for the file's geometry/units/picking to be
#: trusted at all.
SLOPE_ERROR_PCT_THRESHOLD = 5.0
#: The propagation medium for the reference pick is air; at X=3 m the
#: expected one-way travel time is 3.0/c_air ~= 10.01 ns. The search window
#: is bounded generously around that physical fact (not a subsurface
#: assumption -- see module docstring) rather than left unconstrained,
#: which would let the picker lock onto the same baseline artefacts that
#: broke the original script. The lower bound is set at 7 ns, not 0: the
#: REFERENCE trace's own separation is always ~3 m, whose minimum possible
#: air-path time (3.0/c_air) is ~10.01 ns, so everything before ~7 ns is
#: safely pre-arrival for THIS trace specifically -- widening the quiet
#: region used for the noise-floor estimate from a statistically fragile
#: ~15-25 samples to ~70-95, without touching the actual search range.
REFERENCE_SEARCH_LO_NS = 7.0
REFERENCE_SEARCH_HI_NS = 30.0
MIN_REFERENCE_PICK_CONFIDENCE = 5.0


class ExperimentError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Phase 2 -- cross-correlation relative alignment
# ---------------------------------------------------------------------------

def detrend(trace: list[float], degree: int = DETREND_DEGREE) -> np.ndarray:
    """Removes the documented smooth baseline; keeps the wavelet's own oscillation."""
    y = np.asarray(trace[MARKER_SAMPLES:], dtype=float)
    x = np.arange(len(y))
    coeffs = np.polyfit(x, y, degree)
    return y - np.polyval(coeffs, x)


@dataclass
class CorrelationResult:
    lag_samples: float
    lag_ns: float
    peak_ncc: float
    accepted: bool
    reason: str


def cross_correlate(reference: np.ndarray, other: np.ndarray, dt_ns: float,
                    max_lag_samples: int = MAX_LAG_SAMPLES) -> CorrelationResult:
    """
    The lag (sub-sample, via parabolic interpolation of the correlation
    peak) that best aligns `other` with `reference`, and whether it is
    trustworthy on DATA-INTRINSIC grounds alone -- peak sign and magnitude,
    never the expected physical shift (see module docstring on why: using
    the expected answer to decide what counts as evidence would be exactly
    the circularity this whole line of work refuses).
    """
    n = min(len(reference), len(other))
    ref, oth = reference[:n], other[:n]
    norm = math.sqrt(float(np.sum(ref ** 2)) * float(np.sum(oth ** 2)))
    if norm == 0:
        return CorrelationResult(0.0, 0.0, 0.0, False, "zero-energy trace")

    full = np.correlate(ref, oth, mode="full")
    lags = np.arange(-(len(oth) - 1), len(ref))
    mask = np.abs(lags) <= max_lag_samples
    corr, lag_vals = full[mask], lags[mask]

    best_i = int(np.argmax(np.abs(corr)))
    peak_ncc = float(corr[best_i] / norm)

    # Sub-sample refinement: parabolic interpolation using the peak's two
    # neighbours, skipped at the search-window edge where it is undefined.
    lag = float(lag_vals[best_i])
    if 0 < best_i < len(corr) - 1:
        y0, y1, y2 = corr[best_i - 1], corr[best_i], corr[best_i + 1]
        denom = (y0 - 2 * y1 + y2)
        if denom != 0:
            lag += 0.5 * (y0 - y2) / denom

    if REQUIRE_POSITIVE_NCC and peak_ncc <= 0:
        return CorrelationResult(lag, lag * dt_ns, peak_ncc, False,
                                 f"peak correlation is non-positive ({peak_ncc:.3f}): likely an "
                                 f"anti-phase (cycle-skipped) match, not a genuine alignment")
    if abs(peak_ncc) < MIN_PEAK_NCC:
        return CorrelationResult(lag, lag * dt_ns, peak_ncc, False,
                                 f"peak correlation {peak_ncc:.3f} below the {MIN_PEAK_NCC} "
                                 f"data-intrinsic quality gate")
    return CorrelationResult(lag, lag * dt_ns, peak_ncc, True, "accepted")


# ---------------------------------------------------------------------------
# reference-trace absolute pick (air path, X=3 m, bounded by physics of air)
# ---------------------------------------------------------------------------

@dataclass
class ReferencePick:
    time_ns: float
    confidence: float
    accepted: bool
    reason: str


def pick_reference_absolute_time(reference: np.ndarray, dt_ns: float) -> ReferencePick:
    """
    The reference trace's own absolute arrival time, by the same global-
    peak-deviation-from-noise-floor rule
    `testum_crosshole_velocity_audit.py::pick_arrival` uses for crosshole
    data -- bounded to the window physically necessary for an AIR path at
    X=3 m (~10 ns one-way), which is a fact about air, not the ground.
    """
    lo = max(1, int(REFERENCE_SEARCH_LO_NS / dt_ns))
    hi = min(len(reference) - 1, int(REFERENCE_SEARCH_HI_NS / dt_ns))
    if hi - lo < 5:
        return ReferencePick(0.0, 0.0, False, "search window too narrow for this file's sampling")

    quiet = reference[:lo]
    if len(quiet) < 5:
        return ReferencePick(0.0, 0.0, False, "no quiet region before the search window")
    mean = float(np.mean(quiet))
    sd = float(np.std(quiet)) or 1.0

    window = reference[lo:hi]
    peak_i = int(np.argmax(np.abs(window - mean)))
    peak_val = window[peak_i]
    confidence = abs(peak_val - mean) / sd
    idx = lo + peak_i
    time_ns = (idx + MARKER_SAMPLES) * dt_ns

    if confidence < MIN_REFERENCE_PICK_CONFIDENCE:
        return ReferencePick(time_ns, confidence, False,
                             f"reference pick confidence {confidence:.2f} below "
                             f"{MIN_REFERENCE_PICK_CONFIDENCE}")
    return ReferencePick(time_ns, confidence, True, "accepted")


# ---------------------------------------------------------------------------
# per-file cross-correlation t0 estimate
# ---------------------------------------------------------------------------

@dataclass
class TraceObservation:
    trace_index: int
    separation_m: float
    expected_shift_ns: float
    correlation: CorrelationResult
    implied_absolute_time_ns: Optional[float]


@dataclass
class FileResult:
    file_name: str
    date: str
    slot: str
    x_start_m: float
    x_end_m: float
    dx_m: float
    n_traces: int
    reference_index: int
    reference_pick: ReferencePick
    observations: list  # TraceObservation, all traces including reference
    n_accepted: int
    n_rejected: int
    slope_fit_attempted: bool
    fitted_slope_ns_per_m: Optional[float]
    fitted_t0_ns: Optional[float]
    slope_error_pct: Optional[float]
    geometry_confirmed: bool
    usable: bool
    reason: str


def analyse_calibration_file(path: Path, date: str, slot: str, comment: str) -> Optional[FileResult]:
    protocol = parse_protocol(comment)
    if protocol is None:
        return None
    x0, x1, dx = protocol
    traces, dt = read_calibration_dzt(path)
    n = len(traces)
    if n < 3:
        return FileResult(path.name, date, slot, x0, x1, dx, n, -1,
                          ReferencePick(0.0, 0.0, False, "n/a"), [], 0, 0, False, None, None, None,
                          False, False, f"only {n} traces in file")

    separations = [x0 + k * dx for k in range(n)]
    # Reference: the trace whose separation is closest to the authors' own
    # X=3 m near-field-avoidance rule -- not assumed to be the last trace,
    # verified per file.
    ref_idx = int(np.argmin([abs(s - 3.0) for s in separations]))
    detrended = [detrend(t) for t in traces]
    reference = detrended[ref_idx]

    ref_pick = pick_reference_absolute_time(reference, dt)

    observations: list[TraceObservation] = []
    for k in range(n):
        expected_shift = (separations[ref_idx] - separations[k]) / C_AIR
        if k == ref_idx:
            corr = CorrelationResult(0.0, 0.0, 1.0, True, "is the reference trace")
        else:
            corr = cross_correlate(reference, detrended[k], dt)
        implied_time = None
        if ref_pick.accepted and corr.accepted:
            # reference arrives `corr.lag_ns` AFTER this trace (ref is farther,
            # for k != ref_idx; corr.lag_ns is 0 for k == ref_idx by construction).
            implied_time = ref_pick.time_ns - corr.lag_ns
        observations.append(TraceObservation(k, separations[k], expected_shift, corr, implied_time))

    accepted = [o for o in observations if o.correlation.accepted and o.implied_absolute_time_ns is not None]
    n_rejected = n - len(accepted)

    if not ref_pick.accepted:
        return FileResult(path.name, date, slot, x0, x1, dx, n, ref_idx, ref_pick,
                          [asdict_obs(o) for o in observations], len(accepted), n_rejected,
                          False, None, None, None, False, False,
                          f"reference trace pick failed: {ref_pick.reason}")

    if len(accepted) < MIN_POINTS_FOR_SLOPE_FIT or len({round(o.separation_m, 3) for o in accepted}) < 2:
        return FileResult(path.name, date, slot, x0, x1, dx, n, ref_idx, ref_pick,
                          [asdict_obs(o) for o in observations], len(accepted), n_rejected,
                          False, None, None, None, False, False,
                          f"only {len(accepted)} accepted observation(s) spanning "
                          f"{len({round(o.separation_m, 3) for o in accepted})} distinct separation(s); "
                          f"need >={MIN_POINTS_FOR_SLOPE_FIT} spanning >=2")

    xs = np.array([o.separation_m for o in accepted])
    ts = np.array([o.implied_absolute_time_ns for o in accepted])
    mx, mt = xs.mean(), ts.mean()
    sxx = float(np.sum((xs - mx) ** 2))
    slope = float(np.sum((xs - mx) * (ts - mt)) / sxx) if sxx > 0 else None
    if slope is None:
        return FileResult(path.name, date, slot, x0, x1, dx, n, ref_idx, ref_pick,
                          [asdict_obs(o) for o in observations], len(accepted), n_rejected,
                          True, None, None, None, False, False,
                          "accepted separations are degenerate (zero spread)")
    intercept = mt - slope * mx
    expected_slope = 1.0 / C_AIR
    slope_err = abs(slope - expected_slope) / expected_slope * 100.0
    confirmed = slope_err < SLOPE_ERROR_PCT_THRESHOLD

    return FileResult(
        path.name, date, slot, x0, x1, dx, n, ref_idx, ref_pick,
        [asdict_obs(o) for o in observations], len(accepted), n_rejected,
        True, round(slope, 5), round(intercept, 4), round(slope_err, 3), confirmed, confirmed,
        ("geometry confirmed: recovered slope matches 1/c_air" if confirmed else
         f"slope {slope:.4f} ns/m does not match expected {expected_slope:.4f} ns/m "
         f"(error {slope_err:.1f}%): even the accepted observations do not pass the falsifier"),
    )


def asdict_obs(o: TraceObservation) -> dict:
    return {
        "trace_index": o.trace_index, "separation_m": round(o.separation_m, 4),
        "expected_shift_ns": round(o.expected_shift_ns, 4),
        "correlation_lag_ns": round(o.correlation.lag_ns, 4),
        "peak_ncc": round(o.correlation.peak_ncc, 4),
        "accepted": o.correlation.accepted, "reason": o.correlation.reason,
        "implied_absolute_time_ns": (round(o.implied_absolute_time_ns, 4)
                                     if o.implied_absolute_time_ns is not None else None),
    }


# ---------------------------------------------------------------------------
# Phase 3 -- aggregation across files, and what the data can actually claim
# ---------------------------------------------------------------------------

def aggregate_t0(files: list[FileResult]) -> dict:
    confirmed = [f for f in files if f.geometry_confirmed]
    t0s = [f.fitted_t0_ns for f in confirmed]

    def stats(values):
        if not values:
            return None
        n = len(values)
        m = sum(values) / n
        sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
        return {"n": n, "mean_ns": round(m, 4), "sd_ns": round(sd, 4),
                "min_ns": round(min(values), 4), "max_ns": round(max(values), 4),
                "range_ns": round(max(values) - min(values), 4),
                "sem_ns": round(sd / math.sqrt(n), 4) if n > 1 else None}

    by_date: dict[str, list[float]] = {}
    for f in confirmed:
        by_date.setdefault(f.date, []).append(f.fitted_t0_ns)
    within_day = [max(v) - min(v) for v in by_date.values() if len(v) > 1]

    independently_identifiable = len(confirmed) >= 2 and (stats(t0s) or {}).get("range_ns", 999) < 3.0

    return {
        "files_with_slope_fit_attempted": sum(1 for f in files if f.slope_fit_attempted),
        "files_geometry_confirmed": len(confirmed),
        "files_total": len(files),
        "fitted_t0_stats": stats(t0s),
        "day_to_day": {
            "n_days": len(by_date),
            "per_day_mean_ns": {d: round(sum(v) / len(v), 4) for d, v in sorted(by_date.items())},
            "max_within_day_spread_ns": round(max(within_day), 4) if within_day else None,
        },
        "t0_independently_identifiable": independently_identifiable,
        "identifiability_note": (
            f"{len(confirmed)} of {len(files)} files passed the slope falsifier after "
            f"data-intrinsic correlation-quality rejection; "
            + (f"their fitted t0 spans {stats(t0s)['range_ns']:.2f} ns, "
               + ("within the 3 ns consistency bound this audit requires to call t0 "
                  "independently identifiable" if independently_identifiable else
                  "exceeding the 3 ns consistency bound this audit requires -- the estimates "
                  "do not agree with each other closely enough to call t0 independently "
                  "identifiable")
               if confirmed else "no file's estimate can be compared against another")
        ),
    }


# ---------------------------------------------------------------------------
# Phase 4 -- fixed-t0 crosshole velocity fit (v only; t0 is NOT refit)
# ---------------------------------------------------------------------------

@dataclass
class FixedT0FitResult:
    t0_ns: float
    n_pairs: int
    velocity_m_per_ns: Optional[float]
    rms_residual_ns: Optional[float]
    max_residual_ns: Optional[float]
    residuals_ns: dict
    note: str


def fit_velocity_fixed_t0(pairs: list[PairResult], t0_ns: float) -> FixedT0FitResult:
    """
    t_measured - t0 = L / v: ONE free parameter (v), fit by ordinary least
    squares through the origin. t0 is a fixed input, never refit here --
    that is the whole point of this phase.
    """
    usable = [p for p in pairs if p.usable]
    if len(usable) < 1:
        return FixedT0FitResult(t0_ns, 0, None, None, None, {}, "no usable pairs")

    L = np.array([p.separation_m for p in usable])
    t_adj = np.array([p.median_time_ns for p in usable]) - t0_ns
    if np.any(t_adj <= 0):
        bad = [p.tx + "-" + p.rx for p, adj in zip(usable, t_adj) if adj <= 0]
        return FixedT0FitResult(t0_ns, len(usable), None, None, None, {},
                                f"t0={t0_ns} exceeds the observed arrival time for: {bad} "
                                f"-- non-physical, no velocity fit")

    sxx = float(np.sum(L * L))
    inv_v = float(np.sum(L * t_adj) / sxx)
    if inv_v <= 0:
        return FixedT0FitResult(t0_ns, len(usable), None, None, None, {},
                                "fit produced a non-physical (non-positive) velocity")
    v = 1.0 / inv_v
    predicted = L * inv_v
    residuals = {f"{p.tx}-{p.rx}": float(t_adj[i] - predicted[i]) for i, p in enumerate(usable)}
    errs = np.array(list(residuals.values()))
    return FixedT0FitResult(
        t0_ns, len(usable), v, float(np.sqrt(np.mean(errs ** 2))), float(np.max(np.abs(errs))),
        residuals, f"fit over {len(usable)} usable pairs, t0 fixed at {t0_ns} ns",
    )


def leave_one_out_fixed_t0(pairs: list[PairResult], t0_ns: float) -> list[dict]:
    usable = [p for p in pairs if p.usable]
    out = []
    for held in usable:
        rest = [p for p in usable if (p.tx, p.rx) != (held.tx, held.rx)]
        fit = fit_velocity_fixed_t0(rest, t0_ns)
        if fit.velocity_m_per_ns is None:
            out.append({"held_out": f"{held.tx}-{held.rx}", "error_ns": None, "note": fit.note})
            continue
        pred = t0_ns + held.separation_m / fit.velocity_m_per_ns
        out.append({"held_out": f"{held.tx}-{held.rx}", "refit_velocity_m_per_ns": fit.velocity_m_per_ns,
                   "predicted_time_ns": pred, "observed_time_ns": held.median_time_ns,
                   "error_ns": pred - held.median_time_ns})
    return out


def sensitivity_to_t0_uncertainty(pairs: list[PairResult], t0_center: float,
                                  t0_uncertainty: float) -> dict:
    """How much v moves across the t0 range this experiment's own uncertainty implies."""
    grid = [t0_center - t0_uncertainty, t0_center - t0_uncertainty / 2, t0_center,
           t0_center + t0_uncertainty / 2, t0_center + t0_uncertainty]
    results = []
    for t0 in grid:
        fit = fit_velocity_fixed_t0(pairs, t0)
        results.append({"t0_ns": round(t0, 4), "velocity_m_per_ns": fit.velocity_m_per_ns})
    vs = [r["velocity_m_per_ns"] for r in results if r["velocity_m_per_ns"] is not None]
    center_fit = fit_velocity_fixed_t0(pairs, t0_center)
    max_delta_frac = None
    if vs and center_fit.velocity_m_per_ns:
        max_delta_frac = max(abs(v - center_fit.velocity_m_per_ns) / center_fit.velocity_m_per_ns
                             for v in vs)
    return {"t0_uncertainty_ns": t0_uncertainty, "grid": results,
           "max_velocity_delta_frac": max_delta_frac}


def sensitivity_to_pick_perturbation(pairs: list[PairResult], t0_ns: float,
                                     sample_interval_ns: float = 0.1465) -> dict:
    """
    Perturbs ONE pair's median picked time at a time by +-1/+-2 samples,
    mirroring bam_hyperbola_velocity_audit.py's own sensitivity design
    (never a uniform shift, which cannot move a through-origin slope at
    all here either -- shifting every point by the same constant changes
    nothing about L*(1/v) - t_adj minimisation's optimal slope only via
    the mean, so per-point perturbation is what actually stresses it).
    """
    usable = [p for p in pairs if p.usable]
    base = fit_velocity_fixed_t0(usable, t0_ns)
    if base.velocity_m_per_ns is None:
        return {"base_velocity_m_per_ns": None, "per_pair": [], "max_velocity_delta_frac": None}
    per_pair = []
    for i, target in enumerate(usable):
        deltas = []
        for n_samples in (-2, -1, 1, 2):
            shifted = list(usable)
            shifted[i] = PairResult(**{**asdict(target),
                                       "median_time_ns": target.median_time_ns + n_samples * sample_interval_ns})
            fit = fit_velocity_fixed_t0(shifted, t0_ns)
            if fit.velocity_m_per_ns is not None:
                deltas.append(abs(fit.velocity_m_per_ns - base.velocity_m_per_ns) / base.velocity_m_per_ns)
        per_pair.append({"pair": f"{target.tx}-{target.rx}",
                         "max_delta_frac": max(deltas) if deltas else None})
    all_deltas = [p["max_delta_frac"] for p in per_pair if p["max_delta_frac"] is not None]
    return {"base_velocity_m_per_ns": base.velocity_m_per_ns, "per_pair": per_pair,
           "max_velocity_delta_frac": max(all_deltas) if all_deltas else None}


# ---------------------------------------------------------------------------
# Phase 5 -- identifiability gate: four distinct claims, never conflated
# ---------------------------------------------------------------------------

def classify_overall(t0_agg: dict, fixed_fit: Optional[FixedT0FitResult],
                     loo: list[dict], t0_sensitivity: Optional[dict]) -> tuple[str, dict, list[str]]:
    """
    Reuses the repository's existing four-way vocabulary
    (FAILED / INCONCLUSIVE / ESTIMATED BUT NOT VALIDATED / VALIDATED VELOCITY)
    rather than inventing new classes -- Phase 5 explicitly asks for this.
    Four claims are tracked and reported SEPARATELY so none is conflated
    into the single headline classification.
    """
    claims = {
        "t0_independently_constrained": t0_agg["t0_independently_identifiable"],
        "velocity_numerically_stable": False,
        "velocity_physically_plausible": False,
        "velocity_independently_validated": False,  # TestUM has no surveyed depth truth; always False
    }
    reasons = [t0_agg["identifiability_note"]]

    if not t0_agg["t0_independently_identifiable"]:
        reasons.append("cross-correlation improves relative precision but does not resolve an "
                       "independent absolute t0 well enough to fix it into the crosshole fit")
        return "INCONCLUSIVE", claims, reasons

    if fixed_fit is None or fixed_fit.velocity_m_per_ns is None:
        reasons.append(f"fixed-t0 crosshole fit failed: "
                       f"{fixed_fit.note if fixed_fit else 'not attempted'}")
        return "FAILED", claims, reasons

    from scripts.testum_crosshole_velocity_audit import (
        MIN_PLAUSIBLE_VELOCITY_M_PER_NS, MAX_PLAUSIBLE_VELOCITY_M_PER_NS,
    )
    claims["velocity_physically_plausible"] = (
        MIN_PLAUSIBLE_VELOCITY_M_PER_NS <= fixed_fit.velocity_m_per_ns <= MAX_PLAUSIBLE_VELOCITY_M_PER_NS
    )
    loo_errs = [r["error_ns"] for r in loo if r.get("error_ns") is not None]
    loo_stable = bool(loo_errs) and max(abs(e) for e in loo_errs) < 15.0
    sens_stable = (t0_sensitivity or {}).get("max_velocity_delta_frac", 1.0) is not None and \
        (t0_sensitivity or {}).get("max_velocity_delta_frac", 1.0) < 0.20
    claims["velocity_numerically_stable"] = loo_stable and sens_stable

    if not claims["velocity_physically_plausible"]:
        reasons.append(f"fixed-t0 velocity {fixed_fit.velocity_m_per_ns:.4f} m/ns is outside the "
                       f"physically plausible range")
        return "FAILED", claims, reasons

    if not claims["velocity_numerically_stable"]:
        reasons.append(
            f"velocity is not stable: leave-one-out max error "
            f"{max((abs(e) for e in loo_errs), default=None)} ns, "
            f"t0-uncertainty sensitivity {(t0_sensitivity or {}).get('max_velocity_delta_frac')}"
        )
        return "ESTIMATED BUT NOT VALIDATED", claims, reasons

    reasons.append(
        "t0 independently constrained by air-WARR cross-correlation and velocity is numerically "
        "stable and physically plausible with t0 fixed -- but TestUM has no independently "
        "surveyed reflector/depth truth (a monitored freezing front, not an attested target), so "
        "velocity_independently_validated remains False and this is capped at ESTIMATED BUT NOT "
        "VALIDATED, never VALIDATED VELOCITY"
    )
    return "ESTIMATED BUT NOT VALIDATED", claims, reasons


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def run_experiment(calibration_raw_dir: Path = CALIBRATION_RAW_DIR,
                   crosshole_raw_dir: Path = CROSSHOLE_RAW_DIR) -> dict:
    generated = datetime.now(timezone.utc).isoformat()

    # Phase 2-3: cross-correlation t0 from every real air-WARR file.
    file_results = []
    missing = []
    for name, date, slot, comment, n_pub in load_index():
        path = calibration_raw_dir / name
        if not path.exists() or path.stat().st_size < 20_000:
            missing.append(name)
            continue
        r = analyse_calibration_file(path, date, slot, comment)
        if r is not None:
            file_results.append(r)
    t0_agg = aggregate_t0(file_results)

    # Phase 4: rerun the real 14-pair crosshole analysis, t0 fixed (not refit).
    wells = load_well_coordinates()
    pairs = []
    for (tx, rx), fname in sorted(PAIR_FILES.items()):
        sep = surveyed_separation_m(wells, tx, rx)
        pairs.append(analyse_pair(tx, rx, fname, sep, crosshole_raw_dir))

    fixed_fit = None
    loo = []
    t0_sensitivity = None
    pick_sensitivity = None
    permittivity = None
    joint_fit_comparison = None
    t0_for_fit = None

    stats = t0_agg["fitted_t0_stats"]
    if t0_agg["t0_independently_identifiable"] and stats:
        t0_for_fit = stats["mean_ns"]
        t0_uncertainty = max(stats["sem_ns"] or 0.0, stats["range_ns"] / 2)
        fixed_fit = fit_velocity_fixed_t0(pairs, t0_for_fit)
        loo = leave_one_out_fixed_t0(pairs, t0_for_fit)
        t0_sensitivity = sensitivity_to_t0_uncertainty(pairs, t0_for_fit, t0_uncertainty)
        pick_sensitivity = sensitivity_to_pick_perturbation(pairs, t0_for_fit)
        permittivity = relative_permittivity(fixed_fit.velocity_m_per_ns)

        from scripts.testum_crosshole_velocity_audit import fit_joint
        prior_joint = fit_joint(pairs)
        joint_fit_comparison = {
            "prior_joint_fit_v_m_per_ns": prior_joint.velocity_m_per_ns,
            "prior_joint_fit_t0_ns": prior_joint.t0_ns,
            "prior_joint_fit_correlation": prior_joint.parameter_correlation,
            "fixed_t0_v_m_per_ns": fixed_fit.velocity_m_per_ns,
            "fixed_t0_used_ns": t0_for_fit,
            "confound_removed": prior_joint.parameter_correlation is not None
                and abs(prior_joint.parameter_correlation) >= 0.9,  # was confounded, cause now gone
        }

    classification, claims, reasons = classify_overall(t0_agg, fixed_fit, loo, t0_sensitivity)

    # ILLUSTRATIVE ONLY, run precisely because Phase 4 of this audit asked to
    # see the fixed-t0 exercise even if this experiment's own t0 aggregation
    # fails identifiability (it does -- see classification above). Uses the
    # two t0 VALUES `scripts/testum_air_warr_t0.py` already produced (its own
    # INCONCLUSIVE result: 21.01 and 22.13 ns, absolute-picking method,
    # disagreeing by 1.12 ns) purely as a sensitivity probe. NEVER adopted as
    # this experiment's own finding, and excluded from `classification`.
    illustrative = None
    if not t0_agg["t0_independently_identifiable"]:
        prior_candidates = {"20230824_t0_end (prior script)": 21.01, "20231205_t0_end (prior script)": 22.13}
        illustrative = {}
        for label, t0_val in prior_candidates.items():
            fit = fit_velocity_fixed_t0(pairs, t0_val)
            illustrative[label] = {
                "t0_ns": t0_val, "velocity_m_per_ns": fit.velocity_m_per_ns,
                "rms_residual_ns": fit.rms_residual_ns, "note": fit.note,
            }
        illustrative["_caveat"] = (
            "NOT adopted as this experiment's t0 -- this experiment's OWN cross-correlation "
            "aggregation found t0 not independently identifiable (see t0_aggregate above). These "
            "two values are scripts/testum_air_warr_t0.py's own prior, already-INCONCLUSIVE "
            "absolute-picking result (which disagree with each other by 1.12 ns), reused here "
            "only to show what the fixed-t0 sensitivity analysis WOULD report if a t0 existed."
        )

    return {
        "audit": "testum-air-warr-crosscorrelation-t0-and-fixed-t0-velocity",
        "generated_utc": generated,
        "method": {
            "cross_correlation": "normalised cross-correlation of cubic-detrended traces against "
                                "the file's own X~3m trace, sub-sample parabolic peak refinement",
            "acceptance_gate": f"peak_ncc > 0 and >= {MIN_PEAK_NCC} (data-intrinsic; never uses "
                              f"the expected physical shift to decide acceptance)",
            "slope_falsifier": f"recovered slope must be within {SLOPE_ERROR_PCT_THRESHOLD}% of "
                              f"1/c_air, exactly as scripts/testum_air_warr_t0.py",
            "fixed_t0_fit": "t_measured - t0 = L/v, ONE free parameter (v); t0 fixed from Phase 3, "
                           "never refit",
        },
        "calibration_files": {
            "expected": len(load_index()), "missing": missing,
            "analysed": len(file_results),
            "results": [asdict(f) for f in file_results],
        },
        "t0_aggregate": t0_agg,
        "fixed_t0_used_ns": t0_for_fit,
        "fixed_t0_crosshole_fit": asdict(fixed_fit) if fixed_fit else None,
        "leave_one_out": loo,
        "sensitivity_to_t0_uncertainty": t0_sensitivity,
        "sensitivity_to_pick_perturbation": pick_sensitivity,
        "relative_permittivity": permittivity,
        "comparison_to_prior_joint_fit": joint_fit_comparison,
        "classification": classification,
        "claims": claims,
        "classification_reasons": reasons,
        "illustrative_fixed_t0_using_prior_scripts_candidates": illustrative,
        "product_implication": (
            "Not a live product change. No production code, converter, schema, provenance, API, "
            "frontend, live dataset, or roadmap file is touched by this script."
        ),
    }


def _print_summary(result: dict) -> None:
    agg = result["t0_aggregate"]
    print(f"Calibration files analysed: {result['calibration_files']['analysed']}/"
         f"{result['calibration_files']['expected']}")
    print(f"  geometry-confirmed (passed slope falsifier): {agg['files_geometry_confirmed']}")
    if agg["fitted_t0_stats"]:
        s = agg["fitted_t0_stats"]
        print(f"  fitted t0: n={s['n']} mean={s['mean_ns']}ns sd={s['sd_ns']} range={s['range_ns']}ns")
    print(f"  t0 independently identifiable: {agg['t0_independently_identifiable']}")
    print(f"  {agg['identifiability_note']}")
    if result["fixed_t0_crosshole_fit"]:
        f = result["fixed_t0_crosshole_fit"]
        print(f"\nFixed-t0 crosshole fit (t0={result['fixed_t0_used_ns']}ns): "
             f"v={f['velocity_m_per_ns']}, RMS={f['rms_residual_ns']}, max={f['max_residual_ns']}")
    if result["comparison_to_prior_joint_fit"]:
        c = result["comparison_to_prior_joint_fit"]
        print(f"  prior joint fit: v={c['prior_joint_fit_v_m_per_ns']} "
             f"t0={c['prior_joint_fit_t0_ns']} corr={c['prior_joint_fit_correlation']}")
    print(f"\nCLASSIFICATION: {result['classification']}")
    print(f"  claims: {result['claims']}")
    for r in result["classification_reasons"]:
        print(f"  - {r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-raw-dir", type=Path, default=CALIBRATION_RAW_DIR)
    parser.add_argument("--crosshole-raw-dir", type=Path, default=CROSSHOLE_RAW_DIR)
    parser.add_argument("--out", type=Path,
                       default=REPO_ROOT / "artifacts" / "testum" / "testum_air_warr_t0_velocity_audit.json")
    args = parser.parse_args()

    try:
        result = run_experiment(args.calibration_raw_dir, args.crosshole_raw_dir)
    except AuditError as exc:
        print(f"EXPERIMENT FAILED: {exc}")
        return 1

    _print_summary(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
