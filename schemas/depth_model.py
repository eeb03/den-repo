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
        tz_ok = bool(self.time_zero) and self.time_zero.get("scientifically_sufficient", False)
        v_ok = self.velocity is not None and velocity_is_scientifically_sufficient(self.velocity)
        return {"status": self.status.value, "validated": False,
                # OPERATIONAL (status) vs SCIENTIFIC: every input stated and none an
                # assumption or a same-survey estimate -- the benchmark depth gate's rule.
                "scientifically_sufficient": bool(
                    self.status is DepthStatus.RESOLVED and tz_ok and v_ok and self.reference_known),
                "reasons": list(self.reasons), "notes": list(self.notes),
                "recording_delay_ns": self.recording_delay_ns,
                "time_zero": self.time_zero,
                "velocity": ({**self.velocity.as_dict(),
                              "scientifically_sufficient": v_ok} if self.velocity else None),
                "reference": {"known": self.reference_known, "description": self.reference},
                "model": "constant velocity: depth = (raw two-way time - time-zero correction) "
                         "x velocity / 2"}


#: Time-zero statuses that are evidence rather than an estimate from the same
#: data: an operator's declaration or an instrument measurement. A DERIVED
#: (Method C) pick is operationally usable and scientifically insufficient.
SCIENTIFIC_TIME_ZERO_STATUSES = ("declared", "measured")
#: Velocity bases the benchmark depth gate accepts.
SCIENTIFIC_VELOCITY_BASES = (VelocityBasis.USER_DECLARED, VelocityBasis.LITERATURE,
                             VelocityBasis.INDEPENDENT_MEASUREMENT)


def velocity_is_scientifically_sufficient(velocity: VelocityModel) -> bool:
    return velocity.basis in SCIENTIFIC_VELOCITY_BASES


def _reference_of(axis) -> tuple[bool, Optional[str]]:
    offset = getattr(axis, "origin_offset", None)
    if offset is not None and offset.relates_the_depth_axis:
        return True, (f"depth-axis origin {offset.offset_m:g} m relative to the "
                      f"{offset.measured_to} ({offset.evidence.value}, {offset.supplied_by})")
    if "ground surface" in (getattr(axis, "origin", "") or "").lower():
        return True, axis.origin
    return False, None


def assess_depth_readiness(axis, time_zero=None, recording_delay_ns: Optional[float] = None,
                           reference=None, stale_reason: Optional[str] = None) -> DepthReadiness:
    """
    Whether this axis supports a depth, and how far it can be trusted.

    `time_zero` is a resolved-or-not `TimeZeroResult` (or None: nothing
    established). `recording_delay_ns` is reported alongside so a reader sees
    the delay and the time zero as the two different numbers they are.
    """
    try:
        velocity = velocity_model_of(getattr(axis, "conversion", None))
        velocity_problem = None
    except ValueError as exc:
        velocity, velocity_problem = None, f"the recorded conversion is unusable: {exc}"
    known, ref_text = _reference_of(axis)
    tz = ({"status": time_zero.status.value, "method": time_zero.method.value,
           "correction_ns": time_zero.correction_ns, "basis": time_zero.basis,
           "declaration_id": time_zero.declaration_id,
           "operationally_available": time_zero.resolved,
           "scientifically_sufficient": time_zero.status.value in SCIENTIFIC_TIME_ZERO_STATUSES}
          if time_zero is not None else
          {"status": "unavailable", "method": "none", "correction_ns": None,
           "basis": "no time zero has been declared, measured or derived",
           "declaration_id": None, "operationally_available": False,
           "scientifically_sufficient": False})
    notes = []
    if time_zero is not None and time_zero.resolved \
            and time_zero.status.value not in SCIENTIFIC_TIME_ZERO_STATUSES:
        notes.append("the time zero is an automatic estimate from this survey's own waveform "
                     f"({time_zero.method.value}); usable for processing and display, but not "
                     "independent evidence")
    if recording_delay_ns:
        notes.append(f"the recording delay ({recording_delay_ns:g} ns) is where the recorded "
                     f"window starts on the instrument clock; it is part of the raw time axis "
                     f"and is not a time zero")
    if velocity is None:
        return DepthReadiness(DepthStatus.UNAVAILABLE,
                              [velocity_problem or
                               "no propagation velocity: the time axis is still a time axis"],
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
    if stale_reason:
        reasons.append(stale_reason)
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
                                  source="DeclarationKind.TIME_ZERO",
                                  declaration_id=declaration_id_of(frame, "time_zero"))
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
    current, stale_reason = derivation_is_current(frame)
    return assess_depth_readiness(frame.vertical_axis, time_zero=frame_time_zero(frame),
                                  recording_delay_ns=frame_recording_delay_ns(frame),
                                  stale_reason=None if current else stale_reason)


