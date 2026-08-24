"""
Does an INDEPENDENTLY-derived time-zero -- from `preprocessing.time_zero`'s
own direct-wave consensus method (Method C), the same framework this
session wired into `POST /api/datasets/{id}/apply_time_zero` -- break the
t0/v identifiability confound that left `scripts/bam_hyperbola_velocity_
audit.py`'s Pk266 known-depth fit `INCONCLUSIVE`?

THIS IS A RESEARCH AUDIT, NOT A PRODUCT FEATURE. Same discipline as the
other BAM audits: reads the real archive already on disk
(`datasets/raw/bam_concrete/Pk266_Dataset.zip`) through the existing
`benchmark.bam_ingest` reader, touches no live dataset, no converter, no
provenance schema. `preprocessing.time_zero.direct_wave_consensus_time_zero`
is imported and reused directly (not reimplemented) -- the one exception to
"touches no `SubterraRecord`" this file makes, and a narrow one: throwaway
`SubterraRecord.model_construct(...)` objects are built purely as an
in-memory carrier for that ALREADY-TESTED function, never saved, never
touching `database.records_store` or any live dataset_id. Reproduce with:

    python -m scripts.bam_independent_t0_velocity_audit --out artifacts/bam/bam_independent_t0_velocity_audit.json

WHY THIS IS A GENUINELY NEW ANGLE, NOT A RETRY. `bam_pk050_velocity_audit.py`
already tried to break this SAME confound by finding MORE known-depth
evidence (401 step-thickness observations across the whole specimen instead
of 4 point targets) and still classified FAILED. This audit tries a
different axis: instead of adding more depth evidence, it REMOVES one of
the two free parameters from Method A's joint fit. t0 is not fit jointly
with v here -- it is measured independently, from the direct/coupling-wave
arrival itself, using the exact same method now live in production. With t0
fixed, v is recovered per target as `v_i = 2*d_i / (t_i - t0)`: four
independent 1-parameter estimates, checkable for CONSISTENCY with each
other directly -- something the original 2-parameter joint fit could not
offer with only 4 points.

WHY t0 IS DERIVED FROM THE SPECIMEN AS A WHOLE, NOT PER TARGET. Instrument
time-zero is a property of the antenna/recording electronics, constant
across one continuous acquisition -- the same reasoning
`preprocessing.time_zero`'s own module docstring gives for treating a
correction as a single global offset. Pk266's four ducts each span the
FULL 800 mm Y-width (`bam_hyperbola_velocity_audit.py`'s own module
docstring), consistent with one continuous robotic raster scan, with no
documented boundary inside the archive suggesting more than one
acquisition pass -- so this audit derives ONE t0 for the whole specimen,
from a broad, representative, NON-averaged sample of its own real traces
(one full X-sweep at a representative Y), so `direct_wave_consensus_time_
zero`'s cross-trace consensus sees each trace's genuine independent noise,
not an already-averaged window.

WHY METHOD A (metadata_instrument_time_zero) DOES NOT APPLY HERE. BAM is
DZT format, not SEG-Y; GSSI's own analogous header field (`rhf_position`)
is explicitly UNTRUSTED by that method (see
`preprocessing/time_zero.py::UNRESOLVED_VENDOR_FIELDS`). This audit
therefore uses ONLY Method C. If that consensus does not resolve
(`INCONCLUSIVE`/`UNAVAILABLE`), this audit reports that honestly rather
than falling back to a guess -- and reports `FAILED` for the whole line of
inquiry, since there would be no independent t0 to fix.

WHAT "SUCCESS" WOULD MEAN, AND WHAT IT DOES NOT MEAN. A materially smaller
t0/v identifiability problem is not the same as a validated velocity: the
per-target velocities must ALSO still agree with Method B's independent
hyperbola-curvature estimate (`compare_methods`, reused verbatim -- the
SAME cross-check and the SAME `MATERIAL_VELOCITY_DISAGREEMENT` threshold
the original script already uses), or the honest classification stops at
`ESTIMATED BUT NOT VALIDATED`, not `VALIDATED VELOCITY`. Passing one check
and failing another is reported as exactly that, not rounded up.
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from benchmark import bam_ingest
from preprocessing.time_zero import direct_wave_consensus_time_zero
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.time_zero import TimeZeroResult, TimeZeroStatus
from scripts.bam_hyperbola_velocity_audit import (
    DEFAULT_APERTURE_MM,
    DEFAULT_Y_MARGIN_MM,
    LARGE_RELATIVE_DEPTH_ERROR,
    MATERIAL_VELOCITY_DISAGREEMENT,
    ArrivalPick,
    MethodAResult,
    TargetAssociation,
    associate_target,
    compare_methods,
    establish_time_axis,
    fit_method_b,
    leave_one_out,
    load_targets,
    relative_permittivity,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class AuditError(RuntimeError):
    """Raised when the audit cannot proceed at all (missing archive, bad shape)."""


# ---------------------------------------------------------------------------
# independent time-zero, from the specimen's own real traces
# ---------------------------------------------------------------------------

def sample_traces_for_time_zero(volume, grid, y_margin_mm: float) -> list[list[float]]:
    """
    One full X-sweep of real, INDIVIDUAL (not averaged) traces at a single
    representative Y, within the same edge margin `associate_target` already
    uses. NOT the target-adjacent averaged windows Method A/B use --
    `direct_wave_consensus_time_zero` needs each trace's own independent
    noise realization for its cross-trace consensus to mean anything; an
    already-averaged window would corrupt exactly that.
    """
    y_lo_mm, y_hi_mm = y_margin_mm, float(grid.y[-1]) - y_margin_mm
    y_indices = [i for i, y in enumerate(grid.y) if y_lo_mm <= y <= y_hi_mm]
    if not y_indices:
        return []
    y_mid = y_indices[len(y_indices) // 2]
    return [volume[x, y_mid, :].astype(float).tolist() for x in range(grid.x.shape[0])]


def derive_independent_time_zero(volume, grid, sample_interval_ns: float,
                                 y_margin_mm: float) -> TimeZeroResult:
    """
    `preprocessing.time_zero.direct_wave_consensus_time_zero`, reused
    verbatim -- the same function `POST /api/datasets/{id}/apply_time_zero`
    calls in production, applied here to real BAM traces instead of a
    live dataset's stored records.
    """
    traces = sample_traces_for_time_zero(volume, grid, y_margin_mm)
    records = [
        SubterraRecord.model_construct(
            dataset_id="bam-research-audit-not-persisted", latitude=None, longitude=None,
            elevation=None, depth=None, signal=t, sensor_type=SensorType.GPR,
            ground_truth="none", metadata={},
        )
        for t in traces
    ]
    return direct_wave_consensus_time_zero(records, sample_interval_ns)


# ---------------------------------------------------------------------------
# velocity, with t0 FIXED rather than jointly fit
# ---------------------------------------------------------------------------

@dataclass
class FixedT0Result:
    t0_ns: Optional[float]
    per_target_velocity_m_per_ns: dict
    usable_targets: list
    mean_velocity_m_per_ns: Optional[float]
    velocity_spread_frac: Optional[float]
    depth_predicted_mm: dict
    depth_error_mm: dict
    rms_depth_error_mm: Optional[float]
    max_depth_error_mm: Optional[float]
    usable: bool
    reason: str


def fit_with_fixed_t0(associations: list[TargetAssociation], t0_ns: float) -> FixedT0Result:
    """
    `v_i = 2*d_i / (t_i - t0)` per target, t0 held fixed (not fit). A target
    whose apex arrives BEFORE the fixed t0 (non-physical: dt <= 0) is
    excluded, not clamped -- the same "never silently valid" rule
    `preprocessing.time_zero.apply_time_zero_correction` already applies to
    a negative corrected time.
    """
    usable_assoc = [a for a in associations if a.usable and a.apex_pick is not None]
    per_v: dict = {}
    for a in usable_assoc:
        dt = a.apex_pick.time_ns - t0_ns
        if dt > 0:
            per_v[a.target.target_id] = 2 * (a.target.depth_mm / 1000.0) / dt

    if len(per_v) < 2:
        return FixedT0Result(
            t0_ns, per_v, [a.target.target_id for a in usable_assoc], None, None, {}, {},
            None, None, False,
            f"fewer than 2 targets gave a physical (positive) travel time after fixing "
            f"t0={t0_ns}; {len(per_v)} usable",
        )

    vs = list(per_v.values())
    mean_v = statistics.mean(vs)
    spread_frac = (max(vs) - min(vs)) / mean_v if mean_v else None

    depth_pred = {
        a.target.target_id: mean_v * (a.apex_pick.time_ns - t0_ns) / 2 * 1000.0
        for a in usable_assoc if a.target.target_id in per_v
    }
    depth_err = {tid: depth_pred[tid] - next(
        a.target.depth_mm for a in usable_assoc if a.target.target_id == tid)
        for tid in depth_pred}
    errs = list(depth_err.values())

    return FixedT0Result(
        t0_ns, per_v, [a.target.target_id for a in usable_assoc], mean_v, spread_frac,
        depth_pred, depth_err,
        float(statistics.sqrt(sum(e ** 2 for e in errs) / len(errs))) if errs else None,
        float(max(abs(e) for e in errs)) if errs else None,
        True, f"{len(per_v)} of {len(usable_assoc)} usable targets gave a physical fit",
    )


def t0_sensitivity(associations: list[TargetAssociation], t0_ns: float,
                   t0_uncertainty_ns: float) -> dict:
    """
    Refits with t0 shifted by the independent estimate's OWN uncertainty
    (`TimeZeroResult.spread_ns`, halved -- the consensus's spread already
    IS the +-uncertainty band around the median), reporting how much the
    mean velocity moves. A t0 that is tight in an absolute sense but whose
    uncertainty still moves velocity materially is not a stable basis for
    a fixed-t0 fit, and this is the check that would catch it.
    """
    base = fit_with_fixed_t0(associations, t0_ns)
    if base.mean_velocity_m_per_ns is None or t0_uncertainty_ns <= 0:
        return {"base_velocity_m_per_ns": base.mean_velocity_m_per_ns,
                "t0_uncertainty_ns": t0_uncertainty_ns, "max_velocity_delta_frac": None}
    deltas = []
    for shift in (-t0_uncertainty_ns, t0_uncertainty_ns):
        shifted = fit_with_fixed_t0(associations, t0_ns + shift)
        if shifted.mean_velocity_m_per_ns is not None:
            deltas.append(abs(shifted.mean_velocity_m_per_ns - base.mean_velocity_m_per_ns)
                         / base.mean_velocity_m_per_ns)
    return {
        "base_velocity_m_per_ns": base.mean_velocity_m_per_ns,
        "t0_uncertainty_ns": t0_uncertainty_ns,
        "max_velocity_delta_frac": max(deltas) if deltas else None,
    }


# ---------------------------------------------------------------------------
# classification -- conservative by construction, same rubric family as
# scripts/bam_hyperbola_velocity_audit.py::classify
# ---------------------------------------------------------------------------

def classify(t0_result: TimeZeroResult, fixed: FixedT0Result, comparison: dict,
            sensitivity: dict, loo: list, associations: list) -> tuple[str, list]:
    reasons: list = []
    known_depth_mm = {a.target.target_id: a.target.depth_mm for a in associations}

    if not t0_result.resolved:
        reasons.append(
            f"the independent time-zero estimate itself did not resolve: "
            f"{t0_result.status.value} -- {t0_result.basis}")
        return "FAILED", reasons

    if not fixed.usable:
        reasons.append(f"fixed-t0 velocity fit failed: {fixed.reason}")
        return "FAILED", reasons

    if fixed.velocity_spread_frac is not None and fixed.velocity_spread_frac > MATERIAL_VELOCITY_DISAGREEMENT:
        reasons.append(
            f"per-target velocities do not agree with EACH OTHER even with t0 fixed "
            f"(spread {fixed.velocity_spread_frac:.1%}, threshold "
            f"{MATERIAL_VELOCITY_DISAGREEMENT:.0%}) -- fixing t0 did not produce a "
            f"self-consistent estimate")
        return "INCONCLUSIVE", reasons

    if not comparison.get("comparable"):
        reasons.append("could not cross-check against Method B: " + comparison.get("reason", ""))
        return "ESTIMATED BUT NOT VALIDATED", reasons

    if comparison["material_disagreement"]:
        reasons.append(
            f"fixed-t0 velocity ({comparison['method_a_velocity_m_per_ns']:.4f} m/ns) and "
            f"the independent hyperbola-curvature velocity "
            f"({comparison['method_b_mean_velocity_m_per_ns']:.4f} m/ns) disagree by "
            f"{comparison['relative_disagreement']:.1%}, exceeding the "
            f"{MATERIAL_VELOCITY_DISAGREEMENT:.0%} materiality threshold -- fixing t0 improved "
            f"self-consistency among the known-depth targets but did NOT produce a velocity "
            f"the independent curvature-based method corroborates")
        return "ESTIMATED BUT NOT VALIDATED", reasons

    large_errors = {
        tid: err for tid, err in fixed.depth_error_mm.items()
        if abs(err) > LARGE_RELATIVE_DEPTH_ERROR * known_depth_mm[tid]
    }
    if large_errors:
        reasons.append(
            f"predicted depth exceeds {LARGE_RELATIVE_DEPTH_ERROR:.0%} error for: "
            f"{', '.join(f'{tid} ({err:+.1f} mm)' for tid, err in large_errors.items())}")
        return "ESTIMATED BUT NOT VALIDATED", reasons

    max_delta = sensitivity.get("max_velocity_delta_frac")
    if max_delta is not None and max_delta > MATERIAL_VELOCITY_DISAGREEMENT:
        reasons.append(
            f"velocity is not robust to the independent t0 estimate's own uncertainty "
            f"(max delta {max_delta:.1%} when t0 is shifted by its own "
            f"+-{sensitivity['t0_uncertainty_ns']:.4f} ns spread, threshold "
            f"{MATERIAL_VELOCITY_DISAGREEMENT:.0%})")
        return "ESTIMATED BUT NOT VALIDATED", reasons

    loo_unstable = [
        r["held_out"] for r in loo
        if r.get("error_mm") is not None
        and abs(r["error_mm"]) > LARGE_RELATIVE_DEPTH_ERROR * known_depth_mm.get(r["held_out"], float("inf"))
    ]
    if loo_unstable:
        reasons.append(f"leave-one-out depth prediction unstable for: {', '.join(loo_unstable)}")
        return "ESTIMATED BUT NOT VALIDATED", reasons

    reasons.append(
        f"independent t0 resolved ({t0_result.status.value}, spread "
        f"{t0_result.spread_ns} ns), per-target velocities self-consistent "
        f"({fixed.velocity_spread_frac:.1%} spread), depth errors within "
        f"{LARGE_RELATIVE_DEPTH_ERROR:.0%}, corroborated by the independent hyperbola-"
        f"curvature cross-check within {MATERIAL_VELOCITY_DISAGREEMENT:.0%}, stable under "
        f"t0 uncertainty and leave-one-out")
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

    t0_result = derive_independent_time_zero(
        volume, scan.grid, time_axis.sample_interval_ns, y_margin_mm)

    associations = [
        associate_target(t, scan.grid, volume, time_axis, aperture_mm, y_margin_mm)
        for t in targets
    ]

    if not t0_result.resolved:
        fixed = FixedT0Result(None, {}, [], None, None, {}, {}, None, None, False,
                              "no independent t0 was available to fix")
        comparison: dict = {"comparable": False, "reason": "no fixed-t0 velocity to compare"}
        sensitivity: dict = {}
        loo: list = []
        classification, reasons = classify(t0_result, fixed, comparison, sensitivity, loo,
                                           associations)
    else:
        fixed = fit_with_fixed_t0(associations, t0_result.correction_ns)
        hyperbolas = [fit_method_b(a) for a in associations if a.usable]
        method_a_shaped = MethodAResult(
            usable_targets=fixed.usable_targets, t0_ns=fixed.t0_ns,
            velocity_m_per_ns=fixed.mean_velocity_m_per_ns, slope_intercept_correlation=None,
            identifiable=True, identifiability_note="t0 fixed, not jointly fit -- not applicable",
            residuals_ns={}, depth_predicted_mm=fixed.depth_predicted_mm,
            depth_error_mm=fixed.depth_error_mm, rms_depth_error_mm=fixed.rms_depth_error_mm,
            max_depth_error_mm=fixed.max_depth_error_mm,
        )
        comparison = compare_methods(method_a_shaped, hyperbolas)
        t0_uncertainty = (t0_result.spread_ns or 0.0) / 2.0
        sensitivity = t0_sensitivity(associations, t0_result.correction_ns, t0_uncertainty)
        loo = leave_one_out_fixed_t0(associations, t0_result.correction_ns)
        classification, reasons = classify(t0_result, fixed, comparison, sensitivity, loo,
                                           associations)

    permittivity = relative_permittivity(fixed.mean_velocity_m_per_ns if fixed.usable else None)

    return {
        "audit": "bam-independent-t0-velocity",
        "generated_utc": generated,
        "model": {
            "independent_t0": "preprocessing.time_zero.direct_wave_consensus_time_zero, "
                             "applied to a full X-sweep of real traces at one representative Y",
            "fixed_t0_velocity": "v_i = 2*d_i / (t_i - t0), t0 fixed from the independent "
                                "estimate, NOT jointly fit with v",
        },
        "source": {
            "specimen_id": specimen_id, "scan_id": scan_id, "archive": scan.archive,
            "provenance": scan.provenance, "dzt_header": scan.dzt_header,
        },
        "geometry": {
            "grid": scan.grid.as_dict(), "aperture_mm": aperture_mm, "y_margin_mm": y_margin_mm,
        },
        "time_axis": {"n_samples": time_axis.n_samples, "range_ns": time_axis.range_ns,
                      "sample_interval_ns": time_axis.sample_interval_ns,
                      "consistent_with_dzt": time_axis.consistent_with_dzt},
        "independent_time_zero": t0_result.model_dump(mode="json"),
        "targets": [asdict(t) for t in targets],
        "associations": [
            {"target_id": a.target.target_id, "usable": a.usable, "reason": a.reason,
             "apex_pick": asdict(a.apex_pick) if a.apex_pick else None}
            for a in associations
        ],
        "fixed_t0_fit": asdict(fixed),
        "method_b": [asdict(fit_method_b(a)) for a in associations if a.usable],
        "comparison": comparison,
        "t0_sensitivity": sensitivity,
        "leave_one_out": loo,
        "relative_permittivity": permittivity,
        "classification": classification,
        "classification_reasons": reasons,
        "comparison_to_original_joint_fit": {
            "note": "scripts/bam_hyperbola_velocity_audit.py's own joint fit for this "
                   "specimen/scan classified INCONCLUSIVE (t0/v confounded). This audit's "
                   "result is independent evidence, not a correction of that result -- both "
                   "stand on their own.",
        },
        "product_implication": (
            "Not a live product change. This is a research audit only; no live dataset, "
            "converter, or provenance schema is touched."
        ),
    }


def leave_one_out_fixed_t0(associations: list[TargetAssociation], t0_ns: float) -> list:
    """Refits `fit_with_fixed_t0` on every N-1 subset, predicting the held-out target's depth."""
    usable = [a for a in associations if a.usable and a.apex_pick is not None]
    out = []
    for held_out in usable:
        rest = [a for a in usable if a.target.target_id != held_out.target.target_id]
        fit = fit_with_fixed_t0(rest, t0_ns)
        if fit.mean_velocity_m_per_ns is None:
            out.append({"held_out": held_out.target.target_id, "predicted_depth_mm": None,
                       "error_mm": None, "reason": fit.reason})
            continue
        pred_mm = fit.mean_velocity_m_per_ns * (held_out.apex_pick.time_ns - t0_ns) / 2 * 1000.0
        out.append({"held_out": held_out.target.target_id, "predicted_depth_mm": pred_mm,
                   "error_mm": pred_mm - held_out.target.depth_mm})
    return out


