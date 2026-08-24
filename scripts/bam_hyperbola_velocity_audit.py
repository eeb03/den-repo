"""
Can the real BAM Pk266 concrete benchmark support a defensible, validated GPR
propagation velocity -- from real radar arrivals, checked against real,
independently-published target depths?

THIS IS A RESEARCH AUDIT, NOT A PRODUCT FEATURE. It reads the real archive
already on disk (`datasets/raw/bam_concrete/Pk266_Dataset.zip`) through the
existing `benchmark.bam_ingest` reader, touches no `SubterraRecord`, no
converter, no provenance schema, no live dataset, and writes only a JSON
artifact under `artifacts/bam/`. Reproduce with:

    python -m scripts.bam_hyperbola_velocity_audit --out artifacts/bam/bam_hyperbola_velocity_audit.json

THE TWO EVIDENCE SOURCES, KEPT SEPARATE THROUGHOUT.

    KNOWN-DEPTH EVIDENCE  the four duct centre-depths and X positions
                          published for Pk266, sourced from the data
                          repository and the companion geometry article
                          (`benchmark/bam_pk266_targets.json`). Independent
                          of the radar volume.

    RADAR EVIDENCE        two-way arrival times picked from the real
                          amplitude volume, using ONLY the shape of the
                          data (where it is a local minimum/maximum in
                          time) and the targets' known X positions (to know
                          WHERE to look). The known DEPTHS are never
                          consulted while picking an arrival time -- using
                          them to do so would manufacture agreement rather
                          than test for it.

The audit's whole question is whether these two independently-obtained
numbers agree, within a defensible margin, for more than one target. If they
do not, or cannot be obtained at all, the correct output is INCONCLUSIVE or
FAILED, not a velocity number.

THE MODELS, STATED ONCE.

    Method A (known-depth joint fit):
        t_measured = t0 + 2 * d / v
    t0 and v are fit JOINTLY by ordinary least squares over the four
    (known_depth, picked_apex_time) pairs. t0 is never assumed to be zero.
    Whether four points can separate t0 from v at all (the confound that
    blocked the TU1208 audit, `scripts/tu1208_depth_calibration.py`) is
    computed and reported before the fit result is trusted.

    Method B (per-target hyperbola):
        t_measured(x) = A_i + sqrt(B_i^2 + (2*(x - x0_i) / v_i)^2)
    fit independently per target against the picked arrival-time curve
    across a window of real traces straddling that target's known X --
    NEVER against its known depth. A_i and B_i are nuisance parameters (the
    instrument offset and the target's own apex time are not separable
    from one hyperbola alone); v_i is what this method estimates, from
    curvature alone. Comparing v_i against Method A's global v, and the
    implied depth `v_i * B_i / 2` against the known depth, is the
    cross-check -- not an input to either fit.

WHY Y IS AVERAGED FIRST. Each duct's own geometry record states it "spans
the full 800 mm width" with its axis parallel to Y (`extent.spans_full_width_y`
in the target file) -- so the SAME reflector should appear, at the same X and
the same two-way time, at every Y position. Averaging traces across a central
band of Y (excluding a margin near the specimen edges, where boundary
diffraction is a real, different effect) is exploiting a stated, real
geometric symmetry to raise arrival-time signal-to-noise -- not fabricating
data no sensor recorded.

WHAT THIS DOES NOT DO. It does not promote anything to `DERIVED` in the
Subterra provenance model, does not change `DEFAULT_GPR_VELOCITY_M_PER_NS`,
does not touch any live dataset, and does not write to any table a product
surface reads. It also does not force a fit: a target whose radar arrival
cannot be picked with a stated confidence is reported UNUSABLE, not guessed
at, exactly as `tu1208_depth_calibration.py` reports a target UNRESOLVED
rather than choosing a reflector for it.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import optimize, signal

from benchmark import bam_ingest

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGETS_PATH = REPO_ROOT / "benchmark" / "bam_pk266_targets.json"

#: Speed of light in vacuum, m/ns -- the one physical constant this audit
#: relies on. Matches `scripts/characterise_4tu.py::C_M_PER_NS`.
C_M_PER_NS = 0.299792458

#: How far from each target's known X to search, in millimetres. Bounded by
#: the real target spacing (500 mm between duct centres): 180 mm each side
#: leaves 140 mm of clearance to the nearest neighbouring duct, so a window
#: never straddles two targets.
DEFAULT_APERTURE_MM = 180.0

#: Y positions within this margin of the 0/800 mm specimen edges are
#: excluded from averaging: edge diffraction is a real, different reflector
#: (the specimen boundary itself), not the duct.
DEFAULT_Y_MARGIN_MM = 100.0

#: The direct/coupling arrival is a multi-cycle wavelet, not a single spike
#: (confirmed against the real trace: its ringdown at 2.6 GHz spans roughly
#: 40+ samples). A fixed sample-count guard past its peak under-skips it, so
#: the search start is instead found from where the signal STOPS being
#: X-invariant: the direct arrival, by definition, does not depend on a
#: subsurface reflector and so has near-zero relative amplitude spread
#: across the trace window at every sample of its own ringdown, while a real
#: reflection's spread grows with distance from the target's own X. A
#: SUSTAINED run of samples above the threshold (not the first one, which a
#: brief zero-crossing inside the ringdown can trigger spuriously) marks
#: where genuine reflector-dependent signal begins.
DIRECT_ARRIVAL_SPREAD_THRESHOLD = 0.15
DIRECT_ARRIVAL_SUSTAINED_SAMPLES = 6

#: Ridge-tracking step bound. A real hyperbola's arrival time cannot change
#: arbitrarily fast between adjacent 5 mm traces; this bounds the search so
#: the tracker cannot jump onto an unrelated, unrelated-in-time peak. Derived
#: below from a generous velocity floor (0.06 m/ns -- slower than any
#: published concrete estimate) at the CLOSEST target depth, so it is a
#: physically loose bound, not a tuned one.
MIN_PLAUSIBLE_VELOCITY_M_PER_NS = 0.06

#: Classification thresholds, stated once, all in physical units.
#: A depth-residual (or implied-depth error) larger than this fraction of
#: the target's own known depth is "large" -- 8% is looser than the
#: repository's own instrument-declared epsr disagreement with any single
#: measurement technique, deliberately conservative rather than tuned to
#: pass.
LARGE_RELATIVE_DEPTH_ERROR = 0.08
#: Two velocities differing by more than this fraction are "materially
#: different" -- large enough to exceed normal fit noise, small enough that
#: e.g. wet vs dry concrete (a real, documented difference) would trip it.
MATERIAL_VELOCITY_DISAGREEMENT = 0.15
#: A t0/slope correlation (see `identifiability`) at or above this is
#: reported as confounded, mirroring the TU1208 audit's own criterion.
CONFOUND_THRESHOLD = 0.9
#: Minimum pick confidence (peak amplitude / local noise floor) below which
#: a target's radar arrival is not trusted at all.
MIN_PICK_CONFIDENCE = 3.0


class AuditError(RuntimeError):
    """Raised when the audit cannot proceed at all (missing archive, bad shape)."""


# ---------------------------------------------------------------------------
# ground truth (known-depth evidence)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Target:
    target_id: str
    x_mm: float
    depth_mm: float
    depth_source: str
    ground_truth_ambiguity_mm: float  # the cover-vs-centre-reference open question


def load_targets() -> list[Target]:
    """The four real, published Pk266 duct targets. Raises if the file changed shape."""
    data = json.loads(TARGETS_PATH.read_text())
    specimen = next(s for s in data["specimens"] if s["id"] == "Pk266")
    ambiguity = next(
        (q["magnitude_mm"] for q in data.get("open_questions", [])
         if q["id"] == "cover-vs-centre-reference"), 0.0)
    targets = [
        Target(t["target_id"], float(t["x_mm"]), float(t["centre_depth_mm"]),
              t["centre_depth_source"], float(ambiguity))
        for t in specimen["targets"]
    ]
    if len(targets) != 4:
        raise AuditError(f"expected 4 Pk266 targets, found {len(targets)}: file may have changed")
    return targets


# ---------------------------------------------------------------------------
# radar evidence: loading, time axis, arrival-time picking
# ---------------------------------------------------------------------------

@dataclass
class TimeAxis:
    n_samples: int
    range_ns: float
    sample_interval_ns: float
    z_values_ns: np.ndarray
    dzt_range_ns: Optional[float]
    dzt_n_samples: Optional[int]
    dzt_position_ns: Optional[float]
    dzt_epsr: Optional[float]
    consistent_with_dzt: bool
    note: str


def establish_time_axis(scan: "bam_ingest.BenchmarkScan") -> TimeAxis:
    """
    The time axis, from the real acquisition metadata -- never from the
    target depths.

    `Z-values.npy` is the archive's own claimed two-way-time axis (ns,
    `bam_ingest.GridSpec.units_provenance == "inferred_from_documentation"`).
    This function's OWN job is to independently corroborate that claim
    against the DZT header's `range_ns`/`n_samples` fields, exactly as
    `bam_ingest`'s module docstring already does for the archive as a whole,
    and to say plainly if they disagree.
    """
    z = scan.grid.z
    n = int(z.size)
    span = float(z[-1] - z[0])
    interval = span / (n - 1)
    header = scan.dzt_header
    dzt_range = header.get("range_ns")
    dzt_n = header.get("n_samples")
    consistent = True
    note = "Z-values.npy span/step agrees with the DZT header range_ns/n_samples."
    if dzt_range is not None and dzt_n is not None:
        header_interval = float(dzt_range) / (int(dzt_n) - 1) if dzt_n > 1 else None
        if dzt_n != n or (header_interval is not None
                         and abs(header_interval - interval) > 0.05 * interval):
            consistent = False
            note = (
                f"Z-values.npy ({n} samples, {span:.4f} ns span, {interval:.5f} ns/sample) "
                f"does NOT agree with the DZT header ({dzt_n} samples, {dzt_range} ns range, "
                f"{header_interval} ns/sample implied). Treating Z-values.npy as authoritative "
                f"because it indexes the actual volume; the disagreement is reported, not hidden."
            )
    else:
        consistent = False
        note = "DZT header did not supply range_ns/n_samples; only Z-values.npy is used."
    return TimeAxis(
        n_samples=n, range_ns=span, sample_interval_ns=interval, z_values_ns=z,
        dzt_range_ns=dzt_range, dzt_n_samples=dzt_n,
        dzt_position_ns=header.get("position_ns"), dzt_epsr=header.get("epsr"),
        consistent_with_dzt=consistent, note=note,
    )


@dataclass
class ArrivalPick:
    x_mm: float
    time_ns: float
    sample_index: int
    amplitude: float
    confidence: float  # peak amplitude / local noise floor, unitless


@dataclass
class TargetAssociation:
    target: Target
    x_node: int
    y_indices_averaged: list
    direct_arrival_index: int
    apex_pick: Optional[ArrivalPick]
    curve: list  # ArrivalPick per x in the aperture window, ridge-tracked
    usable: bool
    reason: str


def _direct_arrival_extent(traces_by_x_z: np.ndarray) -> int:
    """
    Where the direct/coupling arrival's own ringdown ends and genuine,
    X-dependent reflected signal begins -- the sample index, not just its
    peak.

    At every time sample, the relative spread (std / mean) of amplitude
    ACROSS X is computed: near-zero for the whole duration of the direct
    arrival's ringdown (it does not depend on a subsurface reflector, so
    every trace in the window looks alike), and larger once a real,
    X-dependent reflection begins. A SUSTAINED run of
    `DIRECT_ARRIVAL_SUSTAINED_SAMPLES` consecutive samples above
    `DIRECT_ARRIVAL_SPREAD_THRESHOLD` is required, not the first exceedance,
    because a brief zero-crossing inside the ringdown itself produces a
    spurious spike in relative spread (division by a near-zero mean) without
    the transition actually having happened yet.
    """
    absw = np.abs(traces_by_x_z)
    mean_by_t = absw.mean(axis=0)
    std_by_t = absw.std(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        relative_spread = np.where(mean_by_t > 0, std_by_t / mean_by_t, np.inf)
    exceeds = relative_spread > DIRECT_ARRIVAL_SPREAD_THRESHOLD
    run = DIRECT_ARRIVAL_SUSTAINED_SAMPLES
    for i in range(len(exceeds) - run):
        if np.all(exceeds[i:i + run]):
            return i
    # No sustained transition found: the whole window looks X-invariant.
    # Returning the end leaves nothing to search, which `associate_target`
    # correctly reports as unusable rather than picking from noise.
    return len(exceeds) - 1


def _noise_floor(traces_by_x_z: np.ndarray, start: int) -> float:
    """RMS amplitude of the post-coupling, pre-signal region, as a noise reference."""
    tail = traces_by_x_z[:, start:start + 10]
    return float(np.sqrt(np.mean(tail.astype(float) ** 2))) if tail.size else 1.0


def associate_target(
    target: Target, grid: "bam_ingest.GridSpec", volume: np.ndarray,
    time_axis: TimeAxis, aperture_mm: float, y_margin_mm: float,
) -> TargetAssociation:
    """
    Locates one target on the real grid and picks its radar arrival, using
    ONLY the target's known X (geometry evidence) and the shape of the
    amplitude data. The known DEPTH is never read in this function.
    """
    try:
        x0 = grid.x_node(target.x_mm)
    except bam_ingest.BenchmarkIngestError as exc:
        return TargetAssociation(target, -1, [], -1, None, [], False, str(exc))

    half = int(round(aperture_mm / grid.x_step))
    x_lo, x_hi = max(0, x0 - half), min(grid.x.size - 1, x0 + half)

    y_lo_mm, y_hi_mm = y_margin_mm, float(grid.y[-1]) - y_margin_mm
    y_indices = [i for i, y in enumerate(grid.y) if y_lo_mm <= y <= y_hi_mm]
    if not y_indices:
        return TargetAssociation(target, x0, [], -1, None, [], False,
                                 "y-margin excludes the entire specimen width")

    # (n_x_window, n_samples), averaged over the central Y band -- see the
    # module docstring for why this averaging is a real symmetry, not a guess.
    window = volume[x_lo:x_hi + 1, :, :][:, y_indices, :].mean(axis=1)

    search_start = _direct_arrival_extent(window)
    direct_idx = search_start  # kept as a distinct name in the result for clarity
    if search_start >= time_axis.n_samples - 1:
        return TargetAssociation(target, x0, y_indices, direct_idx, None, [], False,
                                 "no sustained X-dependent signal found after the direct "
                                 "arrival: the whole window looks X-invariant")

    noise = _noise_floor(window, search_start)
    local_x0 = x0 - x_lo  # index of x0 within `window`

    envelope = np.abs(signal.hilbert(window[:, search_start:], axis=1))

    # Apex: global max envelope amplitude at x0 itself, post-guard.
    apex_rel = int(np.argmax(envelope[local_x0]))
    apex_idx = search_start + apex_rel
    apex_amp = float(envelope[local_x0, apex_rel])
    apex_pick = ArrivalPick(
        x_mm=float(grid.x[x0]), time_ns=float(time_axis.z_values_ns[apex_idx]),
        sample_index=apex_idx, amplitude=apex_amp,
        confidence=apex_amp / noise if noise > 0 else float("inf"),
    )

    if apex_pick.confidence < MIN_PICK_CONFIDENCE:
        return TargetAssociation(
            target, x0, y_indices, direct_idx, apex_pick, [], False,
            f"apex pick confidence {apex_pick.confidence:.2f} is below the "
            f"{MIN_PICK_CONFIDENCE} threshold: no reliable reflection distinct from noise",
        )

    # Ridge-track outward from the apex for the hyperbola curve (Method B).
    # Step bound: for t(x) = sqrt(tau^2 + (2x/v)^2), dt/dx -> 2/v as x grows,
    # REGARDLESS OF DEPTH (tau just sets how quickly the curve approaches
    # that asymptote, not its value) -- so the loosest possible per-step
    # time change, at the slowest velocity this audit considers plausible,
    # is a single depth-independent bound, not one that shrinks for a
    # shallow target.
    max_slope_ns_per_m = 2.0 / MIN_PLAUSIBLE_VELOCITY_M_PER_NS
    max_dt_per_step_ns = max_slope_ns_per_m * (grid.x_step / 1000.0)
    track_tolerance = max(3, int(math.ceil(max_dt_per_step_ns / time_axis.sample_interval_ns)))

    curve: list[ArrivalPick] = [None] * window.shape[0]  # type: ignore[list-item]
    curve[local_x0] = apex_pick
    for direction in (1, -1):
        prev_idx = apex_idx
        i = local_x0 + direction
        while 0 <= i < window.shape[0]:
            lo = max(search_start, prev_idx - track_tolerance)
            hi = min(time_axis.n_samples, prev_idx + track_tolerance + 1)
            seg = np.abs(signal.hilbert(window[i, lo:hi]))
            if seg.size == 0:
                break
            rel = int(np.argmax(seg))
            picked_idx = lo + rel
            amp = float(seg[rel])
            curve[i] = ArrivalPick(
                x_mm=float(grid.x[x_lo + i]), time_ns=float(time_axis.z_values_ns[picked_idx]),
                sample_index=picked_idx, amplitude=amp,
                confidence=amp / noise if noise > 0 else float("inf"),
            )
            prev_idx = picked_idx
            i += direction

    curve_picks = [p for p in curve if p is not None]
    return TargetAssociation(target, x0, y_indices, direct_idx, apex_pick, curve_picks,
                             True, "apex pick confidence sufficient")


# ---------------------------------------------------------------------------
# Method A -- known-depth joint fit of t0 and v
# ---------------------------------------------------------------------------

@dataclass
class MethodAResult:
    usable_targets: list
    t0_ns: Optional[float]
    velocity_m_per_ns: Optional[float]
    slope_intercept_correlation: Optional[float]
    identifiable: bool
    identifiability_note: str
    residuals_ns: dict
    depth_predicted_mm: dict
    depth_error_mm: dict
    rms_depth_error_mm: Optional[float]
    max_depth_error_mm: Optional[float]


def fit_method_a(associations: list[TargetAssociation]) -> MethodAResult:
    """
    t_measured = t0 + 2*d/v, fit by ordinary least squares over
    (known_depth, picked_apex_time) for every USABLE target.

    Mirrors `scripts/tu1208_depth_calibration.py`'s own leverage analysis:
    identifiability is read from the correlation between the fitted slope
    and intercept implied by the design matrix, not assumed from the point
    count alone -- four points identify two parameters in principle, but a
    depth set with too little spread can still leave them confounded.
    """
    usable = [a for a in associations if a.usable and a.apex_pick is not None]
    if len(usable) < 2:
        return MethodAResult([a.target.target_id for a in usable], None, None, None, False,
                             f"only {len(usable)} usable target(s); at least 2 are needed to "
                             f"fit 2 parameters, and confounding is likely below 4",
                             {}, {}, {}, None, None)

    d_m = np.array([a.target.depth_mm / 1000.0 for a in usable])
    t_ns = np.array([a.apex_pick.time_ns for a in usable])
    design = np.column_stack([2 * d_m, np.ones_like(d_m)])  # t = (1/v)*2d + t0
    coeffs, *_ = np.linalg.lstsq(design, t_ns, rcond=None)
    inv_v, t0 = coeffs
    if inv_v <= 0:
        return MethodAResult(
            [a.target.target_id for a in usable], float(t0), None, None, False,
            f"fit produced a non-physical velocity (1/v={inv_v:.4g}); arrival times do not "
            f"increase with known depth as the model requires",
            {}, {}, {}, None, None,
        )
    v = 1.0 / inv_v

    # Parameter (not raw-column) correlation: Cov(beta_hat) = sigma^2 * (X^T X)^-1.
    # The intercept COLUMN is constant (all ones) and has zero variance by
    # construction, so correlating the design columns directly (as an
    # earlier version of this function did) always divides by zero. The
    # confound this audit actually cares about -- can the FIT tell t0 apart
    # from v -- lives in (X^T X)^-1, not in the raw data columns; sigma^2
    # cancels out of the correlation ratio, so it needs no residual estimate.
    correlation = None
    try:
        xtx_inv = np.linalg.inv(design.T @ design)
        if xtx_inv[0, 0] > 0 and xtx_inv[1, 1] > 0:
            correlation = float(xtx_inv[0, 1] / math.sqrt(xtx_inv[0, 0] * xtx_inv[1, 1]))
    except np.linalg.LinAlgError:
        correlation = None
    identifiable = len(usable) >= 3 and correlation is not None and abs(correlation) < CONFOUND_THRESHOLD
    if len(usable) < 3:
        id_note = "only 2 usable targets: t0 and v are exactly determined, not independently checkable"
    elif correlation is None:
        id_note = "could not compute a parameter correlation (singular design)"
    else:
        id_note = (
            f"t0 and v parameter correlation {correlation:.4f} "
            f"({'CONFOUNDED' if not identifiable else 'separable'}, "
            f"threshold {CONFOUND_THRESHOLD})"
        )

    predicted_t = design @ np.array([inv_v, t0])
    residuals = {a.target.target_id: float(t_ns[i] - predicted_t[i]) for i, a in enumerate(usable)}
    depth_pred_mm = {
        a.target.target_id: float(v * (a.apex_pick.time_ns - t0) / 2 * 1000.0)
        for a in usable
    }
    depth_err_mm = {
        a.target.target_id: depth_pred_mm[a.target.target_id] - a.target.depth_mm
        for a in usable
    }
    errs = np.array(list(depth_err_mm.values()))
    return MethodAResult(
        [a.target.target_id for a in usable], float(t0), float(v), correlation, identifiable,
        id_note, residuals, depth_pred_mm, depth_err_mm,
        float(np.sqrt(np.mean(errs ** 2))), float(np.max(np.abs(errs))),
    )


def leave_one_out(associations: list[TargetAssociation]) -> list[dict]:
    """Refits Method A on every N-1 subset, predicting the held-out target's depth."""
    usable = [a for a in associations if a.usable and a.apex_pick is not None]
    out = []
    for held_out in usable:
        rest = [a for a in usable if a.target.target_id != held_out.target.target_id]
        fit = fit_method_a(rest)
        if fit.velocity_m_per_ns is None:
            out.append({"held_out": held_out.target.target_id, "predicted_depth_mm": None,
                       "error_mm": None, "note": fit.identifiability_note})
            continue
        pred_mm = fit.velocity_m_per_ns * (held_out.apex_pick.time_ns - fit.t0_ns) / 2 * 1000.0
        out.append({
            "held_out": held_out.target.target_id,
            "refit_velocity_m_per_ns": fit.velocity_m_per_ns, "refit_t0_ns": fit.t0_ns,
            "predicted_depth_mm": pred_mm, "known_depth_mm": held_out.target.depth_mm,
            "error_mm": pred_mm - held_out.target.depth_mm,
        })
    return out


