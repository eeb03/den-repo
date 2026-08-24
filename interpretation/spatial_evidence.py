"""
Every individual (trace, depth) measurement whose processed signal already
cleared the same anomaly-evidence threshold `interpretation.anomaly_candidates`
uses for clustering -- exposed as its own point, with its own position and
its own value. No grouping, no interpolation, no invented position.

THIS IS NOT CANDIDATE GENERATION. `anomaly_candidates.find_anomaly_candidates`
groups adjacent evidence into connected components and reduces each one to a
bounding box plus summary statistics -- the real per-cell shape is computed
and then discarded. This module does the opposite: every measurement that
clears the threshold stays exactly what it is, a single positioned sample,
so a 3D scene can show the evidence landscape a candidate set already
throws away on the way to becoming a handful of spheres.

Reuses the SAME threshold and the SAME z-score `preprocess_trace_local_anomaly`
already wrote onto `record.signal` -- there is no second detector here, and
no grid is built: unlike candidate generation, nothing here needs to know
which cells are adjacent, so each record is read on its own.

SCIENTIFIC FRAMING (do not weaken this when extending the module):
- A sample with no real geographic position is never placed in 3D space.
  `LocalisationCertainty.TRACE_RELATIVE` ("locatable as trace N of file X")
  is a real, useful answer -- and it is not a coordinate. Only
  `SPATIALLY_REGISTERED` samples become spatial evidence; everything else is
  counted as excluded, never guessed at.
- Depth is DERIVED whenever a propagation velocity produced it (the same
  rule `interpretation.candidate_intelligence.depth_of` already applies to
  candidates), UNAVAILABLE otherwise. Nothing here computes or assumes a
  velocity; it only reads whether one was already recorded.
- `reliable` surfaces `metadata["anomaly_reliable"]` verbatim -- an existing
  signal (too few ring neighbours near a trace/depth edge), not a new one.

STAGE A.1 -- REPROJECTED (not just native) POSITIONS. A record whose native
position is PROJECTED and whose frame DECLARES a transformable CRS can also
become spatial evidence: pass `frames` and `fusion.sensor_fusion.
geographic_views` (the SAME function fusion already uses for clustering) is
consulted for a WGS84 view of it. This is deliberately the identical
function, not a second transform implementation, and it is read-only: the
record's own `position`/`latitude`/`longitude` are never written to, and
`schemas.spatial.has_geographic_coordinates` -- used everywhere else in this
codebase -- keeps reporting exactly what it always has. A declared CRS is not
a reprojection, and a reprojection is not a validated geodetic position:
`localisation_reason` says which of the three applies for every sample, and
`has_geographic_coordinates(r)` is still False for these records, on
purpose -- only THIS evidence path additionally accepts a mathematically
transformed coordinate, and it says so on every sample that used one.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from fusion.sensor_fusion import geographic_views
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD
from interpretation.candidate_intelligence import DepthCertainty, LocalisationCertainty
from preprocessing.spatial_grid import _group_by_source_file
from schemas.spatial import has_geographic_coordinates
from schemas.subterra_record import SubterraRecord
from schemas.survey_frame import SurveyFrame


class RawEvidenceSample(BaseModel):
    """
    One measurement whose evidence value exceeded the threshold, already
    classified -- the interpretation layer decides WHAT this sample is;
    `api/scene.py` only shapes it into a response, exactly as it already
    does for candidates (`ic.localisation`/`ic.depth`, computed once here,
    never re-derived downstream).
    """
    source_file: str
    trace_index: int
    depth_m: float
    evidence_value: float
    reliable: bool
    localisation: LocalisationCertainty
    localisation_reason: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    #: DEM-aligned surface elevation at this exact record, if this dataset
    #: has been DEM-aligned -- the raw ingredient `compute_absolute_elevation`
    #: needs. Absolute elevation arithmetic happens in `api/scene.py`, using
    #: the same function and the same declared offset candidates already use.
    surface_elevation_m: Optional[float] = None
    depth_certainty: DepthCertainty
    depth_certainty_reason: str


class SpatialEvidenceResult(BaseModel):
    """
    Everything a caller needs to report honestly on why the evidence field
    looks the way it does, not just the samples themselves.
    """
    samples: list[RawEvidenceSample]
    threshold: float
    n_records_considered: int          # trace-addressable records with anomaly preprocessing applied
    n_above_threshold: int             # before position filtering
    excluded_unpositioned_count: int   # above threshold, but no real geographic position
    reason_if_empty: Optional[str] = None


def _localisation_of_record(
    r: SubterraRecord, views: dict[int, tuple[float, float]],
) -> tuple[LocalisationCertainty, str]:
    """
    Per-record counterpart to `candidate_intelligence.localisation_of` --
    same vocabulary, same reasoning, applied to one measurement instead of a
    cluster's aggregated characteristics.

    `views` is `fusion.sensor_fusion.geographic_views(records, frames)`,
    computed once by the caller: a record present in it has a genuine WGS84
    coordinate, whether that came from its own native geographic position or
    from mathematically transforming a declared PROJECTED one. The reason
    string says which, because the two are not the same claim.
    """
    if has_geographic_coordinates(r):
        return (LocalisationCertainty.SPATIALLY_REGISTERED,
                "this measurement carries a geographic position")
    if id(r) in views:
        return (LocalisationCertainty.SPATIALLY_REGISTERED,
                "this measurement's position was obtained by transforming its declared "
                "PROJECTED coordinate to WGS84 using the frame's declared coordinate "
                "reference system; this is a coordinate transform of a declaration, not "
                "an independently verified geodetic position")
    kind = getattr(r.position, "kind", None)
    if kind == "odometry":
        return (LocalisationCertainty.FRAME_RELATIVE,
                "along-track distance is measured, but no geographic position is available")
    source_file = r.metadata.get("source_file")
    trace_index = r.metadata.get("trace_index")
    if source_file is not None and trace_index is not None:
        return (LocalisationCertainty.TRACE_RELATIVE,
                f"locatable as trace {trace_index} of {source_file}")
    return (LocalisationCertainty.UNKNOWN, "no defensible location exists for this measurement")


def _depth_of_record(r: SubterraRecord) -> tuple[DepthCertainty, str]:
    """Per-record counterpart to `candidate_intelligence.depth_of`."""
    v = r.metadata.get("velocity_m_per_ns")
    if v is None:
        return (DepthCertainty.UNAVAILABLE,
                "no propagation velocity has been declared for this dataset, so this "
                "measurement's position on the instrument axis is not a physical depth")
    return (DepthCertainty.DERIVED,
            f"converted from the time axis using a declared velocity of {v} m/ns, "
            "which is an assumption about this ground and not a measurement")


def find_spatial_evidence_samples(
    records: list[SubterraRecord],
    threshold: float = DEFAULT_ANOMALY_THRESHOLD,
    frames: Optional[dict[str, SurveyFrame]] = None,
) -> SpatialEvidenceResult:
    """
    Every (trace, depth) measurement across all of a dataset's survey lines
    whose z-score magnitude exceeds `threshold` -- the exact test
    `interpretation.anomaly_candidates.find_anomaly_candidates` applies
    before clustering, applied here with no clustering step at all.

    Requires trace-local anomaly preprocessing (`preprocessing_mode=
    'gpr_local_anomaly'`) to have already run: that step is what writes the
    z-score onto `record.signal` and stamps `metadata["anomaly_reliable"]`.
    A record without that stamp carries an ordinary physical signal value,
    not evidence, and is not considered here -- reading it as if it were a
    z-score would silently misinterpret physical units as statistical ones,
    the same failure `anomaly_candidates._require_anomaly_processed` guards
    against.

    `frames` (frame_id -> SurveyFrame), when given, lets a record whose
    native position is PROJECTED but whose frame declares a transformable
    CRS also qualify, via `fusion.sensor_fusion.geographic_views` -- the
    same function fusion already uses, called here rather than duplicated.
    Omitted, behaviour is identical to before Stage A.1: only natively
    geographic (or GeoTie-registered) positions qualify.
    """
    by_file = _group_by_source_file(records)

    processed: list[SubterraRecord] = []
    for source_file, sub_records in by_file.items():
        if not source_file:
            continue
        if any(r.metadata.get("trace_index") is None or r.depth is None for r in sub_records):
            continue
        if any(r.metadata.get("anomaly_reliable") is None for r in sub_records):
            continue
        processed.extend(sub_records)

    if not processed:
        has_trace_addressable = any(
            r.metadata.get("trace_index") is not None and r.depth is not None for r in records
        )
        reason = (
            "trace-local anomaly preprocessing has not been run on this dataset yet "
            "(preprocessing_mode='gpr_local_anomaly')"
            if has_trace_addressable else
            "this dataset carries no genuine multi-sample GPR trace data "
            "(no trace_index/depth metadata)"
        )
        return SpatialEvidenceResult(
            samples=[], threshold=threshold, n_records_considered=0,
            n_above_threshold=0, excluded_unpositioned_count=0, reason_if_empty=reason,
        )

    above_threshold = [r for r in processed if r.signal and abs(r.signal[0]) > threshold]

    # Read-only, exactly as fusion computes it: `views` never touches
    # `r.position`/`r.latitude`/`r.longitude`, and the raw stored coordinate
    # remains exactly what it was, recoverable, whether or not this record
    # ends up in `views`.
    views = geographic_views(above_threshold, frames)

    samples: list[RawEvidenceSample] = []
    excluded_unpositioned = 0
    for r in above_threshold:
        localisation, localisation_reason = _localisation_of_record(r, views)
        if localisation != LocalisationCertainty.SPATIALLY_REGISTERED:
            excluded_unpositioned += 1
            continue
        depth_certainty, depth_reason = _depth_of_record(r)
        lat, lon = views.get(id(r), (r.latitude, r.longitude))
        samples.append(RawEvidenceSample(
            source_file=r.metadata.get("source_file", ""),
            trace_index=r.metadata["trace_index"],
            depth_m=r.depth,
            evidence_value=r.signal[0],
            reliable=bool(r.metadata.get("anomaly_reliable")),
            localisation=localisation,
            localisation_reason=localisation_reason,
            lat=lat,
            lon=lon,
            surface_elevation_m=r.elevation,
            depth_certainty=depth_certainty,
            depth_certainty_reason=depth_reason,
        ))

    reason_if_empty = None
    if not samples:
        if not above_threshold:
            reason_if_empty = (
                f"no measurement exceeded the anomaly evidence threshold (|z| > {threshold})"
            )
        else:
            reason_if_empty = (
                "no measurement with evidence above threshold carries a usable geographic "
                "position"
            )

    return SpatialEvidenceResult(
        samples=samples,
        threshold=threshold,
        n_records_considered=len(processed),
        n_above_threshold=len(above_threshold),
        excluded_unpositioned_count=excluded_unpositioned,
        reason_if_empty=reason_if_empty,
    )
