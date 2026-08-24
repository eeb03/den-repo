"""
The Dataset Report: what this dataset is, what happened to it, how far it can
be trusted, and what Subterra may legitimately do with it next.

WHY THIS IS A DOMAIN MODEL AND NOT A UI RESPONSE. Four later stages need the
same answers -- the spatial workflow needs to know what registration is
missing, candidate intelligence needs to know whether a radargram can be
reconstructed, reconstruction needs to know whether an absolute elevation
exists, and the non-expert mode needs all of it in one sentence each. Computing
that in a route handler would mean recomputing it four more times, differently.
So the report is a value: pure, serialisable, and assembled by one function
that takes already-loaded data and touches neither the database nor the network.

WHAT IS NEW HERE AND WHAT IS NOT. The platform already answers "can this view
show this selection?" (`schemas/views.resolve`) and "how does this depth axis
relate to that surface model?" (`fusion.vertical_reference.assess`). Both are
per-selection or per-frame-pair. Neither answers the question a person actually
asks when they open a dataset: **what can be done with this, as a whole?** That
is the gap this module fills, and it fills it by CONSUMING those two rather
than re-deciding anything they already decide.

READINESS MEANS CAPABILITY, NOT COMPLETION. `candidate_analysis: READY` says
the dataset carries what candidate analysis needs, not that candidates have
been found. The distinction matters because the two failure modes are
different: "not run yet" is a scheduling fact, "cannot be run" is a property of
the evidence. Only the second is a blocker, and only the second is what a user
needs to be told.

EVERY NON-READY STATE CARRIES `missing`. A blocked capability with no
enumerated cause is indistinguishable from a bug, and cannot be acted on. The
entries are phrased as things somebody could go and obtain -- a declared datum,
a surveyed control point, a velocity -- reusing the vocabulary
`vertical_reference` already established.

NOTHING HERE INVENTS A VALUE. Absent metadata is absent: fields are Optional
and render as an explained absence, never as a default, a zero, or a plausible
guess. The one thing this module is for is making the difference between
"declared" and "not declared" impossible to overlook.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas.provenance import LOCAL_ANOMALY_BASIS, ProvenanceClass, QuantityProvenance
from schemas.spatial import AxisKind, CRSKind, CRSProvenance, PositionKind, along_track_extents_m

#: Bumped when the SHAPE of the report changes, so a consumer that stored one
#: can tell whether it is still reading what it thinks it is.
REPORT_VERSION = "1.2"

#: The order the four ALWAYS-ATTEMPTED chain steps are reported in.
#: `time_zero` comes first because it is a property of the acquisition
#: itself (whatever a converter recorded about it, or the fact nothing was),
#: independent of whether `process_gpr_traces` has run at all. The other
#: three are the order `process_gpr_traces` actually applies them in:
#: background removal needs every trace in the line at once, then dewow and
#: gain run per trace. Naming this once here is what lets `build_signal_chain`
#: report the chain in the order it really ran, rather than a client
#: re-guessing it from an unordered dict.
#:
#: `local_anomaly` (see `_local_anomaly_step`) is NOT in this tuple: unlike
#: these four, it is not a property of every GPR record -- it is appended
#: last, only when `preprocess_trace_local_anomaly` has actually run.
SIGNAL_CHAIN_STEP_ORDER: tuple[str, ...] = ("time_zero", "background_removal", "dewow", "gain")

#: The survey-frame assumption key a converter stamps when it records a
#: time-zero-related header field but does not apply it as a correction
#: (e.g. GSSI's `rhf_position`). See `converters/gssi_converter.py`.
TIME_ZERO_ASSUMPTION_KEY = "time_zero_offset_not_applied"


class Capability(str, Enum):
    """
    The pipeline stages a dataset can be assessed against.

    These are Subterra's own stages, in the order of the master sequence, so a
    report reads as a position along the road to reconstruction rather than as
    a checklist of unrelated features.
    """
    INGESTION = "ingestion"
    VALIDATION = "validation"
    SIGNAL_PROCESSING = "signal_processing"
    HORIZONTAL_REGISTRATION = "horizontal_registration"
    VERTICAL_REGISTRATION = "vertical_registration"
    CANDIDATE_ANALYSIS = "candidate_analysis"
    OBJECT_CLASSIFICATION = "object_classification"
    RECONSTRUCTION_3D = "reconstruction_3d"


class Readiness(str, Enum):
    """
    Three states, deliberately not four.

    There is no "unknown": if the report cannot establish that a capability is
    available, that IS a blocker, and calling it unknown would let an
    unanswerable question look like a pending one.
    """
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class CapabilityAssessment(BaseModel):
    """One capability, its state, and -- when it is not READY -- why."""
    capability: Capability
    readiness: Readiness
    #: Always present. A READY state explains what makes it ready, so the
    #: report never asserts a capability without stating its basis.
    reason: str = Field(..., min_length=1)
    #: What would have to be obtained. Empty only when READY.
    missing: list[str] = Field(default_factory=list)
    #: Capabilities this one waits on, so a chain of blockers reads as a chain
    #: rather than as several unrelated failures.
    depends_on: list[Capability] = Field(default_factory=list)


class QualityDimension(BaseModel):
    """
    One measurable aspect of dataset quality.

    `value` is Optional and None is a real answer: some aspects a person would
    like scored have no defensible normalisation here, and emitting a number
    for them would be inventing a measurement. Those carry `value=None` and a
    basis that says why, rather than being quietly omitted.
    """
    name: str
    value: Optional[float] = Field(None, ge=0.0, le=1.0)
    #: Weight in the overall score. 0.0 for dimensions that are reported but
    #: deliberately do not contribute.
    weight: float = 0.0
    basis: str = Field(..., min_length=1)
    counts: dict[str, int] = Field(default_factory=dict)


class QualityReport(BaseModel):
    """
    The existing overall score, preserved, with the dimensions behind it
    exposed.

    The score is not recomputed here and not redefined; `validators.
    dataset_validator` remains its only author. What changes is that the
    components it weighs are no longer invisible -- a 0.83 that is entirely a
    coordinate problem and a 0.83 that is entirely a signal problem are
    different datasets, and used to render identically.
    """
    #: As stored on the dataset row at ingest/reprocess. None when never scored.
    stored_score: Optional[float] = None
    #: Recomputed from the records loaded for this report.
    computed_score: Optional[float] = None
    dimensions: list[QualityDimension] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    #: True when stored and computed disagree -- which means the dataset was
    #: modified after it was scored, and is worth knowing rather than hiding.
    score_is_stale: bool = False


class DatasetIdentity(BaseModel):
    """What this dataset is. Every field Optional; none is ever filled in."""
    dataset_id: str
    name: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    license: Optional[str] = None
    #: The single recorded modality when the frames agree on exactly one;
    #: `None` when they record several, or none. Never a comma-joined string
    #: and never filled from `declared_sensor_type` -- see `recorded_modalities`
    #: for the full composition and `declared_sensor_type` for the ingest
    #: declaration, which are named as two separate facts, not blended here.
    modality: Optional[str] = None
    #: Sorted distinct `frame.modality` values actually recorded on this
    #: dataset's survey frames. Empty when no frame records one -- an empty
    #: list, never a synthetic single modality.
    recorded_modalities: list[str] = Field(default_factory=list)
    #: `dataset.sensor_type` verbatim, the ingest declaration. Independent of
    #: `recorded_modalities`: the two are never reconciled or corrected
    #: against each other here.
    declared_sensor_type: Optional[str] = None
    original_format: Optional[str] = None
    source_files: list[str] = Field(default_factory=list)
    #: Manufacturer/model, only when a converter read it from the file. There
    #: is no inference from filename or format here: "it is a .dt file so it is
    #: an IDS" is a guess about hardware, and hardware metadata is one of the
    #: things that must never be manufactured.
    manufacturer: Optional[str] = None
    device_model: Optional[str] = None
    collection_date: Optional[datetime] = None
    imported_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    checksum: Optional[str] = None
    version: Optional[int] = None
    owner_id: Optional[str] = None
    #: NULL owner means the published reference corpora, not an unknown owner.
    is_system_dataset: bool = False
    has_ground_truth: bool = False
    #: Named so the UI can say "not declared" for exactly these.
    undeclared: list[str] = Field(default_factory=list)


class DatasetVolume(BaseModel):
    """How much data there is, and how much of it survived."""
    record_count: int = 0
    frame_count: int = 0
    #: Traces/stations/pixels per frame, when the frame states it.
    positions_per_frame: dict[str, Optional[int]] = Field(default_factory=dict)
    #: Samples per trace, from the frames that declare it. A range rather than
    #: one number: frames within a dataset need not agree, and averaging them
    #: would describe a trace that does not exist.
    samples_per_trace: Optional[list[int]] = None
    sample_interval: Optional[list[float]] = None
    sample_interval_units: Optional[str] = None
    #: Counted, not estimated.
    records_with_signal: int = 0
    records_with_timestamp: int = 0
    records_with_depth: int = 0
    records_with_position: int = 0
    invalid_signal_count: int = 0
    #: Where positions came from, by kind. The keys are `PositionKind` values.
    position_kinds: dict[str, int] = Field(default_factory=dict)


class HorizontalReference(BaseModel):
    """
    Where the measurements are, horizontally -- and whether that is enough.

    THE TWO QUESTIONS ARE SEPARATE and the report keeps them separate:
    `coordinates_present` asks whether the records carry numbers;
    `earth_referenced` asks whether those numbers mean a place on Earth. An
    odometry frame answers yes and no: it genuinely knows how far along the
    line each trace sits, and genuinely does not know where the line is.
    """
    coordinates_present: bool = False
    earth_referenced: bool = False
    #: Distinct declared references across the dataset's frames.
    declared_refs: list[str] = Field(default_factory=list)
    crs_kinds: list[str] = Field(default_factory=list)
    crs_provenance: list[str] = Field(default_factory=list)
    positioned_record_count: int = 0
    total_record_count: int = 0
    #: A tie is the only sanctioned route from a frame-local coordinate to a
    #: geographic one, so whether one exists is a first-class fact.
    geo_tie_frames: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class VerticalReference(BaseModel):
    """
    What the vertical axis measures, what it is measured from, and whether a
    depth in metres is physically justified.

    THIS IS THE SECTION THE WHOLE REPORT EXISTS FOR. Every other blocker in
    Subterra is a matter of work; this one is a matter of evidence that the
    held datasets do not contain, and it is the single thing standing between
    the platform and a 3D reconstruction. Stating it precisely, per dataset, is
    what makes it actionable instead of folkloric.
    """
    axis_kinds: list[str] = Field(default_factory=list)
    axis_units: list[str] = Field(default_factory=list)
    #: What depth 0 is. Almost always instrument time-zero, which is NOT the
    #: ground surface, which is why an absolute Z cannot be computed.
    axis_origins: list[str] = Field(default_factory=list)
    vertical_datum_declared: bool = False
    vertical_datums: list[str] = Field(default_factory=list)
    #: A depth axis exists when the frame measures depth, or measures time and
    #: carries a conversion. The conversion is an assumption about the ground,
    #: never a measurement of it.
    depth_axis_available: bool = False
    depth_basis: ProvenanceClass = ProvenanceClass.UNAVAILABLE
    time_to_depth_justified: bool = False
    #: Whether the dataset itself holds a surface elevation model to anchor to.
    surface_model_held: bool = False
    surface_frame_ids: list[str] = Field(default_factory=list)
    #: `fusion.vertical_reference.assess`, when a surface model exists to
    #: assess against. None when the dataset holds none -- which is itself the
    #: answer, not a missing computation.
    relationship_kind: Optional[str] = None
    absolute_elevation_available: bool = False
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class SurveyGeometry(BaseModel):
    """
    The shape of the acquisition, computed only from positions that exist.

    Line spacing, orientation and trajectory are NOT inferred here. They are
    derivable only for frames whose positions are Earth-referenced, and
    computing them from odometry or from a single frame would produce a survey
    layout that was never surveyed.
    """
    frame_count: int = 0
    #: Present only when geographic positions exist.
    bounds: Optional[dict[str, float]] = None
    lat_span_m: Optional[float] = None
    lon_span_m: Optional[float] = None
    #: Along-track extent per frame, for frames that carry odometry.
    along_track_extent_m: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class SpatialReport(BaseModel):
    horizontal: HorizontalReference
    vertical: VerticalReference
    geometry: SurveyGeometry


class ProcessingStage(BaseModel):
    """
    One step in what actually happened to this dataset.

    `status` is one of `completed`, `not_run`, or `unavailable`, and is read
    from evidence the platform stored -- not from a wish list of steps a
    pipeline is supposed to perform.
    """
    stage: str
    status: str
    detail: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    at: Optional[datetime] = None


class SignalProcessingStep(BaseModel):
    """
    One step of the recorded GPR signal-processing chain, in the order
    `process_gpr_traces` actually applies it (see `SIGNAL_CHAIN_STEP_ORDER`).

    `ran` is read directly from the stored `processing_applied` flag for this
    step -- never inferred from whether a parameter happens to be present.
    `parameters` holds only what was actually recorded for a step that ran;
    a step that did not run carries no parameters, because there are none to
    report.

    `reason` is only populated for `time_zero`, the one step whose `ran`
    alone cannot say why: `false` might mean a converter recorded and
    withheld an offset, or that nothing about time-zero was ever recorded.
    The other three steps are self-explanatory from their name and `ran`.
    """
    step: str
    ran: bool
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None


class SignalProcessingChain(BaseModel):
    """
    The recorded Phase 5 signal chain for this dataset -- READ, not re-run.

    `recorded` is False either when NEITHER a `processing_applied` entry NOR
    a time-zero claim (see `TIME_ZERO_ASSUMPTION_KEY`) exists for this
    dataset, or when the recorded modality composition names at least one
    modality and none of them is `gpr` (see `build_signal_chain`) -- those
    two are different absences with different `reason` text, never
    conflated: the first means Subterra was never told what happened to a
    GPR acquisition, the second means the GPR chain does not apply at all.
    Neither is an error, and `steps` stays empty rather than presenting an
    invented default chain (dewow/background-removal/gain are not assumed to
    have run just because they are the platform's own defaults).

    Once `recorded` is True, `steps[0]` is always `time_zero` -- never
    omitted -- because a GPR record's time origin is a fact worth stating
    even when nothing else about the chain is known yet.
    """
    recorded: bool
    reason: str = Field(..., min_length=1)
    steps: list[SignalProcessingStep] = Field(default_factory=list)


class CandidateSummary(BaseModel):
    """
    What candidate analysis has produced, described as candidates.

    CANDIDATE IS NOT DETECTION and this model cannot express a detection: there
    is no field for an object class, a probability, or a confirmed structure.
    `classes` carries the detector's own NEUTRAL GEOMETRIC shape class
    (`interpretation.anomaly_candidates` assigns these), which describes the
    shape of a response, not the identity of a thing. Turning one into "pipe"
    requires a validated classifier, and there is none.
    """
    #: Counted from stored `detector_candidate` labels, never by re-running a
    #: detector inside a report request.
    candidate_count: int = 0
    analysed: bool = False
    frames_with_candidates: list[str] = Field(default_factory=list)
    #: Neutral shape classes, with counts. Never object identities.
    shape_classes: dict[str, int] = Field(default_factory=dict)
    #: Each candidate's evidence is addressable, which is what makes the
    #: eventual evidence chain possible.
    evidence_available: bool = False
    #: Confirmed object classifications. Structurally always zero: no validated
    #: classifier exists, so nothing may claim one.
    classified_object_count: int = 0
    note: str = (
        "Candidates are anomalous regions, not detected objects. No object "
        "classification has been performed."
    )

    # -- Stage 13 -------------------------------------------------------------
    # EXTENDED, NOT REPLACED. The fields above already prevented a candidate
    # from claiming an object, and that protection is untouched. What they could
    # not answer is whether the set is still TRUSTWORTHY: which method produced
    # it, under which version, and whether the dataset has changed since. A
    # count with no generation record cannot be reproduced or invalidated, so
    # these are the minimum needed to make the existing summary accountable.

    #: available | limited | blocked. `limited` means a set exists but no longer
    #: matches the dataset; it is not the same as having found nothing.
    status: str = "blocked"
    status_reason: str = "candidate generation has not been run for this dataset"
    #: Never empty when status is not `available`.
    missing: list[str] = Field(default_factory=list)

    method: Optional[str] = None
    method_version: Optional[str] = None
    generated_at: Optional[datetime] = None
    is_stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)

    #: How much of this set is genuinely placeable, and how much has a depth at
    #: all. Counts by certainty level -- see `interpretation.candidate_intelligence`.
    localisation_breakdown: dict[str, int] = Field(default_factory=dict)
    depth_breakdown: dict[str, int] = Field(default_factory=dict)

    #: Structurally BLOCKED. No code path sets this to anything else.
    classification_status: str = "BLOCKED"


class DatasetReport(BaseModel):
    """The whole answer, in one value."""
    report_version: str = REPORT_VERSION
    generated_at: datetime
    identity: DatasetIdentity
    volume: DatasetVolume
    spatial: SpatialReport
    processing: list[ProcessingStage] = Field(default_factory=list)
    #: The Phase 5 ordered signal-processing chain -- see `SignalProcessingChain`.
    #: A more structured, orderable sibling of the `preprocessing` entry in
    #: `processing` above; that entry is unchanged and still exists.
    signal_chain: SignalProcessingChain
    quality: QualityReport
    candidates: CandidateSummary
    readiness: list[CapabilityAssessment] = Field(default_factory=list)
    #: The frame-level provenance projection, so the report and the provenance
    #: pane cannot disagree about where a number came from.
    provenance: list[QuantityProvenance] = Field(default_factory=list)

    def capability(self, capability: Capability) -> Optional[CapabilityAssessment]:
        return next((c for c in self.readiness if c.capability == capability), None)

    @property
    def blocked(self) -> list[Capability]:
        return [c.capability for c in self.readiness if c.readiness == Readiness.BLOCKED]


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
#
# One function per section, each taking already-loaded data. Nothing below
# opens a file, queries a database, or reaches the network -- which is what
# lets every branch be tested against a constructed dataset rather than against
# whichever six datasets happen to be in the corpus.

_EARTH_REFERENCED_KINDS = {CRSKind.GEOGRAPHIC, CRSKind.PROJECTED}
_TIME_KINDS = {AxisKind.TWO_WAY_TIME_NS, AxisKind.TWO_WAY_TIME_MS, AxisKind.TWO_WAY_TIME_S}


def _distinct(values) -> list[str]:
    """Sorted distinct non-empty strings, for fields that vary across frames."""
    return sorted({str(v) for v in values if v not in (None, "")})


def frame_modalities(frames) -> list[str]:
    """
    Sorted distinct `frame.modality` values, verbatim. The single definition
    `build_identity` and the signal-chain routes (report assembler and the
    thin `GET /{id}/signal-chain`) all share, so they cannot compute two
    different recorded compositions for the same frames.
    """
    return _distinct(getattr(getattr(f, "modality", None), "value", None) for f in frames)


def build_identity(dataset, frames, undeclared_extra: Optional[list[str]] = None) -> DatasetIdentity:
    source_files = _distinct(getattr(f, "source_file", None) for f in frames)
    modalities = frame_modalities(frames)
    extra = getattr(dataset, "extra_metadata", None) or {}

    identity = DatasetIdentity(
        dataset_id=dataset.id,
        name=getattr(dataset, "name", None),
        source=getattr(dataset, "source", None),
        source_url=getattr(dataset, "source_url", None),
        license=getattr(dataset, "license", None),
        modality=modalities[0] if len(modalities) == 1 else None,
        recorded_modalities=modalities,
        declared_sensor_type=getattr(dataset, "sensor_type", None),
        original_format=getattr(dataset, "original_format", None),
        source_files=source_files,
        # Read only from where a converter would have put it. Absent stays
        # absent: a format is not a manufacturer.
        manufacturer=extra.get("manufacturer"),
        device_model=extra.get("device_model"),
        collection_date=getattr(dataset, "collection_date", None),
        imported_at=getattr(dataset, "created_at", None),
        updated_at=getattr(dataset, "updated_at", None),
        checksum=getattr(dataset, "checksum", None),
        version=getattr(dataset, "version", None),
        owner_id=getattr(dataset, "owner_id", None),
        is_system_dataset=getattr(dataset, "owner_id", None) is None,
        has_ground_truth=bool(getattr(dataset, "has_ground_truth", False)),
    )

    # Named absences, so the UI can render "not declared" for exactly these
    # rather than deciding for itself which blanks are interesting.
    undeclared = [
        label for label, value in (
            ("source", identity.source),
            ("licence", identity.license),
            ("manufacturer", identity.manufacturer),
            ("device model", identity.device_model),
            ("acquisition date", identity.collection_date),
            ("checksum", identity.checksum),
        ) if not value
    ]
    identity.undeclared = undeclared + list(undeclared_extra or [])
    return identity


def build_volume(records, frames) -> DatasetVolume:
    samples = _distinct(
        getattr(getattr(f, "vertical_axis", None), "n_samples", None) for f in frames)
    intervals = sorted({
        getattr(getattr(f, "vertical_axis", None), "sample_interval", None)
        for f in frames
        if getattr(getattr(f, "vertical_axis", None), "sample_interval", None) is not None
    })
    units = _distinct(getattr(getattr(f, "vertical_axis", None), "units", None) for f in frames)

    position_kinds: dict[str, int] = {}
    with_signal = with_timestamp = with_depth = positioned = invalid = 0
    for r in records:
        kind = str(getattr(getattr(r, "position", None), "kind", PositionKind.NONE.value))
        position_kinds[kind] = position_kinds.get(kind, 0) + 1
        if getattr(r, "signal", None):
            with_signal += 1
            if any(v != v or v in (float("inf"), float("-inf")) for v in r.signal):
                invalid += 1
        if getattr(r, "timestamp", None) is not None:
            with_timestamp += 1
        if getattr(r, "depth", None) is not None:
            with_depth += 1
        if kind != PositionKind.NONE.value:
            positioned += 1

    return DatasetVolume(
        record_count=len(records),
        frame_count=len(frames),
        positions_per_frame={f.frame_id: getattr(f, "n_positions", None) for f in frames},
        samples_per_trace=[int(s) for s in samples] or None,
        sample_interval=list(intervals) or None,
        sample_interval_units=(units[0] if len(units) == 1 else None),
        records_with_signal=with_signal,
        records_with_timestamp=with_timestamp,
        records_with_depth=with_depth,
        records_with_position=positioned,
        invalid_signal_count=invalid,
        position_kinds=position_kinds,
    )


def build_horizontal(records, frames) -> HorizontalReference:
    # Kept paired with their frames, so a frame without a spatial_ref cannot
    # silently shift the list and attribute one frame's CRS to another.
    framed_refs = [(f, getattr(f, "spatial_ref", None)) for f in frames]
    framed_refs = [(f, r) for f, r in framed_refs if r is not None]
    refs = [r for _, r in framed_refs]

    kinds = {r.kind for r in refs}
    earth = bool(kinds) and kinds.issubset(_EARTH_REFERENCED_KINDS)
    partial_earth = bool(kinds & _EARTH_REFERENCED_KINDS)

    geographic = sum(
        1 for r in records
        if str(getattr(getattr(r, "position", None), "kind", "")) == PositionKind.GEOGRAPHIC.value
        or getattr(r, "registered_position", None) is not None
    )
    positioned = sum(
        1 for r in records
        if str(getattr(getattr(r, "position", None), "kind", PositionKind.NONE.value))
        != PositionKind.NONE.value
    )

    reasons: list[str] = []
    missing: list[str] = []

    if not positioned:
        reasons.append("no record carries a horizontal position")
        missing.append(
            "positions from the acquisition, or a GeoTie supplying them for each frame")
    elif not partial_earth:
        reasons.append(
            "positions exist but are expressed in a frame with no relationship to the "
            "Earth (engineering or acquisition coordinates)")
        missing.append(
            "a GeoTie: at least two surveyed control points per frame, asserted by "
            "somebody who knows them")
    elif not earth:
        reasons.append(
            "some frames are Earth-referenced and others are not, so the dataset as a "
            "whole cannot be placed")
        missing.append("a GeoTie for each frame that is not Earth-referenced")

    # A projected frame with no EPSG code is a real and common state: SEG-Y
    # headers carry easting/northing without ever saying which projection.
    undeclared_projections = [
        f.frame_id for f, r in framed_refs
        if r.kind == CRSKind.PROJECTED and not r.code
    ]
    if undeclared_projections:
        reasons.append(
            f"{len(undeclared_projections)} frame(s) carry projected coordinates whose "
            f"projection is not declared, so they cannot be compared with geographic data")
        missing.append(
            "the EPSG code of the projection those easting/northing values are in")

    return HorizontalReference(
        coordinates_present=positioned > 0,
        earth_referenced=earth and not undeclared_projections,
        declared_refs=_distinct(r.code or r.kind.value for r in refs),
        crs_kinds=_distinct(r.kind.value for r in refs),
        crs_provenance=_distinct(
            r.crs_provenance.value if isinstance(r.crs_provenance, CRSProvenance)
            else r.crs_provenance for r in refs),
        positioned_record_count=geographic,
        total_record_count=len(records),
        geo_tie_frames=[f.frame_id for f in frames if getattr(f, "geo_tie", None)],
        reasons=reasons,
        missing=missing,
    )


def build_vertical(frames, assess=None) -> VerticalReference:
    """
    `assess` is `fusion.vertical_reference.assess`, injected so this stays a
    pure function and so a test can drive the assessed states directly rather
    than constructing frames that happen to produce them.
    """
    axes = [(f, getattr(f, "vertical_axis", None)) for f in frames]
    axes = [(f, a) for f, a in axes if a is not None]

    surface = [f for f, a in axes if a.kind == AxisKind.ELEVATION_M]
    # AxisKind.NONE is NOT a subsurface axis -- it is the absence of one.
    # Treating it as subsurface made a 2D surface measurement report that its
    # depth-axis origin was wrong, when it has no depth axis to have an origin.
    subsurface = [(f, a) for f, a in axes
                  if a.kind not in (AxisKind.ELEVATION_M, AxisKind.NONE)]

    depth_frames = [
        (f, a) for f, a in subsurface
        if a.kind == AxisKind.DEPTH_M or (a.kind in _TIME_KINDS and a.conversion)
    ]
    # A depth that came from time via a caller-supplied velocity is DERIVED
    # from an assumption about the ground, and is labelled as such. The test
    # is the PRESENCE OF A CONVERSION, not the axis kind: converters record the
    # result as a depth axis while keeping the conversion that produced it, so
    # keying on kind alone would relabel every derived depth as measured --
    # which is the one distinction this field exists to carry.
    converted = [a for _, a in depth_frames if a.conversion]
    if not depth_frames:
        depth_basis = ProvenanceClass.UNAVAILABLE
    elif converted:
        depth_basis = ProvenanceClass.DERIVED
    else:
        depth_basis = ProvenanceClass.MEASURED

    datums = [
        getattr(a, "vertical_datum", None) for _, a in axes
    ]
    declared_datums = [
        d for d in datums
        if d is not None and d.code and d.provenance != CRSProvenance.NONE
    ]

    reasons: list[str] = []
    missing: list[str] = []
    relationship_kind = None
    absolute = False

    if not subsurface:
        reasons.append("this dataset carries no subsurface vertical axis")
        # NAMED, not merely stated. A surface model on its own is a legitimate
        # dataset and vertical registration is still unavailable for it -- but a
        # blocked capability with an empty `missing` list cannot be acted on,
        # which is the invariant every other branch here maintains. Found by
        # browser verification on a DEM whose horizontal reference was ready.
        missing.append(
            "a subsurface acquisition to register: this dataset is a surface model, "
            "and there is nothing beneath it to place")
    if not surface:
        reasons.append(
            "no surface elevation model is held for this dataset, so there is nothing "
            "for a depth axis to be anchored to")
        missing.append(
            "a surface elevation model (DEM/LiDAR) covering the survey, with a declared "
            "vertical datum")
    elif subsurface and assess is not None:
        # Assessed against the dataset's own surface model. The WEAKEST result
        # across the frames is the dataset's state: one registered line does not
        # register the others.
        results = [assess(f, surface[0]) for f, _ in subsurface]
        absolute = all(r.absolute_elevation_available for r in results)
        weakest = next((r for r in results if not r.absolute_elevation_available), results[0])
        relationship_kind = weakest.kind.value
        reasons.extend(weakest.reasons)
        missing.extend(weakest.missing)

    if not declared_datums:
        reasons.append("no frame declares a vertical datum")
        if not any("vertical datum" in m for m in missing):
            missing.append(
                "a declared vertical datum for the acquisition elevations (the source "
                "states none, so it must be supplied by whoever knows it)")

    # Depth-axis origin. This is the fact that most often surprises people: the
    # GPR time axis starts when the instrument fired, not at the ground.
    origins = _distinct(a.origin for _, a in subsurface)
    ground_origins = [o for o in origins if "ground surface" in o.lower() or "maaiveld" in o.lower()]
    if subsurface and not ground_origins:
        reasons.append(
            f"the depth axis origin is {origins or ['undeclared']}, not the ground "
            f"surface, so depth 0 is not where a surface model is")
        if not any("offset" in m for m in missing):
            missing.append(
                "the offset from the depth-axis origin to the ground surface")

    time_only = [f for f, a in subsurface if a.kind in _TIME_KINDS and not a.conversion]
    if time_only:
        reasons.append(
            f"{len(time_only)} frame(s) carry a measured time axis and no depth: no "
            f"velocity was supplied, so nothing has been placed vertically")
        missing.append("a caller-supplied propagation velocity, to derive depth from time")

    return VerticalReference(
        axis_kinds=_distinct(a.kind.value for _, a in axes),
        axis_units=_distinct(a.units for _, a in axes),
        axis_origins=origins,
        vertical_datum_declared=bool(declared_datums),
        vertical_datums=_distinct(d.code for d in declared_datums),
        depth_axis_available=bool(depth_frames),
        depth_basis=depth_basis,
        # Justified only when a depth axis exists AND its origin is the ground.
        # A velocity alone converts time into a distance; it does not say what
        # that distance is measured from.
        time_to_depth_justified=bool(depth_frames) and bool(ground_origins),
        surface_model_held=bool(surface),
        surface_frame_ids=[f.frame_id for f in surface],
        relationship_kind=relationship_kind,
        absolute_elevation_available=absolute,
        reasons=reasons,
        missing=missing,
    )


def build_geometry(records, frames, bounds=None, spans=None) -> SurveyGeometry:
    """
    `bounds` and `spans` are supplied by the caller, which already computes
    them for `/info` -- passing them in keeps one implementation rather than a
    second one that could disagree about the size of the same survey.
    """
    along_track = along_track_extents_m(records)

    reasons: list[str] = []
    if bounds is None:
        reasons.append(
            "survey bounds need geographic positions; this dataset has none, so no "
            "extent is reported rather than a zero-sized one")
    reasons.append(
        "line spacing, orientation and trajectory are not reported: they are derivable "
        "only from Earth-referenced positions, and computing them otherwise would "
        "describe a survey layout that was never surveyed")

    return SurveyGeometry(
        frame_count=len(frames),
        bounds=bounds,
        lat_span_m=(spans or {}).get("lat_span"),
        lon_span_m=(spans or {}).get("lon_span"),
        along_track_extent_m=along_track,
        reasons=reasons,
    )


#: The frame assumption key `api.spatial._assumption_for` stamps for an
#: operator's `DeclarationKind.TIME_ZERO` declaration (`f"declared_{kind.value}"`,
#: same pattern every other declaration kind uses). Distinct from
#: `TIME_ZERO_ASSUMPTION_KEY`: that one means "a converter recorded a
#: vendor field of unestablished meaning"; this one means "a person
#: declared a correction from evidence" -- different facts, reported
#: differently, never conflated.
DECLARED_TIME_ZERO_KEY = "declared_time_zero"


def _time_zero_claim(frames) -> tuple[Optional[Any], bool]:
    """
    The first frame's time-zero-related assumption, if any, and whether it
    is an operator DECLARATION (True) or an unresolved vendor-field claim
    (False, `TIME_ZERO_ASSUMPTION_KEY`). Declared takes priority when a
    frame somehow carries both, since a human declaration is a stronger
    fact than an unresolved header field about the same axis.
    """
    for f in frames:
        declared = f.assumption(DECLARED_TIME_ZERO_KEY)
        if declared is not None:
            return declared, True
    for f in frames:
        claim = f.assumption(TIME_ZERO_ASSUMPTION_KEY)
        if claim is not None:
            return claim, False
    return None, False


def _time_zero_step(applied: Optional[dict], claim: Optional[Any],
                    claim_is_declared: bool = False) -> SignalProcessingStep:
    """
    ALWAYS RETURNS A STEP -- this is only called once the chain as a whole is
    already known to be `recorded`, and `time_zero` is never omitted from it.

    Reads, in order: (1) `processing_applied`'s own time-zero keys, stamped
    by `preprocessing.time_zero.apply_time_zero_correction` when a
    correction has actually been run against this dataset's records; (2)
    an operator's `DeclarationKind.TIME_ZERO` declaration, recorded but NOT
    YET applied to records (the same non-retroactive contract
    `DeclarationKind.DEPTH_CONVERSION` already has); (3) the survey-frame
    assumption a converter already stamped (GSSI's `rhf_position`,
    recorded but explicitly not applied because its meaning is
    unestablished); (4) otherwise the honest fact that no time-zero
    correction is applied and nothing was recorded about one.
    """
    if applied:
        time_zero_keys = [k for k in applied if k == "time_zero" or k.startswith("time_zero_")]
        if time_zero_keys:
            ran = bool(applied.get("time_zero"))
            parameters = {
                k: v for k, v in applied.items()
                if k != "time_zero" and k.startswith("time_zero_") and v is not None}
            return SignalProcessingStep(step="time_zero", ran=ran, parameters=parameters)

    if claim is not None and claim_is_declared:
        return SignalProcessingStep(
            step="time_zero", ran=False,
            parameters={"time_zero_status": "declared", "time_zero_correction_ns": claim.value},
            reason=(f"declared by an operator ({claim.basis}), not yet applied to this "
                   f"dataset's records"))

    if claim is not None:
        return SignalProcessingStep(
            step="time_zero", ran=False,
            parameters={TIME_ZERO_ASSUMPTION_KEY: claim.value},
            # The converter's own basis already says this was recorded and
            # withheld -- reused verbatim rather than paraphrased.
            reason=claim.basis)

    return SignalProcessingStep(
        step="time_zero", ran=False,
        reason="process_gpr_traces does not apply a time-zero correction, and no "
               "time-zero claim was recorded for this dataset's frames")


def _local_anomaly_step(local_anomaly: Optional[dict]) -> Optional[SignalProcessingStep]:
    """
    `local_anomaly` is the metadata dict of the first record
    `preprocess_trace_local_anomaly` touched, or None -- `anomaly_reliable`
    being present (even `False`) is the presence signal that it ran at all;
    its value says only whether THAT record's cell had enough ring
    neighbours, not whether the step ran.

    Returns None (step omitted entirely) when it never ran -- unlike
    `time_zero`, this is not a property of every GPR record, and a chain
    that ends at `gain` correctly means the stored samples are still
    whatever `process_gpr_traces` left. `reason` reuses
    `schemas.provenance.LOCAL_ANOMALY_BASIS` verbatim -- the same sentence
    the provenance projection gives this quantity, so a viewer reading the
    signal chain and a viewer reading provenance are told the same fact.
    """
    if local_anomaly is None:
        return None
    parameters: dict[str, Any] = {}
    if local_anomaly.get("trace_depth_grid_shape") is not None:
        parameters["trace_depth_grid_shape"] = local_anomaly["trace_depth_grid_shape"]
    return SignalProcessingStep(
        step="local_anomaly", ran=True, parameters=parameters, reason=LOCAL_ANOMALY_BASIS)


def build_signal_chain(
    applied: Optional[dict], frames=None, local_anomaly: Optional[dict] = None,
    recorded_modalities: Optional[list[str]] = None,
) -> SignalProcessingChain:
    """
    `applied` is the `processing_applied` dict already read off a record's
    metadata by the caller (`api.reports._processing_applied`) -- the same
    dict the `preprocessing` `ProcessingStage` reads, so the two cannot
    disagree about what ran. `frames` supplies the survey frames a converter
    may have stamped a time-zero claim onto (see `TIME_ZERO_ASSUMPTION_KEY`).
    `local_anomaly` is the first record's metadata dict carrying
    `anomaly_reliable`, if any (`api.reports._local_anomaly_stamp`).
    `recorded_modalities` is the same sorted list `frame_modalities` /
    `identity.recorded_modalities` already computed for these frames.
    PURE: reads only what is passed in, re-runs nothing, invents nothing.

    THE CHAIN IS A GPR CHAIN. `time_zero` / `background_removal` / `dewow` /
    `gain` are what `process_gpr_traces` does; none of it applies to a LiDAR
    tile or a DEM. When `recorded_modalities` names at least one modality and
    none of them is `gpr`, this returns unrecorded outright -- "preprocessing
    was not recorded" would be the wrong absence for a dataset that was never
    a GPR acquisition, and would read as a logging gap rather than a chain
    that does not apply. An EMPTY composition (no frame records a modality)
    is not this case: that keeps today's ordinary not-recorded behaviour,
    the same as an unset `declared_sensor_type` -- the same rule as slices 1
    and 2, never falling back to the ingest declaration.
    """
    if recorded_modalities and "gpr" not in recorded_modalities:
        return SignalProcessingChain(
            recorded=False,
            reason=(
                f"this dataset's recorded modality composition is "
                f"{', '.join(recorded_modalities)}; the GPR signal-processing chain "
                f"(time-zero, background removal, dewow, gain) does not apply to it"))

    frames = frames or []
    claim, claim_is_declared = _time_zero_claim(frames)
    local_anomaly_step = _local_anomaly_step(local_anomaly)

    if not applied and claim is None and local_anomaly_step is None:
        return SignalProcessingChain(
            recorded=False,
            reason="no record carries a processing_applied entry -- preprocessing "
                   "was not recorded for this dataset")

    time_zero_step = _time_zero_step(applied, claim, claim_is_declared)

    if not applied:
        # Only whichever of a time-zero claim / a local-anomaly stamp exist;
        # process_gpr_traces has not stamped anything, so background
        # removal, dewow and gain have no evidence to report.
        parts = []
        if claim is not None:
            parts.append("a time-zero claim")
        if local_anomaly_step is not None:
            parts.append("a local-anomaly z-score")
        named = " and ".join(parts)
        steps = [time_zero_step]
        if local_anomaly_step is not None:
            steps.append(local_anomaly_step)
        return SignalProcessingChain(
            recorded=True,
            reason=(
                f"{named} {'is' if len(parts) == 1 else 'are'} recorded for this "
                f"dataset; process_gpr_traces has not stamped a processing_applied "
                f"entry, so background removal, dewow and gain are not reported"),
            steps=steps)

    steps = [time_zero_step]
    for name in SIGNAL_CHAIN_STEP_ORDER[1:]:
        ran = bool(applied.get(name))
        parameters: dict[str, Any] = {}
        if ran and name == "dewow" and applied.get("dewow_window") is not None:
            parameters["dewow_window"] = applied["dewow_window"]
        if ran and name == "gain":
            if applied.get("gain_type") is not None:
                parameters["gain_type"] = applied["gain_type"]
            if applied.get("gain_power") is not None:
                parameters["gain_power"] = applied["gain_power"]
        steps.append(SignalProcessingStep(step=name, ran=ran, parameters=parameters))
    if local_anomaly_step is not None:
        steps.append(local_anomaly_step)

    return SignalProcessingChain(
        recorded=True,
        reason="read from the processing_applied entry recorded on this dataset's records",
        steps=steps)


def assess_readiness(
    volume: DatasetVolume,
    horizontal: HorizontalReference,
    vertical: VerticalReference,
    quality: QualityReport,
    candidates: CandidateSummary,
    recorded_modalities: Optional[list[str]] = None,
) -> list[CapabilityAssessment]:
    """
    What Subterra may legitimately do with this dataset right now.

    Read this as a chain: each capability names what it waits on, so a blocked
    3D reconstruction reads as "because the vertical registration is blocked",
    not as an eighth unrelated failure.

    `recorded_modalities` (see `frame_modalities` / `identity.recorded_modalities`)
    only affects `candidate_analysis`: the detector is a GPR-trace detector,
    and a non-empty composition with no `gpr` in it blocks that capability
    outright, regardless of signal or frame count. `signal_processing` is
    deliberately untouched by this -- it means "records carry sample values",
    not "the Phase 5 GPR chain can run", and retargeting it would be a
    different capability's meaning, not a Phase 7 naming fix.
    """
    out: list[CapabilityAssessment] = []

    def add(capability, readiness, reason, missing=None, depends_on=None):
        out.append(CapabilityAssessment(
            capability=capability, readiness=readiness, reason=reason,
            missing=list(missing or []), depends_on=list(depends_on or [])))

    # --- ingestion -------------------------------------------------------
    if volume.record_count > 0:
        add(Capability.INGESTION, Readiness.READY,
            f"{volume.record_count:,} record(s) across {volume.frame_count} frame(s) "
            f"were converted and stored")
    else:
        add(Capability.INGESTION, Readiness.BLOCKED,
            "the dataset holds no records",
            ["a source file that converts to at least one record"])

    # --- validation ------------------------------------------------------
    if quality.computed_score is not None:
        add(Capability.VALIDATION, Readiness.READY,
            "the dataset has been validated and its quality dimensions are reported",
            depends_on=[Capability.INGESTION])
    else:
        add(Capability.VALIDATION, Readiness.BLOCKED,
            "no records are available to validate",
            ["a successful ingestion"], [Capability.INGESTION])

    # --- signal processing -----------------------------------------------
    if volume.records_with_signal == 0:
        add(Capability.SIGNAL_PROCESSING, Readiness.BLOCKED,
            "no record carries a signal, so there is no trace to process",
            ["records carrying sample values"], [Capability.INGESTION])
    elif volume.invalid_signal_count:
        add(Capability.SIGNAL_PROCESSING, Readiness.PARTIAL,
            f"{volume.invalid_signal_count:,} record(s) contain NaN or Inf sample values "
            f"and will not process",
            ["clean sample values for the affected records"], [Capability.INGESTION])
    else:
        add(Capability.SIGNAL_PROCESSING, Readiness.READY,
            f"{volume.records_with_signal:,} record(s) carry sample values",
            depends_on=[Capability.INGESTION])

    # --- horizontal registration -----------------------------------------
    if horizontal.earth_referenced and horizontal.positioned_record_count:
        add(Capability.HORIZONTAL_REGISTRATION, Readiness.READY,
            f"{horizontal.positioned_record_count:,} record(s) carry an Earth-referenced "
            f"position in {', '.join(horizontal.declared_refs) or 'a declared reference'}")
    elif horizontal.coordinates_present:
        add(Capability.HORIZONTAL_REGISTRATION, Readiness.PARTIAL,
            "; ".join(horizontal.reasons) or
            "positions exist but are not sufficient to place the survey on Earth",
            horizontal.missing)
    else:
        add(Capability.HORIZONTAL_REGISTRATION, Readiness.BLOCKED,
            "; ".join(horizontal.reasons) or "no record carries a horizontal position",
            horizontal.missing)

    # --- vertical registration -------------------------------------------
    if vertical.absolute_elevation_available:
        add(Capability.VERTICAL_REGISTRATION, Readiness.READY,
            "both vertical datums are declared and compatible and the depth axis origin "
            "is the ground surface, so an absolute elevation is computable")
    elif vertical.depth_axis_available:
        add(Capability.VERTICAL_REGISTRATION, Readiness.PARTIAL,
            "a depth below the acquisition surface is available, but it cannot be placed "
            "on Earth: " + ("; ".join(vertical.reasons) or "the vertical reference is incomplete"),
            vertical.missing)
    else:
        add(Capability.VERTICAL_REGISTRATION, Readiness.BLOCKED,
            "; ".join(vertical.reasons) or
            "no validated vertical reference or time-to-depth relationship is available",
            vertical.missing)

    # --- candidate analysis ----------------------------------------------
    # A radargram needs a signal and a frame identity; it does not need a
    # position. That is why candidate analysis can be READY on a dataset whose
    # horizontal registration is blocked -- the anomaly is in the trace.
    #
    # The detector is a GPR-trace detector. A non-empty composition that
    # names no `gpr` -- a LiDAR tile, a DEM -- blocks this outright: signal
    # values and a frame identity are not enough, because the capability
    # itself does not apply to those samples. An EMPTY composition is not
    # this case and falls through to the ordinary signal/frame check, the
    # same rule slices 1 and 2 already established.
    if recorded_modalities and "gpr" not in recorded_modalities:
        add(Capability.CANDIDATE_ANALYSIS, Readiness.BLOCKED,
            f"this dataset's recorded modality composition is "
            f"{', '.join(recorded_modalities)}; candidate analysis is a GPR-trace "
            f"capability and does not apply to it",
            ["a GPR acquisition, or frames recording GPR traces"],
            [Capability.SIGNAL_PROCESSING])
    elif volume.records_with_signal and volume.frame_count:
        add(Capability.CANDIDATE_ANALYSIS, Readiness.READY,
            "traces can be reconstructed per frame, which is what candidate analysis "
            "requires; a position is not needed to find an anomaly in a trace"
            + ("" if candidates.analysed else " (not yet run on this dataset)"),
            depends_on=[Capability.SIGNAL_PROCESSING])
    else:
        add(Capability.CANDIDATE_ANALYSIS, Readiness.BLOCKED,
            "candidate analysis needs traces grouped by acquisition frame, and this "
            "dataset provides no such grouping",
            ["records carrying a signal and a frame identity"],
            [Capability.SIGNAL_PROCESSING])

    # --- object classification -------------------------------------------
    # BLOCKED for every dataset, and not because of this dataset. Subterra has
    # no validated classifier: the baseline detector scores at or below chance
    # on both benchmarks, and no model has passed validation. Reporting
    # anything else here would turn candidates into detections, which is the
    # one thing this platform must never do.
    #
    # A non-GPR composition is BLOCKED for a DIFFERENT reason, and the reason
    # has to say so: there is no candidate pipeline here to lack a validated
    # classifier FOR, so "no validated object classifier" -- and especially
    # "candidates describe an anomalous response, not a buried object" --
    # would misname the cause by talking about candidates that were never
    # going to exist for this composition in the first place.
    if recorded_modalities and "gpr" not in recorded_modalities:
        add(Capability.OBJECT_CLASSIFICATION, Readiness.BLOCKED,
            f"this dataset's recorded modality composition is "
            f"{', '.join(recorded_modalities)}; candidate analysis does not apply to "
            f"it, so object classification is not a next step for this dataset",
            ["a GPR acquisition, or frames recording GPR traces"],
            [Capability.CANDIDATE_ANALYSIS])
    else:
        add(Capability.OBJECT_CLASSIFICATION, Readiness.BLOCKED,
            "Subterra has no validated object classifier. Candidates describe the shape of "
            "an anomalous response, not the identity of a buried object, and no model has "
            "been validated to make that step",
            ["a classifier validated against ground truth on a benchmark site"],
            [Capability.CANDIDATE_ANALYSIS])

    # --- 3D reconstruction -----------------------------------------------
    blockers = []
    if not (horizontal.earth_referenced and horizontal.positioned_record_count):
        blockers.append("horizontal registration")
    if not vertical.absolute_elevation_available:
        blockers.append("vertical registration")
    if blockers:
        add(Capability.RECONSTRUCTION_3D, Readiness.BLOCKED,
            "a 3D reconstruction needs every sample placed in one frame with X, Y and Z; "
            f"{' and '.join(blockers)} {'is' if len(blockers) == 1 else 'are'} not "
            f"available for this dataset",
            sorted(set(horizontal.missing + vertical.missing)),
            [Capability.HORIZONTAL_REGISTRATION, Capability.VERTICAL_REGISTRATION])
    else:
        add(Capability.RECONSTRUCTION_3D, Readiness.PARTIAL,
            "horizontal and vertical registration are both available; reconstruction "
            "itself is not yet implemented",
            ["the reconstruction stage (roadmap stage 17)"],
            [Capability.HORIZONTAL_REGISTRATION, Capability.VERTICAL_REGISTRATION])

    return out
