"""
Known-geometry depth calibration: time zero and velocity from reflectors whose
depth is known independently of the radar.

WHY. `depth = v * (t - t0) / 2` has two unknowns. An automatic time zero
(Method C) adds +43 mm of depth bias on BAM's ducts, and a declared velocity is
a claim, not a measurement. Fitting both to reflectors at KNOWN depths -- a
slab's base, a cored interface, a back wall, a pipe from as-built records --
is what took BAM duct depth to +7 mm mean error
(docs/research/bam_quantitative_validation.md, section 11). This module is that
fit, generalised, with the refusals that make it safe.

THE MODEL. Each calibration point i has a known depth d_i (metres, below the
same reference surface as the depth axis) and the two-way time t_i (ns, on the
RAW axis) at which its reflection was picked. With a constant velocity:

    t_i = t0 + (2 / v) * d_i

so ordinary least squares on (d_i, t_i) gives intercept t0 and slope 2/v. With a
single point, one of t0 or v must already be known and is held fixed.

INDEPENDENCE. The DEPTHS must not come from the radar: a depth source named as
radar, GPR, two-way time, velocity or hyperbola is refused, as in
`benchmark.targets`. The TIMES are radar picks by construction; they are read
with a stated convention (onset or peak), and the same convention must be used
when the calibrated depths are later compared with anything. The reflectors used
here become calibration evidence and must be excluded from any later depth
validation of the same calibration (their ids are recorded for that purpose).

REFUSAL, NOT REPAIR. A fit is REFUSED -- never adjusted -- when it is
under-determined, degenerate, physically impossible, internally inconsistent
(residuals beyond the stated pick precision), or fails leave-one-out
prediction. A refusal says which rule failed.

REDUNDANCY. Three or more points allow residuals and leave-one-out checks, so
only such a calibration is `redundant` and scientifically sufficient for depth.
Two points fit exactly and one point needs a fixed partner: both are accepted
and labelled non-redundant, which keeps depth operational but not sufficient.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

#: Physically possible velocity bounds, m/ns: the IDS acquisition software's
#: MinPropVel/MaxPropVel, the upper bound also the speed of light (shared with
#: `converters.ids_dt_converter.validate_velocity`).
MIN_VELOCITY_M_PER_NS = 0.01
MAX_VELOCITY_M_PER_NS = 0.30

#: Default pick precision (ns) when the caller states none: residuals beyond
#: 3x this are inconsistent with one constant-velocity medium.
DEFAULT_PICK_PRECISION_NS = 0.25
#: Leave-one-out tolerance floor (m). A held-out reflector must be predicted
#: within max(this, 2 x its stated depth uncertainty).
DEFAULT_LOO_TOLERANCE_M = 0.10
#: The calibration points must span at least this depth (m) for a joint fit;
#: closer than this the slope is not determined by the data.
MIN_DEPTH_SPAN_M = 0.05

#: Words that mark a depth as radar-derived (mirrors `benchmark.targets`).
_RADAR_WORDS = ("gpr", "radar", "two_way", "twt", "velocity", "hyperbola",
                "migration", "envelope", "method_c")


class DepthSource(str, Enum):
    """How a calibration point's depth is known. None of these is the radar."""
    CONSTRUCTION_RECORD = "construction_record"      # as-built drawings / records
    DESIGN_SPECIFICATION = "design_specification"    # design value, not re-measured
    CORE_OR_BOREHOLE = "core_or_borehole"            # a physical core / borehole log
    EXCAVATION = "excavation"                        # exposed and measured
    SURVEY_INSTRUMENT = "survey_instrument"          # levelling / total station
    TAPE_MEASUREMENT = "tape_measurement"            # measured by hand at placement
    FABRICATION_DRAWING = "fabrication_drawing"      # specimen dimensions


class PickConvention(str, Enum):
    """Which point of the reflected wavelet `time_ns` marks."""
    ONSET = "onset"
    PEAK = "peak"
    ZERO_CROSSING = "zero_crossing"


