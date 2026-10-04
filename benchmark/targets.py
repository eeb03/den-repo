"""
Generic buried-target ground truth: what is physically in the ground.

WHY THIS EXISTS. `benchmark.bam_truth` and `benchmark.tu1208_truth` each model
one publication's targets honestly, in shapes only their own scorer reads.
Yesan and the DRC seeded field will not fit either. This module is the one
shape a buried object takes when it is used as benchmark truth, loaded from a
reviewable per-dataset manifest (`benchmark/manifests/*.targets.json`), with
no database behind it.

PHYSICAL TRUTH ONLY. A target says where an object is, how big, of what, how
deep below a NAMED surface, and how that is known. It never carries a radar
quantity: there is no field for two-way time, velocity or radar-derived
depth, a depth `method` cannot be a radar method, and the manifest loader
refuses such keys by name rather than ignoring them. Predictions live in
`benchmark.predictions`, and only `benchmark.target_scoring` brings the two
together -- behind the gates below.

GATES ARE DATA. Whether a metric may be computed is decided from what the
manifest declares -- a frame's registration to the radar, its origin and
units status, whether the target list is exhaustive, and named open
questions -- never from what would be convenient. An unsupported metric is
refused with the reason, not approximated.

NOTHING HERE READS A DETECTOR. No import of `interpretation`,
`preprocessing`, `benchmark.detection` or `benchmark.predictions`;
`tests/test_blind_benchmark.py` checks both directions.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from benchmark.ground_truth import EvidenceBasis
from schemas.segmentation import EvidenceGrade

SCHEMA = "subterra.targets.v1"
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"

UNITS = ("m", "cm", "mm")


class ManifestError(ValueError):
    """A target or manifest that is scientifically ambiguous or malformed."""


# ---------------------------------------------------------------------------
# vocabularies
# ---------------------------------------------------------------------------

class FrameKind(str, Enum):
    #: 1-D distance along one named survey line from a named origin.
    SURVEY_LINE = "survey_line"
    #: A 2-D site/specimen frame with a stated origin and no CRS (BAM).
    LOCAL_CARTESIAN = "local_cartesian"
    #: Easting/northing in a declared projected CRS.
    PROJECTED = "projected"
    #: Longitude/latitude in a declared geographic CRS. Representable; not
    #: matchable -- no geodesic matching is implemented, so it is refused.
    GEOGRAPHIC = "geographic"


#: How well a frame's ORIGIN is established.
ORIGIN_STATUSES = ("declared", "corroborated", "unverified")
#: How the frame's units are known.
UNITS_STATUSES = ("declared", "documentation_prose", "unknown")
#: Whether the radar's own positions are expressed in this frame. `corroborated`
#: means the data are consistent with it without anyone stating it.
REGISTRATION_STATUSES = ("declared", "corroborated", "unresolved")


class MeasuredTo(str, Enum):
    """Which point of the object a depth or elevation refers to."""
    TOP = "top"
    CENTRE = "centre"
    BOTTOM = "bottom"
    #: The source states a number but not which point; allowed only with a
    #: named open question, and never scored.
    UNRESOLVED = "unresolved"


class DepthMethod(str, Enum):
    """How a PHYSICAL depth was established. There is deliberately no radar
    method: a depth from a radargram is a prediction, not truth."""
    DESIGN_SPECIFICATION = "design_specification"
    PUBLICATION_TRANSCRIPTION = "publication_transcription"
    TAPE_AT_PLACEMENT = "tape_at_placement"
    EXCAVATION_MEASUREMENT = "excavation_measurement"
    PROBING = "probing"
    SURVEY_INSTRUMENT = "survey_instrument"
    CONSTRUCTION_RECORD = "construction_record"
    UNKNOWN = "unknown"


class ElevationMethod(str, Enum):
    SURVEY_INSTRUMENT = "survey_instrument"
    CONSTRUCTION_RECORD = "construction_record"
    PUBLICATION_TRANSCRIPTION = "publication_transcription"


class Capability(str, Enum):
    """The things a benchmark might compute, each gated separately."""
    #: Horizontal matching of predictions to targets (TP/FN, recall).
    DETECTION_MATCHING = "detection_matching"
    #: Calling an unmatched prediction a false positive (FP, precision, F1).
    FALSE_POSITIVES = "false_positives"
    FALSE_ALARMS_PER_METRE = "false_alarms_per_metre"
    #: Distance between a matched prediction and its target, in physical units.
    LOCALIZATION_ERROR = "localization_error"
    DEPTH_SCORING = "depth_scoring"


#: Words that mark a radar-derived quantity. Refused wherever physical truth
#: is described, so one cannot be filed as truth by accident.
_RADAR_WORDS = ("gpr", "radar", "two_way", "twt", "velocity", "hyperbola",
                "migration", "time_zero", "reflection")
_RADAR_KEYS = frozenset({
    "two_way_time_ns", "two_way_time", "twt", "velocity_m_per_ns", "velocity",
    "radar_depth", "predicted_depth", "time_zero", "time_zero_ns", "peak_sample",
    "peak_time_ns", "derived_depth",
})

#: Bases that are a direct physical observation of the object, independent of
#: any radar interpretation. Only these can support Grade A.
_DIRECT_OBSERVATION = frozenset({
    EvidenceBasis.TRENCH_EXCAVATION, EvidenceBasis.SEEDED_PLACEMENT,
    EvidenceBasis.INDEPENDENT_SURVEY, EvidenceBasis.PROBING,
    EvidenceBasis.CONSTRUCTION_RECORD, EvidenceBasis.FABRICATION_RECORD,
})


def _enum(cls, value, name):
    try:
        return value if isinstance(value, cls) else cls(value)
    except ValueError:
        raise ManifestError(
            f"{name}={value!r} is not one of {[m.value for m in cls]}") from None


def _nonneg(value, name):
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ManifestError(f"{name} must be a finite non-negative number, got {value!r}")


def _positive(value, name):
    if value is not None and (not math.isfinite(value) or value <= 0):
        raise ManifestError(f"{name} must be a finite positive number, got {value!r}")


def _units(value, name):
    if value not in UNITS:
        raise ManifestError(f"{name}={value!r}; supported units: {list(UNITS)}")


# ---------------------------------------------------------------------------
# frames and locations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    """
    A reference frame target positions are expressed in, declared once per
    dataset. `registration_to_radar` is the load-bearing field: whether the
    radar's own positions are in this same frame. Nothing is matched across a
    registration nobody has established.
    """
    frame_id: str
    kind: FrameKind
    units: str
    origin: str
    origin_status: str
    units_status: str
    registration_to_radar: str
    registration_note: str = ""
    crs: Optional[str] = None
    line_id: Optional[str] = None
    note: str = ""

    def __post_init__(self):
        object.__setattr__(self, "kind", _enum(FrameKind, self.kind, "frame kind"))
        if not self.frame_id:
            raise ManifestError("frame_id is required")
        _units(self.units, f"frame {self.frame_id} units")
        for value, allowed, name in ((self.origin_status, ORIGIN_STATUSES, "origin_status"),
                                     (self.units_status, UNITS_STATUSES, "units_status"),
                                     (self.registration_to_radar, REGISTRATION_STATUSES,
                                      "registration_to_radar")):
            if value not in allowed:
                raise ManifestError(f"frame {self.frame_id}: {name}={value!r}; one of {allowed}")
        if self.kind in (FrameKind.PROJECTED, FrameKind.GEOGRAPHIC) and not self.crs:
            raise ManifestError(f"frame {self.frame_id}: a {self.kind.value} frame requires a crs")
        if self.kind in (FrameKind.LOCAL_CARTESIAN, FrameKind.SURVEY_LINE) and self.crs:
            raise ManifestError(
                f"frame {self.frame_id}: a {self.kind.value} frame has no crs; got {self.crs!r}")
        if self.kind == FrameKind.SURVEY_LINE and not self.line_id:
            raise ManifestError(f"frame {self.frame_id}: a survey_line frame requires line_id")
        if not str(self.origin or "").strip():
            raise ManifestError(f"frame {self.frame_id}: origin must say what 0 is measured from")

    @property
    def dimensions(self) -> int:
        return 1 if self.kind == FrameKind.SURVEY_LINE else 2


@dataclass(frozen=True)
class PointLocation:
    frame_id: str
    coordinates: tuple
    #: None = not stated by the source (NOT zero).
    uncertainty: Optional[float] = None
    note: str = ""
    geometry: str = "point"

    def __post_init__(self):
        object.__setattr__(self, "coordinates", tuple(float(c) for c in self.coordinates))
        _nonneg(self.uncertainty, "location uncertainty")
        if not all(math.isfinite(c) for c in self.coordinates):
            raise ManifestError(f"non-finite coordinate {self.coordinates}")

    def distance_to(self, point) -> float:
        return math.dist(self.coordinates, tuple(point))


@dataclass(frozen=True)
class SegmentLocation:
    """A linear object's axis (a duct, a pipe run) between two points."""
    frame_id: str
    start: tuple
    end: tuple
    uncertainty: Optional[float] = None
    note: str = ""
    geometry: str = "segment"

    def __post_init__(self):
        object.__setattr__(self, "start", tuple(float(c) for c in self.start))
        object.__setattr__(self, "end", tuple(float(c) for c in self.end))
        _nonneg(self.uncertainty, "location uncertainty")
        if len(self.start) != len(self.end):
            raise ManifestError("segment start and end have different coordinate dimensions")

    @property
    def coordinates(self) -> tuple:
        return self.start

    def distance_to(self, point) -> float:
        p, a, b = tuple(point), self.start, self.end
        ab = [bi - ai for ai, bi in zip(a, b)]
        denom = sum(c * c for c in ab)
        if denom == 0:
            return math.dist(p, a)
        t = max(0.0, min(1.0, sum((pi - ai) * c for pi, ai, c in zip(p, a, ab)) / denom))
        return math.dist(p, tuple(ai + t * c for ai, c in zip(a, ab)))


