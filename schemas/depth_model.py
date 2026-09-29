"""
The radar depth model: one place where time becomes depth, and where the
platform says how much that depth can be trusted.

FOUR QUANTITIES, NEVER ONE:

    recording delay     where the recorded window starts on the instrument
                        clock (SEG-Y DelayRecordingTime, normalised by
                        `converters.segy_time`). It is already INSIDE the raw
                        two-way time; it is not a time-zero and never becomes
                        one by itself.
    radar time zero     the event depth is measured from (direct wave / first
                        break / calibration), as a `schemas.time_zero`
                        TimeZeroResult: declared, measured or derived, with its
                        method and basis. Corrected time = raw - correction.
    velocity            a constant propagation velocity WITH the basis it rests
                        on (`VelocityBasis`): the platform default is an
                        assumption, a same-survey fit is an estimate that is not
                        independent of the data it will be judged against, and
                        only an independent measurement is independent.
    depth reference     what depth zero is below: the frame's declared
                        `VerticalAxis.origin_offset` (stage 12), or an axis whose
                        own origin is the ground surface.

DEPTH STATUS (`DepthStatus`):

    unavailable   no velocity: the time axis is still a time axis.
    approximate   a depth can be drawn, but at least one input is an assumption
                  or unresolved -- the default velocity, no time zero, or no
                  reference. Fine for a preview axis; never for a claim.
    resolved      velocity (not the default), time zero and reference are all
                  STATED. Resolved is not validated: a declaration is a claim,
                  and `validated` stays False until something independent
                  checks the result.

THE ARITHMETIC is `two_way_time_to_depth` below, bit-identical to the
`(t * v) / 2.0` every converter already used, so no stored depth moves.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

#: The platform's preview velocity (typical near-surface soil, relative
#: permittivity ~9). An ASSUMPTION: it never resolves a depth.
DEFAULT_VELOCITY_M_PER_NS = 0.1

#: Physically possible bounds for a propagation velocity, m/ns: above zero and
#: below the speed of light in vacuum (0.2998 m/ns, rounded to the same 0.30 the
#: declaration validator and IDS software use).
MAX_VELOCITY_M_PER_NS = 0.30


def two_way_time_to_depth(two_way_time_ns: float, velocity_m_per_ns: float) -> float:
    """One-way depth from a round-trip time at a constant velocity."""
    return (two_way_time_ns * velocity_m_per_ns) / 2.0


def corrected_time(raw_two_way_time_ns: float, correction_ns: Optional[float]) -> Optional[float]:
    """Raw two-way time minus a time-zero correction; None when there is none."""
    if correction_ns is None:
        return None
    return raw_two_way_time_ns - correction_ns


class VelocityBasis(str, Enum):
    """What a velocity rests on. Kinds of evidence, not a confidence score."""
    #: The platform default. Never resolves a depth.
    ASSUMED_DEFAULT = "assumed_default"
    #: A typical value for the material, from a reference work.
    LITERATURE = "literature"
    #: A person stated it, without a stated measurement behind it.
    USER_DECLARED = "user_declared"
    #: Fitted from THIS survey's own radar data (hyperbola fit, migration
    #: focusing). Useful, but not independent of anything scored against it.
    ESTIMATED_FROM_SAME_SURVEY = "estimated_from_same_survey"
    #: Measured independently of the reflection data being interpreted (CMP/WARR,
    #: borehole, a known-depth reflector not used for scoring, probe permittivity).
    INDEPENDENT_MEASUREMENT = "independent_measurement"


@dataclass(frozen=True)
class VelocityModel:
    value_m_per_ns: float
    basis: VelocityBasis
    method: Optional[str] = None
    uncertainty_m_per_ns: Optional[float] = None
    source: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "basis", VelocityBasis(self.basis))
        v = self.value_m_per_ns
        if not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 \
                or v > MAX_VELOCITY_M_PER_NS:
            raise ValueError(
                f"velocity {v!r} m/ns is not physically possible "
                f"(must be > 0 and <= {MAX_VELOCITY_M_PER_NS}; note m/ns, not cm/ns)")
        u = self.uncertainty_m_per_ns
        if u is not None and (not math.isfinite(u) or u < 0):
            raise ValueError(f"velocity uncertainty {u!r} must be a non-negative number")

    @property
    def independent_of_survey(self) -> bool:
        return self.basis is VelocityBasis.INDEPENDENT_MEASUREMENT

    def as_dict(self) -> dict:
        return {"value_m_per_ns": self.value_m_per_ns, "basis": self.basis.value,
                "method": self.method, "uncertainty_m_per_ns": self.uncertainty_m_per_ns,
                "independent_of_survey": self.independent_of_survey, "source": self.source}


def velocity_model_of(conversion: Optional[dict[str, Any]]) -> Optional[VelocityModel]:
    """
    The velocity a frame's `VerticalAxis.conversion` used, with its basis.

    An explicit `velocity_basis` wins. Without one (conversions written before
    this field existed): a declaration's conversion carries its own `basis`
    sentence, so it is USER_DECLARED; a converter's carries none, and the
    only velocity a converter applies unasked is the platform default, so a
    value equal to it is ASSUMED_DEFAULT and any other value USER_DECLARED
    (it was passed explicitly by whoever called the converter).
    """
    if not conversion or conversion.get("velocity_m_per_ns") is None:
        return None
    v = float(conversion["velocity_m_per_ns"])
    basis = conversion.get("velocity_basis")
    if basis is None:
        if conversion.get("basis") is not None or v != DEFAULT_VELOCITY_M_PER_NS:
            basis = VelocityBasis.USER_DECLARED
        else:
            basis = VelocityBasis.ASSUMED_DEFAULT
    return VelocityModel(value_m_per_ns=v, basis=basis,
                         method=conversion.get("velocity_method"),
                         uncertainty_m_per_ns=conversion.get("velocity_uncertainty_m_per_ns"),
                         source=conversion.get("basis"))


class DepthStatus(str, Enum):
    UNAVAILABLE = "unavailable"
    APPROXIMATE = "approximate"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class DepthReadiness:
    status: DepthStatus
    reasons: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    time_zero: Optional[dict] = None
    velocity: Optional[VelocityModel] = None
    reference_known: bool = False
    reference: Optional[str] = None
    recording_delay_ns: Optional[float] = None

    def as_dict(self) -> dict:
        return {"status": self.status.value, "validated": False,
                "reasons": list(self.reasons), "notes": list(self.notes),
                "recording_delay_ns": self.recording_delay_ns,
                "time_zero": self.time_zero,
                "velocity": self.velocity.as_dict() if self.velocity else None,
                "reference": {"known": self.reference_known, "description": self.reference},
                "model": "constant velocity: depth = (raw two-way time - time-zero correction) "
                         "x velocity / 2"}


def _reference_of(axis) -> tuple[bool, Optional[str]]:
    offset = getattr(axis, "origin_offset", None)
    if offset is not None and offset.relates_the_depth_axis:
        return True, (f"depth-axis origin {offset.offset_m:g} m relative to the "
                      f"{offset.measured_to} ({offset.evidence.value}, {offset.supplied_by})")
    if "ground surface" in (getattr(axis, "origin", "") or "").lower():
        return True, axis.origin
    return False, None


def assess_depth_readiness(axis, time_zero=None, recording_delay_ns: Optional[float] = None,
                           reference=None) -> DepthReadiness:
    """
    Whether this axis supports a depth, and how far it can be trusted.

    `time_zero` is a resolved-or-not `TimeZeroResult` (or None: nothing
    established). `recording_delay_ns` is reported alongside so a reader sees
    the delay and the time zero as the two different numbers they are.
    """
    velocity = velocity_model_of(getattr(axis, "conversion", None))
    known, ref_text = _reference_of(axis)
    tz = ({"status": time_zero.status.value, "method": time_zero.method.value,
           "correction_ns": time_zero.correction_ns, "basis": time_zero.basis}
          if time_zero is not None else
          {"status": "unavailable", "method": "none", "correction_ns": None,
           "basis": "no time zero has been declared, measured or derived"})
    notes = []
    if recording_delay_ns:
        notes.append(f"the recording delay ({recording_delay_ns:g} ns) is where the recorded "
                     f"window starts on the instrument clock; it is part of the raw time axis "
                     f"and is not a time zero")
    if velocity is None:
        return DepthReadiness(DepthStatus.UNAVAILABLE,
                              ["no propagation velocity: the time axis is still a time axis"],
                              notes, tz, None, known, ref_text, recording_delay_ns)
    reasons = []
    if velocity.basis is VelocityBasis.ASSUMED_DEFAULT:
        reasons.append(f"velocity {velocity.value_m_per_ns:g} m/ns is the platform default "
                       f"assumption, not a value stated for this ground")
    if time_zero is None or not time_zero.resolved:
        reasons.append("radar time zero is not established, so depth is measured from the "
                       "instrument clock, not from a physical event")
    if not known:
        reasons.append("no depth reference is declared: depth below what?")
    if velocity.basis is VelocityBasis.ESTIMATED_FROM_SAME_SURVEY:
        notes.append("the velocity was estimated from the same survey; it is not independent "
                     "of anything later compared against this depth")
    status = DepthStatus.APPROXIMATE if reasons else DepthStatus.RESOLVED
    return DepthReadiness(status, reasons, notes, tz, velocity, known, ref_text,
                          recording_delay_ns)


#: Frame assumption keys the SEG-Y converter records the normalised recording
#: start under (`converters/segy_converter.py`).
_RECORDING_DELAY_KEYS = ("time_axis_origin_offset", "time_axis_start_suspect")


def frame_time_zero(frame):
    """
    The time zero a frame's depth rests on, from the frame's own record: a
    resolved applied result (`APPLIED_TIME_ZERO_KEY`) first, then an operator
    declaration (`DECLARED_TIME_ZERO_KEY`, not yet applied), then an
    unresolved applied result (so "tried, inconclusive" is still reported).
    None when nothing exists. The recording delay is never consulted here.
    """
    from schemas.dataset_report import DECLARED_TIME_ZERO_KEY
    from schemas.time_zero import (
        APPLIED_TIME_ZERO_KEY, TimeZeroMethod, TimeZeroResult, TimeZeroStatus,
    )

    applied = frame.assumption(APPLIED_TIME_ZERO_KEY)
    unresolved = None
    if applied is not None and isinstance(applied.value, dict):
        try:
            result = TimeZeroResult.model_validate(applied.value)
        except ValueError:
            result = None
        if result is not None and result.resolved:
            return result
        unresolved = result
    declared = frame.assumption(DECLARED_TIME_ZERO_KEY)
    if declared is not None:
        try:
            correction = float(declared.value)
        except (TypeError, ValueError):
            correction = None
        if correction is not None and math.isfinite(correction):
            return TimeZeroResult(status=TimeZeroStatus.DECLARED,
                                  method=TimeZeroMethod.OPERATOR_DECLARED,
                                  correction_ns=correction, basis=declared.basis,
                                  source="DeclarationKind.TIME_ZERO")
    return unresolved


def frame_recording_delay_ns(frame) -> Optional[float]:
    """The normalised recording start a converter recorded, if any (ns)."""
    for key in _RECORDING_DELAY_KEYS:
        a = frame.assumption(key)
        if a is not None and isinstance(a.value, (int, float)):
            return float(a.value)
    return None


def frame_depth_readiness(frame) -> DepthReadiness:
    """`assess_depth_readiness` for a survey frame, from the frame's own record."""
    return assess_depth_readiness(frame.vertical_axis, time_zero=frame_time_zero(frame),
                                  recording_delay_ns=frame_recording_delay_ns(frame))
