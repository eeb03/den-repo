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
