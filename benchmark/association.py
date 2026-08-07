"""
Benchmark-local trace/target association.

NOT localisation. This records which traces of a benchmark scan sit over which
published target, in the benchmark's own grid indices. It produces no absolute
coordinate and makes no accuracy claim.

It is exact rather than nearest-neighbour, and that is a property of the data
rather than a choice: the published target X values (250, 750, 1250, 1750) are
whole multiples of the grid's 5-unit spacing, so each lands ON a node. The code
refuses to round -- `GridSpec.x_node` raises on a non-node value -- so if a
future grid or target set broke that property, association would fail loudly
instead of silently degrading.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from benchmark.bam_truth import BenchmarkTarget

EXACT_GRID_NODE = "exact_grid_node"
ASSOCIATED = "associated"


@dataclass(frozen=True)
class AssociationRecord:
    benchmark_id: str
    scan_id: str
    specimen_id: str
    target_id: str
    target_type: str
    target_x: float
    target_grid_index: int
    associated_trace_indices: tuple[int, ...]
    footprint_definition: str
    association_method: str
    association_status: str
    provenance: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "benchmark_id": self.benchmark_id,
            "scan_id": self.scan_id,
            "specimen_id": self.specimen_id,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "target_x": self.target_x,
            "target_grid_index": self.target_grid_index,
            "associated_trace_indices": list(self.associated_trace_indices),
            "footprint_definition": self.footprint_definition,
            "association_method": self.association_method,
            "association_status": self.association_status,
            "provenance": self.provenance,
        }


def associate(scan, targets: list[BenchmarkTarget]) -> list[AssociationRecord]:
    """
    One record per target for one scan.

    A line of this benchmark is a traverse along X at fixed Y, so trace index
    IS the X grid node -- there is no resampling between the two and therefore
    nothing to interpolate. Because the ducts run across the full Y width,
    every line of the scan crosses every target at the same trace indices,
    which is why the record is per (scan, target) and not per (line, target).
    """
    records = []
    for t in targets:
        records.append(AssociationRecord(
            benchmark_id=scan.benchmark_id,
            scan_id=scan.scan_id,
            specimen_id=scan.specimen_id,
            target_id=t.target_id,
            target_type=t.target_type,
            target_x=t.x,
            target_grid_index=t.x_node,
            associated_trace_indices=t.footprint.nodes,
            footprint_definition=t.footprint.rule,
            association_method=EXACT_GRID_NODE,
            association_status=ASSOCIATED,
            provenance={
                "target_position": t.provenance,
                "grid": "verified_from_files",
                "interpolation": "none",
                "absolute_origin_verified": scan.grid.absolute_origin_verified,
                "note": (
                    "benchmark-local trace/target association; not localisation, "
                    "and not an absolute coordinate"
                ),
            },
        ))
    return records


def target_for_trace(targets: list[BenchmarkTarget], trace_index: int):
    """The target whose footprint contains this trace, or None."""
    for t in targets:
        if trace_index in t.footprint:
            return t
    return None
