"""
Can TU1208 constrain a time-zero and a propagation velocity?

THE MODEL UNDER TEST, stated once and never quietly reinterpreted:

    t_measured = t0 + 2 * d / v

`t0` is a system delay -- the instrument's own time origin plus whatever air
path precedes the ground. It is NOT the ground-surface time and nothing here
assumes it is. `d` is an independently surveyed physical depth. `v` is the
propagation velocity of the host medium.

THE EXPERIMENT HAS TO CLEAR TWO GATES, IN ORDER, AND IT FAILS AT THE FIRST.

    GATE 1  ASSOCIATION. For a surveyed target to contribute an observation,
            the measured reflector belonging to THAT target must be locatable
            from published acquisition geometry. Choosing the reflector that
            makes the fit look right is the circularity this whole stage exists
            to avoid, so the association is computed from published fields only
            and a target that cannot be placed is UNRESOLVED.

    GATE 2  IDENTIFIABILITY. Even with perfect arrival times, the published
            depths must give enough leverage to tell a change in t0 from a
            change in v. That is a property of the depth set alone and needs no
            measurement, so it is computed regardless of gate 1 -- it says what
            the dataset could achieve at best.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It picks no arrival time. It fits no
velocity. It writes no declaration. It touches no 4TU state. The fitting
routine below is exercised only on the leverage analysis, where the "data" are
the published depths themselves and the quantity computed is a variance ratio,
not a velocity.

Reproduce with:

    python -m scripts.tu1208_depth_calibration --out artifacts/tu1208/depth_calibration.json
"""
from __future__ import annotations

import argparse
import json
import math
import struct
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from benchmark import tu1208_truth as truth

REPO_ROOT = Path(__file__).resolve().parent.parent

#: What locating a surveyed target inside a radargram requires. Both must be
#: known in the SAME frame for a target to become an observation.
ASSOCIATION_REQUIREMENTS = (
    "the target's transverse offset from a named site reference",
    "the profile's along-line origin in that same reference",
)

BLOCKED = "BLOCKED"
INCONCLUSIVE = "INCONCLUSIVE"
RESOLVED = "RESOLVED"


# ---------------------------------------------------------------------------
# gate 1 -- association
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssociationAttempt:
    """
    One surveyed target, and whether a measured reflector can be tied to it.

    `basis` records what the decision rested on. `missing` is non-empty exactly
    when `status` is UNRESOLVED, so a gap can never be silently empty.
    """
    target_id: str
    region_id: str
    host_material: str
    surveyed_depth_m: float
    identity: str
    status: str
    basis: str
    missing: tuple[str, ...]
    candidate_files: tuple[str, ...]


def attempt_associations() -> list[AssociationAttempt]:
    """
    Try to place every surveyed target in a measured radargram.

    THE ONLY INPUTS ARE PUBLISHED FIELDS. `transverse_offset_m` is None for
    every TU1208 target because the paper prints scale-bar segment lengths and
    never ties the bar's origin to the site axis, and no source states where a
    profile's first trace sits. Two unknowns, no equations.
    """
    out: list[AssociationAttempt] = []
    for target in truth.pipe_targets():
        files = tuple(sorted(
            p.published_file_name for p in truth.profiles(target.region_id)))
        missing: list[str] = []
        if target.transverse_offset_m is None:
            missing.append(ASSOCIATION_REQUIREMENTS[0])
        # Published for no profile in the corpus; see the Stage 23 gap list.
        missing.append(ASSOCIATION_REQUIREMENTS[1])

        out.append(AssociationAttempt(
            target_id=target.target_id,
            region_id=target.region_id,
            host_material=target.host_material,
            surveyed_depth_m=target.depth_m,
            identity=target.identity,
            status="UNRESOLVED" if missing else "RESOLVED",
            basis=("published acquisition geometry only; no reflector was inspected, "
                   "because inspecting one before the association is fixed is how a "
                   "target depth ends up choosing its own evidence"),
            missing=tuple(missing),
            candidate_files=files,
        ))
    return out


