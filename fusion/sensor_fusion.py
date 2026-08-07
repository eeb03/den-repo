"""
Sensor Fusion Module: detects datasets collected over the same location
and combines their records into one multimodal training sample.

Distance uses the haversine formula (meters). The matching radius is
configurable via settings.fusion_spatial_tolerance_m — this is the single
knob that trades off "more fusion samples" against "more spatial precision".

SPATIAL PARTITIONING. Records are grouped by the KIND of position they
carry before any distance is computed, because a distance between two
different kinds of position is meaningless. This matters concretely: an
un-georeferenced GPR line, an odometry-positioned cart run, and a projected
survey all carry latitude/longitude 0.0 as their legacy placeholder, so
bucketing on those values put every one of them in the same cell off the
coast of Africa and fused them as if they were collected at one spot.

Records fuse when a real WGS84 coordinate can be obtained for them. That is
true natively for a geographic position, and also for a PROJECTED one whose
frame DECLARES a CRS -- pass `frames` and those are reprojected for
clustering. Without frames, or without a declared CRS, they are not: a
projected pair with no declared system is two numbers of unknown meaning.

Everything else is reported as non-fusable WITH THE REASON rather than
silently dropped or silently merged. An odometry frame has no relationship
to a geographic one until someone supplies a GeoTie, and inventing that
relationship is the failure mode this partitioning exists to prevent.

Reprojection here is READ-ONLY: records are never mutated, and the derived
coordinates exist only for the duration of the clustering. Each sample
records how many of its members were reprojected, so a cluster built partly
from transformed coordinates never looks like one built from measured ones.
"""
import math
from dataclasses import dataclass, field
from typing import Optional

from converters.base import MissingDependencyError
from ingestion.crs_transform import CRSTransformError, is_transformable, to_wgs84
from schemas.spatial import (
    PositionKind, effective_position, has_geographic_coordinates,
)
from schemas.subterra_record import SubterraRecord, SensorType
from configs.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1, math.sqrt(a)))


#: Position kinds that can be compared with a real-world distance. Everything
#: else needs an external tie before it means anything geographically.
FUSABLE_POSITION_KINDS = {"geographic"}

#: Why each non-fusable kind is excluded, reported rather than assumed.
NON_FUSABLE_REASONS = {
    "projected": (
        "projected easting/northing whose frame declares no CRS: two projected frames "
        "cannot be compared without knowing what projection each is in. Supply the "
        "frame (and a declared CRS on it) and these are reprojected to WGS84 and fused"
    ),
    "local_cartesian": (
        "site-local cartesian coordinates have no defined relationship to any other frame"
    ),
    "odometry": (
        "along-track distance locates a trace on its own line only; it says nothing about "
        "where that line is relative to anything else"
    ),
    "none": "no horizontal position",
}


def geographic_views(records: list, frames: dict | None = None) -> dict[int, tuple]:
    """
    WGS84 (lat, lon) for each record that genuinely has one, keyed by id().

    Three routes, in order, and no fourth:
      1. the effective position is already geographic -- native, or placed on
         Earth by a GeoTie registration
      2. it is PROJECTED and its frame DECLARES a CRS -> reprojected here
      3. otherwise absent from the result

    Nothing is inferred. A projected record whose frame declares no CRS is
    absent however plausible its numbers look, because a coordinate pair
    without a system is two numbers of unknown meaning.

    Grouped by CRS and transformed in one call per system: PROJ setup
    dominates a per-point transform, and the INGV archive is millions of
    records. A CRS that fails to transform loses only its own group.
    """
    views: dict[int, tuple] = {}
    by_crs: dict[str, list[tuple]] = {}

    for r in records:
        if has_geographic_coordinates(r):
            pos = effective_position(r)
            views[id(r)] = (pos.lat, pos.lon)
            continue
        if not frames:
            continue
        pos = effective_position(r)
        if pos is None or pos.kind != PositionKind.PROJECTED:
            continue
        frame = frames.get(getattr(r, "frame_id", None))
        code = getattr(getattr(frame, "spatial_ref", None), "code", None)
        if not is_transformable(code):
            continue
        by_crs.setdefault(code, []).append((id(r), pos.easting, pos.northing))

    for code, items in by_crs.items():
        try:
            transformed = to_wgs84(code, [e for _, e, _ in items], [n for _, _, n in items])
        except (CRSTransformError, MissingDependencyError) as e:
            logger.warning(
                f"Fusion: {len(items)} record(s) declared {code} but could not be "
                f"reprojected ({e}); they are excluded rather than placed approximately."
            )
            continue
        logger.info(
            f"Fusion: reprojected {len(items)} record(s) from {code} to WGS84 for "
            f"clustering. These coordinates are DERIVED from a declared CRS, not measured."
        )
        for (rid, _, _), latlon in zip(items, transformed):
            views[rid] = latlon
    return views