# ---------------------------------------------------------------------------
# object properties
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Dimensions:
    """Every field optional: an unknown dimension stays unknown."""
    units: Optional[str] = None
    shape: Optional[str] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    outer_diameter: Optional[float] = None
    inner_diameter: Optional[float] = None
    note: str = ""

    def __post_init__(self):
        values = {k: getattr(self, k) for k in
                  ("length", "width", "height", "outer_diameter", "inner_diameter")}
        for name, value in values.items():
            _positive(value, name)
        if any(v is not None for v in values.values()):
            _units(self.units, "dimensions units")
        if (self.inner_diameter is not None and self.outer_diameter is not None
                and self.inner_diameter >= self.outer_diameter):
            raise ManifestError("inner_diameter must be smaller than outer_diameter")


@dataclass(frozen=True)
class PhysicalDepth:
    """
    A burial depth below a NAMED reference surface, to a named point of the
    object. `reference_surface` is an id declared in the manifest's
    `depth_reference_surfaces`; the manifest loader checks it exists.
    """
    value: float
    units: str
    measured_to: MeasuredTo
    reference_surface: str
    method: DepthMethod
    uncertainty: Optional[float] = None
    source: str = ""
    open_question: Optional[str] = None
    note: str = ""

    def __post_init__(self):
        method = str(getattr(self.method, "value", self.method))
        if any(w in method.lower() for w in _RADAR_WORDS):
            raise ManifestError(
                f"depth method {method!r} is a radar method; a radar-derived depth is a "
                f"prediction, not physical truth, and cannot be recorded here")
        object.__setattr__(self, "method", _enum(DepthMethod, self.method, "depth method"))
        object.__setattr__(self, "measured_to", _enum(MeasuredTo, self.measured_to, "measured_to"))
        _units(self.units, "depth units")
        _nonneg(self.value, "depth value")
        _nonneg(self.uncertainty, "depth uncertainty")
        if not str(self.reference_surface or "").strip():
            raise ManifestError("a depth requires a reference_surface naming what it is below")
        if self.measured_to is MeasuredTo.UNRESOLVED and not self.open_question:
            raise ManifestError(
                "a depth whose measured_to is 'unresolved' must name the open_question "
                "that records why")