class CalibrationError(ValueError):
    """A calibration point is malformed (not a fit refusal)."""


@dataclass(frozen=True)
class CalibrationPoint:
    depth_m: float
    time_ns: float
    depth_source: DepthSource
    depth_evidence: str
    depth_uncertainty_m: Optional[float] = None
    reflector_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationPoint":
        if not isinstance(d, dict):
            raise CalibrationError("each calibration point must be an object")
        raw_source = str(d.get("depth_source") or "").strip().lower()
        if any(w in raw_source for w in _RADAR_WORDS):
            raise CalibrationError(
                f"depth_source {raw_source!r} is radar-derived; a calibration depth must be "
                f"known without the radar (one of {[s.value for s in DepthSource]})")
        try:
            source = DepthSource(raw_source)
        except ValueError:
            raise CalibrationError(
                f"depth_source {raw_source!r} is not one of {[s.value for s in DepthSource]}")
        evidence = str(d.get("depth_evidence") or "").strip()
        if not evidence:
            raise CalibrationError("depth_evidence is required: what document or measurement "
                                   "gives this depth")
        depth = _finite(d.get("depth_m"), "depth_m")
        if depth <= 0:
            raise CalibrationError(f"depth_m {depth} must be positive (below the reference)")
        time = _finite(d.get("time_ns"), "time_ns")
        unc = d.get("depth_uncertainty_m")
        unc = None if unc is None else _finite(unc, "depth_uncertainty_m")
        if unc is not None and unc < 0:
            raise CalibrationError("depth_uncertainty_m must be non-negative")
        rid = d.get("reflector_id")
        return cls(depth_m=depth, time_ns=time, depth_source=source, depth_evidence=evidence,
                   depth_uncertainty_m=unc, reflector_id=str(rid) if rid is not None else None)

    def as_dict(self) -> dict:
        return {"depth_m": self.depth_m, "time_ns": self.time_ns,
                "depth_source": self.depth_source.value, "depth_evidence": self.depth_evidence,
                "depth_uncertainty_m": self.depth_uncertainty_m,
                "reflector_id": self.reflector_id}


class CalibrationStatus(str, Enum):
    CALIBRATED = "calibrated"
    REFUSED = "refused"


@dataclass(frozen=True)
class DepthCalibrationResult:
    status: CalibrationStatus
    reasons: list = field(default_factory=list)
    t0_ns: Optional[float] = None
    velocity_m_per_ns: Optional[float] = None
    t0_std_ns: Optional[float] = None
    velocity_std_m_per_ns: Optional[float] = None
    rms_residual_ns: Optional[float] = None
    max_abs_residual_ns: Optional[float] = None
    leave_one_out: list = field(default_factory=list)
    n_points: int = 0
    redundant: bool = False
    fixed: Optional[str] = None            # "t0" | "velocity" | None (joint fit)
    pick_convention: Optional[str] = None
    pick_precision_ns: float = DEFAULT_PICK_PRECISION_NS

    @property
    def calibrated(self) -> bool:
        return self.status is CalibrationStatus.CALIBRATED

    def depth_m(self, time_ns: float) -> float:
        if not self.calibrated:
            raise ValueError("a refused calibration converts nothing")
        return (time_ns - self.t0_ns) * self.velocity_m_per_ns / 2.0

    def as_dict(self) -> dict:
        return {"status": self.status.value, "reasons": list(self.reasons),
                "t0_ns": self.t0_ns, "velocity_m_per_ns": self.velocity_m_per_ns,
                "t0_std_ns": self.t0_std_ns, "velocity_std_m_per_ns": self.velocity_std_m_per_ns,
                "rms_residual_ns": self.rms_residual_ns,
                "max_abs_residual_ns": self.max_abs_residual_ns,
                "leave_one_out": list(self.leave_one_out), "n_points": self.n_points,
                "redundant": self.redundant, "fixed": self.fixed,
                "pick_convention": self.pick_convention,
                "pick_precision_ns": self.pick_precision_ns,
                "model": "t = t0 + 2 d / v (constant velocity), least squares on known depths"}