def picking_sensitivity(associations: list[TargetAssociation], sample_interval_ns: float) -> dict:
    """
    Refits Method A with ONE target's apex pick at a time perturbed by
    +-1/+-2 SAMPLES (not an arbitrary time value), the rest held fixed,
    reporting how much v and t0 move.

    Deliberately NOT a uniform shift of every pick together: for
    t = t0 + 2d/v, shifting every observation by the same constant changes
    only the fitted t0 (the intercept) and leaves the fitted SLOPE -- and
    therefore v -- exactly unchanged, which would make this check
    mathematically unable to find anything regardless of how good or bad
    the picks are. Perturbing targets one at a time is what actually stresses
    the slope.
    """
    usable = [a for a in associations if a.usable and a.apex_pick is not None]
    base = fit_method_a(usable)
    results = {"base_velocity_m_per_ns": base.velocity_m_per_ns, "base_t0_ns": base.t0_ns,
              "per_target": []}
    if base.velocity_m_per_ns is None:
        return results
    for target_idx, target_assoc in enumerate(usable):
        perturbations = []
        for n_samples in (-2, -1, 1, 2):
            shift_ns = n_samples * sample_interval_ns
            perturbed = []
            for i, a in enumerate(usable):
                if i == target_idx:
                    p = a.apex_pick
                    shifted = ArrivalPick(p.x_mm, p.time_ns + shift_ns, p.sample_index,
                                         p.amplitude, p.confidence)
                    perturbed.append(TargetAssociation(a.target, a.x_node, a.y_indices_averaged,
                                                       a.direct_arrival_index, shifted, [],
                                                       True, ""))
                else:
                    perturbed.append(a)
            fit = fit_method_a(perturbed)
            perturbations.append({
                "shift_samples": n_samples, "shift_ns": shift_ns,
                "velocity_m_per_ns": fit.velocity_m_per_ns, "t0_ns": fit.t0_ns,
                "velocity_delta_frac": (
                    (fit.velocity_m_per_ns - base.velocity_m_per_ns) / base.velocity_m_per_ns
                    if fit.velocity_m_per_ns else None
                ),
            })
        results["per_target"].append({
            "target_id": target_assoc.target.target_id, "perturbations": perturbations,
        })
    max_delta = max(
        (abs(p["velocity_delta_frac"]) for t in results["per_target"]
         for p in t["perturbations"] if p["velocity_delta_frac"] is not None),
        default=None,
    )
    results["max_velocity_delta_frac"] = max_delta
    return results


