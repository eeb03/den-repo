"""
Reprojection between declared coordinate reference systems.

WHY rasterio AND NOT pyproj. pyproj is the canonical Python binding for
PROJ, but rasterio is already a dependency of this project and already
ships PROJ; `rasterio.warp.transform` performs exactly this transform and
is already used by the GeoTIFF, LAS, CSV and SEG-Y converters. Adding
pyproj would mean two sets of PROJ bindings for one capability. If a future
need arises that rasterio cannot serve — pipelines, geodetic operations,
datum transformation pipelines with explicit epochs — that is the moment to
add it, not before.

WHAT THIS DOES NOT DO. It never infers a CRS. A transform happens only
between two systems that were explicitly DECLARED, and a frame whose
`spatial_ref.code` is None is not transformable at any effort. Coordinates
produced here are DERIVED: they are as good as the declaration they came
from, and the caller is expected to keep saying so.
"""
from __future__ import annotations

from functools import lru_cache

from converters.base import MissingDependencyError
from utils.logger import get_logger

logger = get_logger(__name__)

WGS84 = "EPSG:4326"


class CRSTransformError(ValueError):
    """Raised when a declared CRS cannot be interpreted or transformed."""


def _rasterio():
    try:
        from rasterio.crs import CRS
        from rasterio.warp import transform as rio_transform
    except ImportError as e:                       # pragma: no cover - dependency guard
        raise MissingDependencyError(
            "rasterio is required to transform between coordinate reference systems. "
            "Install with: pip install rasterio"
        ) from e
    return CRS, rio_transform


@lru_cache(maxsize=64)
def parse_crs(code: str):
    """Parses a declared CRS identifier. Cached: fusion asks repeatedly."""
    CRS, _ = _rasterio()
    try:
        return CRS.from_user_input(code)
    except Exception as e:
        raise CRSTransformError(
            f"could not interpret the declared CRS {code!r}; give an unambiguous "
            f"identifier such as 'EPSG:32633'"
        ) from e


@lru_cache(maxsize=64)
def is_transformable(code: str | None) -> bool:
    """
    Whether coordinates in this CRS can be brought to WGS84.

    None is not transformable and never becomes so: a projected position
    with no declared CRS is a pair of numbers whose meaning is unknown.
    """
    if not code:
        return False
    try:
        parse_crs(code)
        return True
    except (CRSTransformError, MissingDependencyError):
        return False


def to_wgs84(code: str, eastings, northings) -> list[tuple[float, float]]:
    """
    Transforms declared coordinates to (lat, lon) in WGS84.

    Vectorised deliberately: fusion transforms whole partitions at once, and
    a per-record call would dominate the cost of clustering.
    """
    _, rio_transform = _rasterio()
    crs = parse_crs(code)
    eastings, northings = list(eastings), list(northings)
    if not eastings:
        return []
    if crs.is_geographic:
        # Already lon/lat in this CRS; no transform, but the axis order of
        # the stored pair is still (easting=lon, northing=lat).
        return [(float(n), float(e)) for e, n in zip(eastings, northings)]
    lons, lats = rio_transform(crs, WGS84, eastings, northings)
    return [(float(a), float(b)) for a, b in zip(lats, lons)]