# ---------------------------------------------------------------------------
# stored derived depth: one derivation, one provenance chain, never stale
# ---------------------------------------------------------------------------
#
# THE INVARIANT: a record's stored `depth` always equals
#     two_way_time_to_depth(t, v)
# where t is the raw `two_way_time_ns`, or `corrected_time_ns` when the frame's
# ACTIVE applied time zero produced it, and v is the frame's ACTIVE velocity --
# and the frame's `depth_derivation` assumption names exactly those inputs.
# `rederive_depth` is the only writer after ingest; every change to a velocity
# or time-zero declaration calls it, so a superseded input never survives in a
# stored number. `verify_stored_depth` checks the invariant record by record.
#
# INGEST IS THE ONE EXCEPTION, by design: converters write depth from the raw
# axis and the frame's own conversion without stamping a derivation (so no
# ingest checksum moves). No stamp therefore means "ingest derivation": raw
# time, the frame's conversion, no time zero.

#: Bumped whenever the formula or the meaning of its inputs changes.
DEPTH_MODEL_VERSION = "constant-velocity-twt/2@1"
#: Frame assumption holding the inputs the stored depths were derived from.
DEPTH_DERIVATION_KEY = "depth_derivation"
#: Frame assumption mapping a declaration kind to the log id of the ACTIVE
#: declaration that set it on this frame (`api.spatial.apply_declaration`).
DECLARATION_IDS_KEY = "declaration_ids"
#: Record metadata key pointing at the frame derivation that produced its depth.
RECORD_DERIVATION_ID_KEY = "depth_derivation_id"


def declaration_id_of(frame, kind: str) -> Optional[str]:
    a = frame.assumption(DECLARATION_IDS_KEY) if frame is not None else None
    return (a.value or {}).get(kind) if a is not None and isinstance(a.value, dict) else None


@dataclass(frozen=True)
class ActiveVelocity:
    model: VelocityModel
    #: What each record's `velocity_source` says.
    source_label: Optional[str]
    declaration_id: Optional[str]
    #: "declaration" | "converter" | "record_ingest"
    origin: str


def active_velocity(frame, records=()) -> Optional[ActiveVelocity]:
    """
    THE velocity a frame's derived depth uses -- one source, in this order:

    1. a DEPTH_CONVERSION declaration on the frame's axis (`derived: True`,
       with the log id of the declaration that set it);
    2. the converter's own conversion (the velocity the records were ingested
       with -- the default is `assumed_default`, and says so);
    3. a legacy frame with no conversion at all: the velocity its records
       already carry from ingest.

    There is no fourth channel: `apply_time_zero` no longer takes a velocity of
    its own (it only accepts one equal to the active declaration).
    """
    axis = getattr(frame, "vertical_axis", None)
    conversion = getattr(axis, "conversion", None)
    if conversion and conversion.get("velocity_m_per_ns") is not None:
        model = velocity_model_of(conversion)
        if conversion.get("derived") is True:
            did = conversion.get("declaration_id")
            label = f"declaration:{did}" if did else f"declared:{model.basis.value}"
            return ActiveVelocity(model, label, did, "declaration")
        ingest_label = next((r.metadata.get("velocity_source") for r in records
                             if r.metadata.get("velocity_m_per_ns") is not None), None)
        return ActiveVelocity(model, ingest_label, None, "converter")
    for r in records:
        v = r.metadata.get("velocity_m_per_ns")
        if v is not None:
            model = VelocityModel(value_m_per_ns=float(v), basis=(
                VelocityBasis.ASSUMED_DEFAULT if float(v) == DEFAULT_VELOCITY_M_PER_NS
                else VelocityBasis.USER_DECLARED), source="records' ingest velocity")
            return ActiveVelocity(model, r.metadata.get("velocity_source"), None,
                                  "record_ingest")
    return None


def _applied_time_zero(frame):
    """The frame's active APPLIED time zero (resolved and applied), or None."""
    from schemas.time_zero import APPLIED_TIME_ZERO_KEY, TimeZeroResult

    a = frame.assumption(APPLIED_TIME_ZERO_KEY)
    if a is None or not isinstance(a.value, dict):
        return None
    try:
        result = TimeZeroResult.model_validate(a.value)
    except ValueError:
        return None
    return result if result.resolved and result.applied else None


def _derivation_inputs(frame, records) -> dict:
    import hashlib
    import json

    tz = _applied_time_zero(frame)
    vel = active_velocity(frame, records)
    known, ref_text = _reference_of(getattr(frame, "vertical_axis", None))
    inputs = {
        "raw_time_field": "two_way_time_ns",
        "time_zero": ({"applied": True, "status": tz.status.value, "method": tz.method.value,
                       "correction_ns": tz.correction_ns,
                       "declaration_id": tz.declaration_id}
                      if tz is not None else
                      {"applied": False, "status": "none", "method": "none",
                       "correction_ns": None, "declaration_id": None}),
        "corrected_time_field": "corrected_time_ns" if tz is not None else "two_way_time_ns",
        "velocity": ({"value_m_per_ns": vel.model.value_m_per_ns,
                      "basis": vel.model.basis.value, "origin": vel.origin,
                      "declaration_id": vel.declaration_id}
                     if vel is not None else None),
        "reference": {"known": known, "description": ref_text},
        "depth_model_version": DEPTH_MODEL_VERSION,
        "formula": "depth_m = t_ns * velocity_m_per_ns / 2, t = corrected_time_field",
    }
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode())
    return {"derivation_id": digest.hexdigest()[:16], **inputs}


