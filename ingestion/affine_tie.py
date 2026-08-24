"""
Promoting a frame with a genuine 2D local coordinate to a geographic one,
when -- and only when -- someone supplies real control points.

A frame whose native position is `LocalCartesianPosition` (a real (x, y),
the origin and orientation known only to the sensor) has no defined
relationship to the Earth at all, and none is recoverable from the file at
any effort -- exactly the situation `ingestion.geo_tie` already solves for
odometry frames, except that mechanism is parameterised by a single scalar
(`along_track_m`) and cannot consume a genuine 2D coordinate: applying it
here would mean inventing an along-track axis that does not exist.

REGISTRATION, NOT ESTIMATION -- identical philosophy to `ingestion.geo_tie`,
restated for the reader who lands here first: a tie never modifies the
acquisition. The registered location goes to `record.registered_position`
while `record.position` keeps the local coordinate the instrument actually
reported, so a registration can be corrected, replaced, or discarded
without destroying the measurement underneath it.

THE MODEL. A full 2D affine map (six free parameters) fit by ordinary least
squares, independently per output coordinate -- see `schemas.spatial.AffineTie`
for why an affine model was chosen over a similarity or rigid one. Three
non-collinear control points determine it exactly; four or more make it
checkable, and the residuals (converted to metres via the same haversine
distance `ingestion.geo_tie` uses) are reported rather than hidden.

WHAT THIS DELIBERATELY DOES NOT DO. It does not repair a degenerate
control-point set -- collinear points, duplicates, or a numerically
unstable fit are refused outright, never guessed past. It does not infer
which records to register from a filename or a bounding box; a tie applies
only to records whose OWN position already carries the 2D local coordinate
this module reads.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fusion.sensor_fusion import haversine_m
from schemas.spatial import AffineControlPoint, AffineTie, AffineTieStatus, Assumption, CRSKind
from schemas.subterra_record import SubterraRecord
from utils.logger import get_logger

logger = get_logger(__name__)

#: Below this rank / above this condition number, the control-point
#: geometry cannot determine a numerically trustworthy affine map -- three
#: points that are exactly collinear are rank-deficient; three that are
#: nearly collinear are technically full rank but the fit amplifies any
#: measurement noise in the control points into a large position error.
#: 1e8 is the standard rule-of-thumb boundary for "still solvable in
#: double precision but not to be trusted" (a well-posed geodetic fit at
#: this scale conditions many orders of magnitude better than this).
MAX_CONDITION_NUMBER = 1e8


class AffineTieError(ValueError):
    """Raised when an affine tie cannot be fit or applied."""


@dataclass
class AffineFitQuality:
    rms_residual_m: float | None
    max_residual_m: float | None
    n_control_points: int
    checkable: bool
    note: str


def _design_matrix(points: list[AffineControlPoint]) -> np.ndarray:
    return np.column_stack([
        [p.x for p in points],
        [p.y for p in points],
        np.ones(len(points)),
    ])


def _assert_finite(points: list[AffineControlPoint]) -> None:
    values = [v for p in points for v in (p.x, p.y, p.lat, p.lon)]
    if not all(np.isfinite(v) for v in values):
        raise AffineTieError(
            "control points contain a non-finite value (NaN or infinity); every x, y, "
            "lat and lon must be a real number"
        )


def _assert_well_conditioned(matrix: np.ndarray) -> None:
    """
    Refuses collinear (rank-deficient) and near-collinear (numerically
    unstable) control-point geometry alike, rather than fitting a map that
    happens to solve but cannot be trusted.
    """
    rank = np.linalg.matrix_rank(matrix)
    if rank < 3:
        raise AffineTieError(
            "control points are collinear (or otherwise degenerate): a 2D affine map "
            "needs three points that are not all on one line, and this configuration "
            f"has rank {rank} of the 3 needed"
        )
    condition = np.linalg.cond(matrix)
    if not np.isfinite(condition) or condition > MAX_CONDITION_NUMBER:
        raise AffineTieError(
            f"control points are numerically unstable for a 2D affine fit (condition "
            f"number {condition:.3g}, exceeding {MAX_CONDITION_NUMBER:.0g}); the points "
            "are close enough to collinear that small measurement noise would produce "
            "a large position error, so this configuration is refused rather than fit"
        )


def fit_affine(control_points: list[AffineControlPoint]) -> tuple[tuple[float, ...], AffineFitQuality]:
    """
    Fits `lat = a*x + b*y + e` and `lon = c*x + d*y + f` by ordinary least
    squares, and reports the fit's residuals in metres.

    Returns `((a, b, e, c, d, f), quality)`. Raises `AffineTieError` for
    fewer than three points, non-finite values, or a degenerate/unstable
    configuration -- never silently returns a map fit to bad geometry.
    """
    if len(control_points) < 3:
        raise AffineTieError(
            "an affine fit needs at least three control points; a 2D affine map has six "
            "unknowns and three non-collinear point correspondences are the minimum that "
            "can determine it"
        )
    _assert_finite(control_points)
    matrix = _design_matrix(control_points)
    _assert_well_conditioned(matrix)

    lats = np.array([p.lat for p in control_points])
    lons = np.array([p.lon for p in control_points])
    (a, b, e), *_ = np.linalg.lstsq(matrix, lats, rcond=None)
    (c, d, f), *_ = np.linalg.lstsq(matrix, lons, rcond=None)

    n = len(control_points)
    if n == 3:
        # Six unknowns, six independent equations (three points, two
        # coordinates each): the fit is exact by construction. Reporting a
        # residual of 0.0 here would look like a verification that did not
        # happen -- the same reasoning GeoTie applies to a two-point tie.
        quality = AffineFitQuality(
            None, None, n, False,
            "three points determine a 2D affine map exactly and cannot disagree with it; "
            "supply a fourth to measure whether the map actually explains the data",
        )
    else:
        pred_lat = matrix @ np.array([a, b, e])
        pred_lon = matrix @ np.array([c, d, f])
        residuals = np.array([
            haversine_m(lats[i], lons[i], pred_lat[i], pred_lon[i]) for i in range(n)
        ])
        quality = AffineFitQuality(
            float(np.sqrt(np.mean(residuals ** 2))), float(residuals.max()), n, True,
            "residuals of the control points against the fitted affine map",
        )
    return (float(a), float(b), float(e), float(c), float(d), float(f)), quality


def build_affine_tie(control_points: list[AffineControlPoint], supplied_by: str,
                     notes: str | None = None, max_rms_residual_m: float | None = None,
                     applies_to: str | None = None) -> AffineTie:
    """
    Fits a tie and classifies it -- the 2D counterpart of `ingestion.geo_tie.build_geo_tie`.

    `verified` is set only when the fit was actually CHECKED and passed --
    four or more points fitting the affine map within `max_rms_residual_m`.
    An exact three-point tie is usable but never verified, because nothing
    about it was tested. `status` mirrors that: REGISTERED unless a
    tolerance was supplied and exceeded, in which case
    REGISTERED_WITH_HIGH_RESIDUAL says so explicitly rather than leaving a
    caller to compare numbers itself.
    """
    (a, b, e, c, d, f), quality = fit_affine(control_points)
    verified = False
    status = AffineTieStatus.REGISTERED
    if quality.checkable and max_rms_residual_m is not None:
        verified = quality.rms_residual_m <= max_rms_residual_m
        if not verified:
            status = AffineTieStatus.REGISTERED_WITH_HIGH_RESIDUAL
            logger.warning(
                f"build_affine_tie: control points deviate from the fitted affine map by "
                f"{quality.rms_residual_m:.3f} m RMS (max {quality.max_residual_m:.3f} m), "
                f"exceeding the {max_rms_residual_m} m tolerance. The tie is still usable "
                f"but is NOT marked verified."
            )
    return AffineTie(
        control_points=list(control_points), supplied_by=supplied_by, applies_to=applies_to,
        a=a, b=b, e=e, c=c, d=d, f=f,
        rms_residual_m=quality.rms_residual_m, max_residual_m=quality.max_residual_m,
        verified=verified, status=status, notes=notes or quality.note,
    )


def invert_affine(tie: AffineTie) -> tuple[float, float, float, float, float, float]:
    """
    The inverse map's coefficients: given (lat, lon), recovers (x, y).

    Exists so a registration can be checked by round-tripping a control
    point, and so a consumer can go from a registered position back to the
    sensor-native frame without re-deriving the algebra. Raises
    `AffineTieError` if the linear part is singular -- which the fit's own
    conditioning check makes unreachable for a tie this module produced,
    but this function does not assume that and checks again, since a tie
    could in principle be constructed by hand (`AffineTie(...)` directly)
    without ever going through `fit_affine`.
    """
    linear = np.array([[tie.a, tie.b], [tie.c, tie.d]])
    det = np.linalg.det(linear)
    if not np.isfinite(det) or abs(det) < 1e-12:
        raise AffineTieError(
            f"this affine tie's linear part is singular (determinant {det:.3g}) and cannot "
            "be inverted"
        )
    inv = np.linalg.inv(linear)
    translation = np.array([tie.e, tie.f])
    # (lat, lon) = linear @ (x, y) + translation  =>  (x, y) = inv @ ((lat, lon) - translation)
    ia, ib = inv[0]
    ic, id_ = inv[1]
    it = -inv @ translation
    return float(ia), float(ib), float(it[0]), float(ic), float(id_), float(it[1])


def apply_affine_tie(records: list[SubterraRecord], tie: AffineTie,
                     path_id: str | None = None) -> int:
    """
    REGISTERS local-cartesian records against `tie`, additively -- the 2D
    counterpart of `ingestion.geo_tie.apply_geo_tie`.

    `record.position` -- the acquisition's own local (x, y) -- is NEVER
    modified. The registered location is written to
    `record.registered_position`, so a registration can be corrected,
    replaced, or discarded without having destroyed the measurement it was
    computed from.

    Scoped to ONE frame, exactly as a `GeoTie` is scoped to one line: a tie
    describes how a single frame's local coordinate meets the Earth, and
    applying it to a different frame's coordinates would invent that
    frame's geometry. `path_id`/`applies_to` name it; a mixed input without
    one is refused rather than guessed at.

    Mutates in place and returns how many records were registered.
    """
    from schemas.spatial import GeographicPosition, PositionKind

    local = [r for r in records if r.position.kind == PositionKind.LOCAL_CARTESIAN]
    if not local:
        raise AffineTieError(
            "no record carries a local-cartesian position, so there is no 2D local "
            "coordinate for this tie to map. An affine tie applies to the frame it was "
            "surveyed for."
        )

    target = path_id if path_id is not None else tie.applies_to
    present = {r.frame_id for r in local}
    if target is None:
        if len(present) > 1:
            raise AffineTieError(
                f"these records span {len(present)} frame(s) ({sorted(map(str, present))}) "
                f"and the tie does not name one. A tie is surveyed for a single frame; "
                f"applying it to another would invent that frame's geometry. Set "
                f"AffineTie.applies_to or pass path_id."
            )
    else:
        if target not in present:
            raise AffineTieError(
                f"no record belongs to frame {target!r}; frames present: "
                f"{sorted(map(str, present))}"
            )
        local = [r for r in local if r.frame_id == target]

    for r in local:
        x, y = r.position.x, r.position.y
        lat = tie.a * x + tie.b * y + tie.e
        lon = tie.c * x + tie.d * y + tie.f
        # ADDITIVE: `position` keeps the acquisition's own coordinate.
        r.registered_position = GeographicPosition(lat=lat, lon=lon)
        r.latitude, r.longitude = lat, lon
        r.metadata["local_x"], r.metadata["local_y"] = x, y
        r.metadata["registration_source"] = "affine_tie"
        r.metadata["registered_by"] = tie.supplied_by
        r.metadata["registration_verified"] = tie.verified

    logger.info(
        f"apply_affine_tie: registered {len(local)}/{len(records)} record(s) to geographic "
        f"positions from a tie supplied by {tie.supplied_by!r} "
        f"(verified={tie.verified}, status={tie.status.value}, rms={tie.rms_residual_m})"
    )
    return len(local)


def affine_tie_assumption(tie: AffineTie) -> Assumption:
    """The frame-level record of what a tie asserted and on whose authority."""
    residual = ("not measurable with three control points" if tie.rms_residual_m is None
                else f"{tie.rms_residual_m:.4f} m RMS against the fitted affine map")
    return Assumption(
        key="affine_tie", value=tie.supplied_by,
        basis=(
            f"SUPPLIED BY CALLER: geographic positions were DERIVED from a 2D affine map "
            f"fit to {len(tie.control_points)} control point(s), asserted by "
            f"{tie.supplied_by!r}. Residual: {residual}. Status: {tie.status.value}. "
            f"These positions were computed from an assertion, not observed by an "
            f"instrument."
        ),
        verified=tie.verified,
    )


def tied_spatial_ref_for_affine(tie: AffineTie):
    """The frame's reference once an affine tie has been applied."""
    from schemas.spatial import CRSProvenance, SpatialRef

    return SpatialRef(
        kind=CRSKind.GEOGRAPHIC,
        code="EPSG:4326",
        crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER,
        name=(
            f"derived from a 2D affine tie supplied by {tie.supplied_by!r}; the "
            f"acquisition itself carries no geographic reference"
        ),
        horizontal_units="deg",
    )