# ---------------------------------------------------------------------------
# Method B -- per-target hyperbola fit, independent of known depth
# ---------------------------------------------------------------------------

@dataclass
class HyperbolaResult:
    target_id: str
    usable: bool
    reason: str
    apex_time_ns: Optional[float] = None
    apparent_depth_time_ns: Optional[float] = None  # B in the model
    velocity_m_per_ns: Optional[float] = None
    velocity_stderr_m_per_ns: Optional[float] = None
    param_correlation: Optional[float] = None
    n_points: int = 0
    rms_residual_ns: Optional[float] = None
    implied_depth_mm: Optional[float] = None  # using THIS target's own v, not Method A's


def _hyperbola_model(x_mm, a_ns, b_ns, v_m_per_ns, x0_mm):
    x_m = (np.asarray(x_mm) - x0_mm) / 1000.0
    return a_ns + np.sqrt(b_ns ** 2 + (2 * x_m / v_m_per_ns) ** 2)


def fit_method_b(association: TargetAssociation) -> HyperbolaResult:
    """
    Fits t(x) = A + sqrt(B^2 + (2*(x-x0)/v)^2) to ONE target's ridge-tracked
    arrival curve. x0 is the target's KNOWN X (geometry evidence, not depth
    evidence). The known DEPTH is never used as a fit input here -- it is
    compared against `implied_depth_mm` only afterward, by the caller.
    """
    tid = association.target.target_id
    if not association.usable or len(association.curve) < 5:
        return HyperbolaResult(tid, False,
                               f"only {len(association.curve)} ridge-tracked point(s); "
                               f"at least 5 are needed to constrain 3 parameters")

    xs = np.array([p.x_mm for p in association.curve])
    ts = np.array([p.time_ns for p in association.curve])
    x0_mm = association.apex_pick.x_mm
    a0 = float(ts.min())
    b0 = max(a0 * 0.1, 0.5)
    v0 = 0.1  # starting guess only; not a result, not used elsewhere

    try:
        popt, pcov = optimize.curve_fit(
            lambda x, a, b, v: _hyperbola_model(x, a, b, v, x0_mm),
            xs, ts, p0=[a0, b0, v0],
            bounds=([0, 1e-3, 0.02], [ts.max(), ts.max(), 0.30]),
            maxfev=20000,
        )
    except Exception as exc:  # noqa: BLE001 -- report as unusable, never crash the audit
        return HyperbolaResult(tid, False, f"curve_fit did not converge: {exc}")

    a_fit, b_fit, v_fit = popt
    residuals = ts - _hyperbola_model(xs, a_fit, b_fit, v_fit, x0_mm)
    stderr = np.sqrt(np.diag(pcov)) if pcov is not None and np.all(np.isfinite(pcov)) else None
    correlation = None
    if pcov is not None and stderr is not None and stderr[1] > 0 and stderr[2] > 0:
        correlation = float(pcov[1, 2] / (stderr[1] * stderr[2]))

    implied_depth_mm = v_fit * b_fit / 2 * 1000.0
    return HyperbolaResult(
        tid, True, "fit converged", apex_time_ns=float(a_fit + b_fit),
        apparent_depth_time_ns=float(b_fit), velocity_m_per_ns=float(v_fit),
        velocity_stderr_m_per_ns=float(stderr[2]) if stderr is not None else None,
        param_correlation=correlation, n_points=int(xs.size),
        rms_residual_ns=float(np.sqrt(np.mean(residuals ** 2))), implied_depth_mm=implied_depth_mm,
    )