#: Every scan variant the Pk266 archive actually holds -- run together by
#: default so a reader sees the full picture (this session found t0 itself
#: is remarkably consistent WITHIN a frequency regardless of rotation --
#: 2.6 GHz picks 0.2935 ns in both Rot00 and Rot90, 1.5 GHz picks 0.68-0.73
#: ns in both -- real physical evidence the estimate reflects antenna
#: hardware, not noise, even where the DOWNSTREAM classification differs
#: per scan) rather than one cherry-picked configuration.
ALL_PK266_SCAN_IDS = (
    "Pk266_3D_Dataset_1_5_GHz_Rot00", "Pk266_3D_Dataset_1_5_GHz_Rot90",
    "Pk266_3D_Dataset_2_6_GHz_Rot00", "Pk266_3D_Dataset_2_6_GHz_Rot90",
)

#: Ranks the same way `scripts/bam_pk050_velocity_audit.py` already does,
#: for the same reason: a summary needs SOME ordering to report a "best
#: seen", without implying the other scans are wrong -- each keeps its own
#: full result in `per_scan`.
_RANK = {"FAILED": 0, "INCONCLUSIVE": 1, "ESTIMATED BUT NOT VALIDATED": 2, "VALIDATED VELOCITY": 3}


def run_audit_all_scans(specimen_id: str, scan_ids: list, aperture_mm: float,
                        y_margin_mm: float, root: Path) -> dict:
    """Runs `run_audit` per scan, independently -- each frequency/rotation is a
    genuinely separate acquisition, so no result is pooled or averaged across
    scans; this only aggregates them for reporting."""
    per_scan = {}
    for scan_id in scan_ids:
        try:
            per_scan[scan_id] = run_audit(specimen_id, scan_id, aperture_mm, y_margin_mm, root)
        except AuditError as exc:
            per_scan[scan_id] = {"classification": "FAILED", "classification_reasons": [str(exc)],
                                 "source": {"specimen_id": specimen_id, "scan_id": scan_id}}

    best_scan_id = max(per_scan, key=lambda sid: _RANK.get(per_scan[sid]["classification"], -1))
    t0_by_frequency: dict = {}
    for scan_id, r in per_scan.items():
        freq = "2.6_GHz" if "2_6_GHz" in scan_id else "1_5_GHz" if "1_5_GHz" in scan_id else "unknown"
        tz = r.get("independent_time_zero") or {}
        t0_by_frequency.setdefault(freq, []).append(
            {"scan_id": scan_id, "correction_ns": tz.get("correction_ns")})

    return {
        "audit": "bam-independent-t0-velocity-all-scans",
        "specimen_id": specimen_id,
        "per_scan": {sid: r["classification"] for sid, r in per_scan.items()},
        "per_scan_full": per_scan,
        "best_classification": per_scan[best_scan_id]["classification"],
        "best_scan_id": best_scan_id,
        "t0_consistency_within_frequency": t0_by_frequency,
        "note": (
            "Each scan is a genuinely separate acquisition (frequency and/or antenna "
            "rotation); classifications are NOT pooled or averaged. 'best_classification' "
            "names the strongest single result seen, not a verdict on the specimen as a "
            "whole -- see per_scan for the full, ungeneralized picture."
        ),
    }


