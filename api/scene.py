"""
Assembling a `ScenePayload` for one dataset.

THE SPLIT, same shape as `api/reports.py`: `schemas.scene` decides what a
scene payload MEANS and performs the one piece of arithmetic
(`compute_absolute_elevation`) this whole feature needed; this module only
fetches -- frames, the stored candidate set, records for a surface sample --
and hands what it finds to `schemas.views._scene_3d`/
`fusion.vertical_reference.assess`, which already decide whether a scene may
be shown at all. No detector runs here, no new position is invented, and no
dataset that hasn't cleared `assess` on its own gets a scene anyway.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from api import candidates as candidate_service
from database.frames_store import frames_by_id, load_frames_for
from database.records_store import load_records
from fusion import vertical_reference as vr
from interpretation.candidate_intelligence import LocalisationCertainty
from interpretation.spatial_evidence import find_spatial_evidence_samples
from schemas.scene import (
    MAX_EVIDENCE_SAMPLES,
    MAX_SURFACE_POINTS,
    SceneCandidate,
    SceneElevation,
    SceneEvidenceField,
    SceneEvidenceSample,
    ScenePayload,
    ScenePosition,
    SceneSurface,
    SceneSurfacePoint,
    SceneVerticalRelationship,
    compute_absolute_elevation,
)
from schemas.spatial import AxisKind, has_geographic_coordinates
from schemas.survey_frame import make_frame_id


def _find_surface_frame(frames):
    """The first frame whose vertical axis IS an elevation -- a DEM/LiDAR tile."""
    return next((f for f in frames
                if getattr(f.vertical_axis, "kind", None) == AxisKind.ELEVATION_M), None)


def _find_subsurface_frame(frames):
    """
    The first frame whose vertical axis is a depth or a measured time --
    the kind `fusion.vertical_reference.assess` treats as the thing needing
    a vertical relationship. Deliberately not GPR-specific: a magnetometer
    or seismic depth axis asks the same question.
    """
    depth_ish = {AxisKind.DEPTH_M, AxisKind.TWO_WAY_TIME_NS,
                AxisKind.TWO_WAY_TIME_MS, AxisKind.TWO_WAY_TIME_S}
    return next((f for f in frames if getattr(f.vertical_axis, "kind", None) in depth_ish), None)


def _surface_points(dataset_id: str, frame_id: str) -> tuple[list[SceneSurfacePoint], int, bool]:
    """
    A bounded sample of the surface frame's positioned records.

    Evenly strided rather than the first N, so a downsample of a survey
    still covers its extent instead of showing only one corner.
    """
    # Frames are not (yet) stamped onto individual records for every
    # converter, so this dataset-level surface sample uses every positioned
    # record in the dataset rather than filtering by frame_id -- correct
    # today because a surface dataset holds exactly one frame in every case
    # this feature was built against, and never silently wrong: a dataset
    # with more than one frame simply mixes their points into one surface
    # sample, which a human reviewing the render would notice. `frame_id`
    # is accepted as a parameter so that filtering can be added the moment
    # per-record frame stamping exists, without changing this function's
    # signature or its caller.
    records = load_records(dataset_id)
    positioned = [r for r in records if has_geographic_coordinates(r) and r.elevation is not None]
    total = len(positioned)
    if total == 0:
        return [], 0, False
    if total <= MAX_SURFACE_POINTS:
        sample = positioned
        downsampled = False
    else:
        stride = total / MAX_SURFACE_POINTS
        sample = [positioned[int(i * stride)] for i in range(MAX_SURFACE_POINTS)]
        downsampled = True
    points = [SceneSurfacePoint(lat=r.latitude, lon=r.longitude, elevation_m=r.elevation)
             for r in sample]
    return points, total, downsampled


def _evidence_field(dataset_id: str, offset, radargram_url: str,
                    frames: Optional[dict] = None) -> SceneEvidenceField:
    """
    Stage A: every individually positioned measurement above the anomaly
    threshold, distinct from `candidates` (grouped, classified regions).
    Reuses `compute_absolute_elevation` exactly as the candidate loop below
    does -- the same arithmetic, the same declared offset, applied per
    measurement instead of per cluster mean.

    `frames` (frame_id -> SurveyFrame) is Stage A.1: it lets a record with a
    declared, transformable PROJECTED position also qualify, through the
    same `fusion.sensor_fusion.geographic_views` fusion itself calls.
    """
    records = load_records(dataset_id)
    result = find_spatial_evidence_samples(records, frames=frames)

    scene_samples: list[SceneEvidenceSample] = []
    for s in result.samples:
        position = ScenePosition(
            available=True, lat=s.lat, lon=s.lon,
            basis=s.localisation, reason=s.localisation_reason,
        )
        if s.surface_elevation_m is not None:
            elevation_m = compute_absolute_elevation(s.surface_elevation_m, s.depth_m, offset)
            elevation = SceneElevation(
                available=True, elevation_m=elevation_m, depth_m=s.depth_m,
                depth_certainty=s.depth_certainty,
                provenance=(
                    "derived: surface elevation (from this dataset's DEM alignment) minus "
                    "depth" + (", adjusted by the declared axis-origin offset" if
                              offset is not None and offset.relates_the_depth_axis else "")),
                reason="computed from a declared/derived surface elevation and depth",
            )
        else:
            elevation = SceneElevation(
                available=False, depth_m=s.depth_m, depth_certainty=s.depth_certainty,
                provenance="unavailable",
                reason=(
                    "this measurement was never aligned with a DEM surface, so no surface "
                    "elevation exists at its location"),
            )
        scene_samples.append(SceneEvidenceSample(
            source_file=s.source_file, trace_index=s.trace_index, depth_m=s.depth_m,
            evidence_value=s.evidence_value, reliable=s.reliable,
            position=position, elevation=elevation, evidence_reference=radargram_url,
        ))

    total = len(scene_samples)
    downsampled = False
    if total > MAX_EVIDENCE_SAMPLES:
        stride = total / MAX_EVIDENCE_SAMPLES
        scene_samples = [scene_samples[int(i * stride)] for i in range(MAX_EVIDENCE_SAMPLES)]
        downsampled = True

    return SceneEvidenceField(
        samples=scene_samples,
        threshold=result.threshold,
        point_count_total=total,
        downsampled=downsampled,
        excluded_unpositioned_count=result.excluded_unpositioned_count,
        reason=result.reason_if_empty,
    )


def build_scene(db: Session, dataset_id: str,
                surface_dataset_id: Optional[str] = None) -> ScenePayload:
    """
    Builds the scene payload for `dataset_id`.

    `surface_dataset_id`, when given, looks for the surface frame in a
    SEPARATE dataset -- the real shape of GPR + DEM in this platform, which
    are ingested as two datasets and related through the same fusion
    machinery `/api/fusion/*` already uses (`load_frames_for` is the
    function fusion itself calls to read frames across dataset ids).
    Omitted, the surface is looked for within `dataset_id` itself.
    """
    dataset_ids = [dataset_id] + ([surface_dataset_id] if surface_dataset_id else [])
    frames = load_frames_for(dataset_ids)

    surface_frame = _find_surface_frame(frames)
    subsurface_frame = _find_subsurface_frame(frames)

    diagnostic_views = {
        "report": f"/datasets/{dataset_id}/report",
        "radargram": f"/datasets/{dataset_id}/radargram",
        "spatial": f"/datasets/{dataset_id}/spatial",
    }

    if subsurface_frame is None or surface_frame is None:
        missing = []
        if subsurface_frame is None:
            missing.append("a frame with a depth or time axis in this dataset")
        if surface_frame is None:
            missing.append(
                "a frame with an elevation axis (a DEM/LiDAR surface), in this dataset "
                "or in surface_dataset_id")
        return ScenePayload(
            dataset_id=dataset_id, resolved=False,
            resolution_reason=(
                "a reconstructed scene needs both a subsurface (depth/time) frame and a "
                "surface (elevation) frame; " + " and ".join(missing) + " is missing"),
            missing=missing, diagnostic_views=diagnostic_views,
        )

    rel = vr.assess(subsurface_frame, surface_frame)
    vertical_relationship = SceneVerticalRelationship(
        kind=rel.kind, subsurface_frame_id=rel.subsurface_frame_id,
        surface_frame_id=rel.surface_frame_id, reasons=rel.reasons, missing=rel.missing,
    )
    resolved = rel.absolute_elevation_available

    if not resolved:
        return ScenePayload(
            dataset_id=dataset_id, resolved=False,
            resolution_reason=rel.describe(),
            missing=rel.missing,
            vertical_relationship=vertical_relationship,
            diagnostic_views=diagnostic_views,
        )

    surface_points, total_points, downsampled = _surface_points(
        surface_dataset_id or dataset_id, surface_frame.frame_id)
    surface = SceneSurface(
        frame_id=surface_frame.frame_id,
        dataset_id=surface_dataset_id or dataset_id,
        modality=surface_frame.modality.value,
        vertical_datum_code=getattr(surface_frame.vertical_axis.vertical_datum, "code", None),
        vertical_datum_provenance=(
            surface_frame.vertical_axis.vertical_datum.provenance.value
            if surface_frame.vertical_axis.vertical_datum else None),
        points=surface_points, point_count_total=total_points, downsampled=downsampled,
    )

    offset = subsurface_frame.vertical_axis.origin_offset
    intelligence = candidate_service.current(db, dataset_id)
    scene_candidates: list[SceneCandidate] = []
    # `status` is lower-case ("available" | "limited" | "blocked") in
    # interpretation.candidate_intelligence -- both non-blocked states carry
    # real candidates, "limited" only means the set may be stale, which is
    # a staleness question for the candidate view, not a reason to hide the
    # candidates from a scene that is otherwise resolved.
    if intelligence.status in ("available", "limited"):
        for ic in intelligence.candidates:
            cand = ic.candidate
            lat, lon = cand.characteristics.centroid_lat, cand.characteristics.centroid_lon
            has_position = lat is not None and lon is not None
            position = ScenePosition(
                available=has_position, lat=lat, lon=lon, basis=ic.localisation,
                reason=(ic.localisation_basis if has_position else
                       "this candidate's supporting traces carry no geographic position"),
            )

            surface_elev = cand.characteristics.centroid_elevation_m
            depth_mid = (cand.evidence.depth_range[0] + cand.evidence.depth_range[1]) / 2.0
            if surface_elev is not None:
                elevation_m = compute_absolute_elevation(surface_elev, depth_mid, offset)
                elevation = SceneElevation(
                    available=True, elevation_m=elevation_m, depth_m=depth_mid,
                    depth_certainty=ic.depth,
                    provenance=(
                        "derived: surface elevation (from this dataset's DEM alignment) minus "
                        "depth" + (", adjusted by the declared axis-origin offset" if
                                  offset is not None and offset.relates_the_depth_axis else "")),
                    reason="computed from a declared/derived surface elevation and depth",
                )
            else:
                elevation = SceneElevation(
                    available=False, depth_m=depth_mid, depth_certainty=ic.depth,
                    provenance="unavailable",
                    reason=(
                        "this candidate's records were never aligned with a DEM surface, so "
                        "no surface elevation exists at its location"),
                )

            scene_candidates.append(SceneCandidate(
                id=cand.id, position=position, elevation=elevation,
                score=ic.candidate_score, score_meaning=ic.candidate_score_meaning,
                anomaly_class=cand.interpretation.anomaly_class, note=cand.interpretation.note,
                source_file=cand.evidence.source_file, trace_range=cand.evidence.trace_range,
                depth_range=cand.evidence.depth_range,
                evidence_reference=diagnostic_views["radargram"],
            ))

    evidence = _evidence_field(dataset_id, offset, diagnostic_views["radargram"],
                               frames=frames_by_id(frames))

    return ScenePayload(
        dataset_id=dataset_id, resolved=True,
        vertical_relationship=vertical_relationship,
        surface=surface, candidates=scene_candidates, evidence=evidence,
        diagnostic_views=diagnostic_views,
    )