# ---------------------------------------------------------------------------
# what the instruments themselves attest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileTimeEvidence:
    """The header's own account of the time axis and the along-track axis."""
    published_file_name: str
    region_id: str
    vendor_format: str
    n_samples: Optional[int]
    range_ns: Optional[float]
    header_time_zero_ns: Optional[float]
    header_time_zero_usable: Optional[bool]
    header_time_zero_reason: str
    scans_per_m: Optional[float]
    along_track_available: Optional[bool]


def _gssi_header(path: Path) -> dict:
    raw = path.read_bytes()[:1024]
    u16 = lambda o: struct.unpack_from("<H", raw, o)[0]      # noqa: E731
    f32 = lambda o: struct.unpack_from("<f", raw, o)[0]      # noqa: E731
    return {"n_samples": u16(4), "bits": u16(6), "sps": f32(10), "spm": f32(14),
            "position_ns": f32(22), "range_ns": f32(26), "epsr": f32(54)}


def _mala_header(path: Path) -> dict:
    """MALÅ writes a plain-text .rad sidecar beside the .rd3."""
    rad = path.with_suffix(".rad")
    if not rad.exists():
        rad = path.with_suffix(".RAD")
    fields: dict[str, str] = {}
    if rad.exists():
        for line in rad.read_text(errors="replace").splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip().upper()] = value.strip()
    def num(key):
        try:
            return float(fields[key])
        except (KeyError, ValueError):
            return None
    return {"n_samples": num("SAMPLES"), "range_ns": num("TIMEWINDOW"),
            "spm": (1.0 / num("DISTANCE INTERVAL")
                    if num("DISTANCE INTERVAL") else None)}


def time_evidence(archive_root: Path) -> list[FileTimeEvidence]:
    """
    Read every file's header for a time-zero and an along-track scale.

    THE HEADER TIME-ZERO IS THE OBVIOUS SHORTCUT AND IT DOES NOT WORK. GSSI's
    `rhf_position` holds ~99 ns on the 1999 profiles, against recording windows
    of 60-85 ns. A delay larger than the window is not a delay, and the
    converter already refuses to apply it.
    """
    resolved = truth.resolve_files(archive_root)
    by_name = {p.published_file_name: p for p in truth.profiles()}

    out: list[FileTimeEvidence] = []
    for name, path in sorted(resolved.items()):
        profile = by_name[name]
        suffix = path.suffix.lower()
        if suffix == ".dzt":
            head = _gssi_header(path)
            t0, window = head["position_ns"], head["range_ns"]
            usable = bool(window) and 0.0 < t0 < window
            reason = ("plausible: a positive delay inside the recording window"
                      if usable else
                      f"unusable: rhf_position={t0:g} ns against a {window:g} ns window"
                      if t0 and window and t0 >= window else
                      "unset: rhf_position is 0.0, which the vendor uses for 'not set'")
            spm = head["spm"] or None
            out.append(FileTimeEvidence(
                name, profile.region_id, "GSSI .dzt", head["n_samples"], window,
                t0, usable, reason, spm, bool(spm)))
        elif suffix == ".rd3":
            head = _mala_header(path)
            out.append(FileTimeEvidence(
                name, profile.region_id, "MALA .rd3",
                int(head["n_samples"]) if head["n_samples"] else None,
                head["range_ns"], None, None,
                "the MALA .rad sidecar carries no time-zero field at all",
                head["spm"], bool(head["spm"])))
        else:
            out.append(FileTimeEvidence(
                name, profile.region_id, "IDS .dt", None, profile.range_ns,
                None, None,
                "IDS .dt carries no documented time-zero field; the paper states the "
                "transmitter-receiver separation is confidential",
                profile.scans_per_m, bool(profile.scans_per_m)))
    return out