@dataclass(frozen=True)
class AbsoluteElevation:
    """An independently surveyed elevation. Never derived from radar depth."""
    value: float
    units: str
    vertical_datum: str
    measured_to: MeasuredTo
    method: ElevationMethod
    uncertainty: Optional[float] = None
    source: str = ""

    def __post_init__(self):
        if not str(self.vertical_datum or "").strip():
            raise ManifestError("an absolute elevation requires a vertical_datum")
        method = str(getattr(self.method, "value", self.method))
        if any(w in method.lower() for w in _RADAR_WORDS):
            raise ManifestError(f"elevation method {method!r} is a radar method")
        object.__setattr__(self, "method", _enum(ElevationMethod, self.method, "elevation method"))
        object.__setattr__(self, "measured_to", _enum(MeasuredTo, self.measured_to, "measured_to"))
        if self.measured_to is MeasuredTo.UNRESOLVED:
            raise ManifestError("an absolute elevation must say which point of the object it is")
        _units(self.units, "elevation units")
        _nonneg(self.uncertainty, "elevation uncertainty")
        if not math.isfinite(self.value):
            raise ManifestError("elevation value must be finite")


@dataclass(frozen=True)
class TargetEvidence:
    """
    How the target's existence and position are known, in the project's own
    vocabularies: `EvidenceBasis` (kind of observation) and `EvidenceGrade`
    (how well the physical fact is known). An operator's reading of a
    radargram is never independent of the radar and never Grade A or B.
    """
    basis: EvidenceBasis
    grade: EvidenceGrade
    independent_of_gpr: bool
    source: str
    established_by: str = ""
    notes: str = ""
    uncertainty: str = ""
    verified_by_subterra: bool = False

    def __post_init__(self):
        object.__setattr__(self, "basis", _enum(EvidenceBasis, self.basis, "evidence basis"))
        object.__setattr__(self, "grade", _enum(EvidenceGrade, self.grade, "evidence grade"))
        if not str(self.source or "").strip():
            raise ManifestError("evidence requires a source a reader could consult")
        if self.basis is EvidenceBasis.NOT_RECORDED:
            raise ManifestError(
                "evidence basis 'not_recorded' means nobody observed anything; it cannot "
                "support a target")
        if self.basis is EvidenceBasis.OPERATOR_RADAR_INTERPRETATION:
            if self.independent_of_gpr:
                raise ManifestError(
                    "an operator's radar interpretation cannot be independent_of_gpr")
            if self.grade in (EvidenceGrade.A_INDEPENDENTLY_VERIFIED,
                              EvidenceGrade.B_MEASUREMENT_ASSOCIATED):
                raise ManifestError(
                    f"an operator's radar interpretation cannot carry grade "
                    f"{self.grade.value}; it is at most operator_reviewed (C)")
        if self.grade is EvidenceGrade.A_INDEPENDENTLY_VERIFIED:
            if not self.independent_of_gpr:
                raise ManifestError("grade independently_verified requires independent_of_gpr")
            if self.basis not in _DIRECT_OBSERVATION:
                raise ManifestError(
                    f"grade independently_verified requires a direct physical observation; "
                    f"{self.basis.value} is not one")

    @property
    def is_independent_physical_truth(self) -> bool:
        return self.independent_of_gpr and self.grade in (
            EvidenceGrade.A_INDEPENDENTLY_VERIFIED, EvidenceGrade.B_MEASUREMENT_ASSOCIATED)