def _print_summary(result: dict) -> None:
    print(f"BAM {result['source']['specimen_id']} / {result['source']['scan_id']} "
         f"(independent t0)")
    tz = result["independent_time_zero"]
    print(f"  independent t0: status={tz['status']} method={tz['method']} "
         f"correction_ns={tz['correction_ns']} spread_ns={tz['spread_ns']} "
         f"picks={tz['successful_picks']}/{tz['traces_evaluated']}")
    ft = result["fixed_t0_fit"]
    print(f"  fixed-t0 fit: mean_v={ft['mean_velocity_m_per_ns']} "
         f"spread_frac={ft['velocity_spread_frac']}")
    if ft["rms_depth_error_mm"] is not None:
        print(f"    RMS depth error {ft['rms_depth_error_mm']:.2f} mm, "
             f"max {ft['max_depth_error_mm']:.2f} mm")
    comp = result["comparison"]
    if comp.get("comparable"):
        print(f"  vs Method B (curvature): {comp['relative_disagreement']:.1%} relative "
             f"disagreement (material: {comp['material_disagreement']})")
    print(f"  CLASSIFICATION: {result['classification']}")
    for r in result["classification_reasons"]:
        print(f"    - {r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specimen-id", default="Pk266")
    parser.add_argument("--scan-id", default=None,
                       help="run exactly one scan; default runs all four Pk266 scan variants")
    parser.add_argument("--aperture-mm", type=float, default=DEFAULT_APERTURE_MM)
    parser.add_argument("--y-margin-mm", type=float, default=DEFAULT_Y_MARGIN_MM)
    parser.add_argument("--root", type=Path, default=REPO_ROOT / bam_ingest.DEFAULT_ROOT)
    parser.add_argument("--out", type=Path,
                       default=REPO_ROOT / "artifacts" / "bam" / "bam_independent_t0_velocity_audit.json")
    args = parser.parse_args()

    if args.scan_id is not None:
        try:
            result = run_audit(args.specimen_id, args.scan_id, args.aperture_mm,
                              args.y_margin_mm, args.root)
        except AuditError as exc:
            print(f"AUDIT FAILED: {exc}")
            return 1
        _print_summary(result)
    else:
        result = run_audit_all_scans(args.specimen_id, list(ALL_PK266_SCAN_IDS),
                                     args.aperture_mm, args.y_margin_mm, args.root)
        for scan_id, full in result["per_scan_full"].items():
            if "independent_time_zero" in full:
                _print_summary(full)
            else:
                print(f"BAM {args.specimen_id} / {scan_id}: AUDIT FAILED "
                     f"({full['classification_reasons'][0]})")
            print()
        print(f"BEST CLASSIFICATION ACROSS SCANS: {result['best_classification']} "
             f"({result['best_scan_id']})")
        print("t0 consistency within frequency:")
        for freq, entries in result["t0_consistency_within_frequency"].items():
            print(f"  {freq}: " + ", ".join(
                f"{e['scan_id'].split('_')[-1]}={e['correction_ns']}" for e in entries))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
