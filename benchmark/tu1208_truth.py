"""
The TU1208 / IFSTTAR published target geometry, in the smallest form a later
depth-validation experiment needs.

Everything here comes from `benchmark/tu1208_targets.json`, which is a HAND
TRANSCRIPTION from the open-access paper: the data archive ships radargrams and
instrument sidecars only, and its own index was never packaged. That origin
travels with every object as `provenance="transcribed_from_publication"` and
`verified_by_subterra=False`, and neither is softened anywhere.

WHY THIS IS NOT A SECOND TRUTH SYSTEM. It reuses `benchmark.ground_truth`'s
vocabulary for what counts as evidence and `benchmark.bam_truth`'s transcription
pattern for how a publication becomes data. What it does NOT reuse is
`EvaluationUnit`: TU1208 has no labelled evaluation units because nothing here
is a detection question. These are surveyed depths, and their only role is to be
compared against a depth Subterra later computes.

WHAT THIS MODULE REFUSES TO DO, and `tests/test_tu1208_target_truth.py` holds it
to each one:

    * no velocity, and no permittivity-to-velocity conversion. The published
      permittivities are carried as MODELLED material properties, kept in their
      own accessor so they cannot be mistaken for surveyed geometry.
    * no time-zero, and no arrival time of any kind.
    * no depth computed from a radargram.
    * no detector label. A target depth is not a class, and nothing here
      produces a y-value for a scorer.
    * no absolute transverse offset, because the figures publish segment
      lengths and never tie the scale bar's origin to the site axis.

THE THREE-MEDIUM STRUCTURE IS THE POINT. Four regions carry three pipe layers
each at three distinct published depths. Three depths in one medium make
`t = t0 + 2d/v` over-determined, which is what turns a later fit into a test
with residuals rather than an assertion. This module hands over the depths and
stops there.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TRUTH_FILE = Path(__file__).resolve().parent / "tu1208_targets.json"

TRANSCRIBED = "transcribed_from_publication"

#: Bumped by hand ONLY when the meaning of a field changes. Truth changes are
#: covered by the content hash in `truth_version`, which nobody has to remember.
SCHEMA_VERSION = "1"

#: Where the radargrams live, relative to the repository root.
ARCHIVE_ROOT = Path("datasets/raw/zenodo/1211173/extracted/Database_2018")

RADARGRAM_SUFFIXES = (".dzt", ".rd3", ".dt")


class TU1208TruthError(RuntimeError):
    """Raised when the transcription and the archive on disk disagree."""


# ---------------------------------------------------------------------------
# surveyed geometry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PipeTarget:
    """
    One pipe, from a published layer depth and a published laying order.

    `depth_m` is the LAYER's published depth, carried verbatim. `identity` comes
    from the paper's statement of the laying order within every layer, counted
    from the longitudinal axis. `position_in_layer` is that ordinal and is NOT a
    distance -- the transverse offset is unavailable and stays that way.
    """
    target_id: str
    region_id: str
    host_material: str
    layer: int
    position_in_layer: int
    identity: str
    depth_m: float
    depth_evidence_type: str
    length_m: Optional[float]
    diameter_mm: Optional[float]
    transverse_offset_m: Optional[float]
    figure: str
    provenance: str = TRANSCRIBED
    verified_by_subterra: bool = False

    @property
    def derived(self) -> bool:
        """
        The RECORD is an expansion of two published statements -- a layer depth
        and a laying order -- rather than a row somebody printed. Every VALUE on
        it is published; the per-pipe granularity is not.
        """
        return True


@dataclass(frozen=True)
class PublishedDepth:
    """
    A depth printed on a transversal section that is not a pipe layer.

    `object_certain` is the whole reason this type exists separately. Where a
    dashed line terminates unambiguously at one drawn object, the object is
    named. Where three printed depths sit among symbols the text says are at two
    depths, `object` stays None and `candidates` records what it might be. A
    guess would look identical in the data and is refused.
    """
    region_id: str
    depth_m: float
    object: Optional[str]
    object_certain: bool
    candidates: tuple[str, ...]
    figure_part: Optional[str]
    note: str
    provenance: str = TRANSCRIBED
    verified_by_subterra: bool = False


@dataclass(frozen=True)
class MaterialLayer:
    """One stratum of the multilayer region, with its published thickness."""
    index: int
    material: str
    thickness_m: float
    evidence_type: str


@dataclass(frozen=True)
class InterfaceDepth:
    """
    A layer interface depth, DERIVED by cumulative sum of published thicknesses.

    Kept in its own type so it can never be confused with a surveyed target
    depth. The figure prints thicknesses and a 0.00 surface and prints no
    interface depth at all, so this is arithmetic on published values -- which is
    allowed, and is labelled.
    """
    region_id: str
    below_layer: int
    material_above: str
    material_below: Optional[str]
    depth_m: float
    derived: bool = True
    derivation: str = ("cumulative sum of the published layer thicknesses from the "
                       "published 0.00 surface; the figure draws the layers contiguous")
    verified_by_subterra: bool = False


# ---------------------------------------------------------------------------
# modelled material properties -- deliberately a different type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelledPermittivity:
    """
    A relative permittivity the authors obtained by matching FDTD models to the
    measurements, with their own caveat attached.

    A SEPARATE TYPE FROM GEOMETRY, ON PURPOSE. Surveyed depth and modelled
    permittivity are different kinds of knowledge and the whole stage turns on
    not blurring them. `is_a_velocity` is False on every instance and there is
    no method here that converts one into the other.
    """
    region_id: str
    relative_permittivity: float
    method: str
    authors_caveat: str
    attenuation_db_per_m: Optional[tuple[float, float]]
    symbol_as_printed: Optional[str]
    evidence_type: str = "modelled"
    is_a_velocity: bool = False
    verified_by_subterra: bool = False


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Profile:
    """One published radargram row, and the file on disk it resolves to."""
    published_file_name: str
    region_id: str
    lines: tuple[int, ...]
    line_offsets_m: tuple[Optional[float], ...]
    gpr_system: str
    year: int
    frequency_mhz: int
    n_traces: int
    profile_length_m: Optional[float]
    scans_per_m: Optional[float]
    samples: int
    bits: int
    range_ns: float
    source_table: str
    note: Optional[str] = None

    @property
    def has_metric_scale(self) -> bool:
        """
        Whether the paper published enough to place a trace along the profile.

        False for the 22 rows whose profile length the paper prints as NA. A
        along-line ORIGIN is still unavailable for all 67 -- this only says the
        spacing is known.
        """
        return self.profile_length_m is not None and self.scans_per_m is not None


def _load() -> dict:
    return json.loads(TRUTH_FILE.read_text())


def _norm(name: str) -> str:
    """
    Fold a file name for comparison: case and the `-`/`_` separators only.

    NEEDED BECAUSE THE PAPER AND THE ARCHIVE DISAGREE COSMETICALLY. The paper
    writes `200MHz_Limestone_2.dzt` where the archive holds
    `200MHz-Limestone_2.dzt`, and `900MHz_Limestone2_rev.dzt` where the archive
    holds `900MHz_Limestone_2_rev.dzt`. Nothing but case and separators differs,
    and `resolve_files` proves that by requiring a bijection -- a fuzzy match
    that silently paired the wrong files would fail that test, not pass it.
    """
    return name.replace("-", "").replace("_", "").lower()


# ---------------------------------------------------------------------------
# the public surface
# ---------------------------------------------------------------------------

def regions() -> list[dict]:
    return _load()["regions"]


def region(region_id: str) -> dict:
    found = next((r for r in _load()["regions"] if r["id"] == region_id), None)
    if found is None:
        raise TU1208TruthError(f"no region {region_id!r} in {TRUTH_FILE.name}")
    return found


def pipe_targets(region_id: Optional[str] = None) -> list[PipeTarget]:
    """
    Every pipe, expanded from the published layer depths and laying order.

    The expansion is deliberate and stated: the paper publishes three pipes per
    layer and the order they were laid in, counted from the longitudinal axis,
    'in all layers'. It does not publish a per-pipe row.
    """
    doc = _load()
    spec = doc["pipe_specification"]
    order = spec["order_from_axis"]

    out: list[PipeTarget] = []
    for reg in doc["regions"]:
        if region_id is not None and reg["id"] != region_id:
            continue
        for layer in reg["pipe_layers"]:
            if layer["n_pipes"] != len(order):
                raise TU1208TruthError(
                    f"{reg['id']} layer {layer['layer']} declares {layer['n_pipes']} pipes "
                    f"but the published laying order names {len(order)}")
            for position, identity in enumerate(order, start=1):
                out.append(PipeTarget(
                    target_id=f"tu1208-{reg['id']}-L{layer['layer']}-P{position}",
                    region_id=reg["id"],
                    host_material=reg["host_material"],
                    layer=layer["layer"],
                    position_in_layer=position,
                    identity=identity,
                    depth_m=layer["depth_m"],
                    depth_evidence_type=layer["evidence_type"],
                    length_m=spec["length_m"],
                    diameter_mm=spec["diameter_mm"],
                    # UNAVAILABLE, and None is the honest value. Zero would be a
                    # claim that the pipe sits on the longitudinal axis.
                    transverse_offset_m=None,
                    figure=reg["figure"],
                ))
    return out


def pipe_layer_depths(region_id: str) -> list[float]:
    """The published layer depths for one region, shallowest first."""
    return [layer["depth_m"] for layer in region(region_id)["pipe_layers"]]


def published_depths(region_id: Optional[str] = None) -> list[PublishedDepth]:
    """Every non-pipe depth printed on a section, certain or not."""
    out: list[PublishedDepth] = []
    for reg in _load()["regions"]:
        if region_id is not None and reg["id"] != region_id:
            continue
        for entry in reg.get("other_published_depths", []):
            out.append(PublishedDepth(
                region_id=reg["id"],
                depth_m=entry["depth_m"],
                object=entry.get("object"),
                object_certain=bool(entry.get("object_certain")),
                candidates=tuple(entry.get("candidates", ())),
                figure_part=entry.get("figure_part"),
                note=entry.get("note", ""),
            ))
    return out


def material_layers(region_id: str = "multilayer") -> list[MaterialLayer]:
    return [MaterialLayer(index=layer["index"], material=layer["material"],
                          thickness_m=layer["thickness_m"],
                          evidence_type=layer["evidence_type"])
            for layer in region(region_id).get("layers", [])]


def interface_depths(region_id: str = "multilayer") -> list[InterfaceDepth]:
    """
    Layer interfaces, DERIVED from the published thicknesses.

    Offered because a planar interface at a known depth is a better velocity
    reference than a pipe -- no hyperbola, no crown-versus-centre question. It
    is still derived, and every instance says so.
    """
    layers = material_layers(region_id)
    out: list[InterfaceDepth] = []
    running = 0.0
    for i, layer in enumerate(layers):
        running += layer.thickness_m
        below = layers[i + 1].material if i + 1 < len(layers) else None
        out.append(InterfaceDepth(
            region_id=region_id, below_layer=layer.index,
            material_above=layer.material, material_below=below,
            depth_m=-round(running, 10)))
    return out


def modelled_permittivities() -> list[ModelledPermittivity]:
    """
    The authors' FDTD-matched permittivities.

    NOT GEOMETRY, and not a velocity. Returned from its own function so that
    reading geometry never hands a caller a material property by accident.
    """
    out: list[ModelledPermittivity] = []
    for reg in _load()["regions"]:
        entry = reg.get("modelled_permittivity")
        if not entry:
            continue
        att = entry.get("attenuation_db_per_m")
        out.append(ModelledPermittivity(
            region_id=reg["id"],
            relative_permittivity=entry["relative_permittivity"],
            method=entry["method"],
            authors_caveat=entry["authors_caveat"],
            attenuation_db_per_m=tuple(att) if att else None,
            symbol_as_printed=entry.get("symbol_as_printed"),
        ))
    return out


def acquisition_line_offset(line: int) -> Optional[float]:
    """Published distance from the upstream border, or None if unpublished."""
    return _load()["acquisition_lines"]["offsets_m_from_upstream_border"].get(str(line))


def profiles(region_id: Optional[str] = None) -> list[Profile]:
    doc = _load()
    offsets = doc["acquisition_lines"]["offsets_m_from_upstream_border"]
    out: list[Profile] = []
    for row in doc["profiles"]:
        if region_id is not None and row["region"] != region_id:
            continue
        lines = tuple(row["lines"])
        out.append(Profile(
            published_file_name=row["published_file_name"],
            region_id=row["region"],
            lines=lines,
            line_offsets_m=tuple(offsets.get(str(n)) for n in lines),
            gpr_system=row["gpr_system"], year=row["year"],
            frequency_mhz=row["frequency_mhz"], n_traces=row["n_traces"],
            profile_length_m=row["profile_length_m"],
            scans_per_m=row["scans_per_m"], samples=row["samples"],
            bits=row["bits"], range_ns=row["range_ns"],
            source_table=row["source_table"], note=row.get("note"),
        ))
    return out


def resolve_files(archive_root: Path) -> dict[str, Path]:
    """
    Map every published file name onto the file on disk, or raise.

    A BIJECTION IS REQUIRED IN BOTH DIRECTIONS. Every published name must match
    exactly one archive file, every archive radargram must be claimed exactly
    once, and each must sit in the region directory the paper assigns it to.
    Anything less would let a transcription error hide as a near-match.
    """
    archive_root = Path(archive_root)
    if not archive_root.is_dir():
        raise TU1208TruthError(f"archive root {archive_root} is not a directory")

    on_disk: dict[str, list[Path]] = {}
    for path in sorted(archive_root.glob("*/*")):
        if path.name.startswith("._") or path.suffix.lower() not in RADARGRAM_SUFFIXES:
            continue
        on_disk.setdefault(_norm(path.name), []).append(path)

    collisions = {k: v for k, v in on_disk.items() if len(v) > 1}
    if collisions:
        raise TU1208TruthError(f"archive names collide once folded: {collisions}")

    doc = _load()
    directories = {r["id"]: r["archive_directory"] for r in doc["regions"]}

    resolved: dict[str, Path] = {}
    missing: list[str] = []
    misplaced: list[str] = []
    for row in doc["profiles"]:
        name = row["published_file_name"]
        hits = on_disk.get(_norm(name))
        if not hits:
            missing.append(name)
            continue
        path = hits[0]
        if path.parent.name != directories[row["region"]]:
            misplaced.append(
                f"{name}: paper assigns region {row['region']} "
                f"({directories[row['region']]}) but the archive holds it in {path.parent.name}")
            continue
        resolved[name] = path

    if missing:
        raise TU1208TruthError(
            f"{len(missing)} published file name(s) have no archive file: {missing}")
    if misplaced:
        raise TU1208TruthError("region disagreement between paper and archive: " + "; ".join(misplaced))

    unclaimed = sorted(p.name for paths in on_disk.values() for p in paths
                       if p not in set(resolved.values()))
    if unclaimed:
        raise TU1208TruthError(
            f"{len(unclaimed)} archive radargram(s) are not named by any published table: "
            f"{unclaimed}")
    return resolved


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

def truth_content() -> dict:
    """
    The canonical content the version hashes: the transcribed truth, nothing else.

    ORDER-INDEPENDENT BY CONSTRUCTION. Records are sorted by their own identity
    before hashing, so shuffling the JSON file does not mint a new version. What
    DOES change it is any transcribed value -- a depth, a permittivity, a file
    association, an unavailable entry, an open question.
    """
    doc = _load()
    return {
        "schema_version": SCHEMA_VERSION,
        "provenance_class": doc["provenance_class"],
        "verified_by_subterra": doc["verified_by_subterra"],
        "pipe_layers": sorted(
            [f"{r['id']}|{layer['layer']}|{layer['depth_m']}|{layer['n_pipes']}"
             for r in doc["regions"] for layer in r["pipe_layers"]]),
        "published_depths": sorted(
            [f"{r['id']}|{e['depth_m']}|{e.get('object')}|{bool(e.get('object_certain'))}"
             for r in doc["regions"] for e in r.get("other_published_depths", [])]),
        "material_layers": sorted(
            [f"{r['id']}|{layer['index']}|{layer['material']}|{layer['thickness_m']}"
             for r in doc["regions"] for layer in r.get("layers", [])]),
        "permittivities": sorted(
            [f"{r['id']}|{r['modelled_permittivity']['relative_permittivity']}"
             for r in doc["regions"] if r.get("modelled_permittivity")]),
        "pipe_specification": sorted(f"{k}={v}" for k, v in doc["pipe_specification"].items()
                                     if not k.startswith("$")),
        "acquisition_lines": sorted(
            f"{k}={v}" for k, v in
            doc["acquisition_lines"]["offsets_m_from_upstream_border"].items()),
        "profiles": sorted(
            f"{p['published_file_name']}|{p['region']}|{sorted(p['lines'])}|"
            f"{p['frequency_mhz']}|{p['n_traces']}|{p['profile_length_m']}"
            for p in doc["profiles"]),
        "attested_absent_regions": sorted(
            r["id"] for r in doc["regions"] if r.get("targets_attested_absent")),
        "unavailable": sorted(f"{u['quantity']}|{u['scope']}" for u in doc["unavailable"]),
        "open_questions": sorted(q["id"] for q in doc["open_questions"]),
    }


def truth_version() -> str:
    """A content hash of the transcription. Not a version anybody bumps."""
    blob = json.dumps(truth_content(), sort_keys=True, separators=(",", ":"))
    return f"tu1208-{SCHEMA_VERSION}-{hashlib.sha256(blob.encode()).hexdigest()[:16]}"


def summary() -> dict:
    """Counts, for a report or a stage deliverable."""
    doc = _load()
    pipes = pipe_targets()
    return {
        "truth_version": truth_version(),
        "provenance_class": doc["provenance_class"],
        "verified_by_subterra": doc["verified_by_subterra"],
        "n_regions": len(doc["regions"]),
        "n_pipe_targets": len(pipes),
        "n_pipe_layers": sum(len(r["pipe_layers"]) for r in doc["regions"]),
        "n_published_depths_other": len(published_depths()),
        "n_profiles": len(doc["profiles"]),
        "pipe_depths_by_region": {
            r["id"]: [layer["depth_m"] for layer in r["pipe_layers"]]
            for r in doc["regions"] if r["pipe_layers"]},
        "regions_with_targets_attested_absent": [
            r["id"] for r in doc["regions"] if r.get("targets_attested_absent")],
        "n_unavailable": len(doc["unavailable"]),
        "n_open_questions": len(doc["open_questions"]),
    }