# ---------------------------------------------------------------------------
# target and manifest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GroundTruthTarget:
    target_id: str
    dataset_id: str
    object_class: str
    locations: tuple
    evidence: TargetEvidence
    depths: tuple = ()
    material: Optional[str] = None
    subtype: Optional[str] = None
    dimensions: Optional[Dimensions] = None
    absolute_elevation: Optional[AbsoluteElevation] = None
    line_id: Optional[str] = None
    notes: str = ""

    def location_in(self, frame_id: str):
        return next((loc for loc in self.locations if loc.frame_id == frame_id), None)


class EmptyKind(str, Enum):
    """Why a listed location is known to hold no object."""
    #: Dug, left empty and refilled -- a disturbance without an object.
    CONTROL_HOLE = "control_hole"
    #: Documented as having nothing placed, and not dug.
    UNDISTURBED_EMPTY = "undisturbed_empty"


@dataclass(frozen=True)
class AttestedEmptyLocation:
    """
    A location INDEPENDENTLY DOCUMENTED to hold no buried object -- not a
    target with a class of "nothing", and not merely ground where no target
    is known. It is never a false negative; a prediction on it is a
    documented false alarm, reported as a control response.
    """
    location_id: str
    dataset_id: str
    kind: EmptyKind
    locations: tuple
    evidence: Optional[TargetEvidence]
    hole_depth: Optional[PhysicalDepth] = None
    notes: str = ""

    def __post_init__(self):
        object.__setattr__(self, "kind", _enum(EmptyKind, self.kind, "attested-empty kind"))
        if not self.locations:
            raise ManifestError(f"attested-empty {self.location_id}: a location is required")
        if not isinstance(self.evidence, TargetEvidence):
            raise ManifestError(f"attested-empty {self.location_id}: evidence is required")
        if not self.evidence.independent_of_gpr:
            raise ManifestError(
                f"attested-empty {self.location_id}: emptiness must be documented "
                f"independently of the radar")
        if self.kind is EmptyKind.UNDISTURBED_EMPTY and self.hole_depth is not None:
            raise ManifestError(
                f"attested-empty {self.location_id}: an undisturbed location has no hole_depth")

    def location_in(self, frame_id: str):
        return next((loc for loc in self.locations if loc.frame_id == frame_id), None)


