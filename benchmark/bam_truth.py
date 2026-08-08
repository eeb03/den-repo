"""
The benchmark's target ground truth, in the smallest form detection scoring
needs.

Everything here comes from `benchmark/bam_pk266_targets.json`, which is a HAND
TRANSCRIPTION from publications: the data repository ships no geometry file of
any kind. That origin travels with every object as
`provenance="transcribed_from_publication"` and is never softened.

What this module deliberately does NOT build: a global XYZ model. Targets are
expressed as benchmark-local X, a grid-node index, and a detection footprint in
grid nodes. Depth is carried verbatim for reporting, and is not turned into a
scoring quantity -- `benchmark.gates` blocks that.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TRUTH_FILE = Path(__file__).resolve().parent / "bam_pk266_targets.json"

TRANSCRIBED = "transcribed_from_publication"


class BenchmarkTruthError(RuntimeError):
    """Raised when the truth file and the ingested grid disagree."""


@dataclass(frozen=True)
class TargetFootprint:
    """
    The grid nodes a target occupies along X.

    Deterministic: derived from the published outer diameter centred on the
    published X, intersected with the grid. No tolerance is added, and the
    rule is carried alongside the result so a report can state it.
    """
    first_node: int
    last_node: int
    nodes: tuple[int, ...]
    rule: str

    def __contains__(self, node: int) -> bool:
        return self.first_node <= node <= self.last_node

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)


@dataclass(frozen=True)
class BenchmarkTarget:
    target_id: str
    target_type: str
    material: str
    x: float
    x_node: int
    footprint: TargetFootprint
    #: Carried for reporting only. Depth scoring is gated.
    centre_depth: Optional[float]
    depth_provenance: str
    orientation: str
    spans_full_width_y: bool
    outer_diameter: float
    inner_diameter: float
    provenance: str = TRANSCRIBED
    status: str = "published_numeric"


@dataclass(frozen=True)
class ControlRegion:
    """
    A specimen attested to contain no embedded elements.

    `attested` is the whole point: absence stated by the fabricator, not a
    blank field. `caveat` is equally important and is never dropped -- the
    step back walls are real reflectors, so this controls for embedded
    objects, not for "no reflector".
    """
    specimen_id: str
    attested: bool
    attestation: str
    caveat: str
    provenance: str = TRANSCRIBED


def _load() -> dict:
    return json.loads(TRUTH_FILE.read_text())


def build_footprint(x: float, outer_diameter: float, grid) -> TargetFootprint:
    """The nodes within one outer radius of the target centre."""
    r = outer_diameter / 2.0
    nodes = [i for i, v in enumerate(grid.x) if x - r <= v <= x + r]
    if not nodes:
        raise BenchmarkTruthError(f"target at x={x} has no grid nodes within +/-{r}")
    return TargetFootprint(
        first_node=nodes[0], last_node=nodes[-1], nodes=tuple(nodes),
        rule=(f"grid nodes v with |v - {x}| <= {r} (half the published outer "
              f"diameter {outer_diameter}); no tolerance added"),
    )


def load_targets(grid, specimen_id: str = "Pk266") -> list[BenchmarkTarget]:
    """
    The specimen's targets, resolved against an ingested grid.

    Resolving against the grid rather than against hard-coded indices is what
    makes the exactness real: `grid.x_node` raises if a published X does not
    land on a node, so a grid change cannot silently degrade the association
    into nearest-neighbour matching.
    """
    spec = next((s for s in _load()["specimens"] if s["id"] == specimen_id), None)
    if spec is None:
        raise BenchmarkTruthError(f"no specimen {specimen_id!r} in {TRUTH_FILE.name}")

    targets = []
    for t in spec.get("targets", []):
        geom = t["geometry"]
        targets.append(BenchmarkTarget(
            target_id=t["target_id"],
            target_type=t["type"],
            material=t["material"],
            x=t["x_mm"],
            x_node=grid.x_node(t["x_mm"]),
            footprint=build_footprint(t["x_mm"], geom["outer_diameter_mm"], grid),
            centre_depth=t.get("centre_depth_mm"),
            depth_provenance=t.get("centre_depth_source", "unrecorded"),
            orientation=t["orientation"],
            spans_full_width_y=bool(t["extent"]["spans_full_width_y"]),
            outer_diameter=geom["outer_diameter_mm"],
            inner_diameter=geom["inner_diameter_mm"],
        ))

    _check_disjoint(targets)
    return targets


def _check_disjoint(targets: list[BenchmarkTarget]) -> None:
    """Overlapping footprints would make a detection ambiguous between targets."""
    ordered = sorted(targets, key=lambda t: t.footprint.first_node)
    for a, b in zip(ordered, ordered[1:]):
        if b.footprint.first_node <= a.footprint.last_node:
            raise BenchmarkTruthError(
                f"footprints of {a.target_id} and {b.target_id} overlap "
                f"({a.footprint.last_node} >= {b.footprint.first_node}); a detection "
                f"could not be attributed to one target"
            )


def load_control(specimen_id: str = "Pk050") -> ControlRegion:
    spec = next((s for s in _load()["specimens"] if s["id"] == specimen_id), None)
    if spec is None:
        raise BenchmarkTruthError(f"no specimen {specimen_id!r} in {TRUTH_FILE.name}")
    if spec.get("targets"):
        raise BenchmarkTruthError(f"{specimen_id} has targets; it is not a control region")
    return ControlRegion(
        specimen_id=specimen_id,
        attested=bool(spec.get("empty_is_attested")),
        attestation=spec.get("empty_attestation", ""),
        caveat=spec.get("back_wall_note", ""),
    )