# ---------------------------------------------------------------------------
# comparison, permittivity, classification
# ---------------------------------------------------------------------------

def compare_methods(method_a: MethodAResult, hyperbolas: list[HyperbolaResult]) -> dict:
    usable_hyp = [h for h in hyperbolas if h.usable and h.velocity_m_per_ns is not None]
    if method_a.velocity_m_per_ns is None or not usable_hyp:
        return {"comparable": False, "reason": "one or both methods produced no usable velocity"}
    hyp_v = np.array([h.velocity_m_per_ns for h in usable_hyp])
    mean_hyp_v = float(np.mean(hyp_v))
    spread = float(np.std(hyp_v))
    rel_disagreement = abs(mean_hyp_v - method_a.velocity_m_per_ns) / method_a.velocity_m_per_ns
    return {
        "comparable": True,
        "method_a_velocity_m_per_ns": method_a.velocity_m_per_ns,
        "method_b_velocities_m_per_ns": {h.target_id: h.velocity_m_per_ns for h in usable_hyp},
        "method_b_mean_velocity_m_per_ns": mean_hyp_v,
        "method_b_spread_m_per_ns": spread,
        "relative_disagreement": rel_disagreement,
        "material_disagreement": rel_disagreement > MATERIAL_VELOCITY_DISAGREEMENT,
    }


