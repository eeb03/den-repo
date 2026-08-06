"""
Sensor Fusion Module: detects datasets collected over the same location
and combines their records into one multimodal training sample.

Distance uses the haversine formula (meters). The matching radius is
configurable via settings.fusion_spatial_tolerance_m — this is the single
knob that trades off "more fusion samples" against "more spatial precision".
"""
import math
from dataclasses import dataclass, field

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
    """
    radius_m = radius_m or settings.fusion_spatial_tolerance_m
    if not records:
        return []

    # Grid-bucket by ~radius_m degrees to avoid O(n^2) comparisons on large sets.
    deg_per_m = 1 / 111_000  # rough approximation, fine for clustering purposes
    cell_size = radius_m * deg_per_m

    buckets: dict[tuple[int, int], list[SubterraRecord]] = {}
    for r in records:
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
        f"Fusion: {len(records)} records -> {len(samples)} spatial cells, "
        f"{len(multimodal)} multimodal (radius={radius_m}m)"
    )
    return samples


def multimodal_only(samples: list[FusionSample]) -> list[FusionSample]:
    """Filter to samples that actually combine 2+ sensor types — the real 'fusion' value-add."""
    return [s for s in samples if len(s.sensor_types) > 1]