def _time_for_depth(record, time_zero_applied: bool) -> Optional[float]:
    if time_zero_applied:
        if record.metadata.get("time_zero_excluded"):
            return None
        return record.metadata.get("corrected_time_ns")
    return record.metadata.get("two_way_time_ns")


def rederive_depth(frame, records) -> dict:
    """
    Recompute every stored depth of `records` (this frame's own) from the
    frame's ACTIVE inputs, stamp each record with the derivation id and the
    frame with the derivation. Returns the derivation. Raw time is never
    written. Records without a raw time (not per-sample GPR) are untouched.
    """
    from schemas.spatial import Assumption

    derivation = _derivation_inputs(frame, records)
    vel = active_velocity(frame, records)
    tz_applied = derivation["time_zero"]["applied"]
    for r in records:
        if r.metadata.get("two_way_time_ns") is None:
            continue
        t = _time_for_depth(r, tz_applied)
        if vel is None or t is None:
            r.depth = None
        else:
            r.depth = two_way_time_to_depth(t, vel.model.value_m_per_ns)
            r.metadata["velocity_m_per_ns"] = vel.model.value_m_per_ns
            if vel.source_label is not None:
                r.metadata["velocity_source"] = vel.source_label
        r.metadata[RECORD_DERIVATION_ID_KEY] = derivation["derivation_id"]
        # `preprocessing.dem_alignment` stored ground elevation - depth; it
        # follows the depth it was computed from, or goes.
        if "absolute_elevation_m" in r.metadata:
            r.metadata["absolute_elevation_m"] = (
                float(r.elevation) - r.depth
                if r.elevation is not None and r.depth is not None else None)
    frame.assumptions = [a for a in (frame.assumptions or [])
                         if a.key != DEPTH_DERIVATION_KEY] + [Assumption(
        key=DEPTH_DERIVATION_KEY, value=derivation, verified=False,
        basis=("the inputs every stored depth of this frame was derived from; "
               "rederived whenever a velocity or time-zero declaration changes"))]
    return derivation


def derivation_is_current(frame, records=()) -> tuple[bool, Optional[str]]:
    """
    Frame-level check, cheap enough for every assessment: do the stamped
    inputs still equal the frame's active inputs? No stamp = ingest
    derivation, current unless a time zero has since been applied.
    """
    stamp = frame.assumption(DEPTH_DERIVATION_KEY)
    if stamp is None:
        if _applied_time_zero(frame) is not None:
            return False, ("a time zero is applied but the stored depths carry no "
                           "derivation stamp, so what they were derived from is unknown")
        return True, None
    current = _derivation_inputs(frame, records)
    stamped = stamp.value or {}
    for part in ("time_zero", "velocity", "reference", "depth_model_version"):
        if part == "velocity" and not records and current.get("velocity") is None \
                and (stamped.get("velocity") or {}).get("origin") == "record_ingest":
            # A legacy frame with no conversion: its velocity lives on the
            # records, which a frame-only check cannot see. Nothing on the
            # frame can have changed it (a declaration writes a conversion).
            continue
        if stamped.get(part) != current.get(part):
            return False, (f"stored depths were derived with a superseded {part.replace('_', ' ')}; "
                           f"they do not describe the active inputs")
    return True, None


def verify_stored_depth(frame, records, rel_tol: float = 1e-12) -> list[str]:
    """
    Every way the stored depths disagree with the active provenance. Empty
    means the invariant holds. For tests and audits (it reads every record).
    """
    problems = []
    ok, why = derivation_is_current(frame, records)
    if not ok:
        problems.append(why)
    vel = active_velocity(frame, records)
    tz_applied = _applied_time_zero(frame) is not None
    stamp = frame.assumption(DEPTH_DERIVATION_KEY)
    stamp_id = (stamp.value or {}).get("derivation_id") if stamp is not None else None
    for r in records:
        if r.metadata.get("two_way_time_ns") is None:
            continue
        t = _time_for_depth(r, tz_applied)
        expected = (two_way_time_to_depth(t, vel.model.value_m_per_ns)
                    if vel is not None and t is not None else None)
        if (expected is None) != (r.depth is None) or (
                expected is not None and not math.isclose(r.depth, expected, rel_tol=rel_tol,
                                                          abs_tol=1e-15)):
            problems.append(f"record trace {r.metadata.get('trace_index')} t="
                            f"{r.metadata.get('two_way_time_ns')}: depth {r.depth} != {expected}")
            if len(problems) > 20:
                break
        if stamp_id is not None and r.depth is not None \
                and r.metadata.get(RECORD_DERIVATION_ID_KEY) != stamp_id:
            problems.append(f"record trace {r.metadata.get('trace_index')}: derivation id "
                            f"{r.metadata.get(RECORD_DERIVATION_ID_KEY)} != {stamp_id}")
            if len(problems) > 20:
                break
    return problems
