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

Only GEOGRAPHIC records are fused. Everything else is reported as
non-fusable with the reason rather than silently dropped OR silently
merged: an odometry frame genuinely has no relationship to a geographic
one until someone supplies a tie, and inventing that relationship is the
failure mode this partitioning exists to prevent.
"""
import math
from dataclasses import dataclass, field

from schemas.spatial import has_geographic_coordinates
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
        "projected easting/northing with no declared CRS: two projected frames cannot be "
        "compared without knowing they share a projection"
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


def partition_by_spatial_ref(records: list[SubterraRecord]) -> list[SpatialPartition]:
    """
    Groups records by position kind, marking which groups can be fused.

    Partitioning happens BEFORE any distance is computed. Mixing kinds and
    then measuring between them is how placeholder coordinates turn into
    false co-location.
    """
    by_kind: dict[str, list[SubterraRecord]] = {}
    for r in records:
        # A record counts as geographic when its coordinates are real, which
        # includes ones a KMZ track supplied even though `position` still
        # reports what the file itself said.
        if has_geographic_coordinates(r):
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
    center_lat: float
    center_lon: float
    radius_m: float
    records_by_sensor: dict[str, list[SubterraRecord]] = field(default_factory=dict)

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
) -> list[FusionSample]:
    """
    Cluster records from different sensor types into fusion samples using a
    simple greedy spatial clustering (grid-bucketed for tractability on
    large record sets). Records from the *same* sensor type at the same
    spot are kept together rather than exploding into separate samples.

    ONLY records with a geographic position take part. Anything positioned
    by odometry, by a projected frame with no declared CRS, or not at all is
    excluded and logged -- see `non_fusable_partitions` to enumerate them.
    Fusing them would require inventing a spatial relationship that does not
    exist in the data.
    """
    radius_m = radius_m or settings.fusion_spatial_tolerance_m
    if not records:
        return []

    # Partition by position kind FIRST. Without this, every record carrying the
    # legacy (0.0, 0.0) placeholder -- odometry runs, un-georeferenced lines,
    # projected surveys -- lands in one bucket at null island and fuses as if
    # co-located.
    partitions = partition_by_spatial_ref(records)
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

    buckets: dict[tuple[int, int], list[SubterraRecord]] = {}
    for r in geographic:
        key = (int(r.latitude / cell_size), int(r.longitude / cell_size))
        buckets.setdefault(key, []).append(r)

    samples: list[FusionSample] = []
    for cell_records in buckets.values():
        if not cell_records:
            continue
        center_lat = sum(r.latitude for r in cell_records) / len(cell_records)
        center_lon = sum(r.longitude for r in cell_records) / len(cell_records)

        sample = FusionSample(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
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


def non_fusable_partitions(records: list[SubterraRecord]) -> list[SpatialPartition]:
    """
    The partitions fuse_datasets left out, so a caller can report them rather
    than wonder where the records went.
    """
    return [p for p in partition_by_spatial_ref(records) if not p.fusable]


def multimodal_only(samples: list[FusionSample]) -> list[FusionSample]:
    """Filter to samples that actually combine 2+ sensor types — the real 'fusion' value-add."""
    return [s for s in samples if len(s.sensor_types) > 1]