@dataclass(frozen=True)
class OpenQuestion:
    """Same shape as `benchmark.gates.OpenQuestion`, plus what it blocks."""
    id: str
    statement: str
    blocks: tuple
    resolution_route: str = ""
    status: str = "BLOCKED"


@dataclass(frozen=True)
class DepthReferenceSurface:
    surface_id: str
    description: str


@dataclass(frozen=True)
class TargetManifest:
    dataset_id: str
    title: str
    truth_source: dict
    exhaustive: dict
    frames: tuple
    depth_reference_surfaces: tuple
    open_questions: tuple
    targets: tuple
    path: Optional[str] = None
    notes: tuple = ()
    attested_empty_locations: tuple = ()

    def frame(self, frame_id: str) -> Frame:
        for f in self.frames:
            if f.frame_id == frame_id:
                return f
        raise ManifestError(f"no frame {frame_id!r} in manifest {self.dataset_id}")

    def open_blockers(self, capability: Capability) -> list[str]:
        return [f"{q.id}: {q.statement}" for q in self.open_questions
                if q.status != "RESOLVED" and capability.value in q.blocks]

    def capability(self, capability: Capability, frame_id: str) -> tuple[bool, list[str]]:
        """
        Whether the TRUTH side supports a capability in one frame, and every
        reason it does not. The prediction side has its own requirements,
        checked by `benchmark.target_scoring`.
        """
        frame = self.frame(frame_id)
        reasons = self.open_blockers(capability)
        if frame.kind == FrameKind.GEOGRAPHIC:
            reasons.append(f"frame {frame_id} is geographic; no geodesic matching is implemented")
        if frame.registration_to_radar == "unresolved":
            reasons.append(
                f"frame {frame_id}: the radar's positions are not registered to this frame "
                f"({frame.registration_note or 'no registration recorded'})")
        if capability in (Capability.FALSE_POSITIVES, Capability.FALSE_ALARMS_PER_METRE):
            if not self.exhaustive.get("value"):
                reasons.append(
                    "the target list is not attested exhaustive, so an unmatched prediction "
                    "is not known to be false")
        if capability in (Capability.FALSE_ALARMS_PER_METRE, Capability.LOCALIZATION_ERROR):
            if frame.units_status != "declared":
                reasons.append(f"frame {frame_id} units are {frame.units_status}, not declared")
        if capability is Capability.LOCALIZATION_ERROR:
            if frame.origin_status != "declared":
                reasons.append(f"frame {frame_id} origin is {frame.origin_status}, not declared")
            if frame.registration_to_radar != "declared":
                reasons.append(
                    f"frame {frame_id} registration to the radar is "
                    f"{frame.registration_to_radar}, not declared")
        if capability is Capability.DEPTH_SCORING:
            resolved = [d for t in self.targets for d in t.depths
                        if d.measured_to is not MeasuredTo.UNRESOLVED]
            if not resolved:
                reasons.append("no target carries a depth to a resolved point of the object")
        return (not reasons, reasons)

    def readiness(self) -> dict:
        """
        Derived, never declared: `scoring_ready` only when there are targets
        and detection matching is supported in at least one frame. Every
        capability's reasons are listed per frame.
        """
        frames = {f.frame_id: {c.value: self.capability(c, f.frame_id)[1] for c in Capability}
                  for f in self.frames}
        matchable = [fid for fid, caps in frames.items()
                     if not caps[Capability.DETECTION_MATCHING.value]]
        if self.targets and matchable:
            status = "scoring_ready"
        elif not self.targets and matchable and self.exhaustive.get("value"):
            # An attested-empty control: nothing to detect, so false alarms only.
            status = "control_only"
        else:
            status = "not_scoring_ready"
        reasons = ([] if self.targets else ["the manifest holds no targets"]) + (
            [] if matchable else ["detection matching is blocked in every frame"])
        return {"status": status, "reasons": reasons, "frames": frames}

    def evidence_summary(self) -> dict:
        grades: dict[str, int] = {}
        bases: dict[str, int] = {}
        for t in self.targets:
            grades[t.evidence.grade.value] = grades.get(t.evidence.grade.value, 0) + 1
            bases[t.evidence.basis.value] = bases.get(t.evidence.basis.value, 0) + 1
        independent = sum(t.evidence.is_independent_physical_truth for t in self.targets)
        if not self.targets:
            truth_class = "no_targets"
        elif independent == len(self.targets):
            truth_class = "independent_physical_truth"
        elif independent == 0:
            truth_class = "NOT_INDEPENDENT_operator_or_weak_evidence"
        else:
            truth_class = "MIXED_independent_and_non_independent"
        return {"truth_class": truth_class, "n_targets": len(self.targets),
                "n_independent_physical": independent, "by_grade": grades,
                "by_basis": bases,
                "verified_by_subterra": sum(t.evidence.verified_by_subterra
                                            for t in self.targets)}