def geographic_view(record, frames: dict | None = None) -> tuple | None:
    """WGS84 (lat, lon) for one record, or None. See `geographic_views`."""
    return geographic_views([record], frames).get(id(record))


@dataclass
class SpatialPartition:
    """One group of records whose positions are mutually comparable."""
    kind: str
    records: list = field(default_factory=list)
    fusable: bool = False
    reason: str | None = None

    @property
    def dataset_ids(self) -> list[str]:
        return sorted({r.dataset_id for r in self.records})

    @property
    def sensor_types(self) -> list[str]:
        return sorted({r.sensor_type.value for r in self.records})


def partition_by_spatial_ref(records: list[SubterraRecord],
                             frames: list | None = None,
                             views: dict | None = None) -> list[SpatialPartition]:
    """
    Groups records by position kind, marking which groups can be fused.

    Partitioning happens BEFORE any distance is computed. Mixing kinds and
    then measuring between them is how placeholder coordinates turn into
    false co-location.
    """
    if views is None:
        views = geographic_views(records, {f.frame_id: f for f in (frames or [])})
    by_kind: dict[str, list[SubterraRecord]] = {}
    for r in records:
        # A record counts as geographic when a real WGS84 coordinate can be
        # obtained for it -- natively, via a GeoTie registration, or by
        # reprojecting a projected position whose frame declares a CRS.
        if id(r) in views:
            kind = "geographic"
        else:
            kind = str(getattr(getattr(r, "position", None), "kind", None) or "none")
        by_kind.setdefault(kind, []).append(r)

    partitions = []
    for kind, recs in sorted(by_kind.items()):
        fusable = kind in FUSABLE_POSITION_KINDS
        partitions.append(SpatialPartition(
            kind=kind, records=recs, fusable=fusable,
            reason=None if fusable else NON_FUSABLE_REASONS.get(kind, "unknown position kind"),
        ))
    return partitions


@dataclass
class FusionSample:
    """
    One cluster of co-located records, with a centre expressed in the frame
    it was clustered in.

    center_lat/center_lon are Optional because a sample clustered in a
    non-geographic frame genuinely has no latitude. Giving it one to satisfy
    a NOT NULL column is how a placeholder gets back in.
    """
    radius_m: float
    spatial_ref_kind: str = "geographic"
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    center_x: Optional[float] = None
    center_y: Optional[float] = None
    #: How many members reached this centre through a CRS transform rather
    #: than carrying a geographic coordinate of their own. Non-zero means the
    #: centre is only as good as the declared CRS it was computed from.
    n_reprojected: int = 0
    records_by_sensor: dict[str, list[SubterraRecord]] = field(default_factory=dict)

    @property
    def has_geographic_centre(self) -> bool:
        return self.center_lat is not None and self.center_lon is not None

    @property
    def sensor_types(self) -> list[str]:
        return list(self.records_by_sensor.keys())

    @property
    def dataset_ids(self) -> list[str]:
        ids = set()
        for recs in self.records_by_sensor.values():
            ids.update(r.dataset_id for r in recs)
        return sorted(ids)

    @property
    def has_ground_truth(self) -> bool:
        return any(
            r.ground_truth.value != "none"
            for recs in self.records_by_sensor.values()
            for r in recs
        )