def relative_permittivity(velocity_m_per_ns: Optional[float]) -> Optional[dict]:
    if velocity_m_per_ns is None or velocity_m_per_ns <= 0:
        return None
    eps_r = (C_M_PER_NS / velocity_m_per_ns) ** 2
    # Sanity reference only -- see the module's own instruction not to treat
    # plausibility as proof. Typical published dry-to-saturated concrete
    # relative permittivity spans roughly 6-16 (varies with mix and moisture).
    plausible_range = (6.0, 16.0)
    return {
        "velocity_m_per_ns": velocity_m_per_ns, "relative_permittivity": eps_r,
        "typical_concrete_range": plausible_range,
        "within_typical_range": plausible_range[0] <= eps_r <= plausible_range[1],
        "note": "Range is a sanity reference from general GPR literature, not a validation "
                "criterion; a value outside it is a reason to look harder, not to discard.",
    }


def classify(method_a: MethodAResult, hyperbolas: list[HyperbolaResult],
            comparison: dict, sensitivity: dict, loo: list[dict],
            associations: list[TargetAssociation]) -> tuple[str, list[str]]:
    """
    Conservative by construction: every branch below can only downgrade the
    result from `VALIDATED VELOCITY`, never argue its way back up. Each
    threshold is one of the module-level constants, stated once at the top
    of the file with the physical reasoning behind it.
    """
    reasons: list[str] = []
    known_depth_mm = {a.target.target_id: a.target.depth_mm for a in associations}
    n_usable_targets = sum(1 for a in associations if a.usable)

    if n_usable_targets < 2 or method_a.velocity_m_per_ns is None:
        reasons.append(f"fewer than 2 targets produced a usable radar arrival, or the "
                       f"known-depth fit was non-physical: {method_a.identifiability_note}")
        return "FAILED", reasons

    if not method_a.identifiable:
        reasons.append(f"known-depth fit is not identifiable: {method_a.identifiability_note}")
        return "INCONCLUSIVE", reasons

    usable_hyp = [h for h in hyperbolas if h.usable]
    if len(usable_hyp) == 0:
        reasons.append("no per-target hyperbola fit converged; only the known-depth method "
                       "produced a result, so it cannot be cross-checked against an "
                       "independent radar-only estimate")
        return "ESTIMATED BUT NOT VALIDATED", reasons

    if not comparison.get("comparable"):
        reasons.append("could not compare the two methods: " + comparison.get("reason", ""))
        return "ESTIMATED BUT NOT VALIDATED", reasons

    if comparison["material_disagreement"]:
        reasons.append(
            f"known-depth velocity ({comparison['method_a_velocity_m_per_ns']:.4f} m/ns) and "
            f"hyperbola-curvature velocity ({comparison['method_b_mean_velocity_m_per_ns']:.4f} "
            f"m/ns) disagree by {comparison['relative_disagreement']:.1%}, exceeding the "
            f"{MATERIAL_VELOCITY_DISAGREEMENT:.0%} materiality threshold"
        )
        return "ESTIMATED BUT NOT VALIDATED", reasons

    # Method A's own depth errors, each judged against ITS OWN target's known
    # depth (a flat mm threshold would be meaningless across a 94-275 mm range).
    large_errors = {
        tid: err for tid, err in method_a.depth_error_mm.items()
        if abs(err) > LARGE_RELATIVE_DEPTH_ERROR * known_depth_mm[tid]
    }
    if large_errors:
        reasons.append(
            f"known-depth fit's own predicted depth exceeds {LARGE_RELATIVE_DEPTH_ERROR:.0%} "
            f"error for: {', '.join(f'{tid} ({err:+.1f} mm)' for tid, err in large_errors.items())}"
        )
        return "ESTIMATED BUT NOT VALIDATED", reasons

    max_delta = sensitivity.get("max_velocity_delta_frac")
    unstable = max_delta is not None and max_delta > MATERIAL_VELOCITY_DISAGREEMENT
    if unstable:
        reasons.append(
            f"velocity is not robust to +-1/+-2 sample picking perturbation of a single "
            f"target (max delta {max_delta:.1%}, threshold {MATERIAL_VELOCITY_DISAGREEMENT:.0%})"
        )
        return "ESTIMATED BUT NOT VALIDATED", reasons

    loo_unstable_targets = [
        r["held_out"] for r in loo
        if r.get("error_mm") is not None
        and abs(r["error_mm"]) > LARGE_RELATIVE_DEPTH_ERROR * known_depth_mm[r["held_out"]]
    ]
    if loo_unstable_targets:
        reasons.append(
            f"leave-one-out depth prediction exceeds {LARGE_RELATIVE_DEPTH_ERROR:.0%} error "
            f"for: {', '.join(loo_unstable_targets)}"
        )
        return "ESTIMATED BUT NOT VALIDATED", reasons

    reasons.append(
        f"identifiable known-depth fit ({method_a.identifiability_note}), depth errors within "
        f"{LARGE_RELATIVE_DEPTH_ERROR:.0%} for every usable target, hyperbola cross-check "
        f"within {MATERIAL_VELOCITY_DISAGREEMENT:.0%}, stable under picking perturbation and "
        f"leave-one-out"
    )
    return "VALIDATED VELOCITY", reasons


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def run_audit(specimen_id: str, scan_id: str, aperture_mm: float, y_margin_mm: float,
             root: Path) -> dict:
    generated = datetime.now(timezone.utc).isoformat()
    try:
        scan = bam_ingest.load_scan(specimen_id, scan_id, root=root)
        volume = bam_ingest.load_volume(scan, root=root)
    except bam_ingest.BenchmarkIngestError as exc:
        raise AuditError(f"could not load real BAM data: {exc}") from exc

    time_axis = establish_time_axis(scan)
    targets = load_targets()

    associations = [
        associate_target(t, scan.grid, volume, time_axis, aperture_mm, y_margin_mm)
        for t in targets
    ]
    method_a = fit_method_a(associations)
    hyperbolas = [fit_method_b(a) for a in associations if a.usable]
    comparison = compare_methods(method_a, hyperbolas)
    loo = leave_one_out(associations)
    sensitivity = picking_sensitivity(associations, time_axis.sample_interval_ns)
    permittivity = relative_permittivity(method_a.velocity_m_per_ns)
    classification, reasons = classify(method_a, hyperbolas, comparison, sensitivity, loo,
                                       associations)

    return {
        "audit": "bam-pk266-hyperbola-known-depth-velocity",
        "generated_utc": generated,
        "model": {
            "method_a": "t_measured = t0 + 2*d/v, jointly fit over known depths",
            "method_b": "t_measured(x) = A + sqrt(B^2 + (2*(x-x0)/v)^2), fit per target, "
                       "independent of known depth",
        },
        "source": {
            "specimen_id": specimen_id, "scan_id": scan_id, "archive": scan.archive,
            "provenance": scan.provenance, "dzt_header": scan.dzt_header,
        },
        "geometry": {
            "grid": scan.grid.as_dict(), "aperture_mm": aperture_mm, "y_margin_mm": y_margin_mm,
        },
        "time_axis": asdict(time_axis) | {"z_values_ns": None},  # array omitted from JSON
        "targets": [asdict(t) for t in targets],
        "associations": [
            {
                "target_id": a.target.target_id, "x_node": a.x_node, "usable": a.usable,
                "reason": a.reason, "direct_arrival_index": a.direct_arrival_index,
                "n_y_averaged": len(a.y_indices_averaged),
                "apex_pick": asdict(a.apex_pick) if a.apex_pick else None,
                "n_curve_points": len(a.curve),
            }
            for a in associations
        ],
        "method_a": asdict(method_a),
        "method_b": [asdict(h) for h in hyperbolas],
        "comparison": comparison,
        "leave_one_out": loo,
        "picking_sensitivity": sensitivity,
        "relative_permittivity": permittivity,
        "classification": classification,
        "classification_reasons": reasons,
        "product_implication": (
            "Not a live product change. If VALIDATED VELOCITY, the smallest legitimate next "
            "step is a bridge from this benchmark's grid into SubterraRecord so the same "
            "evidence becomes available as a live capability -- not an automatic change to "
            "DEFAULT_GPR_VELOCITY_M_PER_NS or to any live dataset's provenance."
        ),
    }