# ---------------------------------------------------------------------------
# strict loading
# ---------------------------------------------------------------------------

_MANIFEST_KEYS = {"schema", "dataset_id", "title", "truth_source", "exhaustive", "frames",
                  "depth_reference_surfaces", "open_questions", "targets", "notes", "$comment",
                  "attested_empty_locations"}
_EMPTY_KEYS = {"location_id", "kind", "locations", "hole_depth", "evidence", "notes"}
_FRAME_KEYS = {f for f in Frame.__dataclass_fields__}
_TARGET_KEYS = {"target_id", "object_class", "material", "subtype", "dimensions",
                "locations", "depths", "absolute_elevation", "evidence", "line_id", "notes"}
_LOCATION_KEYS = {"frame_id", "geometry", "coordinates", "start", "end", "uncertainty", "note"}
_DEPTH_KEYS = {f for f in PhysicalDepth.__dataclass_fields__}
_ELEV_KEYS = {f for f in AbsoluteElevation.__dataclass_fields__}
_DIM_KEYS = {f for f in Dimensions.__dataclass_fields__}
_EVIDENCE_KEYS = {f for f in TargetEvidence.__dataclass_fields__}
_OQ_KEYS = {"id", "statement", "blocks", "resolution_route", "status"}


def _build(cls, d: dict, where: str):
    """Construct, turning a missing required field into a ManifestError that names it."""
    try:
        return cls(**d)
    except TypeError as e:
        raise ManifestError(f"{where}: {e}") from None


def _check_keys(d: dict, allowed: set, where: str) -> None:
    if not isinstance(d, dict):
        raise ManifestError(f"{where} must be an object, got {type(d).__name__}")
    for key in d:
        if key in _RADAR_KEYS:
            raise ManifestError(
                f"{where}: '{key}' is a radar quantity; physical truth cannot carry it "
                f"(predictions belong in benchmark.predictions)")
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise ManifestError(f"{where}: unknown field(s) {unknown}; refused rather than ignored")