# ---------------------------------------------------------------------------
# gate 2 -- identifiability, from the published depths alone
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Leverage:
    """
    How well a set of known depths could separate t0 from velocity.

    NO MEASUREMENT ENTERS THIS. For the linear model t = t0 + (2/v) d, the
    least-squares parameter covariance depends only on the depths. The number
    that matters is `t0_slope_correlation`: at -0.95 a change in t0 is almost
    exactly compensable by a change in slope, so the two are not separately
    determined however clean the picks are.
    """
    group: str
    n_depths: int
    depths_m: tuple[float, ...]
    depth_span_m: float
    #: corr(intercept, slope) for X = [1, 2d]. -1 means perfectly confounded.
    t0_slope_correlation: float
    #: Condition number of the design matrix. Large means ill-posed.
    condition_number: float
    #: Standard errors per 1 ns of independent arrival-time noise.
    t0_se_ns_per_ns_noise: float
    velocity_se_frac_per_ns_noise: Optional[float]
    identifiable: bool
    verdict: str


#: A nominal velocity used ONLY to express a slope uncertainty as a fraction.
#: It is not fitted, not declared, and not attributed to any medium: it converts
#: a standard error on the slope into a relative standard error on v, which is
#: scale-free. Any other value would give the same fraction.
_REFERENCE_V_FOR_SCALING = 0.1


def leverage(group: str, depths: list[float]) -> Leverage:
    """
    Parameter covariance for t = t0 + (2/v) d, from the depths alone.

    Uses the closed-form OLS covariance rather than a fit, because there is
    nothing to fit -- the question is what the design would permit.
    """
    d = [abs(x) for x in depths]
    n = len(d)
    x = [2.0 * v for v in d]
    if n < 2:
        return Leverage(group, n, tuple(depths), 0.0, float("nan"), float("inf"),
                        float("inf"), None, False,
                        "fewer than two depths cannot determine two parameters")

    mean_x = sum(x) / n
    mean_x2 = sum(v * v for v in x) / n
    sxx = sum((v - mean_x) ** 2 for v in x)
    if sxx == 0:
        return Leverage(group, n, tuple(depths), 0.0, float("nan"), float("inf"),
                        float("inf"), None, False,
                        "every depth is identical, so the slope is undetermined")

    # corr(b0, b1) = -mean(x) / sqrt(mean(x^2))
    corr = -mean_x / math.sqrt(mean_x2)
    # Standard errors for unit noise.
    se_slope = math.sqrt(1.0 / sxx)
    se_t0 = math.sqrt(mean_x2 / sxx)
    # slope = 2/v, so a relative error on v equals the relative error on slope.
    slope_ref = 2.0 / _REFERENCE_V_FOR_SCALING
    se_v_frac = se_slope / slope_ref

    singular_ratio = _condition_number(x)
    identifiable = abs(corr) < 0.9
    verdict = ("t0 and velocity are separable on these depths"
               if identifiable else
               f"t0 and velocity are {abs(corr) * 100:.1f}% confounded: a shift in t0 is "
               f"almost exactly compensated by a change in velocity")
    return Leverage(group, n, tuple(depths), max(d) - min(d), corr, singular_ratio,
                    se_t0, se_v_frac, identifiable, verdict)


def _condition_number(x: list[float]) -> float:
    """Condition number of [1, x] via the 2x2 Gram matrix eigenvalues."""
    n = len(x)
    a, b, c = float(n), sum(x), sum(v * v for v in x)
    trace, det = a + c, a * c - b * b
    disc = max(trace * trace - 4.0 * det, 0.0)
    lo = (trace - math.sqrt(disc)) / 2.0
    hi = (trace + math.sqrt(disc)) / 2.0
    return float("inf") if lo <= 0 else math.sqrt(hi / lo)


def leverage_analysis() -> list[Leverage]:
    """Every published depth grouping the source actually supports."""
    out = [leverage(region_id, truth.pipe_layer_depths(region_id))
           for region_id in ("silt", "limestone", "gneiss_14_20", "gneiss_0_20")]

    pooled: list[float] = []
    for region_id in ("silt", "limestone", "gneiss_14_20", "gneiss_0_20"):
        pooled.extend(truth.pipe_layer_depths(region_id))
    out.append(leverage("all-pipe-layers-pooled", pooled))

    # The widest depth range the corpus offers -- and the one grouping where a
    # horizontal association would not be needed, because the reflectors are
    # planar. The depths are DERIVED from published thicknesses.
    out.append(leverage("multilayer-interfaces-derived",
                        [i.depth_m for i in truth.interface_depths()]))
    return out


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------

