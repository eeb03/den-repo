"""
Can TestUM's real crosshole GPR data support a defensible, independently
constrained propagation velocity -- from real picked arrivals, against real,
independently surveyed transmitter-receiver separations?

THIS IS A RESEARCH AUDIT, NOT A PRODUCT FEATURE. It reads the real archive
already on disk (`datasets/raw/pangaea/971978/`), decodes the DZT files with
an independent, dependency-free reader (never Subterra's own GSSI converter
-- see `docs/testum-air-warr-t0-experiment.md` for why: using the platform's
own reader to produce evidence ABOUT the platform would make the platform
its own referee), touches no `SubterraRecord`, no converter, no provenance
schema, no live dataset, and writes only a JSON artifact under
`artifacts/testum/`. Reproduce with:

    python -m scripts.testum_crosshole_velocity_audit --out artifacts/testum/testum_velocity_audit.json

WHAT THIS BUILDS ON, AND DOES NOT REPEAT.

`docs/testum-evidence-audit.md` established, from surveyed geometry alone
(no traces): 18 crosshole borehole pairs, real DGPS-surveyed separations
1.12-6.10 m, and a geometry-only t0/velocity design correlation of -0.881 --
better-conditioned than BAM (-0.9387) or TU1208 (-0.949), but still high if
t0 had to be fit jointly.

`docs/testum-air-warr-t0-experiment.md` then attempted the INDEPENDENT route
that removes t0 from the fit entirely -- an air-path calibration at surveyed
antenna separations, physically decoupled from the ground. Result:
INCONCLUSIVE. 2 of 26 files passed a hard physics falsifier (the fitted
slope must equal 1/c_air), and the two survivors disagree by 1.12 ns. No
TestUM t0 was obtained.

THIS SCRIPT is the piece neither prior stage ran: actually picking real
crosshole first arrivals across MULTIPLE real surveyed separations, and
testing -- empirically, not just geometrically -- whether a joint t0/v fit
on TestUM's own crosshole data is identifiable. It downloads (see
`docs/testum-raw-data-validation.md`'s established, no-account-needed
access method) one representative file per surveyed borehole pair.

A REAL, NON-OBVIOUS PHYSICAL SUBTLETY FOUND BEFORE WRITING THIS SCRIPT, AND
WHY THE PICKER IS NOT "FIRST THRESHOLD CROSSING". A naive first-sustained-
deviation picker on real trace 20230221_GEWS_C07_C10.DZT (separation
2.795 m) finds an early, weak (confidence ~5-6x noise) event at ~19-29 ns,
implying v~0.098 m/ns (eps_r~9.3) -- a typical DRY-SOIL number, physically
implausible for a site the authors describe as a saturated quaternary
glacial aquifer. Scanning the FULL window for the GLOBAL peak deviation
instead finds a vastly stronger (confidence 20-140x noise), depth-to-depth
CONSISTENT event at ~80-88 ns, implying v~0.033 m/ns (eps_r~83) -- within
a few percent of pure water's relative permittivity (~80), exactly what a
fully water-saturated aquifer predicts. The early event is very likely a
borehole-guided (casing/filter-pack) or coupling artifact, not the
cross-formation arrival -- a known real phenomenon in crosshole geophysics.
This script therefore picks the GLOBAL PEAK deviation from the noise floor,
not the first crossing, and reports both candidates per trace so this
reasoning is auditable rather than asserted.

WHY Y (DEPTH) IS NOT AVERAGED AWAY. Unlike BAM's ducts, TestUM's crosshole
geometry samples ~67 different DEPTHS at the SAME horizontal separation per
borehole pair. Real depth-to-depth variation in the picked arrival time is
kept and reported (not smoothed into one number) -- it is either genuine
depth-dependent velocity structure (plausible: this is an aquifer under
active freeze-thaw manipulation) or a real limitation on how well "one
effective velocity per pair" describes the ground. The per-pair MEDIAN
across usable depths is used for the separation-vs-time regression, exactly
because it is a summary of repeated measurements of the same L, not a
disguised average across different physical quantities.

WHAT THIS DOES NOT DO. It does not adopt TestUM's air-WARR t0 (which was
never obtained) as a known constant -- the joint fit below estimates t0 FROM
the crosshole data itself, honestly re-testing whether the geometry-only
-0.881 correlation survives contact with real picked data. It does not
touch any live dataset, does not change any converter, and does not promote
anything to `DERIVED` in the Subterra provenance model.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import statistics
import struct
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "datasets/raw/pangaea/971978/raw"
GPS_ZIP = REPO_ROOT / "datasets/raw/pangaea/971978/GEWS_Deviation_and_GPS.zip"
GPS_MEMBER = "GPS_Wittstock_GEWS_2Z.xlsx"
METADATA = REPO_ROOT / "datasets/raw/pangaea/971978/PANGAEA_971978_metadata.txt"

#: Speed of light in vacuum, m/ns. Matches every other velocity script in
#: this repository (scripts/characterise_4tu.py, bam_hyperbola_velocity_audit.py).
C_M_PER_NS = 0.299792458

#: One representative real file per surveyed borehole pair (the first-dated,
#: unsuffixed file for each pair in the published data matrix -- never the
#: "cleanest-looking" one, to avoid selecting on the outcome).
PAIR_FILES = {
    ("C04", "C05"): "20231011_GEWS_C04_C05.DZT",
    ("C04", "C12"): "20230221_GEWS_C04_C12.DZT",
    ("C05", "C12"): "20230221_GEWS_C05_C12.DZT",
    ("C07", "C10"): "20230221_GEWS_C07_C10.DZT",
    ("C12", "C09"): "20230221_GEWS_C12_C09.DZT",
    ("D04", "C08"): "20230221_GEWS_D04_C08.DZT",
    ("D04", "D05"): "20230824_GEWS_D04_D05.DZT",
    ("D04", "U04"): "20230615_GEWS_D04_U04.DZT",
    ("D04", "U06"): "20230615_GEWS_D04_U06.DZT",
    ("D05", "C10"): "20230221_GEWS_D05_C10.DZT",
    ("D05", "C12"): "20230221_GEWS_D05_C12.DZT",
    ("D05", "D04"): "20231004_GEWS_D05_D04.DZT",
    ("D05", "U05"): "20230615_GEWS_D05_U05.DZT",
    ("U04", "C09"): "20230221_GEWS_U04_C09.DZT",
    ("U05", "C10"): "20230221_GEWS_U05_C10.DZT",
    ("U06", "C08"): "20230221_GEWS_U06_C08.DZT",
    ("U06", "U05"): "20230824_GEWS_U06_U05.DZT",
}

#: Depth stations before this sample index cannot be a genuine crosshole
#: arrival at ANY physically plausible GPR velocity (even air, 0.3 m/ns,
#: over the shortest surveyed separation ~1.1 m, needs >=3.7 ns = ~25
#: samples at 0.1465 ns/sample) -- used only to exclude the marker/DC region,
#: not tuned per file.
MIN_ARRIVAL_SAMPLE = 20
#: Depth stations after this are within the tail of the 150 ns window, where
#: multiple reflections/reverberation make a "first formation arrival"
#: label unreliable; excluded from the search, not from the file.
MAX_ARRIVAL_SAMPLE = 950
MARKER_SAMPLES = 2
MIN_PICK_CONFIDENCE = 8.0
#: A velocity outside this range is not a plausible GPR propagation velocity
#: in any geological material at this frequency (looser than published
#: dry-soil-to-pure-water bounds, so it is a physical sanity gate, not a
#: tuned one).
MIN_PLAUSIBLE_VELOCITY_M_PER_NS = 0.01
MAX_PLAUSIBLE_VELOCITY_M_PER_NS = 0.30
#: Mirrors scripts/bam_hyperbola_velocity_audit.py and
#: scripts/tu1208_depth_calibration.py: a t0/(1/v) parameter correlation at
#: or above this is confounded.
CONFOUND_THRESHOLD = 0.9


class AuditError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# geometry: real, DGPS-surveyed borehole separations (independent of radar)
# ---------------------------------------------------------------------------

def _read_xlsx_rows(outer_zip: zipfile.ZipFile, member: str) -> list[dict]:
    """
    A minimal, dependency-free XLSX cell reader (no openpyxl/pandas
    available in this environment). `member` is itself an .xlsx -- a zip --
    nested inside `outer_zip` (TestUM's published GEWS_Deviation_and_GPS.zip).
    Reads shared strings and the first worksheet only -- sufficient for
    TestUM's flat GPS table.
    """
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    xlsx_bytes = outer_zip.read(member)
    zf = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.findall(".//m:t", ns)))
    sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall(".//m:row", ns):
        cells: dict[str, Optional[str]] = {}
        for c in row.findall("m:c", ns):
            col = "".join(ch for ch in c.get("r", "") if ch.isalpha())
            v = c.find("m:v", ns)
            val = v.text if v is not None else None
            if c.get("t") == "s" and val is not None:
                val = shared[int(val)]
            cells[col] = val
        rows.append(cells)
    return rows


def load_well_coordinates(gps_zip: Path = GPS_ZIP) -> dict[str, tuple[float, float]]:
    """Real UTM (easting, northing) per 2-inch well, from the published DGPS survey."""
    if not gps_zip.exists():
        raise AuditError(f"GPS archive not present: {gps_zip}")
    with zipfile.ZipFile(gps_zip) as zf:
        rows = _read_xlsx_rows(zf, GPS_MEMBER)
    header = rows[0]
    col_of = {v: k for k, v in header.items() if v}
    wells: dict[str, tuple[float, float]] = {}
    for r in rows[1:]:
        wid = r.get(col_of.get("ID_2inch_borehole", ""))
        east = r.get(col_of.get("UTM_east[m]", ""))
        north = r.get(col_of.get("UTM_north[m]", ""))
        if not wid or east is None or north is None:
            continue
        wells[wid.split("_")[-1]] = (float(east), float(north))
    if len(wells) < 15:
        raise AuditError(f"expected >=15 wells in the GPS survey, found {len(wells)}")
    return wells


def surveyed_separation_m(wells: dict[str, tuple[float, float]], a: str, b: str) -> float:
    """
    Real, DGPS-surveyed collar-to-collar separation. NOT deviation-corrected
    at the antenna's actual depth -- the boreholes are near-vertical
    monitoring wells over an 18 m depth range with collar spacing of the
    same order (1-6 m), so collar separation is the working approximation
    this audit uses, exactly as the prior TestUM stages did ("ray path ~
    their separation"). Reported as a limitation, not silently assumed away.
    """
    if a not in wells or b not in wells:
        raise AuditError(f"well {a!r} or {b!r} missing from the surveyed GPS table")
    ea, na = wells[a]
    eb, nb = wells[b]
    return math.hypot(ea - eb, na - nb)


# ---------------------------------------------------------------------------
# radar evidence: DZT decoding, independent of Subterra's own converter
# ---------------------------------------------------------------------------

@dataclass
class TimeAxis:
    n_samples: int
    range_ns: float
    sample_interval_ns: float


def read_dzt(path: Path) -> tuple[list[list[float]], TimeAxis]:
    """
    Traces and the real time axis, decoded directly from the file's own
    header -- independent of `converters.gssi_converter`, so this evidence
    is never produced by the same code it might one day inform. Matches
    `scripts/testum_air_warr_t0.py::read_dzt` exactly (same file family,
    same header layout, already verified against the published data matrix
    in `docs/testum-raw-data-validation.md`).
    """
    raw = path.read_bytes()
    u16 = lambda o: struct.unpack_from("<H", raw, o)[0]  # noqa: E731
    f32 = lambda o: struct.unpack_from("<f", raw, o)[0]  # noqa: E731
    nsamp, bits, rng = u16(4), u16(6), f32(26)
    width = bits // 8
    header = u16(2) * 1024
    body = len(raw) - header
    n_traces = body // (nsamp * width)
    fmt = {2: "<h", 4: "<i"}[width]
    traces = []
    for t in range(n_traces):
        base = header + t * nsamp * width
        traces.append([float(struct.unpack_from(fmt, raw, base + s * width)[0])
                       for s in range(nsamp)])
    return traces, TimeAxis(n_samples=nsamp, range_ns=rng, sample_interval_ns=rng / nsamp)


@dataclass
class ArrivalCandidate:
    sample_index: int
    time_ns: float
    confidence: float
    baseline: float


@dataclass
class TracePick:
    trace_index: int
    depth_m: Optional[float]
    global_peak: Optional[ArrivalCandidate]
    first_sustained: Optional[ArrivalCandidate]
    usable: bool
    reason: str


def pick_arrival(trace: list[float], time_axis: TimeAxis) -> TracePick:
    """
    Two candidates per trace, picked WITHOUT any reference to the known
    separation or an expected velocity -- purely from the trace's own
    amplitude structure, exactly as `associate_target` in
    `bam_hyperbola_velocity_audit.py` never consults a known depth while
    picking:

      * `first_sustained` -- the first run of >=3 consecutive samples
        deviating > 5 sigma from a quiet-window baseline. Reported for
        transparency; NOT used as the primary pick (see module docstring
        for the borehole-guided-arrival finding this would otherwise miss).
      * `global_peak` -- the single largest |deviation| from that same
        baseline anywhere in the search window. This is the pick used for
        velocity, on the physical grounds stated in the module docstring.

    `usable` requires the global peak's confidence to clear
    MIN_PICK_CONFIDENCE; a trace that does not is reported unusable with a
    reason, never guessed at.
    """
    body = trace[MARKER_SAMPLES:]
    n = len(body)
    if n < MAX_ARRIVAL_SAMPLE:
        return TracePick(-1, None, None, None, False,
                         f"trace has only {n} post-marker samples, need >={MAX_ARRIVAL_SAMPLE}")

    quiet = body[MIN_ARRIVAL_SAMPLE - MARKER_SAMPLES:MIN_ARRIVAL_SAMPLE - MARKER_SAMPLES + 50]
    mean = statistics.mean(quiet)
    sd = statistics.pstdev(quiet) or 1.0

    search_lo = MIN_ARRIVAL_SAMPLE - MARKER_SAMPLES + 50
    search_hi = MAX_ARRIVAL_SAMPLE - MARKER_SAMPLES

    first = None
    run = 0
    for i in range(search_lo, search_hi):
        if abs(body[i] - mean) > 5.0 * sd:
            run += 1
            if run >= 3:
                idx = i - 2
                first = ArrivalCandidate(
                    sample_index=idx + MARKER_SAMPLES,
                    time_ns=(idx + MARKER_SAMPLES) * time_axis.sample_interval_ns,
                    confidence=abs(body[idx] - mean) / sd, baseline=mean)
                break
        else:
            run = 0

    peak_i = max(range(search_lo, search_hi), key=lambda i: abs(body[i] - mean))
    peak = ArrivalCandidate(
        sample_index=peak_i + MARKER_SAMPLES,
        time_ns=(peak_i + MARKER_SAMPLES) * time_axis.sample_interval_ns,
        confidence=abs(body[peak_i] - mean) / sd, baseline=mean)

    if peak.confidence < MIN_PICK_CONFIDENCE:
        return TracePick(-1, None, peak, first, False,
                         f"global peak confidence {peak.confidence:.2f} is below "
                         f"the {MIN_PICK_CONFIDENCE} threshold")
    return TracePick(-1, None, peak, first, True, "global peak confidence sufficient")


# ---------------------------------------------------------------------------
# per-pair aggregation and the separation-vs-time model
# ---------------------------------------------------------------------------

@dataclass
class PairResult:
    tx: str
    rx: str
    file_name: str
    separation_m: float
    n_traces: int
    n_usable: int
    n_unusable: int
    picked_times_ns: list  # one per usable trace, in file (depth) order
    picked_confidences: list
    median_time_ns: Optional[float]
    time_spread_ns: Optional[float]  # max - min across usable depths
    usable: bool
    reason: str


def analyse_pair(tx: str, rx: str, file_name: str, separation_m: float,
                 raw_dir: Path) -> PairResult:
    path = raw_dir / file_name
    if not path.exists():
        return PairResult(tx, rx, file_name, separation_m, 0, 0, 0, [], [], None, None,
                          False, f"file not present locally: {path}")
    traces, time_axis = read_dzt(path)
    picks = [pick_arrival(t, time_axis) for t in traces]
    usable = [p for p in picks if p.usable]
    if len(usable) < 5:
        return PairResult(tx, rx, file_name, separation_m, len(traces), len(usable),
                          len(traces) - len(usable), [], [], None, None, False,
                          f"only {len(usable)} of {len(traces)} depth stations produced a "
                          f"usable pick (confidence >= {MIN_PICK_CONFIDENCE})")
    times = [p.global_peak.time_ns for p in usable]
    confs = [p.global_peak.confidence for p in usable]
    med = statistics.median(times)
    return PairResult(
        tx, rx, file_name, separation_m, len(traces), len(usable), len(traces) - len(usable),
        [round(t, 4) for t in times], [round(c, 2) for c in confs],
        round(med, 4), round(max(times) - min(times), 4), True,
        f"{len(usable)} of {len(traces)} depth stations usable",
    )


# ---------------------------------------------------------------------------
# Method A -- joint fit of t0 and 1/v from crosshole (separation, time) pairs
# ---------------------------------------------------------------------------

@dataclass
class JointFitResult:
    n_pairs: int
    t0_ns: Optional[float]
    velocity_m_per_ns: Optional[float]
    parameter_correlation: Optional[float]
    identifiable: bool
    identifiability_note: str
    residuals_ns: dict
    rms_residual_ns: Optional[float]
    max_residual_ns: Optional[float]


def fit_joint(pairs: list[PairResult]) -> JointFitResult:
    """
    t_measured = t0 + L / v, jointly fit over every USABLE pair's (surveyed
    separation, median picked time). Mirrors the identifiability analysis in
    `bam_hyperbola_velocity_audit.py::fit_method_a` exactly: identifiability
    is read from (X^T X)^-1, never assumed from the point count.
    """
    usable = [p for p in pairs if p.usable]
    if len(usable) < 2:
        return JointFitResult(len(usable), None, None, None, False,
                              f"only {len(usable)} usable pair(s); at least 2 are needed to "
                              f"fit 2 parameters", {}, None, None)

    import numpy as np
    L = np.array([p.separation_m for p in usable])
    t = np.array([p.median_time_ns for p in usable])
    design = np.column_stack([L, np.ones_like(L)])  # t = (1/v)*L + t0
    coeffs, *_ = np.linalg.lstsq(design, t, rcond=None)
    inv_v, t0 = coeffs
    if inv_v <= 0:
        return JointFitResult(len(usable), float(t0), None, None, False,
                              f"fit produced a non-physical velocity (1/v={inv_v:.4g}); "
                              f"arrival time does not increase with separation as the "
                              f"model requires", {}, None, None)
    v = 1.0 / inv_v
    if not (MIN_PLAUSIBLE_VELOCITY_M_PER_NS <= v <= MAX_PLAUSIBLE_VELOCITY_M_PER_NS):
        return JointFitResult(len(usable), float(t0), None, None, False,
                              f"fitted velocity {v:.4f} m/ns is outside the physically "
                              f"plausible range [{MIN_PLAUSIBLE_VELOCITY_M_PER_NS}, "
                              f"{MAX_PLAUSIBLE_VELOCITY_M_PER_NS}] m/ns", {}, None, None)

    correlation = None
    try:
        xtx_inv = np.linalg.inv(design.T @ design)
        if xtx_inv[0, 0] > 0 and xtx_inv[1, 1] > 0:
            correlation = float(xtx_inv[0, 1] / math.sqrt(xtx_inv[0, 0] * xtx_inv[1, 1]))
    except np.linalg.LinAlgError:
        correlation = None
    identifiable = len(usable) >= 3 and correlation is not None and abs(correlation) < CONFOUND_THRESHOLD
    if len(usable) < 3:
        note = "only 2 usable pairs: t0 and v are exactly determined, not independently checkable"
    elif correlation is None:
        note = "could not compute a parameter correlation (singular design)"
    else:
        note = (f"t0 and v parameter correlation {correlation:.4f} "
               f"({'CONFOUNDED' if not identifiable else 'separable'}, "
               f"threshold {CONFOUND_THRESHOLD})")

    predicted = design @ np.array([inv_v, t0])
    residuals = {f"{p.tx}-{p.rx}": float(t[i] - predicted[i]) for i, p in enumerate(usable)}
    errs = np.array(list(residuals.values()))
    return JointFitResult(
        len(usable), float(t0), float(v), correlation, identifiable, note,
        residuals, float(np.sqrt(np.mean(errs ** 2))), float(np.max(np.abs(errs))),
    )


def leave_one_out(pairs: list[PairResult]) -> list[dict]:
    usable = [p for p in pairs if p.usable]
    out = []
    for held in usable:
        rest = [p for p in usable if (p.tx, p.rx) != (held.tx, held.rx)]
        fit = fit_joint(rest)
        if fit.velocity_m_per_ns is None:
            out.append({"held_out": f"{held.tx}-{held.rx}", "predicted_time_ns": None,
                       "error_ns": None, "note": fit.identifiability_note})
            continue
        pred = fit.t0_ns + held.separation_m / fit.velocity_m_per_ns
        out.append({
            "held_out": f"{held.tx}-{held.rx}", "refit_velocity_m_per_ns": fit.velocity_m_per_ns,
            "refit_t0_ns": fit.t0_ns, "predicted_time_ns": pred,
            "observed_time_ns": held.median_time_ns, "error_ns": pred - held.median_time_ns,
        })
    return out


def relative_permittivity(v: Optional[float]) -> Optional[dict]:
    if v is None or v <= 0:
        return None
    eps_r = (C_M_PER_NS / v) ** 2
    saturated_range = (60.0, 90.0)  # water-saturated sediment, water itself ~80
    return {
        "velocity_m_per_ns": v, "relative_permittivity": eps_r,
        "saturated_aquifer_reference_range": saturated_range,
        "within_saturated_reference_range": saturated_range[0] <= eps_r <= saturated_range[1],
        "note": "Reference range for a fully water-saturated sediment/aquifer, consistent with "
               "TestUM's own site description. A sanity check, not a validation criterion.",
    }


def classify(fit: JointFitResult, pairs: list[PairResult], loo: list[dict]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    n_usable = sum(1 for p in pairs if p.usable)
    if n_usable < 2 or fit.velocity_m_per_ns is None:
        reasons.append(f"fewer than 2 usable pairs, or the joint fit was non-physical: "
                       f"{fit.identifiability_note}")
        return "FAILED", reasons
    if not fit.identifiable:
        reasons.append(f"joint fit is not identifiable: {fit.identifiability_note}")
        return "INCONCLUSIVE", reasons
    loo_errs = [r["error_ns"] for r in loo if r.get("error_ns") is not None]
    if loo_errs and max(abs(e) for e in loo_errs) > 10.0:
        reasons.append(f"leave-one-out prediction error exceeds 10 ns "
                       f"(max {max(abs(e) for e in loo_errs):.2f} ns) -- unstable across pairs")
        return "ESTIMATED BUT NOT VALIDATED", reasons
    reasons.append(
        f"identifiable joint fit ({fit.identifiability_note}), RMS residual "
        f"{fit.rms_residual_ns:.2f} ns, leave-one-out stable -- but no independently surveyed "
        f"DEPTH truth exists at TestUM to check the resulting velocity against a physical "
        f"target the way BAM's ducts could: the freezing front is a monitored process, not an "
        f"attested reflector at a published depth. Capped at ESTIMATED BUT NOT VALIDATED."
    )
    return "ESTIMATED BUT NOT VALIDATED", reasons


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def run_audit(raw_dir: Path = RAW_DIR) -> dict:
    generated = datetime.now(timezone.utc).isoformat()
    wells = load_well_coordinates()

    pairs = []
    missing_files = []
    for (tx, rx), fname in sorted(PAIR_FILES.items()):
        try:
            sep = surveyed_separation_m(wells, tx, rx)
        except AuditError as exc:
            missing_files.append({"pair": f"{tx}-{rx}", "reason": str(exc)})
            continue
        result = analyse_pair(tx, rx, fname, sep, raw_dir)
        if not (raw_dir / fname).exists():
            missing_files.append({"pair": f"{tx}-{rx}", "file": fname,
                                  "reason": "not downloaded locally"})
        pairs.append(result)

    fit = fit_joint(pairs)
    loo = leave_one_out(pairs)
    permittivity = relative_permittivity(fit.velocity_m_per_ns)
    classification, reasons = classify(fit, pairs, loo)

    return {
        "audit": "testum-crosshole-velocity-audit",
        "generated_utc": generated,
        "source": {
            "doi": "10.1594/PANGAEA.971978",
            "dataset": "Jung, Pohle & Werban (2024), TestUM Wittstock/Dosse borehole GPR",
            "licence": "CC-BY-4.0",
            "site": "shallow quaternary glacial aquifer, controlled freeze-thaw experiment",
        },
        "model": "t_measured = t0 + L/v, jointly fit over surveyed borehole-pair separations "
                "and picked crosshole zero-offset arrival times",
        "geometry": {
            "n_pairs_documented": len(PAIR_FILES),
            "n_pairs_analysed": len(pairs),
            "n_pairs_missing_locally": len(missing_files),
            "missing": missing_files,
            "separation_range_m": [round(min(p.separation_m for p in pairs), 3),
                                   round(max(p.separation_m for p in pairs), 3)] if pairs else None,
        },
        "pairs": [asdict(p) for p in pairs],
        "joint_fit": asdict(fit),
        "leave_one_out": loo,
        "relative_permittivity": permittivity,
        "classification": classification,
        "classification_reasons": reasons,
        "geometry_only_identifiability_reference": {
            "note": "docs/testum-evidence-audit.md computed corr(t0, slope) = -0.881 from "
                   "surveyed separations alone, before any trace was picked. Compare against "
                   "joint_fit.parameter_correlation above -- the empirical figure, from real "
                   "picked arrivals on the pairs actually analysed here.",
            "geometry_only_correlation": -0.881,
        },
        "product_implication": (
            "Not a live product change. TestUM's crosshole geometry is not 4TU-transferable "
            "(borehole-coupled vs. air-launched, no air gap) -- see "
            "docs/testum-evidence-audit.md's transferability table. This audit concerns "
            "whether TestUM's OWN data can support a validated velocity claim, independent of "
            "4TU."
        ),
    }


def _print_summary(result: dict) -> None:
    print(f"TestUM crosshole velocity audit ({result['geometry']['n_pairs_analysed']} pairs)")
    for p in result["pairs"]:
        if p["usable"]:
            print(f"  {p['tx']}-{p['rx']}: L={p['separation_m']:.3f}m "
                 f"t_median={p['median_time_ns']:.2f}ns spread={p['time_spread_ns']:.2f}ns "
                 f"({p['n_usable']}/{p['n_traces']} depths usable)")
        else:
            print(f"  {p['tx']}-{p['rx']}: UNUSABLE ({p['reason']})")
    fit = result["joint_fit"]
    print(f"\nJoint fit: v={fit['velocity_m_per_ns']}, t0={fit['t0_ns']}, "
         f"identifiable={fit['identifiable']} ({fit['identifiability_note']})")
    if fit["rms_residual_ns"] is not None:
        print(f"  RMS residual {fit['rms_residual_ns']:.3f} ns, max {fit['max_residual_ns']:.3f} ns")
    if result["relative_permittivity"]:
        rp = result["relative_permittivity"]
        print(f"  implied relative permittivity: {rp['relative_permittivity']:.2f} "
             f"(saturated-aquifer reference {rp['saturated_aquifer_reference_range']}, "
             f"within range: {rp['within_saturated_reference_range']})")
    loo_errs = [r["error_ns"] for r in result["leave_one_out"] if r.get("error_ns") is not None]
    if loo_errs:
        print(f"  leave-one-out: max {max(abs(e) for e in loo_errs):.3f} ns")
    print(f"\nCLASSIFICATION: {result['classification']}")
    for r in result["classification_reasons"]:
        print(f"  - {r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out", type=Path,
                       default=REPO_ROOT / "artifacts" / "testum" / "testum_velocity_audit.json")
    args = parser.parse_args()

    try:
        result = run_audit(args.raw_dir)
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
