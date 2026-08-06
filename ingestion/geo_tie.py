"""
Promoting an odometry frame to a geographic one, when — and only when —
someone supplies real control points.

An odometry acquisition knows how far along its line each trace sits and
nothing else. Where that line lies on Earth is not recoverable from the
file, at any effort, so the platform records `OdometryPosition` and stops.
This module is the sanctioned way past that: a caller asserts the
correspondence between along-track distance and real coordinates, and takes
responsibility for it.

REGISTRATION, NOT ESTIMATION. A tie never modifies the acquisition. The
registered location goes to `record.registered_position` while
`record.position` keeps the along-track coordinate the instrument actually
measured, so a registration can be corrected, replaced, or thrown away
without having destroyed the measurement underneath it. Three tiers stay
distinguishable through `position_provenance`:

    native      the acquisition's own coordinate
    registered  placed on Earth by a supplied tie
    derived     computed from a native position plus a declared CRS

ONE LINE PER TIE. A tie describes how a single acquisition's along-track
axis meets the Earth. Applying it to a second line would be inventing that
line's geometry, so `applies_to`/`path_id` scopes it and a multi-line input
without one is refused rather than guessed at.

QUALITY IS MEASURED WHERE IT CAN BE. With three or more control points the
tie is checked against a straight line and the residuals are reported: a
survey line that curves will not fit, and the numbers say so. With exactly
two points no check is possible — two points define a line and cannot
disagree with it — so the residual is None rather than a flattering 0.0.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fusion.sensor_fusion import haversine_m
from schemas.spatial import Assumption, ControlPoint, CRSKind, GeoTie, SpatialRef
from schemas.subterra_record import SubterraRecord
from utils.logger import get_logger

logger = get_logger(__name__)

#: A tie whose control points span far less than the line itself is
#: extrapolating rather than interpolating, which is where a small bearing
#: error turns into a large position error.
MIN_SPAN_FRACTION = 0.5


class GeoTieError(ValueError):
    """Raised when a tie cannot be built or applied."""


@dataclass
class TieQuality:
    rms_residual_m: float | None
    max_residual_m: float | None
    n_control_points: int
    checkable: bool
    note: str


def _interpolate(tie: GeoTie, along_track_m: float) -> tuple[float, float]:
    """
    Position at an along-track distance, by linear interpolation between the
    bracketing control points (and linear extrapolation beyond the ends).

    Linear in lat/lon rather than along a great circle: survey lines here are
    metres to hundreds of metres, where the difference is far below the
    metre-level accuracy of the control points themselves.
    """
    points = sorted(tie.control_points, key=lambda c: c.along_track_m)
    d = np.array([c.along_track_m for c in points])
    lat = np.array([c.lat for c in points])
    lon = np.array([c.lon for c in points])
    if along_track_m <= d[0]:
        i = 0
    elif along_track_m >= d[-1]:
        i = len(d) - 2
    else:
        i = int(np.searchsorted(d, along_track_m, side="right") - 1)
    frac = (along_track_m - d[i]) / (d[i + 1] - d[i])
    return (float(lat[i] + frac * (lat[i + 1] - lat[i])),
            float(lon[i] + frac * (lon[i + 1] - lon[i])))


def assess_tie(control_points: list[ControlPoint]) -> TieQuality:
    """
    How well the control points agree with a straight line.

    Two points cannot be checked: they define the line. Three or more can,
    and a curved survey line will show it in the residuals rather than
    silently producing wrong positions in the middle of the line.
    """
    n = len(control_points)
    if n < 3:
        return TieQuality(
            None, None, n, False,
            "two control points define a line and cannot disagree with it; "
            "supply a third to measure whether the line is actually straight",
        )
    points = sorted(control_points, key=lambda c: c.along_track_m)
    d = np.array([c.along_track_m for c in points])
    lat = np.array([c.lat for c in points])
    lon = np.array([c.lon for c in points])
    # Least-squares straight line in each coordinate against along-track
    # distance -- a constant-bearing, constant-speed model.
    lat_fit = np.polyval(np.polyfit(d, lat, 1), d)
    lon_fit = np.polyval(np.polyfit(d, lon, 1), d)
    residuals = np.array([
        haversine_m(lat[i], lon[i], lat_fit[i], lon_fit[i]) for i in range(n)
    ])
    return TieQuality(
        float(np.sqrt(np.mean(residuals ** 2))), float(residuals.max()), n, True,
        "residuals of the control points against a straight-line fit",
    )


def build_geo_tie(control_points: list[ControlPoint], supplied_by: str,
                  method: str = "control_points", notes: str | None = None,
                  max_rms_residual_m: float | None = None,
                  applies_to: str | None = None) -> GeoTie:
    """
    Builds a tie and measures its quality.

    `verified` is set only when the control points were actually CHECKED and
    passed -- three or more points fitting a straight line within
    `max_rms_residual_m`. A two-point tie is usable but never verified,
    because nothing about it was tested.
    """
    quality = assess_tie(control_points)
    verified = False
    if quality.checkable and max_rms_residual_m is not None:
        verified = quality.rms_residual_m <= max_rms_residual_m
        if not verified:
            logger.warning(
                f"build_geo_tie: control points deviate from a straight line by "
                f"{quality.rms_residual_m:.3f} m RMS (max {quality.max_residual_m:.3f} m), "
                f"exceeding the {max_rms_residual_m} m tolerance. The tie is still usable "
                f"but is NOT marked verified."
            )
    return GeoTie(
        method=method, control_points=list(control_points), supplied_by=supplied_by,
        applies_to=applies_to,
        rms_residual_m=quality.rms_residual_m, max_residual_m=quality.max_residual_m,
        verified=verified, notes=notes or quality.note,
    )


def apply_geo_tie(records: list[SubterraRecord], tie: GeoTie,
                  path_id: str | None = None) -> int:
    """
    REGISTERS odometry records against `tie`, additively.

    `record.position` -- the acquisition's own along-track coordinate -- is
    NEVER modified. The registered location is written to
    `record.registered_position`, so a registration can be corrected,
    replaced, or discarded without having destroyed the measurement it was
    computed from. That is the difference between registration and
    estimation.

    Scoped to ONE line. A tie describes how a single acquisition's
    along-track axis meets the Earth; applying it to a second line would be
    inventing that line's geometry. `path_id` selects the line, defaulting
    to the tie's own `applies_to`; if records span several lines and neither
    names one, this refuses rather than guessing.

    Mutates in place and returns how many records were registered.
    """
    from schemas.spatial import GeographicPosition, PositionKind

    odometry = [r for r in records if r.position.kind == PositionKind.ODOMETRY]
    if not odometry:
        raise GeoTieError(
            "no record carries an odometry position, so there is no along-track axis "
            "for this tie to map. A tie applies to the acquisition it was surveyed for."
        )

    target = path_id if path_id is not None else tie.applies_to
    present = {r.position.path_id for r in odometry}
    if target is None:
        if len(present) > 1:
            raise GeoTieError(
                f"these records span {len(present)} survey lines ({sorted(map(str, present))}) "
                f"and the tie does not name one. A tie is surveyed for a single line; applying "
                f"it to another would invent that line's geometry. Set GeoTie.applies_to or "
                f"pass path_id."
            )
    else:
        if target not in present:
            raise GeoTieError(
                f"no record belongs to line {target!r}; lines present: "
                f"{sorted(map(str, present))}"
            )
        odometry = [r for r in odometry if r.position.path_id == target]

    line_span = max(r.position.along_track_m for r in odometry) - \
        min(r.position.along_track_m for r in odometry)
    if line_span > 0 and tie.span_m < MIN_SPAN_FRACTION * line_span:
        logger.warning(
            f"apply_geo_tie: control points span {tie.span_m:.3f} m of a {line_span:.3f} m "
            f"line ({100 * tie.span_m / line_span:.0f}%). Positions outside that span are "
            f"EXTRAPOLATED, where a small bearing error becomes a large position error."
        )

    for r in odometry:
        along = r.position.along_track_m
        lat, lon = _interpolate(tie, along)
        # ADDITIVE: `position` keeps the acquisition's own coordinate.
        r.registered_position = GeographicPosition(lat=lat, lon=lon)
        r.latitude, r.longitude = lat, lon
        r.metadata["along_track_m"] = along
        r.metadata["registration_source"] = "geo_tie"
        r.metadata["registered_by"] = tie.supplied_by
        r.metadata["registration_verified"] = tie.verified

    logger.info(
        f"apply_geo_tie: registered {len(odometry)}/{len(records)} record(s) to geographic "
        f"positions from a tie supplied by {tie.supplied_by!r} "
        f"(verified={tie.verified}, rms={tie.rms_residual_m})"
    )
    return len(odometry)


def tie_assumption(tie: GeoTie) -> Assumption:
    """The frame-level record of what a tie asserted and on whose authority."""
    residual = ("not measurable with two control points" if tie.rms_residual_m is None
                else f"{tie.rms_residual_m:.4f} m RMS against a straight-line fit")
    return Assumption(
        key="geo_tie", value=tie.supplied_by,
        basis=(
            f"SUPPLIED BY CALLER: geographic positions were DERIVED by interpolating "
            f"{len(tie.control_points)} control point(s) spanning {tie.span_m:.3f} m along "
            f"the line, asserted by {tie.supplied_by!r} using method {tie.method!r}. "
            f"Residual: {residual}. These positions were computed from an assertion, not "
            f"observed by an instrument."
        ),
        verified=tie.verified,
    )


def tied_spatial_ref(tie: GeoTie) -> SpatialRef:
    """The frame's reference once a tie has been applied."""
    from schemas.spatial import CRSProvenance

    return SpatialRef(
        kind=CRSKind.GEOGRAPHIC,
        code="EPSG:4326",
        crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER,
        name=(
            f"derived from an along-track GeoTie supplied by {tie.supplied_by!r}; "
            f"the acquisition itself carries no geographic reference"
        ),
        horizontal_units="deg",
    )