def verdict(attempts: list[AssociationAttempt], levers: list[Leverage]) -> dict:
    resolved = [a for a in attempts if a.status == "RESOLVED"]
    unresolved = [a for a in attempts if a.status == "UNRESOLVED"]
    separable = [lv for lv in levers if lv.identifiable]

    return {
        "status": BLOCKED if not resolved else INCONCLUSIVE,
        "gate_1_association": {
            "status": BLOCKED if not resolved else RESOLVED,
            "n_targets": len(attempts),
            "n_resolved": len(resolved),
            "n_unresolved": len(unresolved),
            "missing_quantities": sorted({m for a in unresolved for m in a.missing}),
            "consequence": (
                "No surveyed target can be tied to a measured reflector from published "
                "geometry, so there are zero observations of t_measured. Nothing is "
                "fitted, because fitting would require choosing reflectors, and the only "
                "available basis for choosing would be the target depths themselves."),
        },
        "gate_2_identifiability": {
            "status": RESOLVED if separable else BLOCKED,
            "n_groups": len(levers),
            "n_separable": len(separable),
            "separable_groups": [lv.group for lv in separable],
            "consequence": (
                "Reported for every grouping regardless of gate 1, because it is a "
                "property of the published depths and says what the dataset could do "
                "at best."),
        },
        "fitted_t0_ns": None,
        "fitted_velocity_m_per_ns": None,
        "held_out_depth_error_m": None,
        "why_no_numbers": (
            "Zero usable observations. A fitted parameter here would be a number with "
            "no measurement behind it."),
    }


def build(archive_root: Path) -> dict:
    attempts = attempt_associations()
    levers = leverage_analysis()
    evidence = time_evidence(archive_root)

    usable_header_t0 = [e for e in evidence if e.header_time_zero_usable]
    with_along_track = [e for e in evidence if e.along_track_available]

    return {
        "experiment": "tu1208-time-zero-and-velocity",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "truth_version": truth.truth_version(),
        "model": "t_measured = t0 + 2 * d / v",
        "model_note": ("t0 is a system delay, not the ground-surface time. Nothing here "
                       "assumes the ground surface is time zero."),
        "verdict": verdict(attempts, levers),
        "association": [asdict(a) for a in attempts],
        "leverage": [asdict(lv) for lv in levers],
        "instrument_time_evidence": {
            "n_files": len(evidence),
            "n_with_usable_header_time_zero": len(usable_header_t0),
            "n_with_along_track_scale": len(with_along_track),
            "files": [asdict(e) for e in evidence],
        },
        "declarations_written": [],
        "fourtu_state_touched": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path,
                        default=REPO_ROOT / truth.ARCHIVE_ROOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    result = build(args.archive_root)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2))

    v = result["verdict"]
    print(f"VERDICT: {v['status']}")
    print(f"  association    : {v['gate_1_association']['n_resolved']}"
          f"/{v['gate_1_association']['n_targets']} targets resolved")
    for quantity in v["gate_1_association"]["missing_quantities"]:
        print(f"      missing: {quantity}")
    print(f"  identifiability: {v['gate_2_identifiability']['n_separable']}"
          f"/{v['gate_2_identifiability']['n_groups']} groupings separable")
    for lv in result["leverage"]:
        print(f"      {lv['group']:34s} n={lv['n_depths']} "
              f"span={lv['depth_span_m']:.2f} m  corr(t0,slope)={lv['t0_slope_correlation']:+.3f}"
              f"  {'separable' if lv['identifiable'] else 'CONFOUNDED'}")
    ev = result["instrument_time_evidence"]
    print(f"  headers        : {ev['n_with_usable_header_time_zero']}/{ev['n_files']} "
          f"carry a usable time-zero; {ev['n_with_along_track_scale']}/{ev['n_files']} "
          f"carry an along-track scale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