def _location(d: dict, where: str, frames: dict):
    _check_keys(d, _LOCATION_KEYS, where)
    frame = frames.get(d.get("frame_id"))
    if frame is None:
        raise ManifestError(f"{where}: frame {d.get('frame_id')!r} is not declared")
    geometry = d.get("geometry", "point")
    kw = {"frame_id": frame.frame_id, "uncertainty": d.get("uncertainty"),
          "note": d.get("note", "")}
    if geometry == "point":
        loc = PointLocation(coordinates=tuple(d.get("coordinates", ())), **kw)
        coords = [loc.coordinates]
    elif geometry == "segment":
        loc = SegmentLocation(start=tuple(d.get("start", ())), end=tuple(d.get("end", ())), **kw)
        coords = [loc.start, loc.end]
    else:
        raise ManifestError(f"{where}: geometry {geometry!r}; one of ['point', 'segment']")
    for c in coords:
        if len(c) != frame.dimensions:
            raise ManifestError(
                f"{where}: {len(c)} coordinate(s) given for a {frame.dimensions}-D "
                f"{frame.kind.value} frame")
    return loc


def _target(d: dict, dataset_id: str, frames: dict, surfaces: set, questions: set,
            where: str) -> GroundTruthTarget:
    _check_keys(d, _TARGET_KEYS, where)
    tid = d.get("target_id")
    if not tid:
        raise ManifestError(f"{where}: target_id is required")
    where = f"target {tid}"
    if not d.get("object_class"):
        raise ManifestError(f"{where}: object_class is required (use 'unknown' if it is)")
    locs = tuple(_location(x, f"{where} location {i}", frames)
                 for i, x in enumerate(d.get("locations") or []))
    if not locs:
        raise ManifestError(f"{where}: a target needs at least one location")
    for i, a in enumerate(locs):
        for b in locs[i + 1:]:
            if a.frame_id != b.frame_id or not isinstance(a, PointLocation):
                continue
            gap = b.distance_to(a.coordinates)
            if gap > (a.uncertainty or 0.0) + (b.uncertainty or 0.0):
                raise ManifestError(
                    f"{where}: two locations in frame {a.frame_id} disagree by {gap:g} "
                    f"(more than their combined uncertainty)")
    depths = []
    for i, x in enumerate(d.get("depths") or []):
        _check_keys(x, _DEPTH_KEYS, f"{where} depth {i}")
        depth = _build(PhysicalDepth, x, f"{where} depth {i}")
        if depth.reference_surface not in surfaces:
            raise ManifestError(
                f"{where}: depth reference_surface {depth.reference_surface!r} is not declared "
                f"in depth_reference_surfaces")
        if depth.open_question and depth.open_question not in questions:
            raise ManifestError(f"{where}: open_question {depth.open_question!r} is not declared")
        depths.append(depth)
    dims = None
    if d.get("dimensions") is not None:
        _check_keys(d["dimensions"], _DIM_KEYS, f"{where} dimensions")
        dims = _build(Dimensions, d["dimensions"], f"{where} dimensions")
    elev = None
    if d.get("absolute_elevation") is not None:
        _check_keys(d["absolute_elevation"], _ELEV_KEYS, f"{where} absolute_elevation")
        elev = _build(AbsoluteElevation, d["absolute_elevation"], f"{where} absolute_elevation")
    _check_keys(d.get("evidence") or {}, _EVIDENCE_KEYS, f"{where} evidence")
    return GroundTruthTarget(
        target_id=tid, dataset_id=dataset_id, object_class=d["object_class"],
        material=d.get("material"), subtype=d.get("subtype"), dimensions=dims,
        locations=locs, depths=tuple(depths), absolute_elevation=elev,
        evidence=_build(TargetEvidence, d["evidence"], f"{where} evidence"), line_id=d.get("line_id"),
        notes=d.get("notes", ""),
    )