def fuse_datasets(
    records: list[SubterraRecord],
    radius_m: float | None = None,
    frames: list | None = None,
) -> list[FusionSample]:
    """
    Cluster records from different sensor types into fusion samples using a
    simple greedy spatial clustering (grid-bucketed for tractability on
    large record sets). Records from the *same* sensor type at the same
    spot are kept together rather than exploding into separate samples.

    ONLY records for which a real WGS84 coordinate exists take part. That
    covers geographic positions, GeoTie-registered ones, and -- when `frames`
    is supplied -- PROJECTED ones whose frame declares a CRS, which are
    reprojected so a projected survey and a geographic one over the same
    ground finally cluster together.

    Anything else -- odometry, a projected frame with no declared CRS, no
    position at all -- is excluded and logged; see `non_fusable_partitions`
    to enumerate them. Fusing those would require inventing a spatial
    relationship that does not exist in the data.

    REPROJECTION IS READ-ONLY. Records are never mutated; the derived
    coordinates live only as long as the clustering. Each sample reports how
    many of its members were reprojected, so a cluster assembled from
    transformed coordinates never passes for one assembled from measured
    ones.
    """
    radius_m = radius_m or settings.fusion_spatial_tolerance_m
    if not records:
        return []

    # Partition by position kind FIRST. Without this, every record carrying the
    # legacy (0.0, 0.0) placeholder -- odometry runs, un-georeferenced lines,
    # projected surveys -- lands in one bucket at null island and fuses as if
    # co-located.
    frames_by_id = {f.frame_id: f for f in (frames or [])}
    views = geographic_views(records, frames_by_id)
    partitions = partition_by_spatial_ref(records, views=views)
    fusable = [p for p in partitions if p.fusable]
    excluded = [p for p in partitions if not p.fusable]
    for p in excluded:
        logger.info(
            f"Fusion: excluding {len(p.records)} record(s) with position kind "
            f"'{p.kind}' -- {p.reason}"
        )
    geographic = [r for p in fusable for r in p.records]
    if not geographic:
        logger.warning(
            f"Fusion: none of the {len(records)} record(s) carry a geographic position; "
            f"nothing can be fused. Kinds present: "
            f"{ {p.kind: len(p.records) for p in partitions} }"
        )
        return []

    # Grid-bucket by ~radius_m degrees to avoid O(n^2) comparisons on large sets.
    deg_per_m = 1 / 111_000  # rough approximation, fine for clustering purposes
    cell_size = radius_m * deg_per_m

    # Clustering uses `views`, NOT r.latitude: a reprojected record has no
    # latitude of its own and must not be given one.
    buckets: dict[tuple[int, int], list[SubterraRecord]] = {}
    for r in geographic:
        lat, lon = views[id(r)]
        buckets.setdefault((int(lat / cell_size), int(lon / cell_size)), []).append(r)

    samples: list[FusionSample] = []
    for cell_records in buckets.values():
        if not cell_records:
            continue
        coords = [views[id(r)] for r in cell_records]
        center_lat = sum(c[0] for c in coords) / len(coords)
        center_lon = sum(c[1] for c in coords) / len(coords)
        # A member is reprojected when it has a usable coordinate here but is
        # not natively geographic -- the honest count of derived members.
        n_reprojected = sum(1 for r in cell_records if not has_geographic_coordinates(r))

        sample = FusionSample(radius_m=radius_m, spatial_ref_kind="geographic",
                              center_lat=center_lat, center_lon=center_lon,
                              n_reprojected=n_reprojected)
        for r in cell_records:
            sample.records_by_sensor.setdefault(r.sensor_type.value, []).append(r)

        # Only keep it as a "fusion" sample if it's genuinely multimodal;
        # single-sensor cells are still useful but aren't fusion samples.
        samples.append(sample)

    multimodal = [s for s in samples if len(s.sensor_types) > 1]
    logger.info(
        f"Fusion: {len(records)} records ({len(geographic)} geographic, "
        f"{len(records) - len(geographic)} excluded) -> {len(samples)} spatial cells, "
        f"{len(multimodal)} multimodal (radius={radius_m}m)"
    )
    return samples


def non_fusable_partitions(records: list[SubterraRecord],
                           frames: list | None = None) -> list[SpatialPartition]:
    """
    The partitions fuse_datasets left out, so a caller can report them rather
    than wonder where the records went.

    Pass the same `frames` fuse_datasets was given, or this over-reports:
    projected records that fusion successfully reprojected would appear here
    as excluded.
    """
    return [p for p in partition_by_spatial_ref(records, frames=frames) if not p.fusable]


def multimodal_only(samples: list[FusionSample]) -> list[FusionSample]:
    """Filter to samples that actually combine 2+ sensor types — the real 'fusion' value-add."""
    return [s for s in samples if len(s.sensor_types) > 1]
