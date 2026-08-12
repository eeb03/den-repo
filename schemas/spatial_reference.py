"""
What spatial relationship a dataset actually has to the physical world.

WHAT THIS ADDS, AND WHAT IT DOES NOT. Almost every spatial concept Subterra
needs already exists and works: `SpatialRef` with `CRSProvenance`,
`VerticalDatum`, `VerticalAxis`, `GeoTie` with residual checking in
`ingestion/geo_tie.py`, `Assumption`, `fusion.vertical_reference.assess`, and
`validate_velocity` with physically-justified bounds. None of it was reachable
by a user: there was no way to DECLARE any of it after ingest, and no single
place that said which pieces were present.

So this module adds two things and rebuilds nothing:

  1. a per-dimension assessment -- seven questions, each with its own
     vocabulary, its own reason, and the declaration that would resolve it;
  2. the definition of what a declaration may say.

SEVEN DIMENSIONS, NOT ONE BOOLEAN. "Is this spatially registered?" has no
useful answer. A dataset can have perfect horizontal coordinates and no vertical
reference at all; another can have a depth axis in metres that is not placeable
on Earth. Collapsing those into one flag is how a reconstruction ends up drawn
somewhere nobody measured.

THE DISTINCTIONS THIS MODULE EXISTS TO PRESERVE, each of which is a separate
field rather than a shade of one:

    coordinates exist          != coordinates are correct
    a CRS is declared          != a CRS is validated
    a time axis exists         != a physical depth exists
    a DEM exists               != a usable surface reference exists
    relative geometry exists   != absolute geolocation exists

Nothing here computes a coordinate, an elevation, a depth or a velocity. It
reads what frames declare and reports it. Where evidence is absent the state is
`missing` or `unresolved`, and that is a correct answer rather than a gap to be
filled.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas.spatial import AxisKind, CRSKind, CRSProvenance

#: Bumped when the shape of an assessment changes.
SPATIAL_CONTRACT_VERSION = "1.0"


class DeclarationKind(str, Enum):
    """
    What a user may assert about a dataset's relationship to the world.

    Each maps onto a schema that already exists. None of them invents a
    concept, and none of them can express a measurement -- a declaration is
    always somebody's claim, recorded as one.
    """
    #: The horizontal reference the acquisition's coordinates are expressed in.
    CRS = "crs"
    #: What the vertical coordinates are measured FROM.
    VERTICAL_DATUM = "vertical_datum"
    #: The offset from the sensor to the ground surface.
    ANTENNA_OFFSET = "antenna_offset"
    #: A propagation velocity, turning a measured time axis into a derived depth.
    DEPTH_CONVERSION = "depth_conversion"
    #: Control points tying an along-track axis to real coordinates.
    GEO_TIE = "geo_tie"
    #: Another dataset asserted to be this survey's surface elevation model.
    SURFACE_REFERENCE = "surface_reference"


class SpatialDimension(str, Enum):
    HORIZONTAL_POSITION = "horizontal_position"
    CRS = "crs"
    VERTICAL_REFERENCE = "vertical_reference"
    SURFACE_REFERENCE = "surface_reference"
    ORIENTATION = "orientation"
    DEPTH_CONVERSION = "depth_conversion"
    SURVEY_GEOMETRY = "survey_geometry"


#: The states each dimension may report. Kept per-dimension rather than
#: flattened into one enum because the distinctions differ: a CRS can be
#: `inferred`, a position cannot; depth can be `derived`, a datum cannot. A
#: single shared vocabulary would have to drop whichever distinction did not
#: generalise, and those are the distinctions that matter.
DIMENSION_STATES: dict[SpatialDimension, tuple[str, ...]] = {
    SpatialDimension.HORIZONTAL_POSITION: ("available", "partial", "missing", "unresolved"),
    SpatialDimension.CRS: ("declared", "inferred", "missing", "invalid", "unresolved"),
    SpatialDimension.VERTICAL_REFERENCE: ("declared", "missing", "unresolved"),
    SpatialDimension.SURFACE_REFERENCE: ("available", "unavailable", "unvalidated"),
    SpatialDimension.ORIENTATION: ("available", "missing", "unresolved"),
    SpatialDimension.DEPTH_CONVERSION: ("measured", "declared", "derived", "unavailable"),
    SpatialDimension.SURVEY_GEOMETRY: ("available", "partial", "missing"),
}

#: Which states mean "this dimension is settled". Everything else is an open
#: question, and the report says so.
_RESOLVED_STATES = {"available", "declared", "measured", "derived"}


class DimensionState(BaseModel):
    """One spatial question, its answer, and how to change the answer."""
    dimension: SpatialDimension
    state: str
    #: Always present, in the platform's own words rather than a UI paraphrase.
    reason: str = Field(..., min_length=1)
    #: What would have to be obtained or declared. Empty only when resolved.
    missing: list[str] = Field(default_factory=list)
    #: The declaration that would resolve this, when one can. None means no
    #: declaration helps -- the evidence has to come from outside Subterra.
    action: Optional[DeclarationKind] = None
    #: Where the current answer came from, in the existing 7-class vocabulary.
    provenance: Optional[str] = None
    #: Free-form supporting facts, for the interface to render.
    detail: dict[str, Any] = Field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.state in _RESOLVED_STATES


class SpatialReference(BaseModel):
    """The whole spatial picture for one dataset."""
    contract_version: str = SPATIAL_CONTRACT_VERSION
    dataset_id: str
    dimensions: list[DimensionState] = Field(default_factory=list)
    #: Declarations currently in force, newest first.
    declarations: list[dict] = Field(default_factory=list)
    #: True when a declaration landed after something derived from spatial
    #: reference was computed. See `stale_products`.
    has_stale_products: bool = False
    stale_products: list[str] = Field(default_factory=list)

    def dimension(self, which: SpatialDimension) -> Optional[DimensionState]:
        return next((d for d in self.dimensions if d.dimension == which), None)

    @property
    def unresolved(self) -> list[SpatialDimension]:
        return [d.dimension for d in self.dimensions if not d.resolved]


# ---------------------------------------------------------------------------
# assessment
# ---------------------------------------------------------------------------
#
# Pure. Takes frames and records that are already loaded, returns a value.
# Nothing below opens a file or a database, which is what lets every state be
# reached by a constructed frame rather than by whichever datasets happen to be
# in the corpus -- all six of which are unresolved for the same reasons.

_TIME_KINDS = {AxisKind.TWO_WAY_TIME_NS, AxisKind.TWO_WAY_TIME_MS, AxisKind.TWO_WAY_TIME_S}
_EARTH_KINDS = {CRSKind.GEOGRAPHIC, CRSKind.PROJECTED}


def _state(dimension, state, reason, missing=None, action=None, provenance=None, **detail):
    return DimensionState(
        dimension=dimension, state=state, reason=reason, missing=list(missing or []),
        action=action, provenance=provenance, detail=detail)


def assess_horizontal(frames, records) -> DimensionState:
    """
    Whether the measurements have a horizontal position at all.

    DELIBERATELY SEPARATE FROM THE CRS. An odometry frame has positions -- real
    ones, measured by a wheel encoder -- and no relationship to the Earth. A
    frame with easting/northing and no declared projection has the opposite
    problem. Reporting one number for both would hide whichever failure the
    other dataset did not have.
    """
    D = SpatialDimension.HORIZONTAL_POSITION
    if not records:
        return _state(D, "unresolved", "no records are stored, so there is nothing to position",
                      ["a successful ingest"])

    from schemas.spatial import PositionKind, effective_position

    kinds: dict[str, int] = {}
    for record in records:
        pos = effective_position(record)
        key = str(getattr(pos, "kind", PositionKind.NONE.value))
        kinds[key] = kinds.get(key, 0) + 1

    total = len(records)
    geographic = kinds.get(PositionKind.GEOGRAPHIC.value, 0)
    none = kinds.get(PositionKind.NONE.value, 0)
    tied = [f.frame_id for f in frames if getattr(f, "geo_tie", None)]

    if geographic == total:
        return _state(D, "available",
                      f"every one of {total:,} record(s) carries a geographic position",
                      provenance="registered" if tied else "measured",
                      position_kinds=kinds, geo_tie_frames=tied)
    if none == total:
        return _state(D, "missing",
                      "no record carries a horizontal position",
                      ["positions from the acquisition, or a GeoTie supplying them"],
                      action=DeclarationKind.GEO_TIE, provenance="unavailable",
                      position_kinds=kinds)
    if geographic == 0:
        # Positions exist but are not on Earth: odometry, local cartesian, or
        # projected coordinates. Whether they CAN be is the CRS's question.
        return _state(D, "partial",
                      "positions exist but are not geographic; whether they can be placed "
                      "on Earth depends on the coordinate reference system",
                      ["a declared CRS, or a GeoTie for an along-track acquisition"],
                      action=DeclarationKind.GEO_TIE, provenance="measured",
                      position_kinds=kinds)
    return _state(D, "partial",
                  f"{geographic:,} of {total:,} record(s) carry a geographic position",
                  ["positions for the remaining records"],
                  action=DeclarationKind.GEO_TIE, provenance="measured",
                  position_kinds=kinds)


def assess_crs(frames) -> DimensionState:
    """
    Whether the coordinates mean a place on Earth, and on whose word.

    DECLARED IS NOT VALIDATED. `crs_provenance` already distinguishes a CRS the
    file states about itself from one a caller asserted from one something
    deduced, and this reports that distinction rather than collapsing it into
    "we have a CRS". Subterra does not validate a CRS against the coordinates --
    a plausible-looking easting is not evidence of a projection, and inferring
    one from the number's magnitude is precisely the guess this refuses.
    """
    D = SpatialDimension.CRS
    refs = [(f, getattr(f, "spatial_ref", None)) for f in frames]
    refs = [(f, r) for f, r in refs if r is not None]
    if not refs:
        return _state(D, "unresolved", "no survey frame is stored, so no reference is declared",
                      ["a survey frame"], action=DeclarationKind.CRS)

    earth = [(f, r) for f, r in refs if r.kind in _EARTH_KINDS]
    coded = [(f, r) for f, r in earth if r.code]
    uncoded = [f.frame_id for f, r in earth if not r.code]
    non_earth = [f.frame_id for f, r in refs if r.kind not in _EARTH_KINDS]

    if not earth:
        return _state(D, "missing",
                      "every frame is expressed in an engineering or acquisition frame, "
                      "which has no relationship to the Earth by definition",
                      ["a GeoTie, which is the sanctioned route from a frame-local "
                       "coordinate to a geographic one"],
                      action=DeclarationKind.GEO_TIE, provenance="unavailable",
                      frames_without_earth_reference=non_earth)

    if uncoded:
        return _state(D, "unresolved",
                      f"{len(uncoded)} frame(s) carry projected coordinates whose projection "
                      f"is not declared, so the numbers cannot be compared with geographic data",
                      ["the EPSG code of the projection those coordinates are in"],
                      action=DeclarationKind.CRS, provenance="unavailable",
                      frames=uncoded)

    provenances = {r.crs_provenance for _, r in coded}
    codes = sorted({r.code for _, r in coded})
    if CRSProvenance.INFERRED in provenances:
        return _state(D, "inferred",
                      f"the reference {', '.join(codes)} was deduced rather than declared; "
                      f"a deduction is usable and is not the same as the source stating it",
                      ["confirmation from the source, or a declaration by somebody who knows"],
                      action=DeclarationKind.CRS, provenance="inferred", codes=codes)

    provenance = ("declared_by_source"
                  if CRSProvenance.DECLARED_BY_SOURCE in provenances
                  else "supplied_by_caller")
    return _state(D, "declared",
                  f"{', '.join(codes)}, "
                  + ("stated by the source itself" if provenance == "declared_by_source"
                     else "supplied by a caller who took responsibility for it"),
                  provenance=provenance, codes=codes,
                  # Stated so nobody reads "declared" as "checked".
                  validated=False,
                  validation_note=("Subterra does not verify a CRS against the coordinate "
                                   "values; a plausible-looking coordinate is not evidence "
                                   "of a projection"))


def assess_vertical(frames) -> DimensionState:
    """Whether anything says what the vertical coordinates are measured from."""
    D = SpatialDimension.VERTICAL_REFERENCE
    axes = [(f, getattr(f, "vertical_axis", None)) for f in frames]
    axes = [(f, a) for f, a in axes if a is not None]
    if not axes:
        return _state(D, "unresolved", "no survey frame is stored",
                      ["a survey frame"], action=DeclarationKind.VERTICAL_DATUM)

    declared = [
        (f, a.vertical_datum) for f, a in axes
        if a.vertical_datum is not None and a.vertical_datum.code
        and a.vertical_datum.provenance != CRSProvenance.NONE
    ]
    if not declared:
        return _state(D, "missing",
                      "no frame declares a vertical datum, so no vertical coordinate here "
                      "can be compared with one from any other source",
                      ["a declared vertical datum for the acquisition elevations, from "
                       "somebody who knows which one the survey used"],
                      action=DeclarationKind.VERTICAL_DATUM, provenance="unavailable")

    if len(declared) < len(axes):
        return _state(D, "unresolved",
                      f"{len(declared)} of {len(axes)} frame(s) declare a vertical datum; "
                      f"the dataset as a whole has no single vertical reference",
                      ["a declared vertical datum for the remaining frames"],
                      action=DeclarationKind.VERTICAL_DATUM, provenance="unavailable")

    codes = sorted({d.code for _, d in declared})
    if len(codes) > 1:
        return _state(D, "unresolved",
                      f"frames declare different vertical datums ({', '.join(codes)}) and "
                      f"Subterra performs no datum transformation",
                      [f"a transformation between {' and '.join(codes)}, or one datum for "
                       f"the whole survey"],
                      action=DeclarationKind.VERTICAL_DATUM, codes=codes)

    provenance = {d.provenance.value for _, d in declared}

    # THE DATUM IS NOT THE WHOLE VERTICAL REFERENCE. A subsurface axis also
    # needs its zero placed against the ground, and until stage 12 there was no
    # way to say where that was. When the datum is settled and the origin is
    # not, the action points at the offset rather than at the datum the caller
    # has already given -- so the workflow always asks for the next missing
    # thing instead of the first.
    subsurface = [
        (f, a) for f, a in axes
        if a.kind not in (AxisKind.ELEVATION_M, AxisKind.NONE)
    ]
    unplaced = [
        f.frame_id for f, a in subsurface
        if not (a.origin_offset is not None and a.origin_offset.relates_the_depth_axis)
        and "ground surface" not in (a.origin or "").lower()
    ]
    if unplaced:
        return _state(D, "unresolved",
                      f"the vertical datum {codes[0]} is declared, but {len(unplaced)} "
                      f"subsurface frame(s) do not say where their depth axis begins "
                      f"relative to the ground: depth zero is instrument time zero, not "
                      f"the surface",
                      ["the offset from the depth-axis origin to the ground surface"],
                      action=DeclarationKind.ANTENNA_OFFSET,
                      provenance=sorted(provenance)[0], codes=codes,
                      frames_without_origin_offset=unplaced)

    return _state(D, "declared",
                  f"{codes[0]}, "
                  + ("stated by the source" if "declared_by_source" in provenance
                     else "supplied by a caller who took responsibility for it")
                  + (
                      "; the depth axis origin is placed relative to the ground"
                      if subsurface else ""),
                  provenance=sorted(provenance)[0], codes=codes, validated=False)


def assess_depth(frames) -> DimensionState:
    """
    Whether a depth in metres exists, and whether it was measured or assumed.

    FOUR STATES, AND THE DIFFERENCE BETWEEN THE FIRST TWO IS SUBTLE AND REAL.

        measured     an instrument reported a depth. NO CONVERTER SETS THIS,
                     and no dataset held reaches it -- reserved so that a
                     genuinely measured depth has somewhere to be, rather than
                     being flattened into the state below.
        declared     the SOURCE stated a depth. A CSV with a `depth` column is
                     this: somebody computed it before the file reached us, by
                     means we cannot see. Calling that "measured" would claim an
                     instrument observed it, which we do not know.
        derived      a caller supplied a velocity and the platform converted a
                     measured time with it -- an assumption about the ground,
                     not an observation of it.
        unavailable  the time axis is still a time axis.

    Rendering `derived` as `measured` is the single most consequential thing
    this module prevents; rendering `declared` as `measured` is the same
    mistake one step upstream.
    """
    D = SpatialDimension.DEPTH_CONVERSION
    axes = [(f, getattr(f, "vertical_axis", None)) for f in frames]
    axes = [(f, a) for f, a in axes if a is not None
            and a.kind not in (AxisKind.NONE, AxisKind.ELEVATION_M)]
    if not axes:
        return _state(D, "unavailable", "this dataset carries no subsurface vertical axis",
                      ["a subsurface acquisition"], provenance="unavailable")

    time_only = [f.frame_id for f, a in axes if a.kind in _TIME_KINDS and not a.conversion]
    converted = [(f, a) for f, a in axes if a.conversion]
    direct = [(f, a) for f, a in axes if a.kind == AxisKind.DEPTH_M and not a.conversion]

    if time_only:
        return _state(D, "unavailable",
                      f"{len(time_only)} frame(s) carry a MEASURED time axis and no depth: "
                      f"radar time zero is when the instrument fired, not the ground surface, "
                      f"and no velocity has been supplied",
                      ["a propagation velocity, supplied by somebody prepared to state it "
                       "as an assumption about this ground"],
                      action=DeclarationKind.DEPTH_CONVERSION, provenance="unavailable",
                      frames=time_only)

    if converted:
        conversions = [a.conversion for _, a in converted]
        return _state(D, "derived",
                      "depth was DERIVED from a measured time axis using a supplied "
                      "velocity; it is an assumption about the subsurface, not a "
                      "measurement of it",
                      provenance="derived", conversions=conversions)

    return _state(D, "declared",
                  f"{len(direct)} frame(s) carry a depth axis the SOURCE stated, with no "
                  f"conversion recorded. How that depth was arrived at happened before the "
                  f"file reached Subterra and is not visible here",
                  provenance="declared_by_source", frames=[f.frame_id for f, _ in direct])


def assess_surface(frames, surface_frames) -> DimensionState:
    """
    Whether a surface elevation model is linked AND usable.

    A DEM EXISTING IS NOT A SURFACE REFERENCE. The Lazaresti COP30 DEM held here
    is the case in point: the file is real, and its frame is reconstructed with
    origin "unrecorded", its vertical axis is `none` rather than an elevation,
    and not one of its 196 records carries an elevation. It is a DEM that can
    anchor nothing, and calling it a surface reference because the file exists
    would put a fabricated Z under every later reconstruction.
    """
    D = SpatialDimension.SURFACE_REFERENCE
    if not surface_frames:
        return _state(D, "unavailable",
                      "no surface elevation model is linked to this survey",
                      ["a DEM or LiDAR surface covering the survey, with a declared "
                       "vertical datum"],
                      action=DeclarationKind.SURFACE_REFERENCE, provenance="unavailable")

    usable, problems = [], []
    for frame in surface_frames:
        axis = getattr(frame, "vertical_axis", None)
        if axis is None or axis.kind != AxisKind.ELEVATION_M:
            problems.append(
                f"{frame.frame_id}: its vertical axis is "
                f"{getattr(axis, 'kind', None)}, not an elevation")
            continue
        datum = getattr(axis, "vertical_datum", None)
        if not (datum and datum.code and datum.provenance != CRSProvenance.NONE):
            problems.append(f"{frame.frame_id}: it declares no vertical datum")
            continue
        usable.append(frame.frame_id)

    if not usable:
        return _state(D, "unvalidated",
                      "a surface model is linked but cannot anchor anything: "
                      + "; ".join(problems),
                      ["a surface model whose vertical axis is an elevation with a "
                       "declared datum -- for the DEM held here that means re-ingesting "
                       "it with its elevation preserved, not annotating the existing one"],
                      action=DeclarationKind.SURFACE_REFERENCE, provenance="unavailable",
                      problems=problems)

    return _state(D, "available",
                  f"{len(usable)} surface frame(s) carry an elevation axis with a declared "
                  f"datum", provenance="declared_by_source", frames=usable)


def assess_orientation(frames, records) -> DimensionState:
    """
    Whether the acquisition's heading is known.

    NOT INFERRED FROM POSITIONS. A line of geographic positions implies a
    bearing, but bearing is not orientation: it says where the cart went, not
    which way the antenna faced or how it was tilted. That needs an IMU or a
    declaration, and neither exists here yet, so this reports `missing` rather
    than quietly reporting a track bearing under an orientation label.
    """
    D = SpatialDimension.ORIENTATION
    declared = [
        f.frame_id for f in frames
        if any(a.key in ("orientation", "heading", "antenna_orientation")
               for a in getattr(f, "assumptions", []) or [])
    ]
    if declared:
        return _state(D, "available", "orientation is declared on the frame",
                      provenance="supplied_by_caller", frames=declared)
    return _state(D, "missing",
                  "no frame declares an orientation, and none is inferred: a track bearing "
                  "says where the acquisition went, not how the sensor was oriented",
                  ["an IMU record, or a declared antenna orientation"],
                  provenance="unavailable")


def assess_geometry(frames, records) -> DimensionState:
    """Whether the shape of the acquisition is known."""
    D = SpatialDimension.SURVEY_GEOMETRY
    if not frames:
        return _state(D, "missing", "no survey frame is stored", ["a survey frame"])

    positioned = [f for f in frames if getattr(f, "n_positions", None)]
    if len(positioned) == len(frames):
        return _state(D, "available",
                      f"{len(frames)} frame(s), each reporting its own position count",
                      frames=[f.frame_id for f in frames],
                      n_positions={f.frame_id: f.n_positions for f in frames})
    if positioned:
        return _state(D, "partial",
                      f"{len(positioned)} of {len(frames)} frame(s) report a position count",
                      ["position counts for the remaining frames"])
    return _state(D, "missing",
                  "no frame reports how many positions it contains",
                  ["frames that record their own position count"])


def assess_spatial_reference(
    dataset_id: str, frames, records, surface_frames=None, declarations=None,
    stale_products=None,
) -> SpatialReference:
    """The seven questions, answered from what is stored."""
    surface_frames = list(surface_frames or [])
    stale = list(stale_products or [])
    return SpatialReference(
        dataset_id=dataset_id,
        dimensions=[
            assess_horizontal(frames, records),
            assess_crs(frames),
            assess_vertical(frames),
            assess_depth(frames),
            assess_surface(frames, surface_frames),
            assess_orientation(frames, records),
            assess_geometry(frames, records),
        ],
        declarations=list(declarations or []),
        has_stale_products=bool(stale),
        stale_products=stale,
    )
