"""
Does anything Subterra holds anchor the time axis near the acquisition surface?

WHY THIS STAGE EXISTS. Stage 24 found t0 and v 95-97% confounded on TU1208 and
recommended "a reflector at 0.1-0.2 m". This module tests that recommendation
before anybody acts on it, and the recommendation turns out to be WRONG in a way
that matters: the confounding is scale-invariant. Depth magnitude is irrelevant.

    corr(t0, slope) = -1 / sqrt(1 + CV^2)

where CV is the coefficient of variation of the depth set. Multiply every depth
by ten and the number does not move. BAM's ducts sit at 94-275 mm, an order of
magnitude shallower than TU1208's targets, and are just as confounded (-0.939 vs
-0.949). A shallow reflector does not fix this. RELATIVE SPREAD fixes it, and
nothing fixes it completely: for strictly positive depths mean(x) > 0, so the
correlation is strictly negative and a two-level design cannot beat -0.707
however shallow its shallow point is.

WHAT ACTUALLY BREAKS THE DEGENERACY is an observation at d = 0 -- a directly
measured system delay -- because that constrains t0 without going through v at
all. Everything else mitigates.

WHAT THIS MODULE DOES NOT DO. It picks no arrival time, fits no velocity, writes
no declaration and reads no 4TU state. Candidate acquisition designs are
expressed as DEPTH SETS and fed to the same closed-form covariance used on the
real ones; that is parameter arithmetic, not a synthetic radargram and not a
synthetic target.

Reproduce with:

    python -m scripts.stage25_shallow_anchor_audit --out artifacts/tu1208/shallow_anchor_audit.json
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

#: Electromagnetic propagation in air. A physical constant used only to convert
#: a header delay into the antenna height it would imply -- never as a fitted or
#: assumed ground velocity.
C_AIR_M_PER_NS = 0.2998


# ---------------------------------------------------------------------------
# the evidence inventory
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnchorCandidate:
    """
    One thing that might anchor the time axis, and what it actually does.

    `identifiable_without_depth` is the question that separates evidence from
    circularity: could a reviewer point at this feature without already knowing
    where the target is? A reflector chosen because it lands at the right depth
    fails it, and so does a header field nobody can interpret.
    """
    dataset: str
    source: str
    feature: str
    measured_time: Optional[str]
    physical_reference: Optional[str]
    truth_source: str
    identifiable_without_depth: Optional[bool]
    constrains_t0: bool
    constrains_velocity: bool
    verdict: str
    reason: str


INVENTORY: tuple[AnchorCandidate, ...] = (
    AnchorCandidate(
        dataset="4tu-nl-utility",
        source="SEG-Y trace header bytes 109-110, all 751 files",
        feature="DelayRecordingTime",
        measured_time="raw 0-13307; 0.00-13.31 ns read in the vendor's picosecond convention",
        physical_reference=None,
        truth_source="measured from the raw bytes by this module",
        identifiable_without_depth=True,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="RULED OUT",
        reason=(
            "SEG-Y rev 1 defines it as the time between source initiation and the start "
            "of sample recording -- a RECORDING-START offset, not a propagation path. "
            "Two independent facts rule it out as a ground-surface anchor. First, if it "
            "were the air gap it would imply antenna heights of 0.00-2.00 m, against the "
            "author's 'a few centimetres' (which is ~0.33 ns two-way). Second, 9 of 751 "
            "files carry exactly 0, which for an air-launched antenna would mean no air "
            "path and no internal delay at all. It is a recording-window placement "
            "setting. It is also unit-ambiguous: the scalar at bytes 215-216 is -1000 on "
            "every file, which per the standard means milliseconds and would make these "
            "delays physically absurd, so the nanosecond reading rests on the same "
            "vendor pre-scaling inference the sample interval already needs."),
    ),
    AnchorCandidate(
        dataset="4tu-nl-utility",
        source="Dr. ter Huurne, direct correspondence (stage 19 evidence)",
        feature="author statement on time zero and air gap",
        measured_time=None,
        physical_reference=None,
        truth_source="author_stated",
        identifiable_without_depth=True,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="CONSTRAINS INTERPRETATION ONLY",
        reason=(
            "The author establishes that no time-zero correction and no air-gap removal "
            "were applied, so the ground surface does not correspond to depth zero and an "
            "air-path contribution remains. That makes the offset's EXISTENCE certain and "
            "supplies no magnitude. It rules interpretations out; it anchors nothing."),
    ),
    AnchorCandidate(
        dataset="4tu-nl-utility",
        source="Metadata.csv, 125 activities",
        feature="ground relative permittivity 8.16-19.46",
        measured_time=None,
        physical_reference=None,
        truth_source="declared_by_source, no method stated",
        identifiable_without_depth=True,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="NOT A MEASUREMENT",
        reason=(
            "A provider-declared site estimate with no stated method, instrument or "
            "uncertainty. It could seed a velocity but constrains t0 not at all, and "
            "converting it here would produce a number that looks measured and is not."),
    ),
    AnchorCandidate(
        dataset="tu1208-ifsttar",
        source="paper section 3.3.1",
        feature="10-cm limestone surface layer and asphalt wearing course",
        measured_time=None,
        physical_reference="a real shallow interface, present across the whole site",
        truth_source="published prose",
        identifiable_without_depth=False,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="RULED OUT",
        reason=(
            "The only genuinely shallow documented interface in the corpus, and it fails "
            "on both counts. Its depth is not known: it sits below an asphalt wearing "
            "course whose thickness the paper never gives, so d is unavailable. And at "
            "the site's frequencies a 10 cm layer is below resolution, so the feature "
            "could not be identified independently even if d were known."),
    ),
    AnchorCandidate(
        dataset="tu1208-ifsttar",
        source="paper figures 6, 9, 11, 13",
        feature="36 surveyed pipe targets, shallowest 0.80 m",
        measured_time=None,
        physical_reference="theodolite-surveyed depth",
        truth_source="transcribed_from_publication",
        identifiable_without_depth=False,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="RULED OUT",
        reason=(
            "Stage 24: no published transverse offset and no along-line origin, so the "
            "reflector cannot be located without using the depth that is supposed to be "
            "the answer. Identifiability is separately confounded at -0.949 to -0.967."),
    ),
    AnchorCandidate(
        dataset="tu1208-ifsttar / hillside-lancaster",
        source="MALA .rad header, 15 and 313 files",
        feature="SIGNAL POSITION, RAW SIGNAL POSITION, SYSTEM CALIBRATION",
        measured_time="TU1208 -0.033 to -0.381; hillside 27.6 to 1053.5",
        physical_reference=None,
        truth_source="vendor header field",
        identifiable_without_depth=True,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="UNRESOLVED -- NOT USABLE",
        reason=(
            "The most promising lead in the corpus, and it does not survive checking. "
            "MALA's own published format specification (Guideline Geo, 'Appendix 1 - "
            "Detailed description of RD3, RD7 and RAD formats') enumerates the .rad "
            "parameters and DOES NOT LIST any of these three; the words 'time zero' do "
            "not appear in it at all. The values are also mutually incoherent: hillside "
            "carries SIGNAL POSITION 1053.5 against a 66.3 ns window, which cannot be a "
            "time in ns, while TU1208 carries -0.033 to -0.381. Undocumented by the "
            "vendor and uninterpretable from the files. A vendor answer could move this "
            "to usable, which is why it is UNRESOLVED rather than RULED OUT."),
    ),
    AnchorCandidate(
        dataset="bam-concrete-gpr",
        source="GSSI DZT header, Pk266/Pk050",
        feature="rhf_position",
        measured_time="0.0 ns",
        physical_reference=None,
        truth_source="vendor header field",
        identifiable_without_depth=True,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="RULED OUT",
        reason=(
            "0.0 is the vendor's 'not set', not a measured zero. Reading it as a physical "
            "surface would assert that the first sample is the specimen face."),
    ),
    AnchorCandidate(
        dataset="bam-concrete-gpr",
        source="Dataverse description + geometry article Table 4",
        feature="4 tendon ducts, centre depths 94.4-274.5 mm, published X",
        measured_time=None,
        physical_reference="fabricator-attested depth below the measuring surface",
        truth_source="transcribed_from_publication",
        identifiable_without_depth=True,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="ASSOCIATION AVAILABLE, IDENTIFIABILITY STILL FAILS",
        reason=(
            "The one holding where the association is genuinely published: target X is "
            "given numerically and the scanner grid is expressed in the same millimetre "
            "specimen frame, so which traces sit over which duct needs no inference. That "
            "is a real architectural asset. It still does not anchor t0: the four depths "
            "give corr(t0, slope) = -0.939, no better than TU1208's 1.8 m targets, "
            "because the confounding depends on relative spread and not on depth."),
    ),
    AnchorCandidate(
        dataset="bam-concrete-gpr",
        source="Dataverse description",
        feature="step back walls, 210.3-569.9 mm",
        measured_time=None,
        physical_reference="fabricator-attested step thickness",
        truth_source="transcribed_from_publication",
        identifiable_without_depth=False,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="RULED OUT",
        reason=(
            "Planar reflectors needing no lateral association, but the X range of each "
            "step is not published and the thickness list carries no stated ordering "
            "along X, so assigning a step to a trace range would be an inference. "
            "corr(t0, slope) = -0.946 in any case."),
    ),
    AnchorCandidate(
        dataset="hillside-lancaster",
        source="description PDF, 24 surveyed plot corners",
        feature="surveyed corner elevations, 29.54-32.09 m aOD",
        measured_time=None,
        physical_reference="Ordnance Datum Newlyn",
        truth_source="surveyed",
        identifiable_without_depth=True,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="WRONG QUANTITY",
        reason=(
            "A surveyed SURFACE elevation, not a subsurface reflector. It constrains "
            "where the ground is in space and says nothing about where it is in time."),
    ),
    AnchorCandidate(
        dataset="all holdings",
        source="filesystem search",
        feature="metal-plate, CMP, calibration or reference-trace file",
        measured_time=None,
        physical_reference=None,
        truth_source="absent",
        identifiable_without_depth=None,
        constrains_t0=False,
        constrains_velocity=False,
        verdict="ABSENT",
        reason=(
            "No holding contains a CMP gather, a metal-plate reflection at a measured "
            "standoff, a reference trace, or any file named or documented as a timing "
            "calibration."),
    ),
)


# ---------------------------------------------------------------------------
# identifiability
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DesignLeverage:
    """
    What a set of known depths can do for t0 and v, before any measurement.

    `corr` is exact and closed-form. `t0_se_ns_per_ns_noise` says how a 1 ns
    arrival-time error propagates into t0, which is the number a practitioner
    actually feels.
    """
    name: str
    kind: str
    depths_m: tuple[float, ...]
    n: int
    coefficient_of_variation: float
    corr_t0_slope: float
    t0_se_ns_per_ns_noise: float
    has_direct_t0_observation: bool
    note: str


def leverage(name: str, depths: list[float], kind: str, note: str = "") -> DesignLeverage:
    """
    Closed-form OLS covariance for t = t0 + (2/v) d.

    corr(intercept, slope) = -mean(x) / sqrt(mean(x^2)) with x = 2d, which is
    identically -1/sqrt(1 + CV^2). Both are computed and the test file checks
    they agree, because the CV form is what makes the scale-invariance obvious.
    """
    d = [abs(v) for v in depths]
    n = len(d)
    x = [2.0 * v for v in d]
    mean_x = sum(x) / n
    mean_x2 = sum(v * v for v in x) / n
    var_x = sum((v - mean_x) ** 2 for v in x) / n
    sxx = sum((v - mean_x) ** 2 for v in x)

    corr = -mean_x / math.sqrt(mean_x2) if mean_x2 > 0 else 0.0
    cv = math.sqrt(var_x) / mean_x if mean_x > 0 else float("inf")
    se_t0 = math.sqrt(mean_x2 / sxx) if sxx > 0 else float("inf")

    return DesignLeverage(
        name=name, kind=kind, depths_m=tuple(depths), n=n,
        coefficient_of_variation=cv, corr_t0_slope=corr,
        t0_se_ns_per_ns_noise=se_t0,
        has_direct_t0_observation=any(v == 0.0 for v in d),
        note=note)


#: Depth sets that exist, measured or published. Nothing here is invented.
REAL_DEPTH_SETS = {
    "TU1208 silt": ([0.80, 1.20, 1.83], "published surveyed"),
    "TU1208 limestone": ([1.20, 1.70, 2.40], "published surveyed"),
    "TU1208 gneiss 14/20": ([0.90, 1.50, 2.10], "published surveyed"),
    "TU1208 gneiss 0/20": ([1.15, 1.56, 2.20], "published surveyed"),
    "BAM Pk266 ducts": ([0.0944, 0.1514, 0.2146, 0.2745], "published attested"),
    "BAM Pk266 step walls": ([0.2103, 0.3298, 0.4482, 0.5699], "published attested"),
}

#: Candidate acquisition designs, as DEPTH SETS. Parameter arithmetic only --
#: no signal, no geometry, no site. Named to match the stage's options A-E.
CANDIDATE_DESIGNS = {
    "A: shallow + deep known reflector": (
        [0.15, 2.00], "two levels, widely separated"),
    "B: multiple shallow reflectors": (
        [0.10, 0.15, 0.20], "the design stage 24's wording would have produced"),
    "C: measured system delay + one deep target": (
        [0.0, 2.00], "a direct t0 observation plus one depth"),
    "C+: repeated system delay + two targets": (
        [0.0, 0.0, 0.0, 1.00, 2.00], "three repeats of the direct measurement"),
    "E: shallow surveyed target + three deep": (
        [0.15, 1.00, 1.50, 2.00], "one shallow anchor against a spread"),
}


def identifiability() -> dict:
    real = [asdict(leverage(name, depths, kind))
            for name, (depths, kind) in REAL_DEPTH_SETS.items()]
    designs = [asdict(leverage(name, depths, "candidate design", note))
               for name, (depths, note) in CANDIDATE_DESIGNS.items()]

    base = leverage("scale check x1", [0.0944, 0.1514, 0.2146, 0.2745], "check")
    scaled = leverage("scale check x10", [0.944, 1.514, 2.146, 2.745], "check")

    return {
        "law": "corr(t0, slope) = -1 / sqrt(1 + CV^2), CV of the depth set",
        "scale_invariance": {
            "statement": "multiplying every depth by a constant leaves the correlation unchanged",
            "corr_x1": base.corr_t0_slope,
            "corr_x10": scaled.corr_t0_slope,
            "identical": abs(base.corr_t0_slope - scaled.corr_t0_slope) < 1e-12,
        },
        "structural_floor": {
            "statement": ("for strictly positive depths mean(x) > 0, so the correlation is "
                          "strictly negative: t0 and velocity are never independent under "
                          "this model. A two-level design cannot beat -1/sqrt(2)."),
            "two_level_floor": -1.0 / math.sqrt(2.0),
        },
        "real_depth_sets": real,
        "candidate_designs": designs,
    }


def build() -> dict:
    inventory = [asdict(c) for c in INVENTORY]
    return {
        "stage": "25-shallow-anchor-and-time-zero-audit",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "question": ("does any existing holding contain an independently identifiable "
                     "shallow reflector or system-delay measurement that anchors t0?"),
        "answer": "no",
        "n_candidates": len(inventory),
        "n_constraining_t0": sum(1 for c in INVENTORY if c.constrains_t0),
        "n_constraining_velocity": sum(1 for c in INVENTORY if c.constrains_velocity),
        "inventory": inventory,
        "identifiability": identifiability(),
        "declarations_written": [],
        "datasets_modified": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    result = build()
    if args.out:
        from pathlib import Path
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2))

    print(f"candidates examined      : {result['n_candidates']}")
    print(f"candidates constraining t0: {result['n_constraining_t0']}")
    print(f"candidates constraining v : {result['n_constraining_velocity']}")
    print()
    for c in result["inventory"]:
        print(f"  {c['verdict']:44s} {c['dataset']:28s} {c['feature'][:44]}")
    ident = result["identifiability"]
    print()
    print(f"  {ident['law']}")
    print(f"  scale invariant: {ident['scale_invariance']['identical']}"
          f"  (x1 {ident['scale_invariance']['corr_x1']:+.6f}, "
          f"x10 {ident['scale_invariance']['corr_x10']:+.6f})")
    print()
    print(f"  {'depth set':42s} {'n':>2s} {'CV':>6s} {'corr':>8s} {'se(t0)/ns':>10s}")
    for row in ident["real_depth_sets"] + ident["candidate_designs"]:
        print(f"  {row['name']:42s} {row['n']:2d} {row['coefficient_of_variation']:6.3f} "
              f"{row['corr_t0_slope']:+8.3f} {row['t0_se_ns_per_ns_noise']:10.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
