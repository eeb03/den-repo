"""
Assembling a `DatasetReport` from what the platform has stored.

THE SPLIT. `schemas/dataset_report.py` decides what a report MEANS -- what
counts as ready, what counts as missing, what may never be claimed. This module
only fetches: records, frames, labels, the dataset row. Keeping the judgement
out of the I/O is what lets every readiness branch be tested against a
constructed dataset instead of against whichever datasets happen to be in the
corpus, and it is what will let the spatial workflow (stage 8) reuse the same
assessment without going through an HTTP route.

NOTHING HERE RE-RUNS ANALYSIS. A report is a description of what has happened,
not an opportunity to make more of it happen. In particular, candidate
detection is NOT invoked: the summary counts `detector_candidate` labels that a
previous analysis stored. Running a detector inside a GET would make the report
slow, non-deterministic, and would quietly turn "what do we know" into "let me
go and find out", which is a different operation with a different cost.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from database.frames_store import load_frames, synthesize_frames_from_records
from database.labels_store import load_labels
from database.records_store import load_records
from fusion.vertical_reference import assess
from schemas.dataset_report import (
    CandidateSummary,
    DatasetReport,
    ProcessingStage,
    QualityDimension,
    QualityReport,
    SpatialReport,
    assess_readiness,
    build_geometry,
    build_horizontal,
    build_identity,
    build_vertical,
)
from schemas.labels import LabelKind
from schemas.provenance import ProvenanceClass, frame_provenance
from schemas.spatial import has_geographic_coordinates
from validators.dataset_validator import (
    quality_dimensions,
    score_from_dimensions,
)


def _bounds_and_spans(records) -> tuple[Optional[dict], Optional[dict]]:
    """
    Survey extent, from records that actually carry a geographic position.

    A dataset with none reports None rather than a zero-sized survey centred on
    the Gulf of Guinea -- the same rule `/info` follows, and the reason the
    (0, 0) placeholder was removed from the record schema in the first place.
    """
    positioned = [r for r in records if has_geographic_coordinates(r)]
    if not positioned:
        return None, None
    lats = [r.latitude for r in positioned]
    lons = [r.longitude for r in positioned]
    mean_lat = sum(lats) / len(lats)
    bounds = {
        "min_lat": min(lats), "max_lat": max(lats),
        "min_lon": min(lons), "max_lon": max(lons),
    }
    spans = {
        "lat_span": round((max(lats) - min(lats)) * 110540, 1),
        "lon_span": round(
            (max(lons) - min(lons)) * 111320 * math.cos(math.radians(mean_lat)), 1),
    }
    return bounds, spans


def _provenance_completeness(frames) -> QualityDimension:
    """
    How much of what the frames say about themselves is actually vouched for.

    Reported, not scored into the overall number: it measures the DECLARATIONS
    around the data rather than the data, and folding it into a quality score
    that gates dataset search would conflate "poorly documented" with "poorly
    measured". Those need to stay separable, because the first is fixable by
    asking somebody and the second is not.
    """
    entries = [e for f in frames for e in frame_provenance(f)]
    if not entries:
        return QualityDimension(
            name="provenance_completeness", value=None, weight=0.0,
            basis="no survey frame is stored, so nothing declares its own provenance")
    unavailable = sum(1 for e in entries if e.provenance == ProvenanceClass.UNAVAILABLE)
    assumed = sum(1 for e in entries if e.provenance == ProvenanceClass.ASSUMED)
    return QualityDimension(
        name="provenance_completeness",
        value=round(1.0 - unavailable / len(entries), 4),
        weight=0.0,
        basis=("frame-level quantities whose origin is known rather than unavailable; "
               "reported, not scored -- documentation quality is not measurement quality"),
        counts={"quantities": len(entries), "unavailable": unavailable, "assumed": assumed},
    )


def _metadata_completeness(identity) -> QualityDimension:
    """
    How much of the identity block the source actually declared.

    The field set is fixed and listed, so the number means something specific
    rather than being a proportion of whatever happened to be checked.
    """
    fields = {
        "name": identity.name, "source": identity.source, "licence": identity.license,
        "modality": identity.modality, "format": identity.original_format,
        "manufacturer": identity.manufacturer, "device_model": identity.device_model,
        "acquisition_date": identity.collection_date, "checksum": identity.checksum,
    }
    present = sum(1 for v in fields.values() if v)
    return QualityDimension(
        name="metadata_completeness",
        value=round(present / len(fields), 4),
        weight=0.0,
        basis=("declared identity fields out of " + str(len(fields)) + ": "
               + ", ".join(fields) + ". Reported, not scored: undeclared metadata is a "
               "gap in the record, not a defect in the measurement"),
        counts={"declared": present, "checked": len(fields)},
    )


def _signal_quality_placeholder() -> QualityDimension:
    """
    Signal quality is reported as unmeasured, on purpose.

    There is no reference against which a radargram's quality could be scored
    here -- no noise floor, no calibration target, no repeat survey. Emitting a
    number anyway would be inventing a measurement, which is the one thing this
    report exists to prevent. NaN/Inf counts, which ARE measurable, live under
    signal integrity.
    """
    return QualityDimension(
        name="signal_quality", value=None, weight=0.0,
        basis=("not measured: no noise floor, calibration target or repeat survey is "
               "held for this dataset, so any score would be invented. Sample-level "
               "defects are counted under signal_integrity"))


def _processing_stages(dataset, records, frames) -> list[ProcessingStage]:
    """
    What actually happened to this dataset, read from stored evidence.

    Each entry is backed by something the platform recorded. A stage nobody ran
    says `not_run` rather than being omitted, because a missing row and an
    unperformed step look the same in a list and mean different things.
    """
    extra = getattr(dataset, "extra_metadata", None) or {}
    formats = sorted({f.source_format for f in frames if getattr(f, "source_format", None)})
    sample = next((r for r in records if "processing_applied" in (r.metadata or {})), None)
    applied = (sample.metadata or {}).get("processing_applied") if sample else None
    velocity = next(
        (f.vertical_axis.conversion for f in frames
         if getattr(f, "vertical_axis", None) and f.vertical_axis.conversion), None)

    stages = [
        ProcessingStage(
            stage="format_identification",
            status="completed" if formats else "unavailable",
            detail=(", ".join(formats) if formats
                    else "no survey frame records the source format"),
        ),
        ProcessingStage(
            stage="normalisation",
            status="completed" if records else "not_run",
            detail=(f"{len(records):,} record(s) in the common schema"
                    if records else "no records were produced"),
            at=getattr(dataset, "created_at", None),
        ),
        ProcessingStage(
            stage="validation",
            status="completed" if getattr(dataset, "quality_score", None) is not None
            else "not_run",
            detail=(f"quality score {dataset.quality_score}"
                    if getattr(dataset, "quality_score", None) is not None
                    else "the dataset has not been scored"),
        ),
        ProcessingStage(
            stage="preprocessing",
            status="completed" if applied else "not_run",
            detail=(str(applied) if applied
                    else "no record carries a processing_applied entry"),
            parameters={"mode": extra.get("last_preprocessing_mode")}
            if extra.get("last_preprocessing_mode") else {},
        ),
        ProcessingStage(
            stage="time_to_depth_conversion",
            status="completed" if velocity else "not_run",
            detail=("depth derived from the time axis using a caller-supplied velocity; "
                    "an assumption about the ground, not a measurement of it"
                    if velocity else "no velocity has been supplied, so no depth exists"),
            parameters=dict(velocity) if isinstance(velocity, dict) else {},
        ),
        ProcessingStage(
            stage="spatial_registration",
            status="completed" if extra.get("dem_aligned") else "not_run",
            detail=("aligned against a surface model" if extra.get("dem_aligned")
                    else "no surface alignment has been performed"),
        ),
    ]
    return stages


def _candidate_summary(dataset_id: str) -> CandidateSummary:
    """
    Candidates that a previous analysis stored, counted -- never re-detected.

    Reads `detector_candidate` labels only. A `human_interpretation` or a
    `ground_truth` label is a different kind of claim and is deliberately not
    folded in: mixing them is exactly how a benchmark's truth ends up counted
    as a machine's output.
    """
    try:
        label_set = load_labels(dataset_id)
    except Exception:  # noqa: BLE001 -- absent or unreadable label file
        return CandidateSummary()

    candidates = [l for l in getattr(label_set, "labels", [])
                  if l.kind == LabelKind.DETECTOR_CANDIDATE]
    if not candidates:
        return CandidateSummary(analysed=False)

    shape_classes: dict[str, int] = {}
    frames: set[str] = set()
    for label in candidates:
        value = str(label.value) if label.value is not None else "unclassified"
        shape_classes[value] = shape_classes.get(value, 0) + 1
        source_file = getattr(label.target, "source_file", None)
        if source_file:
            frames.add(source_file)

    return CandidateSummary(
        candidate_count=len(candidates),
        analysed=True,
        frames_with_candidates=sorted(frames),
        shape_classes=shape_classes,
        # Every candidate label carries an evidence_ref back to the candidate
        # id, which decodes to the source file, trace range and threshold that
        # produced it. That is the lower half of the evidence chain.
        evidence_available=all(getattr(l, "evidence_ref", None) for l in candidates),
        classified_object_count=0,
    )


def build_dataset_report(dataset, *, now: Optional[datetime] = None) -> DatasetReport:
    """
    The one place a report is produced. Everything it needs is loaded here and
    judged in `schemas/dataset_report.py`.
    """
    dataset_id = dataset.id
    records = load_records(dataset_id)
    frames = load_frames(dataset_id) or (
        synthesize_frames_from_records(records) if records else [])

    identity = build_identity(dataset, frames)
    from schemas.dataset_report import build_volume

    volume = build_volume(records, frames)
    horizontal = build_horizontal(records, frames)
    # `assess` is injected rather than imported inside the schema module, so
    # the judgement stays testable and the dependency stays one-way.
    vertical = build_vertical(frames, assess=assess)
    bounds, spans = _bounds_and_spans(records)
    geometry = build_geometry(records, frames, bounds=bounds, spans=spans)

    scored = quality_dimensions(records)
    computed = score_from_dimensions(scored) if scored else None
    stored = getattr(dataset, "quality_score", None)
    dimensions = scored + [
        _signal_quality_placeholder(),
        _metadata_completeness(identity),
        _provenance_completeness(frames),
    ]
    quality = QualityReport(
        stored_score=stored,
        computed_score=computed,
        dimensions=dimensions,
        # A difference means the dataset changed after it was scored. Worth
        # surfacing: the stored score is what dataset search filters on.
        score_is_stale=(
            stored is not None and computed is not None
            and abs(stored - computed) > 1e-6),
    )

    candidates = _candidate_summary(dataset_id)

    return DatasetReport(
        generated_at=now or datetime.utcnow(),
        identity=identity,
        volume=volume,
        spatial=SpatialReport(horizontal=horizontal, vertical=vertical, geometry=geometry),
        processing=_processing_stages(dataset, records, frames),
        quality=quality,
        candidates=candidates,
        readiness=assess_readiness(volume, horizontal, vertical, quality, candidates),
        provenance=[e for f in frames for e in frame_provenance(f)],
    )
