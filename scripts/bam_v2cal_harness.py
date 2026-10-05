"""
Shared harness for the calibrated Candidate V2 experiment on BAM.
Research only. Changes no production code.

WHAT THIS FILE ENFORCES
  * The Rot90 scans are the final held-out set. `load_eval_scan` refuses to open
    a Rot90 scan unless the frozen configuration
    (`configs/candidate_v2_calibrated_frozen.json`) is committed and unmodified
    in the working tree. The commit that froze it is returned and is recorded
    with every held-out result.
  * Calibration is recomputed here from the scan itself (back-wall steps and
    fabricated thicknesses: `scripts.bam_quantitative_validation`'s unchanged
    functions). Nothing is read from the committed
    `evidence/bam/results/quantitative_validation.json`, because that file also
    holds known-position target depths for the Rot90 scans.

TWO CALIBRATIONS, KEPT APART
  scorer_cal     The calibration the pre-registered L-XZ scorer has always
                 used (`fit_calibration` when the back-wall selection is
                 accepted, i.e. as-drawn and RMS <= CAL_MAX_RMS_NS). It is
                 identical for every arm. Without it, only L-X is scored.
  generator_cal  What calibrated V2 may use: the same back-wall picks passed
                 through the PRODUCT fit (`schemas.depth_calibration`,
                 peak convention, 0.1 ns precision, as in
                 `scripts.bam_calibration_product_path`). It is given to the
                 generator only if that fit is accepted AND redundant, i.e.
                 scientifically sufficient. Otherwise the generator receives
                 None and must run uncalibrated.
  Drawn object positions are used only to exclude object windows from the
  back-wall picks (the existing, unchanged rule). The generator receives t0, v,
  the pick convention and the precision, and nothing else.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from benchmark.bam_ingest import load_scan, load_volume
from scripts.bam_quantitative_validation import (
    CAL_MAX_RMS_NS, STEP_THICKNESS_MM, backwall_candidates, fit_calibration, lines_for, load_gt,
    select_backwall,
)

FROZEN_CONFIG = Path("configs/candidate_v2_calibrated_frozen.json")
CACHE = Path("artifacts/bam/v2cal")

DEV_SCANS = [("Pk266", "1_5_GHz_Rot00"), ("Pk266", "2_6_GHz_Rot00"),
             ("Pk401", "1_5_GHz_Rot00"), ("Pk401", "2_6_GHz_Rot00"),
             ("Pk050", "1_5_GHz_Rot00"), ("Pk050", "2_6_GHz_Rot00")]
HELDOUT_SCANS = [(s, f.replace("Rot00", "Rot90")) for s, f in DEV_SCANS]
OBJECT_TYPE = {"Pk266": "duct", "Pk401": "foam_cuboid", "Pk050": "control (no targets)"}

GENERATOR_PICK_CONVENTION = "peak"
GENERATOR_PICK_PRECISION_NS = 0.1


class HeldOutLocked(RuntimeError):
    pass


def _git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()


def frozen_commit() -> str:
    """The commit that last changed the frozen config; refuses if not committed or modified."""
    if not FROZEN_CONFIG.exists():
        raise HeldOutLocked(f"{FROZEN_CONFIG} does not exist: freeze before touching Rot90")
    if not _git("ls-files", str(FROZEN_CONFIG)):
        raise HeldOutLocked(f"{FROZEN_CONFIG} is not committed")
    if _git("status", "--porcelain", str(FROZEN_CONFIG)):
        raise HeldOutLocked(f"{FROZEN_CONFIG} has uncommitted changes")
    return _git("log", "-n1", "--format=%H", "--", str(FROZEN_CONFIG))


def load_frozen() -> tuple[dict, str]:
    commit = frozen_commit()
    return json.loads(FROZEN_CONFIG.read_text()), commit


class CalScan:
    """One scan with its truth windows (for scoring only) and both calibrations."""

    def __init__(self, spec: str, scan: str, allow_heldout: bool = False):
        if "Rot90" in scan and not allow_heldout:
            raise HeldOutLocked(f"{spec} {scan} is held out; use load_eval_scan after freezing")
        self.spec, self.scan = spec, scan
        self.sid = f"{spec}_3D_Dataset_{scan}"
        self.s = load_scan(spec, self.sid)
        targets, boreholes = load_gt()
        self.targets = targets.get(spec, [])
        self.boreholes = [b for b in boreholes if b["id"].startswith(spec)]
        self.n_lines = len(self.s.grid.y)
        self.windows = [(t, lines_for(t, self.s.grid)) for t in self.targets]
        self.object_type = OBJECT_TYPE[spec]
        self.antenna = "1.5 GHz" if scan.startswith("1_5") else "2.6 GHz"
        self._vol = None
        self.cal = None
        self.tbw = {k: 99.0 for k in range(4)}
        self.generator_cal = None
        self.calibration_record = {}

    def volume(self):
        if self._vol is None:
            self._vol = load_volume(self.s)
        return self._vol

    def release(self):
        self._vol = None

    @property
    def depth_scoreable(self):
        return self.cal is not None

    def calibrate(self):
        """Back-wall calibration (truth-free: specimen geometry only)."""
        from schemas.depth_calibration import CalibrationPoint, fit_depth_calibration

        vol, grid = self.volume(), self.s.grid
        dt = float(grid.z[1] - grid.z[0])
        thick = STEP_THICKNESS_MM[self.spec]
        cands = backwall_candidates(vol, grid, dt, self.targets, self.boreholes)
        sel = select_backwall(cands, thick)
        rec = {"orientation_fit_rms_ns": {k: (None if v is None else round(v["rms_ns"], 4))
                                          for k, v in sel.items()}}
        if sel["as_drawn"] is not None and sel["as_drawn"]["rms_ns"] > CAL_MAX_RMS_NS:
            sel = dict(sel, as_drawn=None)
        if sel["as_drawn"] is None:
            rec["scorer"] = "REFUSED (no accepted back-wall selection): L-X only"
            rec["generator"] = "none: no back-wall selection to calibrate from"
            self.calibration_record = rec
            return self
        times = sel["as_drawn"]["times"]
        self.tbw = {k: times[k] for k in range(4)}
        self.cal = fit_calibration(times, thick)
        rec["scorer"] = {k: self.cal[k] for k in ("v_m_per_ns", "t0_ns", "residual_rms_ns")}
        pts = [CalibrationPoint.from_dict({
            "depth_m": thick[k] / 1000.0, "time_ns": float(times[k]),
            "depth_source": "fabrication_drawing",
            "depth_evidence": f"Grohmann et al. 2026 drawings: back-wall step {k}",
            "reflector_id": f"{self.spec}-backwall-step{k}"}) for k in range(4)]
        fit = fit_depth_calibration(pts, GENERATOR_PICK_CONVENTION, GENERATOR_PICK_PRECISION_NS)
        fd = fit.as_dict()
        sufficient = fd.get("status") == "calibrated" and bool(fd.get("redundant"))
        rec["generator"] = {"status": fd.get("status"), "redundant": fd.get("redundant"),
                            "reasons": fd.get("reasons"), "t0_ns": fd.get("t0_ns"),
                            "velocity_m_per_ns": fd.get("velocity_m_per_ns"),
                            "scientifically_sufficient": sufficient}
        if sufficient:
            self.generator_cal = {"t0_ns": float(fd["t0_ns"]),
                                  "velocity_m_per_ns": float(fd["velocity_m_per_ns"]),
                                  "pick_convention": GENERATOR_PICK_CONVENTION,
                                  "pick_precision_ns": GENERATOR_PICK_PRECISION_NS}
        self.calibration_record = rec
        return self


def load_dev_scan(spec, scan) -> CalScan:
    return CalScan(spec, scan).calibrate()


def load_eval_scan(spec, scan) -> tuple[CalScan, str]:
    commit = frozen_commit()
    return CalScan(spec, scan, allow_heldout=True).calibrate(), commit


def cache_path(arm: str, sid: str) -> Path:
    return CACHE / f"{arm}__{sid}.json"


def cached(arm: str, sid: str, fn):
    p = cache_path(arm, sid)
    if p.exists():
        return json.loads(p.read_text())
    out = fn()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    return out


def jsonable(x):
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    return x