def load_manifest_dict(d: dict, path: Optional[str] = None) -> TargetManifest:
    _check_keys(d, _MANIFEST_KEYS, "manifest")
    if d.get("schema") != SCHEMA:
        raise ManifestError(f"manifest schema {d.get('schema')!r}; expected {SCHEMA!r}")
    dataset_id = d.get("dataset_id")
    if not dataset_id:
        raise ManifestError("manifest dataset_id is required")
    for key in ("truth_source", "exhaustive"):
        if not isinstance(d.get(key), dict):
            raise ManifestError(f"manifest {key} is required")
    if "value" not in d["exhaustive"] or not d["exhaustive"].get("statement"):
        raise ManifestError("manifest exhaustive needs a value and the statement it rests on")

    frames = {}
    for i, f in enumerate(d.get("frames") or []):
        _check_keys(f, _FRAME_KEYS, f"frame {i}")
        frame = _build(Frame, f, f"frame {i}")
        if frame.frame_id in frames:
            raise ManifestError(f"frame {frame.frame_id} is declared twice")
        frames[frame.frame_id] = frame
    surfaces = []
    for s in d.get("depth_reference_surfaces") or []:
        _check_keys(s, {"surface_id", "description"}, "depth_reference_surface")
        if not s.get("surface_id") or not s.get("description"):
            raise ManifestError("a depth reference surface needs an id and a description")
        surfaces.append(DepthReferenceSurface(**s))
    questions = []
    for q in d.get("open_questions") or []:
        _check_keys(q, _OQ_KEYS, "open_question")
        blocks = tuple(q.get("blocks") or ())
        for b in blocks:
            _enum(Capability, b, f"open question {q.get('id')} blocks")
        questions.append(OpenQuestion(id=q["id"], statement=q["statement"], blocks=blocks,
                                      resolution_route=q.get("resolution_route", ""),
                                      status=q.get("status", "BLOCKED")))
    surface_ids = {s.surface_id for s in surfaces}
    question_ids = {q.id for q in questions}

    targets, seen = [], set()
    for i, t in enumerate(d.get("targets") or []):
        target = _target(t, dataset_id, frames, surface_ids, question_ids, f"target {i}")
        if target.target_id in seen:
            raise ManifestError(f"target_id {target.target_id} appears twice")
        seen.add(target.target_id)
        targets.append(target)

    empties = []
    for i, e in enumerate(d.get("attested_empty_locations") or []):
        where = f"attested_empty_location {e.get('location_id', i)}"
        _check_keys(e, _EMPTY_KEYS, where)
        lid = e.get("location_id")
        if not lid:
            raise ManifestError(f"{where}: location_id is required")
        if lid in seen:
            raise ManifestError(f"{where}: id {lid} is already used by a target or location")
        seen.add(lid)
        hole = None
        if e.get("hole_depth") is not None:
            _check_keys(e["hole_depth"], _DEPTH_KEYS, f"{where} hole_depth")
            hole = _build(PhysicalDepth, e["hole_depth"], f"{where} hole_depth")
            if hole.reference_surface not in surface_ids:
                raise ManifestError(f"{where}: hole_depth reference_surface "
                                    f"{hole.reference_surface!r} is not declared")
        if e.get("evidence") is None:
            raise ManifestError(f"{where}: evidence is required")
        _check_keys(e["evidence"], _EVIDENCE_KEYS, f"{where} evidence")
        empties.append(AttestedEmptyLocation(
            location_id=lid, dataset_id=dataset_id, kind=e.get("kind"),
            locations=tuple(_location(x, f"{where} location {j}", frames)
                            for j, x in enumerate(e.get("locations") or [])),
            evidence=_build(TargetEvidence, e["evidence"], f"{where} evidence"),
            hole_depth=hole, notes=e.get("notes", "")))

    return TargetManifest(
        dataset_id=dataset_id, title=d.get("title", ""), truth_source=d["truth_source"],
        exhaustive=d["exhaustive"], frames=tuple(frames.values()),
        depth_reference_surfaces=tuple(surfaces), open_questions=tuple(questions),
        targets=tuple(targets), path=path, notes=tuple(d.get("notes") or ()),
        attested_empty_locations=tuple(empties),
    )


def load_manifest(path) -> TargetManifest:
    path = Path(path)
    return load_manifest_dict(json.loads(path.read_text()), path=str(path))
