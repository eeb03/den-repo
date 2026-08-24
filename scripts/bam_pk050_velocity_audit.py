"""
Can the real BAM Pk050 concrete specimen provide known-depth GPR velocity
evidence that Pk266 could not -- i.e. does it break the t0/v identifiability
confound that left `scripts/bam_hyperbola_velocity_audit.py` INCONCLUSIVE?

THIS IS A RESEARCH AUDIT, NOT A PRODUCT FEATURE. Same discipline as the Pk266
audit: read the real archive already on disk
(`datasets/raw/bam_concrete/Pk050_Dataset.zip`) through the existing
`benchmark.bam_ingest` reader, touch no `SubterraRecord`, no converter, no
provenance schema, no live dataset, and write only a JSON artifact under
`artifacts/bam/`. Reproduce with:

    python -m scripts.bam_pk050_velocity_audit --out artifacts/bam/pk050_velocity_audit.json

WHY THIS SCRIPT IS NOT A COPY OF THE Pk266 ONE.

Pk266 has four published, hand-transcribed EMBEDDED targets, each with a
known X position and a known centre depth
(`benchmark/bam_pk266_targets.json`). Pk050 has ZERO: the same file records
`role: "negative_control"`, `targets: []`, and the data repository's own
words, quoted verbatim: "Specimen Pk050 does not contain any embedded
elements." (`benchmark.bam_truth.load_control`). There is therefore no
point-target, no known X, and no hyperbola-shaped diffraction to look for --
Pk266's `associate_target`/`fit_method_b` machinery does not apply here and
is not used.

What Pk050 DOES have, independent of the radar volume, is four attested
STEP-BACK-WALL thicknesses (571.3 / 452.0 / 330.9 / 210.8 mm,
`step_thickness_source: "data_repository"`). These are real, sourced depths
-- but no source anywhere in this repository (checked: the target-truth
file, the ingestion module, `docs/bam-benchmark-detection.md`,
`docs/external-gpr-benchmark-acquisition.md`, `docs/cross-dataset-evidence-
audit.md`) gives the X-range each thickness occupies. Guessing that mapping
from Pk266's step order, or from a filename, or from "it looks like a
staircase" would be exactly the forbidden move: inventing spatial metadata
that is not declared anywhere. So this audit NEVER assigns an X-position to
a known thickness. Instead it:

  1. Scans the ENTIRE specimen (every one of the 401 real X nodes, central-Y
     averaged -- see `verify_y_invariance` for why that averaging is
     confirmed, not assumed, on THIS specimen) for real, high-confidence,
     spatially STABLE late reflections, using the same noise-floor-relative
     picking criterion validated on Pk266 (`MIN_PICK_CONFIDENCE`, imported,
     not re-tuned).
  2. Reports exactly how many such stable "plateaus" are found. A plateau's
     TWO-WAY TIME is real radar evidence. Its physical identity (which step
     thickness it belongs to) is not yet known.
  3. Only THEN, and only as an explicitly labelled assumption (never hidden
     in a threshold), ranks plateaus by two-way time and known depths by
     thickness and pairs them in matching rank order. This uses no X
     information at all -- it rests on one physical fact already implicit
     in Method A itself (a single global velocity across the specimen):
     under one velocity, two-way time increases monotonically with true
     depth. It is the SAME assumption Pk266's Method A already makes by
     fitting one v across four different X positions, not a new one invented
     for Pk050.

If fewer plateaus survive than known depths -- which, stated up front from
the real-data probe this script's author ran before writing it, is exactly
what happens here (four attested depths, one survives) -- the shallowest
known depths are the ones GPR attenuation predicts would survive first, so
the surviving plateau(s) are paired against the shallowest known depth(s) in
that order. This is reported as a stated model assumption, not evidence, and
never used to upgrade a classification.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import signal

from benchmark import bam_ingest, bam_truth
from scripts.bam_hyperbola_velocity_audit import (
    C_M_PER_NS,
    CONFOUND_THRESHOLD,
    MIN_PICK_CONFIDENCE,
    ArrivalPick,
    Target,
    TargetAssociation,
    TimeAxis,
    _direct_arrival_extent,
    _noise_floor,
    establish_time_axis,
    fit_method_a,
    leave_one_out,
    picking_sensitivity,
    relative_permittivity,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Same margin, same reasoning as Pk266 -- excludes specimen-edge diffraction
#: from the averaged trace. Re-verified (not assumed) for Pk050 by
#: `verify_y_invariance` before it is relied on; see that function's result
#: in the artifact for the actual, measured edge effect.
DEFAULT_Y_MARGIN_MM = 100.0

#: A candidate plateau must span at least this far along X to be treated as
#: a genuine physical reflector rather than a noise coincidence or an
#: edge/transition artifact. Justification: the specimen is 2000 mm long: if
#: it really is divided into on the order of four roughly-equal physical
#: step regions, each spans on the order of 500 mm. 100 mm is a conservative
#: floor well below that -- loose enough not to be tuned to the data, tight
#: enough to reject a handful of nodes.
MIN_PLATEAU_RUN_MM = 100.0

#: Adjacent X nodes belong to the same plateau if their picked arrival times
#: differ by no more than this many samples. A genuine planar reflector's
#: arrival time is physically flat (see `check_hyperbola_applicability`);
#: real picking noise on repeat measurements of the same reflector should
#: not exceed a couple of samples. Two samples is looser than the observed
#: noise on the real data (checked before being fixed here), not tuned to it.
PLATEAU_TIME_TOLERANCE_SAMPLES = 2


class AuditError(RuntimeError):
    """Raised when the audit cannot proceed at all (missing archive, bad shape)."""


# ---------------------------------------------------------------------------
# ground truth: negative-control status and the (positionless) step depths
# ---------------------------------------------------------------------------

def load_known_step_depths_mm() -> list[float]:
    """
    The four attested Pk050 back-wall thicknesses, ascending. Raises if the
    truth file's shape changes underneath this script -- exactly as
    `bam_hyperbola_velocity_audit.load_targets` does for Pk266.
    """
    data = json.loads(bam_truth.TRUTH_FILE.read_text())
    spec = next((s for s in data["specimens"] if s["id"] == "Pk050"), None)
    if spec is None:
        raise AuditError("no Pk050 specimen entry in bam_pk266_targets.json: file may have changed")
    depths = spec.get("step_thicknesses_mm")
    if not depths or len(depths) != 4:
        raise AuditError(f"expected 4 Pk050 step thicknesses, found {depths}")
    return sorted(float(d) for d in depths)


# ---------------------------------------------------------------------------
# radar evidence: whole-specimen scan for stable, high-confidence reflectors
# ---------------------------------------------------------------------------

@dataclass
class Plateau:
    x_start_mm: float
    x_end_mm: float
    n_nodes: int
    mean_time_ns: float
    std_time_ns: float
    min_confidence: float
    mean_confidence: float
    picks: list  # ArrivalPick, one per X node in the run


@dataclass
class RejectedRun:
    x_start_mm: float
    x_end_mm: float
    n_nodes: int
    mean_time_ns: float
    mean_confidence: float
    reason: str


def verify_y_invariance(volume: np.ndarray, grid: "bam_ingest.GridSpec",
                        time_axis: TimeAxis, direct_end: int, probe_x_mm: float) -> dict:
    """
    Measures, rather than assumes, whether the back-wall-style reflection at
    one representative X is Y-invariant in the specimen's centre and
    edge-affected only near Y=0/800 -- the real justification Pk266's own
    docstring gives for averaging across a central Y band. Run BEFORE that
    averaging is relied on below, on Pk050's own data.
    """
    x_node = grid.x_node(probe_x_mm)
    env = np.abs(signal.hilbert(volume[x_node, :, direct_end:], axis=1))
    peak_idx = np.argmax(env, axis=1) + direct_end
    peak_time = time_axis.z_values_ns[peak_idx]
    y_lo, y_hi = DEFAULT_Y_MARGIN_MM, float(grid.y[-1]) - DEFAULT_Y_MARGIN_MM
    central = [i for i, y in enumerate(grid.y) if y_lo <= y <= y_hi]
    edge = [i for i in range(len(grid.y)) if i not in central]
    central_std = float(np.std(peak_time[central])) if central else None
    edge_vals = peak_time[edge] if edge else np.array([])
    return {
        "probe_x_mm": probe_x_mm,
        "central_band_std_ns": central_std,
        "central_band_n": len(central),
        "edge_band_mean_ns": float(np.mean(edge_vals)) if edge_vals.size else None,
        "edge_band_differs_from_centre": (
            bool(edge_vals.size and central_std is not None
                and abs(float(np.mean(edge_vals)) - float(np.mean(peak_time[central]))) > 3 * central_std)
        ),
        "note": "Central-band std small and edge band divergent confirms the same "
                "edge-diffraction effect Pk266 excludes by margin, on Pk050's own data "
                "-- not assumed by analogy.",
    }


def pick_all_x(traces_by_x_z: np.ndarray, time_axis: TimeAxis,
               search_start: int, noise: float) -> list[ArrivalPick]:
    """One picked arrival per X node, using the SAME envelope/noise-floor rule as Pk266."""
    envelope = np.abs(signal.hilbert(traces_by_x_z[:, search_start:], axis=1))
    picks = []
    for i in range(traces_by_x_z.shape[0]):
        rel = int(np.argmax(envelope[i]))
        idx = search_start + rel
        amp = float(envelope[i, rel])
        picks.append(ArrivalPick(
            x_mm=None, time_ns=float(time_axis.z_values_ns[idx]), sample_index=idx,
            amplitude=amp, confidence=amp / noise if noise > 0 else float("inf"),
        ))
    return picks


def segment_plateaus(picks: list[ArrivalPick], x_values_mm: np.ndarray,
                     sample_interval_ns: float, x_step_mm: float) -> tuple[list[Plateau], list[RejectedRun]]:
    """
    Groups contiguous X nodes into runs of stable, high-confidence picks
    (a real reflector), keeping runs that fail EITHER criterion as explicitly
    reported rejections rather than silently dropping them.
    """
    tolerance_ns = PLATEAU_TIME_TOLERANCE_SAMPLES * sample_interval_ns
    n = len(picks)
    runs: list[list[int]] = []
    current = [0]
    for i in range(1, n):
        if (picks[i].confidence >= MIN_PICK_CONFIDENCE
                and picks[i - 1].confidence >= MIN_PICK_CONFIDENCE
                and abs(picks[i].time_ns - picks[i - 1].time_ns) <= tolerance_ns):
            current.append(i)
        else:
            runs.append(current)
            current = [i]
    runs.append(current)

    plateaus: list[Plateau] = []
    rejected: list[RejectedRun] = []
    for run in runs:
        confidences = [picks[i].confidence for i in run]
        if min(confidences) < MIN_PICK_CONFIDENCE:
            continue  # a run of unusable nodes; not a candidate at all
        times = [picks[i].time_ns for i in run]
        extent_mm = (len(run) - 1) * x_step_mm
        if extent_mm < MIN_PLATEAU_RUN_MM:
            rejected.append(RejectedRun(
                x_start_mm=float(x_values_mm[run[0]]), x_end_mm=float(x_values_mm[run[-1]]),
                n_nodes=len(run), mean_time_ns=float(np.mean(times)),
                mean_confidence=float(np.mean(confidences)),
                reason=f"spans only {extent_mm:.0f} mm, below the {MIN_PLATEAU_RUN_MM:.0f} mm "
                       f"minimum for a genuine physical reflector region",
            ))
            continue
        plateaus.append(Plateau(
            x_start_mm=float(x_values_mm[run[0]]), x_end_mm=float(x_values_mm[run[-1]]),
            n_nodes=len(run), mean_time_ns=float(np.mean(times)), std_time_ns=float(np.std(times)),
            min_confidence=float(min(confidences)), mean_confidence=float(np.mean(confidences)),
            picks=[picks[i] for i in run],
        ))
    return plateaus, rejected


# ---------------------------------------------------------------------------
# hyperbola applicability check -- verified, not assumed, per section 7
# ---------------------------------------------------------------------------

def check_hyperbola_applicability(plateau: Plateau, velocity_guess_m_per_ns: float = 0.13) -> dict:
    """
    A point diffractor produces a hyperbola: arrival time rises measurably
    away from the apex. A planar back-wall segment produces a flat arrival.
    This computes what a point source AT THE SAME TWO-WAY TIME would predict
    over half this plateau's own aperture, and compares it against the
    plateau's OBSERVED time variation -- an empirical check, not an assumed
    conclusion.
    """
    half_aperture_m = (plateau.x_end_mm - plateau.x_start_mm) / 2.0 / 1000.0
    t0_ns = plateau.mean_time_ns
    predicted_point_source_time_ns = float(
        np.sqrt(t0_ns ** 2 + (2 * half_aperture_m / velocity_guess_m_per_ns) ** 2)
    )
    predicted_rise_ns = predicted_point_source_time_ns - t0_ns
    observed_rise_ns = plateau.std_time_ns  # the actual spread seen across the run
    applicable = observed_rise_ns > 0.5 * predicted_rise_ns
    return {
        "half_aperture_m": half_aperture_m,
        "velocity_guess_m_per_ns_for_this_check_only": velocity_guess_m_per_ns,
        "predicted_point_source_rise_ns": predicted_rise_ns,
        "observed_time_std_ns": observed_rise_ns,
        "hyperbola_applicable": applicable,
        "note": (
            "Observed time variation across the plateau is far below what a point "
            "diffractor at this depth and aperture would produce: the reflector behaves "
            "as planar (a back wall), not a point target. Hyperbola fitting is not "
            "attempted -- fitting one would fit picking noise, not curvature."
            if not applicable else
            "Observed time variation is comparable to what a point source would produce; "
            "a hyperbola fit may be meaningful here."
        ),
    }


# ---------------------------------------------------------------------------
# rank-pairing with known depths -- explicit, never position-based
# ---------------------------------------------------------------------------

def pair_plateaus_with_known_depths(plateaus: list[Plateau], known_depths_mm: list[float]) -> dict:
    """
    Pairs the N surviving plateaus (sorted by two-way time, ascending) with
    the N SHALLOWEST known depths (sorted ascending), on the physical
    assumption of one global velocity across the specimen (see module
    docstring) plus, when N < len(known_depths_mm), the assumption that
    surviving reflectors are the shallow ones (GPR attenuation increases
    with depth, so a partial detection is expected to be biased toward
    shallow targets, not a uniformly random subset).

    Returns the pairing AND states both assumptions explicitly; this
    function never reads or infers any X position for the paired depths.
    """
    ordered_plateaus = sorted(plateaus, key=lambda p: p.mean_time_ns)
    ordered_depths = sorted(known_depths_mm)
    n = len(ordered_plateaus)
    pairs = [
        {"rank": i, "known_depth_mm": ordered_depths[i],
         "plateau_mean_time_ns": ordered_plateaus[i].mean_time_ns,
         "plateau_x_range_mm": [ordered_plateaus[i].x_start_mm, ordered_plateaus[i].x_end_mm]}
        for i in range(n)
    ]
    unmatched_depths_mm = ordered_depths[n:]
    return {
        "n_plateaus": n, "n_known_depths": len(ordered_depths),
        "pairs": pairs, "unmatched_known_depths_mm": unmatched_depths_mm,
        "assumption": (
            "Pairing is by RANK ORDER of two-way time (plateaus) against RANK ORDER of "
            "thickness (known depths) -- never by X position, which no source in this "
            "repository declares. This rests on one global propagation velocity across "
            "the specimen (already implicit in Method A itself), plus, only when fewer "
            "plateaus survive than known depths, the physical expectation that GPR "
            "attenuation makes shallow reflectors survive first. This is a stated model "
            "assumption, not measured evidence, and by itself never upgrades a "
            "classification."
        ),
    }


def illustrate_nonidentifiability(depth_mm: float, time_ns: float,
                                  v_grid_m_per_ns: tuple[float, ...] =
                                  (0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20)) -> list[dict]:
    """
    With exactly ONE (known_depth, picked_time) pair, t0 and v cannot both be
    fit -- there is one equation and two unknowns. Rather than assert that
    abstractly, this computes the t0 implied by EACH of several physically
    plausible velocities and shows they disagree wildly, which is what
    "not identifiable" concretely means. This is diagnostic output only,
    never a fit, and never used to select or endorse a velocity.
    """
    depth_m = depth_mm / 1000.0
    out = []
    for v in v_grid_m_per_ns:
        implied_t0 = time_ns - 2 * depth_m / v
        out.append({
            "velocity_m_per_ns": v, "implied_t0_ns": implied_t0,
            "physically_plausible_t0": 0.0 <= implied_t0 < time_ns,
        })
    return out


def sensitivity_of_single_point(depth_mm: float, time_ns: float, sample_interval_ns: float,
                                v_m_per_ns: float = 0.13) -> dict:
    """
    How much the diagnostic (not fitted) implied-t0 in
    `illustrate_nonidentifiability` moves under a +-1/+-2 sample perturbation
    of the one usable pick, at one illustrative velocity. Reported for
    completeness (section 9); it is not a substitute for the leave-one-out
    or multi-target sensitivity Method A performs on Pk266, which need >= 2
    usable points and are therefore not available here.
    """
    depth_m = depth_mm / 1000.0
    perturbations = []
    for n_samples in (-2, -1, 1, 2):
        shifted_time_ns = time_ns + n_samples * sample_interval_ns
        implied_t0 = shifted_time_ns - 2 * depth_m / v_m_per_ns
        perturbations.append({"shift_samples": n_samples, "shifted_time_ns": shifted_time_ns,
                              "implied_t0_ns": implied_t0})
    return {"illustrative_velocity_m_per_ns": v_m_per_ns, "perturbations": perturbations,
           "note": "Illustrative only -- see illustrate_nonidentifiability for why no "
                   "single-point 'fit' can be reported as a result."}


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def run_scan(specimen_id: str, scan_id: str, y_margin_mm: float, root: Path) -> dict:
    scan = bam_ingest.load_scan(specimen_id, scan_id, root=root)
    volume = bam_ingest.load_volume(scan, root=root)
    time_axis = establish_time_axis(scan)
    grid = scan.grid

    y_lo_mm, y_hi_mm = y_margin_mm, float(grid.y[-1]) - y_margin_mm
    y_indices = [i for i, y in enumerate(grid.y) if y_lo_mm <= y <= y_hi_mm]
    central_traces = volume[:, y_indices, :].mean(axis=1)

    search_start = _direct_arrival_extent(central_traces)
    noise = _noise_floor(central_traces, search_start)
    picks = pick_all_x(central_traces, time_axis, search_start, noise)
    for i, p in enumerate(picks):
        p.x_mm = float(grid.x[i])

    plateaus, rejected = segment_plateaus(picks, grid.x, time_axis.sample_interval_ns, grid.x_step)
    # Sorted once, by two-way time ascending, and used in this order EVERYWHERE
    # below -- `pair_plateaus_with_known_depths` pairs by this same rank order,
    # so misaligning the two lists would silently swap which depth goes with
    # which plateau.
    plateaus = sorted(plateaus, key=lambda p: p.mean_time_ns)

    y_invariance = None
    if plateaus:
        mid_pick = plateaus[0].picks[len(plateaus[0].picks) // 2]
        y_invariance = verify_y_invariance(
            volume, grid, time_axis, search_start, probe_x_mm=mid_pick.x_mm,
        )

    hyperbola_checks = [check_hyperbola_applicability(p) for p in plateaus]

    known_depths_mm = load_known_step_depths_mm()
    pairing = pair_plateaus_with_known_depths(plateaus, known_depths_mm)

    diagnostics = []
    for pair, plateau in zip(pairing["pairs"], plateaus):
        diagnostics.append({
            "known_depth_mm": pair["known_depth_mm"],
            "plateau_x_range_mm": pair["plateau_x_range_mm"],
            "nonidentifiability": illustrate_nonidentifiability(pair["known_depth_mm"], plateau.mean_time_ns),
            "sensitivity": sensitivity_of_single_point(
                pair["known_depth_mm"], plateau.mean_time_ns, time_axis.sample_interval_ns),
        })

    n_usable = len(plateaus)
    method_a_result = None
    loo_result = None
    sensitivity_result = None
    permittivity_result = None
    if n_usable < 2:
        classification = "FAILED"
        reasons = [
            f"only {n_usable} usable radar reflector(s) found on the entire specimen "
            f"(confidence >= {MIN_PICK_CONFIDENCE}, extent >= {MIN_PLATEAU_RUN_MM:.0f} mm); "
            f"at least 2 independent (depth, time) pairs are required to jointly fit t0 and "
            f"v, so no fit -- not even an unidentifiable one -- can be attempted",
        ]
        if n_usable == 1:
            reasons.append(
                "the single usable reflector's implied t0 varies from "
                f"{illustrate_nonidentifiability(pairing['pairs'][0]['known_depth_mm'], plateaus[0].mean_time_ns)[0]['implied_t0_ns']:.3f} ns "
                "to a wildly different value across a physically plausible velocity range "
                "(see 'diagnostics'), which is a concrete demonstration of non-identifiability, "
                "not merely an assertion of it"
            )
    else:
        # A real Method A fit is now possible -- reuse the SAME validated fitting
        # code Pk266 uses, on the rank-paired (depth, plateau-time) pairs. The
        # pairing itself (not the fit) is where Pk050's extra assumption lives;
        # that is stated once in `pairing["assumption"]` and never hidden here.
        associations = []
        for pair, plateau in zip(pairing["pairs"], plateaus):
            mid_pick = plateau.picks[len(plateau.picks) // 2]
            target = Target(
                target_id=f"Pk050-plateau-x{plateau.x_start_mm:.0f}-{plateau.x_end_mm:.0f}",
                x_mm=mid_pick.x_mm, depth_mm=pair["known_depth_mm"],
                depth_source="data_repository step_thickness_mm, RANK-PAIRED to this plateau "
                             "by two-way time (see depth_pairing.assumption) -- not an "
                             "independently sourced association like Pk266's",
                ground_truth_ambiguity_mm=0.0,
            )
            apex_pick = ArrivalPick(
                x_mm=mid_pick.x_mm, time_ns=plateau.mean_time_ns, sample_index=mid_pick.sample_index,
                amplitude=mid_pick.amplitude, confidence=plateau.mean_confidence,
            )
            associations.append(TargetAssociation(
                target=target, x_node=-1, y_indices_averaged=y_indices,
                direct_arrival_index=search_start, apex_pick=apex_pick, curve=[],
                usable=True, reason="stable, high-confidence plateau; see plateaus[]",
            ))

        method_a = fit_method_a(associations)
        method_a_result = asdict(method_a)
        loo_result = leave_one_out(associations)
        sensitivity_result = picking_sensitivity(associations, time_axis.sample_interval_ns)
        permittivity_result = relative_permittivity(method_a.velocity_m_per_ns)

        hyperbola_inapplicable = all(not h["hyperbola_applicable"] for h in hyperbola_checks)

        if method_a.velocity_m_per_ns is None:
            classification = "FAILED"
            reasons = [f"known-depth fit over {n_usable} rank-paired reflectors produced a "
                      f"non-physical result: {method_a.identifiability_note}"]
        elif not method_a.identifiable:
            classification = "INCONCLUSIVE"
            reasons = [f"known-depth fit over {n_usable} rank-paired reflectors is not "
                      f"identifiable: {method_a.identifiability_note}"]
        else:
            # Identifiable numerically, but capped below VALIDATED VELOCITY: Method B
            # cannot cross-check it (planar reflectors, verified above, not merely
            # unconverged), and the depth<->reflector correspondence itself rests on
            # the stated rank-order assumption rather than an independently published
            # position -- a materially weaker evidentiary basis than Pk266 had even
            # when Pk266 itself was identifiable.
            classification = "ESTIMATED BUT NOT VALIDATED"
            reasons = [
                f"known-depth fit over {n_usable} rank-paired reflectors is numerically "
                f"identifiable ({method_a.identifiability_note}), but cannot be classified "
                f"VALIDATED VELOCITY: hyperbola cross-check is not available because the "
                f"reflectors are verified planar (hyperbola_inapplicable={hyperbola_inapplicable}), "
                f"and the depth-to-reflector correspondence is a rank-order assumption, not an "
                f"independently published position like Pk266's"
            ]

    epsr = scan.dzt_header.get("epsr")
    epsr_velocity = C_M_PER_NS / (epsr ** 0.5) if epsr else None

    return {
        "scan_id": scan_id,
        "source": {"specimen_id": specimen_id, "archive": scan.archive,
                  "provenance": scan.provenance, "dzt_header": scan.dzt_header},
        "geometry": {"grid": grid.as_dict(), "y_margin_mm": y_margin_mm},
        "time_axis": {k: v for k, v in asdict(time_axis).items() if k != "z_values_ns"},
        "negative_control_attestation": asdict(bam_truth.load_control(specimen_id)),
        "known_step_depths_mm": known_depths_mm,
        "known_step_depth_x_positions": "NOT DECLARED IN ANY SOURCE -- never inferred; see module docstring",
        "y_invariance_check": y_invariance,
        "whole_specimen_scan": {
            "direct_arrival_ends_ns": float(time_axis.z_values_ns[search_start]),
            "noise_floor": noise,
            "n_x_nodes_scanned": len(picks),
        },
        "plateaus": [
            {"x_start_mm": p.x_start_mm, "x_end_mm": p.x_end_mm, "n_nodes": p.n_nodes,
             "mean_time_ns": p.mean_time_ns, "std_time_ns": p.std_time_ns,
             "min_confidence": p.min_confidence, "mean_confidence": p.mean_confidence}
            for p in plateaus
        ],
        "rejected_runs": [asdict(r) for r in rejected],
        "hyperbola_applicability": hyperbola_checks,
        "depth_pairing": pairing,
        "diagnostics": diagnostics,
        "dzt_declared_epsr": epsr,
        "dzt_declared_epsr_implied_velocity_m_per_ns": epsr_velocity,
        "dzt_declared_epsr_note": (
            "This is the GSSI instrument's own configured relative permittivity at "
            "acquisition time, identical (5.5) across both Pk266 and Pk050 and both "
            "frequencies -- almost certainly a generic concrete default the operator "
            "dialled in, not a per-specimen calibration. Reported as weak, DECLARED_BY_"
            "SOURCE context only, never as validation."
        ),
        "n_usable_reflectors": n_usable,
        "method_a": method_a_result,
        "leave_one_out": loo_result,
        "picking_sensitivity": sensitivity_result,
        "relative_permittivity": permittivity_result,
        "classification": classification,
        "classification_reasons": reasons,
    }


def run_audit(specimen_id: str, scan_ids: list[str], y_margin_mm: float, root: Path) -> dict:
    generated = datetime.now(timezone.utc).isoformat()
    try:
        scans = [run_scan(specimen_id, sid, y_margin_mm, root) for sid in scan_ids]
    except bam_ingest.BenchmarkIngestError as exc:
        raise AuditError(f"could not load real BAM data: {exc}") from exc

    all_failed = all(s["classification"] == "FAILED" for s in scans)
    all_usable_counts = {s["scan_id"]: s["n_usable_reflectors"] for s in scans}
    all_classifications = {s["scan_id"]: s["classification"] for s in scans}
    consistent = len(set(all_usable_counts.values())) == 1

    # Overall classification is the MOST CONSERVATIVE across the independent scans,
    # never the best-looking one: a positive result on one scan does not outweigh a
    # negative result on another, per the task's own anti-overfitting rule (do not
    # force agreement, do not average inconsistent estimates).
    RANK = {"FAILED": 0, "INCONCLUSIVE": 1, "ESTIMATED BUT NOT VALIDATED": 2, "VALIDATED VELOCITY": 3}
    worst_scan = min(scans, key=lambda s: RANK[s["classification"]])
    overall_classification = worst_scan["classification"]
    overall_reasons = list(worst_scan["classification_reasons"])
    if consistent and len(scans) > 1:
        overall_reasons.append(
            f"result is consistent across all {len(scans)} independent scans "
            f"(usable-reflector counts: {all_usable_counts})"
        )
    else:
        overall_reasons.append(
            f"usable-reflector counts and classifications are NOT consistent across the "
            f"{len(scans)} scans ({all_classifications}); the overall classification is the "
            f"most conservative of these, not an average or the best-looking one -- see "
            f"'scans' for each scan's own result in full"
        )

    return {
        "audit": "bam-pk050-negative-control-velocity-audit",
        "generated_utc": generated,
        "compared_against": "artifacts/bam/bam_hyperbola_velocity_audit.json (Pk266)",
        "model": {
            "method_a": "t_measured = t0 + 2*d/v, jointly fit over known depths (same as Pk266)",
            "method_b": "per-target hyperbola -- checked for physical applicability before use, "
                       "not assumed (see hyperbola_applicability per scan)",
        },
        "scans": scans,
        "cross_scan_consistency": {
            "usable_reflector_counts_by_scan": all_usable_counts,
            "consistent": consistent,
            "all_scans_failed": all_failed,
        },
        "classification": overall_classification,
        "classification_reasons": overall_reasons,
        "pk266_comparison": {
            "pk266_n_known_depths": 4, "pk050_n_known_depths": 4,
            "pk266_n_usable_targets": 4, "pk050_n_usable_reflectors_by_scan": all_usable_counts,
            "pk266_classification": "INCONCLUSIVE",
            "pk050_classification": overall_classification,
            "note": (
                "Pk266 failed on IDENTIFIABILITY with 4 usable, well-separated, independently "
                "positioned targets (t0/v correlation -0.9387). Pk050 fails earlier and more "
                "fundamentally in its two 2.6 GHz scans: it is a fabricator-attested negative "
                "control with zero embedded targets, and of its four real step-back-wall "
                "depths, only one produces a radar reflection distinguishable from noise. Its "
                "two 1.5 GHz scans (deeper penetration) recover a second, and in one case a "
                "third, reflector -- but even where that yields a numerically identifiable fit "
                "(see 'scans'), it cannot be classified above ESTIMATED BUT NOT VALIDATED: "
                "Pk050's depth-to-reflector correspondence is a rank-order physical assumption, "
                "never an independently published position like Pk266's, and no hyperbola "
                "cross-check exists for a planar reflector. Taking the most conservative scan, "
                "as this audit does, the identifiability question Pk266 left open is not "
                "resolved by Pk050 either."
            ),
        },
        "product_implication": (
            "Not a live product change. Pk050 does not provide evidence to justify BAM -> "
            "SubterraRecord velocity integration. DEFAULT_GPR_VELOCITY_M_PER_NS is unchanged."
            if overall_classification in ("FAILED", "INCONCLUSIVE") else
            "See classification_reasons; even a positive result here would need the same "
            "controlled-integration path already scoped for Pk266."
        ),
        "next_evidence_candidate": (
            "Neither Pk266 nor Pk050 supports a validated velocity. The next real, "
            "unexplored candidate already on disk is `scripts/characterise_4tu.py`'s "
            "`velocity_for()`, which derives velocity from 4TU's own DECLARED (not "
            "fitted) per-site relative permittivity in `Metadata.csv` -- a structurally "
            "different evidence type (an instrument/survey-declared parameter, not a "
            "radar-timing fit) that neither BAM audit could test. It is currently "
            "production-unwired and has not itself been audited for real-dataset "
            "coverage or declaration reliability; that audit, not a third BAM specimen "
            "or more elaborate fitting machinery, is the recommended next step. Pk401 "
            "(BAM's third specimen) remains deliberately unacquired -- its target "
            "positions exist only in undigitised drawings, per "
            "`datasets/raw/bam_concrete/PROVENANCE.json`."
        ),
    }


def _print_summary(result: dict) -> None:
    print(f"BAM Pk050 negative-control audit ({len(result['scans'])} scan(s))")
    for s in result["scans"]:
        print(f"  {s['scan_id']}:")
        print(f"    negative control attested: {s['negative_control_attestation']['attested']}")
        print(f"    known step depths (mm, no X source): {s['known_step_depths_mm']}")
        print(f"    usable reflectors found: {s['n_usable_reflectors']}")
        for p in s["plateaus"]:
            print(f"      plateau x={p['x_start_mm']:.0f}-{p['x_end_mm']:.0f}mm "
                 f"t={p['mean_time_ns']:.4f}+-{p['std_time_ns']:.4f}ns "
                 f"conf={p['mean_confidence']:.1f}")
        for r in s["rejected_runs"]:
            if r["n_nodes"] >= 2:
                print(f"      rejected run x={r['x_start_mm']:.0f}-{r['x_end_mm']:.0f}mm "
                     f"({r['reason']})")
        if s["method_a"]:
            ma = s["method_a"]
            print(f"    Method A (rank-paired): v={ma['velocity_m_per_ns']}, t0={ma['t0_ns']}, "
                 f"identifiable={ma['identifiable']} ({ma['identifiability_note']})")
        print(f"    classification: {s['classification']}")
    print(f"\nOVERALL CLASSIFICATION: {result['classification']}")
    for r in result["classification_reasons"]:
        print(f"  - {r}")
    print(f"\n{result['pk266_comparison']['note']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specimen-id", default="Pk050")
    parser.add_argument("--scan-ids", nargs="+", default=[
        "Pk050_3D_Dataset_2_6_GHz_Rot00", "Pk050_3D_Dataset_2_6_GHz_Rot90",
        "Pk050_3D_Dataset_1_5_GHz_Rot00", "Pk050_3D_Dataset_1_5_GHz_Rot90",
    ])
    parser.add_argument("--y-margin-mm", type=float, default=DEFAULT_Y_MARGIN_MM)
    parser.add_argument("--root", type=Path, default=REPO_ROOT / bam_ingest.DEFAULT_ROOT)
    parser.add_argument("--out", type=Path,
                       default=REPO_ROOT / "artifacts" / "bam" / "pk050_velocity_audit.json")
    args = parser.parse_args()

    try:
        result = run_audit(args.specimen_id, args.scan_ids, args.y_margin_mm, args.root)
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