def _finite(v, name) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise CalibrationError(f"{name} {v!r} is not a number")
    if not math.isfinite(x):
        raise CalibrationError(f"{name} {v!r} is not finite")
    return x


def _refuse(reasons, n, **kw) -> DepthCalibrationResult:
    return DepthCalibrationResult(status=CalibrationStatus.REFUSED, reasons=list(reasons),
                                  n_points=n, **kw)


def _ols(depths, times):
    """t = a + b d. Returns (a, b, residuals, cov) -- cov None with < 3 points."""
    n = len(depths)
    md, mt = sum(depths) / n, sum(times) / n
    sdd = sum((d - md) ** 2 for d in depths)
    b = sum((d - md) * (t - mt) for d, t in zip(depths, times)) / sdd
    a = mt - b * md
    res = [t - (a + b * d) for d, t in zip(depths, times)]
    cov = None
    if n > 2:
        s2 = sum(r * r for r in res) / (n - 2)
        var_b = s2 / sdd
        var_a = s2 * (1.0 / n + md * md / sdd)
        cov = (var_a, var_b, -md * var_b)
    return a, b, res, cov


def fit_depth_calibration(points: list[CalibrationPoint], pick_convention: str,
                          pick_precision_ns: Optional[float] = None,
                          fixed_t0_ns: Optional[float] = None,
                          fixed_velocity_m_per_ns: Optional[float] = None,
                          loo_tolerance_m: float = DEFAULT_LOO_TOLERANCE_M,
                          ) -> DepthCalibrationResult:
    """
    Fit (or refuse) t0 and v from `points`. `pick_convention` is required: a
    calibration is only meaningful against picks read the same way.
    """
    try:
        convention = PickConvention(str(pick_convention).strip().lower()).value
    except ValueError:
        raise CalibrationError(
            f"pick_convention {pick_convention!r} is not one of {[c.value for c in PickConvention]}")
    precision = DEFAULT_PICK_PRECISION_NS if pick_precision_ns is None else float(pick_precision_ns)
    if not math.isfinite(precision) or precision <= 0:
        raise CalibrationError("pick_precision_ns must be a positive number")
    if fixed_t0_ns is not None and fixed_velocity_m_per_ns is not None:
        raise CalibrationError("fix at most one of t0 and velocity; fixing both is a "
                               "declaration, not a calibration")
    n = len(points)
    common = dict(pick_convention=convention, pick_precision_ns=precision)
    if n == 0:
        return _refuse(["no calibration points"], 0, **common)
    depths = [p.depth_m for p in points]
    times = [p.time_ns for p in points]
    span = max(depths) - min(depths)

    fixed = None
    if fixed_t0_ns is None and fixed_velocity_m_per_ns is None:
        if n < 2:
            return _refuse(["one point cannot determine both t0 and velocity: add a second "
                            "reflector at a different depth, or fix t0 or the velocity"], n,
                           **common)
        if span < MIN_DEPTH_SPAN_M:
            return _refuse([f"calibration depths span {span:.3f} m, less than "
                            f"{MIN_DEPTH_SPAN_M} m: the velocity is not determined"], n,
                           **common)
        a, b, res, cov = _ols(depths, times)
        if b <= 0:
            return _refuse(["deeper reflectors were picked at earlier or equal times: the "
                            "picks contradict the known geometry"], n, **common)
        t0, v = a, 2.0 / b
        t0_std = math.sqrt(cov[0]) if cov else None
        v_std = (2.0 / (b * b)) * math.sqrt(cov[1]) if cov else None
    elif fixed_t0_ns is not None:
        fixed = "t0"
        t0 = _finite(fixed_t0_ns, "fixed_t0_ns")
        # least squares through the fixed intercept: t - t0 = (2/v) d
        num = sum(d * (t - t0) for d, t in zip(depths, times))
        den = sum(d * d for d in depths)
        if num <= 0:
            return _refuse(["with the fixed time zero, the reflectors arrive before it"], n,
                           **common)
        v = 2.0 * den / num
        res = [t - (t0 + 2.0 * d / v) for d, t in zip(depths, times)]
        t0_std = v_std = None
    else:
        fixed = "velocity"
        v = _finite(fixed_velocity_m_per_ns, "fixed_velocity_m_per_ns")
        t0 = sum(t - 2.0 * d / v for d, t in zip(depths, times)) / n
        res = [t - (t0 + 2.0 * d / v) for d, t in zip(depths, times)]
        t0_std = v_std = None

    reasons = []
    if not (MIN_VELOCITY_M_PER_NS <= v <= MAX_VELOCITY_M_PER_NS):
        reasons.append(f"fitted velocity {v:.4f} m/ns is outside the physically possible "
                       f"[{MIN_VELOCITY_M_PER_NS}, {MAX_VELOCITY_M_PER_NS}] m/ns")
    if t0 >= min(times):
        reasons.append(f"fitted time zero {t0:.3f} ns is not before the earliest reflection "
                       f"({min(times):.3f} ns)")
    rms = math.sqrt(sum(r * r for r in res) / n)
    worst = max(abs(r) for r in res)
    if worst > 3 * precision:
        reasons.append(f"a pick misses the fitted line by {worst:.3f} ns, more than 3x the "
                       f"stated pick precision ({precision} ns): the picks are not consistent "
                       f"with one constant-velocity medium")

    # leave-one-out depth prediction (needs a redundant joint fit: >= 3 points)
    loo = []
    if fixed is None and n >= 3:
        for i in range(n):
            dd = depths[:i] + depths[i + 1:]
            tt = times[:i] + times[i + 1:]
            if max(dd) - min(dd) < MIN_DEPTH_SPAN_M:
                continue
            a_i, b_i, _, _ = _ols(dd, tt)
            if b_i <= 0:
                reasons.append(f"without point {i} the remaining picks contradict the geometry")
                continue
            pred = (times[i] - a_i) / b_i
            err = pred - depths[i]
            unc = points[i].depth_uncertainty_m or 0.0
            tol = max(loo_tolerance_m, 2 * unc)
            loo.append({"held_out": i, "reflector_id": points[i].reflector_id,
                        "known_depth_m": depths[i], "predicted_depth_m": round(pred, 4),
                        "error_m": round(err, 4), "tolerance_m": tol})
            if abs(err) > tol:
                reasons.append(f"leave-one-out: point {i} is predicted at {pred:.3f} m against "
                               f"a known {depths[i]:.3f} m ({err:+.3f} m, tolerance {tol} m)")
    redundant = fixed is None and n >= 3 and len(loo) == n
    kw = dict(t0_ns=round(t0, 4), velocity_m_per_ns=round(v, 5),
              t0_std_ns=None if t0_std is None else round(t0_std, 4),
              velocity_std_m_per_ns=None if v_std is None else round(v_std, 5),
              rms_residual_ns=round(rms, 4), max_abs_residual_ns=round(worst, 4),
              leave_one_out=loo, fixed=fixed, **common)
    if reasons:
        return _refuse(reasons, n, **kw)
    notes = []
    if not redundant:
        notes.append("not redundant: " + (
            "two points fit exactly, so nothing checks them" if fixed is None else
            f"{fixed} was held fixed from another declaration, so only one quantity was fitted")
            + "; depth is operational but not scientifically sufficient")
    return DepthCalibrationResult(status=CalibrationStatus.CALIBRATED, reasons=notes,
                                  n_points=n, redundant=redundant, **kw)