def _print_summary(result: dict) -> None:
    print(f"BAM {result['source']['specimen_id']} / {result['source']['scan_id']}")
    ta = result["time_axis"]
    print(f"  time axis: {ta['n_samples']} samples, {ta['range_ns']:.4f} ns range, "
         f"{ta['sample_interval_ns']:.5f} ns/sample (DZT-consistent: {ta['consistent_with_dzt']})")
    for a in result["associations"]:
        pick = a["apex_pick"]
        if pick:
            print(f"  {a['target_id']}: x_node={a['x_node']} usable={a['usable']} "
                 f"apex={pick['time_ns']:.4f} ns (confidence {pick['confidence']:.1f})")
        else:
            print(f"  {a['target_id']}: usable=False ({a['reason']})")
    ma = result["method_a"]
    print(f"  Method A: v={ma['velocity_m_per_ns']}, t0={ma['t0_ns']}, "
         f"identifiable={ma['identifiable']} ({ma['identifiability_note']})")
    if ma["rms_depth_error_mm"] is not None:
        print(f"    RMS depth error {ma['rms_depth_error_mm']:.2f} mm, "
             f"max {ma['max_depth_error_mm']:.2f} mm")
    for h in result["method_b"]:
        if h["usable"]:
            print(f"  Method B {h['target_id']}: v={h['velocity_m_per_ns']:.5f} m/ns "
                 f"+-{h['velocity_stderr_m_per_ns']}, implied depth {h['implied_depth_mm']:.1f} mm")
        else:
            print(f"  Method B {h['target_id']}: unusable ({h['reason']})")
    if result["relative_permittivity"]:
        rp = result["relative_permittivity"]
        print(f"  implied relative permittivity: {rp['relative_permittivity']:.3f} "
             f"(typical concrete range {rp['typical_concrete_range']}, "
             f"within range: {rp['within_typical_range']})")
    comp = result["comparison"]
    if comp.get("comparable"):
        print(f"  Method A vs B: {comp['relative_disagreement']:.1%} relative disagreement "
             f"(material: {comp['material_disagreement']})")
    max_delta = result["picking_sensitivity"].get("max_velocity_delta_frac")
    if max_delta is not None:
        print(f"  max single-target picking-perturbation sensitivity: {max_delta:.1%}")
    loo_errs = [r["error_mm"] for r in result["leave_one_out"] if r.get("error_mm") is not None]
    if loo_errs:
        print(f"  leave-one-out depth error: max {max(abs(e) for e in loo_errs):.2f} mm")
    print(f"  CLASSIFICATION: {result['classification']}")
    for r in result["classification_reasons"]:
        print(f"    - {r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specimen-id", default="Pk266")
    parser.add_argument("--scan-id", default="Pk266_3D_Dataset_2_6_GHz_Rot00",
                       help="2.6 GHz chosen by default: finer range resolution for these "
                            "94-275 mm target depths than the 1.5 GHz scan in the same archive")
    parser.add_argument("--aperture-mm", type=float, default=DEFAULT_APERTURE_MM)
    parser.add_argument("--y-margin-mm", type=float, default=DEFAULT_Y_MARGIN_MM)
    parser.add_argument("--root", type=Path, default=REPO_ROOT / bam_ingest.DEFAULT_ROOT)
    parser.add_argument("--out", type=Path,
                       default=REPO_ROOT / "artifacts" / "bam" / "bam_hyperbola_velocity_audit.json")
    args = parser.parse_args()

    try:
        result = run_audit(args.specimen_id, args.scan_id, args.aperture_mm, args.y_margin_mm,
                          args.root)
    except AuditError as exc:
        print(f"AUDIT FAILED: {exc}")
        return 1

    _print_summary(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
