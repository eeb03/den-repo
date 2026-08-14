"""
Explicit spatial representation: how a sample is positioned, and in what
reference frame.

WHY THIS EXISTS
---------------
Before this module, `SubterraRecord.latitude`/`.longitude` were required
WGS84 floats. Every converter therefore had to produce a lat/lon pair even
when the source data has none, which forced two bad outcomes:

- SEGYConverter wrote a literal (0.0, 0.0) whenever trace headers weren't
  in WGS84 range -- silently DISCARDING real projected coordinates (the
  INGV-UNISA lines carry UTM easting/northing ~501134/4544705, which is a
  genuine position, not missing data).
- Anything downstream that measured distance between those records got a
  fabricated answer. `interpretation/anomaly_candidates.py` reports
  `approx_lateral_extent_m = haversine_m(0,0, 0,0)` = exactly 0.0 metres
  for candidates on that data -- a measurement that was never measured.

Making latitude/longitude merely *nullable* would not fix this: `None` is
indistinguishable from a converter that forgot to set a field. So instead
a position is a REQUIRED discriminated union whose legal values include an
explicit `NoPosition` carrying a reason. Absence becomes a declaration
rather than an omission, and a converter must choose rather than default.

The five kinds are deliberately distinct rather than collapsed into
"x/y plus a CRS string", because the correct behaviour differs per kind:
geographic positions can be haversined, projected ones need reprojection
before they can be compared to geographic ones, local and odometry frames
have no defined relationship to the Earth at all until someone supplies a
tie, and NONE must never be silently coerced to any of the above.

WHAT LIVES WHERE
----------------
Per-RECORD (this module's `Position`): only the varying coordinate values.
Per-FRAME (`schemas/survey_frame.py`): the CRS, units, datum, vertical
axis and provenance -- constant across a survey line, so it is stored once
rather than duplicated across millions of records.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class PositionKind(str, Enum):
    """Symbolic constants for the `Position.kind` discriminator.

    Values match the `Literal` discriminators below exactly, so
    `record.position.kind == PositionKind.GEOGRAPHIC` works (str Enum
    compares equal to its own value).
    """
    GEOGRAPHIC = "geographic"
    PROJECTED = "projected"
    LOCAL_CARTESIAN = "local_cartesian"
    ODOMETRY = "odometry"
    NONE = "none"


class GeographicPosition(BaseModel):
    """Latitude/longitude on a geodetic datum (the frame names which one)."""
    kind: Literal["geographic"] = "geographic"
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class ProjectedPosition(BaseModel):
    """
    Easting/northing in a projected CRS. The EPSG code lives on the frame's
    SpatialRef, not here -- repeating it per record would duplicate the same
    string across every sample of a survey.

    Deliberately unbounded: a UTM northing of 4,544,705 is a perfectly valid
    position and must not be rejected by a latitude range check, which is
    exactly what happens today (LASConverter fails outright on any real
    projected point cloud for this reason).
    """
    kind: Literal["projected"] = "projected"
    easting: float
    northing: float


class LocalCartesianPosition(BaseModel):
    """
    Site-local cartesian coordinates. The frame states the origin and
    orientation; without those this is not convertible to anything else,
    which is precisely why the kind is distinct from PROJECTED.
    """
    kind: Literal["local_cartesian"] = "local_cartesian"
    x: float
    y: float


class OdometryPosition(BaseModel):
    """
    Distance travelled along an acquisition path -- a wheel encoder, a
    cable counter. This is the honest representation for GPR collected
    without GNSS (e.g. cart-mounted surveys such as CMU-GPR): the sensor
    genuinely knows how far it has moved, and genuinely does not know where
    on Earth it is.
    """
    kind: Literal["odometry"] = "odometry"
    along_track_m: float
    cross_track_m: float = 0.0
    path_id: Optional[str] = None   # which run/pass, when a site has several


class NoPosition(BaseModel):
    """
    No horizontal position exists for this sample.

    `reason` is required and must be non-empty: the whole point of this
    variant is that it records WHY the position is absent, so a reader can
    tell "the instrument provides none" from "the sidecar file didn't
    match" from "we haven't implemented this yet".

    Note this constrains only the HORIZONTAL axes. A depth/time-only
    measurement is fully representable: NoPosition plus a real value on the
    frame's vertical axis.
    """
    kind: Literal["none"] = "none"
    reason: str = Field(..., min_length=1)


Position = Annotated[
    Union[
        GeographicPosition,
        ProjectedPosition,
        LocalCartesianPosition,
        OdometryPosition,
        NoPosition,
    ],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------
# Frame-level reference information (stored once per survey line)
# --------------------------------------------------------------------------

class CRSKind(str, Enum):
    GEOGRAPHIC = "geographic"
    PROJECTED = "projected"
    ENGINEERING = "engineering"    # site-local cartesian
    ACQUISITION = "acquisition"    # along-path / odometry
    UNKNOWN = "unknown"            # positions not determined


#: Which `PositionKind` a frame of each `CRSKind` may hold. Checked by
#: `assert_position_matches_ref` so a frame can never disagree with its
#: own records about what their numbers mean.
POSITION_KIND_FOR_CRS: dict[CRSKind, PositionKind] = {
    CRSKind.GEOGRAPHIC: PositionKind.GEOGRAPHIC,
    CRSKind.PROJECTED: PositionKind.PROJECTED,
    CRSKind.ENGINEERING: PositionKind.LOCAL_CARTESIAN,
    CRSKind.ACQUISITION: PositionKind.ODOMETRY,
    CRSKind.UNKNOWN: PositionKind.NONE,
}


class CRSProvenance(str, Enum):
    """
    WHERE a coordinate reference system came from.

    This distinction is load-bearing. "EPSG:32633" carries very different
    weight when a file declares it than when an operator asserted it at
    ingest, and different again when something deduced it. Collapsing the
    three would make an externally supplied CRS indistinguishable from one
    the data vouches for.
    """
    DECLARED_BY_SOURCE = "declared_by_source"   # the file itself states it
    SUPPLIED_BY_CALLER = "supplied_by_caller"   # asserted as ingest configuration
    INFERRED = "inferred"                       # deduced; must carry a justification
    NONE = "none"                               # no CRS is known


class SpatialRef(BaseModel):
    """
    The reference frame a survey line's positions are expressed in.

    `code` is only meaningful for GEOGRAPHIC/PROJECTED refs -- an
    engineering or acquisition frame has no EPSG identity by definition, so
    carrying one would be a category error and is rejected below. A
    PROJECTED ref with `code=None` is legal and common: SEG-Y headers give
    easting/northing without ever declaring which projection they are in.
    """
    kind: CRSKind
    code: Optional[str] = None            # "EPSG:32633"
    crs_provenance: CRSProvenance = CRSProvenance.NONE
    name: Optional[str] = None            # human-readable description
    horizontal_units: str = "m"           # "deg" for geographic
    vertical_datum: Optional[str] = None  # "EGM96", "WGS84 ellipsoid", "local ground surface"
    origin_description: Optional[str] = None  # required-in-spirit for engineering/acquisition

    @model_validator(mode="after")
    def _code_requires_a_provenance(self) -> "SpatialRef":
        """A CRS with no stated origin is indistinguishable from a guess."""
        if self.code and self.crs_provenance == CRSProvenance.NONE:
            raise ValueError(
                f"SpatialRef.code={self.code!r} was set without a crs_provenance. State whether "
                "the source declared it, a caller supplied it, or it was inferred."
            )
        return self

    @model_validator(mode="after")
    def _code_only_for_earth_referenced(self) -> "SpatialRef":
        if self.code and self.kind in (CRSKind.ENGINEERING, CRSKind.ACQUISITION, CRSKind.UNKNOWN):
            raise ValueError(
                f"SpatialRef.code={self.code!r} is not meaningful for kind={self.kind.value!r}; "
                "an engineering/acquisition/unknown frame has no EPSG identity. Supply a GeoTie "
                "(a later milestone) to relate it to an Earth-referenced CRS instead."
            )
        return self


class AxisKind(str, Enum):
    """What the vertical axis of a frame actually measures.

    Time axes are named by the unit the SOURCE reports, not by a canonical
    unit, so no silent rescaling is implied by the label. Converting a time
    axis to depth requires a velocity model and is recorded on the frame's
    VerticalAxis.conversion when (and only when) it has been applied.
    """
    DEPTH_M = "depth_m"
    TWO_WAY_TIME_NS = "two_way_time_ns"    # GPR
    TWO_WAY_TIME_MS = "two_way_time_ms"    # seismic, per SEG-Y rev-1 convention
    TWO_WAY_TIME_S = "two_way_time_s"
    ELEVATION_M = "elevation_m"            # DEM / point cloud
    NONE = "none"                          # 2D surface measurement


class VerticalDatum(BaseModel):
    """
    What a vertical coordinate is measured FROM.

    Separate from `SpatialRef` because the horizontal and vertical references
    of a dataset are declared independently and are routinely both present,
    both absent, or one of each. AHN is the clean example: it declares
    EPSG:28992 horizontally in three places and declares NOTHING vertically --
    the file has no VERT_CS, no band units, no band description.

    ABSENCE IS THE DEFAULT AND IT MEANS UNDECLARED. A vertical coordinate
    whose datum nobody stated cannot be compared with one from another
    source, however similar the numbers look. `code` may only be set with a
    provenance that says who set it.
    """
    code: Optional[str] = None          # "NAP", "EPSG:5709", "ODN", ...
    provenance: CRSProvenance = CRSProvenance.NONE
    name: str = ""

    @model_validator(mode="after")
    def _code_requires_provenance(self):
        if self.code and self.provenance == CRSProvenance.NONE:
            raise ValueError(
                f"vertical datum code {self.code!r} was set with provenance NONE. A datum "
                f"nobody declared is not a datum; either record who declared it or leave "
                f"the code unset."
            )
        return self


class AcquisitionElevationDatum(BaseModel):
    """
    What the ELEVATION STORED WITH THE SURVEY is measured from -- the GNSS or
    levelling height of the instrument position, which is a different quantity
    from the frame's own vertical axis and does not share its datum.

    IT EXISTS BECAUSE ONE FRAME CARRIES TWO VERTICAL QUANTITIES. A 4TU GPR line
    has a vertical axis of two-way travel time from instrument time zero -- which
    no geodetic datum describes -- and, separately, a per-trace acquisition
    elevation from a GNSS receiver, which one certainly does. Before this there
    was one slot, so declaring the elevation's datum meant writing it onto the
    time axis: asserting that instrument time zero is referenced to an ellipsoid.

    `field` NAMES WHICH STORED ELEVATION, in the source's own words, because a
    source may store more than one and they need not share a datum. The 4TU
    SEG-Y files populate two elevation fields that differ by ~44 m.

    KNOWING THIS DATUM DOES NOT PLACE THE DEPTH AXIS. It says where the
    instrument was, not where the axis zero sits relative to the ground.
    """
    datum: VerticalDatum
    field: Optional[str] = None


class VerticalRelationshipKind(str, Enum):
    """
    How a subsurface depth axis relates to a surface elevation model.

    The four states are kept distinct because collapsing them is how a
    fabricated Z coordinate gets born.
    """
    #: Both vertical references are declared and compatible, and the depth
    #: axis origin is tied to the surface: absolute elevation is computable.
    ABSOLUTE_ELEVATION = "absolute_elevation"
    #: Depth below the acquisition surface is known; the surface's own
    #: elevation is not usable to anchor it.
    RELATIVE_DEPTH_ONLY = "relative_depth_only"
    #: The pieces exist but a declaration or tie is missing. What is missing
    #: is enumerated, so the gap is actionable rather than mysterious.
    REGISTRATION_REQUIRED = "registration_required"
    #: No relationship can be established from the available data.
    UNRELATED = "unrelated"


class OriginReference(str, Enum):
    """
    WHICH physical point an offset is measured from.

    These were previously one free-text string, and `assess` decided whether
    depth zero was the ground by searching it for the words "ground surface".
    They are not interchangeable: an antenna's phase centre is where the pulse
    effectively leaves the antenna, the housing is what a tape measure touches,
    and the DEPTH-AXIS ORIGIN is where sample zero sits -- which for a GPR is
    instrument time zero, set by the electronics, and is the only one vertical
    registration is about. A phase-centre height is a real measurement that does
    not answer the question until somebody also relates it to time zero.
    """
    DEPTH_AXIS_ORIGIN = "depth_axis_origin"
    SENSOR_PHASE_CENTRE = "sensor_phase_centre"
    SENSOR_HOUSING = "sensor_housing"


class NorthReference(str, Enum):
    """
    WHAT A DECLARED ANTENNA HEADING IS MEASURED FROM.

    True, magnetic and grid north disagree with each other by amounts that
    vary with location and date -- sometimes by tens of degrees -- so a
    heading with no stated reference is not a usable claim, and defaulting one
    silently would misattribute the difference to the antenna. No member of
    this enum is the default; a declaration must name one.
    """
    TRUE_NORTH = "true_north"
    MAGNETIC_NORTH = "magnetic_north"
    GRID_NORTH = "grid_north"


class OffsetEvidence(str, Enum):
    """
    WHERE an offset came from. Ordered by how much the world vouches for it.

    Kept separate from `verified`: documentation can be authoritative and still
    unchecked against this particular acquisition.
    """
    #: Physically measured during acquisition -- a tape on the day.
    FIELD_MEASUREMENT = "field_measurement"
    #: Stated by the instrument or operator documentation for this setup.
    ACQUISITION_DOCUMENTATION = "acquisition_documentation"
    #: Supplied by a user with no independent basis given.
    USER_DECLARATION = "user_declaration"
    #: Computed from another known relationship, whose inputs are recorded.
    DERIVED = "derived"


#: THE SIGN CONVENTION, fixed and singular.
#:
#:     positive  =  the reference point is ABOVE the ground
#:
#: It is not chosen here: `api/spatial.py` has recorded
#: `"positive_direction": "sensor above ground"` since the antenna-offset
#: declaration was introduced, and changing it would silently invert every
#: value already declared under it. So a cart-mounted antenna 0.45 m off the
#: ground is `offset_m = +0.45`, and a sensor lowered into a trench below the
#: surface is negative.
#:
#: For a depth axis (positive_down), the ground therefore lies at
#: `+offset_m` ON that axis: a sample at depth d is (d - offset_m) below
#: ground. Nothing in this module performs that arithmetic -- it is written
#: down so that whatever eventually does cannot get the sign backwards.
OFFSET_POSITIVE_MEANS = "the reference point is above the ground"


class DepthOriginOffset(BaseModel):
    """
    Where the depth/time axis begins, relative to the ground.

    THE MISSING LINK. A GPR's depth axis starts at instrument time zero, which
    is not the ground surface; until somebody says how far apart they are, a
    sample's depth cannot be placed against a surface model however good both
    are. This records that statement -- and only that statement.

    IT IS NOT A DEPTH, AND NOT A VELOCITY. Declaring this does not convert time
    to metres, does not validate any depth already present, and does not make a
    dataset vertically registered on its own. It removes exactly one of the
    three things `fusion.vertical_reference.assess` enumerates as missing.
    """
    #: Metres, always. The field name carries the unit so a bare number cannot
    #: arrive meaning centimetres.
    offset_m: float
    #: See `OriginReference`. Only DEPTH_AXIS_ORIGIN answers the registration
    #: question; the others are recorded and reported as insufficient.
    measured_from: OriginReference
    measured_to: str = "ground surface"
    evidence: OffsetEvidence
    #: The AUTHORITY for the claim, in their own words -- not the account that
    #: typed it. Same rule as every other spatial declaration.
    supplied_by: str
    #: Independently checked against something. Nothing sets this true yet:
    #: Subterra has no way to verify an offset, and saying otherwise would make
    #: a declaration look like a measurement.
    verified: bool = False
    sign_convention: str = OFFSET_POSITIVE_MEANS
    note: Optional[str] = None

    @property
    def relates_the_depth_axis(self) -> bool:
        """Whether this offset answers the question registration actually asks."""
        return self.measured_from == OriginReference.DEPTH_AXIS_ORIGIN


class VerticalAxis(BaseModel):
    """
    The vertical/time axis of a survey line, and how a stored `depth` was
    arrived at.

    `conversion` exists so a derived depth is never mistaken for a measured
    one: SEGYConverter turns two-way travel time into metres using an
    ASSUMED constant velocity, and that assumption belongs in the data, not
    only in a module docstring.
    """
    kind: AxisKind
    units: str
    origin: str                      # "ground surface at trace", "mean sea level", ...
    positive_down: bool
    n_samples: Optional[int] = None
    sample_interval: Optional[float] = None
    conversion: Optional[dict[str, Any]] = None  # {"method": "constant_velocity", ...}
    #: What the axis is measured FROM, when anyone has said. Absent means
    #: UNDECLARED -- which is the honest state for every dataset held so far,
    #: and the reason absolute elevation cannot be computed for any of them.
    vertical_datum: Optional[VerticalDatum] = None
    #: Where this axis's zero sits relative to the ground. Absent means nobody
    #: has said, which is a legitimate terminal state and not a gap to fill
    #: with a typical antenna height. Lives on the AXIS, which lives on the
    #: frame, because a survey line is exactly the unit over which a sensor
    #: geometry is constant -- two lines of one survey may legitimately differ.
    origin_offset: Optional[DepthOriginOffset] = None


class Assumption(BaseModel):
    """
    One stated assumption, with its basis and whether anything actually
    checked it.

    Generalises the ad-hoc booleans currently scattered through record
    metadata (`kmz_direction_verified`, `dem_vertical_datum_verified`,
    `velocity_m_per_ns`), which `interpretation/anomaly_candidates.py`
    already has to hand-collect one by one into AnomalyConfidence.
    """
    key: str
    value: Any = None
    basis: str                # "assumed default" | "file header" | "user supplied" | "observed: ..."
    verified: bool = False


#: Inverse of POSITION_KIND_FOR_CRS, for converters that classify positions
#: first and then have to describe the frame as a whole.
CRS_KIND_FOR_POSITION: dict[PositionKind, CRSKind] = {
    v: k for k, v in POSITION_KIND_FOR_CRS.items()
}


def crs_kind_for_positions(kinds) -> CRSKind:
    """
    The CRSKind describing a whole acquisition unit, given the position
    kinds its samples actually carry.

    A frame with mixed position kinds is reported UNKNOWN rather than
    resolved to whichever kind is commoner: mixed header quality within one
    line means the line as a whole cannot be characterised, and silently
    picking a majority would be exactly the kind of quiet guess this module
    exists to prevent.
    """
    distinct = set(kinds)
    if len(distinct) == 1:
        return CRS_KIND_FOR_POSITION[PositionKind(next(iter(distinct)))]
    return CRSKind.UNKNOWN


class ControlPoint(BaseModel):
    """
    One asserted correspondence between a frame-local coordinate and a real
    geographic one -- a surveyed line end, a GNSS fix taken at a known
    along-track distance, a mapped waypoint.
    """
    along_track_m: float
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    label: Optional[str] = None


class GeoTie(BaseModel):
    """
    The ONLY sanctioned route from a frame with no Earth reference to a
    geographic one.

    An odometry frame knows how far along its line each trace sits and
    nothing else; a local cartesian frame knows even less. Neither can be
    placed on Earth from its own contents, and guessing is exactly what the
    Position abstraction exists to prevent. A GeoTie is somebody ASSERTING
    the correspondence, with their name on it.

    Positions derived through a tie are geographic, but they are DERIVED --
    the same distinction depth-from-velocity carries. `apply_geo_tie` marks
    every record it touches so a consumer can tell a tied position from a
    measured one.

    `rms_residual_m` is how well the control points agree with a straight
    line. It is None for a two-point tie, because two points define a line
    and cannot disagree with it -- reporting 0.0 there would imply a
    verification that did not happen.
    """
    method: str                      # "endpoints" | "control_points"
    control_points: list[ControlPoint]
    supplied_by: str                 # who asserted this, and on what authority
    #: The ONE acquisition line this tie was surveyed for. A tie describes
    #: how a single line's along-track axis meets the Earth; applying it to
    #: another line would be inventing that line's geometry.
    applies_to: Optional[str] = None
    rms_residual_m: Optional[float] = None
    max_residual_m: Optional[float] = None
    verified: bool = False
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _needs_two_distinct_points(self) -> "GeoTie":
        if len(self.control_points) < 2:
            raise ValueError(
                "a GeoTie needs at least two control points; one point fixes a location "
                "but not the line's bearing, so nothing can be interpolated from it"
            )
        distances = [c.along_track_m for c in self.control_points]
        if len(set(distances)) < len(distances):
            raise ValueError(
                f"control points must sit at distinct along-track distances, got {distances}"
            )
        return self

    @property
    def span_m(self) -> float:
        d = [c.along_track_m for c in self.control_points]
        return max(d) - min(d)


#: The three ways a record can come to have a spatial position. Keeping them
#: distinct is the whole point of registration being additive.
POSITION_NATIVE = "native"          # the acquisition's own coordinate
POSITION_REGISTERED = "registered"  # placed on Earth by a supplied GeoTie
POSITION_DERIVED = "derived"        # computed from a native position + a declared CRS


def effective_position(record):
    """
    The position downstream work should use: the registered one when a tie
    has been applied, otherwise the acquisition's own.

    Never discards the native coordinate -- it stays on `record.position`,
    and `position_provenance` says which of the two this returned.
    """
    registered = getattr(record, "registered_position", None)
    return registered if registered is not None else getattr(record, "position", None)


def along_track_extents_m(records) -> dict[str, float]:
    """
    Per-frame along-track distance, from recorded odometry positions only.

    ONE DEFINITION, used by `dataset_report.build_geometry` (survey volume)
    and `spatial_reference.assess_geometry` (the Stage 8 dimension), so the
    two cannot disagree about the size of the same survey. `max - min` of
    `along_track_m`, per frame, and only when a frame has more than one such
    value -- a single position has no extent to report, and reporting zero
    would look like a measurement rather than an absence.

    NEVER A LINE SPACING, AN ORIENTATION OR A TRAJECTORY. Those need
    Earth-referenced positions to mean anything; an along-track distance
    exists whether or not the acquisition is geolocated at all.
    """
    by_frame: dict[str, list[float]] = {}
    for r in records:
        pos = getattr(r, "position", None)
        if getattr(pos, "kind", None) == PositionKind.ODOMETRY.value:
            by_frame.setdefault(getattr(r, "frame_id", "") or "", []).append(pos.along_track_m)
    return {
        frame_id: round(max(values) - min(values), 3)
        for frame_id, values in by_frame.items()
        if len(values) > 1
    }


def position_provenance(record) -> str:
    """
    Whether a record's effective position is native, registered, or derived.

    A consumer that treats a registered position as if it were surveyed is
    making exactly the mistake this distinction exists to prevent.
    """
    if getattr(record, "registered_position", None) is not None:
        return POSITION_REGISTERED
    pos = getattr(record, "position", None)
    kind = getattr(pos, "kind", None)
    # A geographic view computed from projected coordinates plus a declared
    # CRS is derived, not observed.
    if kind == PositionKind.PROJECTED and getattr(record, "latitude", None) is not None:
        return POSITION_DERIVED
    return POSITION_NATIVE


def has_geographic_coordinates(record) -> bool:
    """
    True when a record's latitude/longitude are REAL, not the legacy
    placeholder.

    Judged on the EFFECTIVE position, so a line registered by a GeoTie
    counts -- its registered position is geographic even though its native
    one is odometry.

    Deliberately strict otherwise: a projected position is not geographic
    even when a declared CRS has produced latitude/longitude for it. Widening
    this to "has non-None lat/lon" immediately mis-classified records built
    with an explicit (0.0, 0.0), which is the exact failure mode this whole
    abstraction exists to prevent.

    This is otherwise simply "is the position geographic". It was briefly more
    than that: KMZ georeferencing used to write real coordinates while
    leaving `position` reporting what the file itself said, so a second
    check on metadata was needed to avoid discarding perfectly good
    coordinates -- a mistake made twice, in lateral-extent measurement and
    in fusion partitioning. KMZ now sets the position too, so there is one
    source of truth and no second check.
    """
    pos = effective_position(record)
    return pos is not None and getattr(pos, "kind", None) == PositionKind.GEOGRAPHIC


def assert_position_matches_ref(position: Position, ref: SpatialRef) -> None:
    """Raises ValueError if a record's position kind contradicts its frame's CRS kind."""
    expected = POSITION_KIND_FOR_CRS[ref.kind]
    if position.kind != expected:
        raise ValueError(
            f"position.kind={position.kind!r} contradicts frame SpatialRef.kind="
            f"{ref.kind.value!r} (which requires {expected.value!r})"
        )
