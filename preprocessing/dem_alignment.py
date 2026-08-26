"""
DEM alignment: looks up ground-surface elevation from a GeoTIFF DEM at each
record's (lat, lon) via bilinear interpolation, so a sensor's `depth` field
(depth below the local survey datum) can be paired with a real elevation
(depth below true ground surface). Also computes each record's absolute
elevation (surface elevation - depth) into metadata, which is what the
upcoming 3D viewer/fusion module needs to place GPR readings and DEM
surface in the same vertical reference frame.

Assumes a north-up (no rotation) GeoTIFF in EPSG:4326 — true for
OpenTopography's globaldem/usgsdem API output, which is the DEM source
the ingestion/sources.py connector uses.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from converters.base import MissingDependencyError
from schemas.spatial import has_geographic_coordinates
from schemas.subterra_record import SubterraRecord
from utils.logger import get_logger

logger = get_logger(__name__)


def sample_dem_bilinear(band: np.ndarray, transform, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """
    Vectorized bilinear sampling of a raster band at arbitrary (lat, lon)
    points. Returns NaN for points outside the raster or falling on a
    nodata pixel. `transform` is a rasterio/affine Affine (assumed
    north-up: no row/column rotation, true for standard GeoTIFFs).
    """
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)

    col = (lons - transform.c) / transform.a
    row = (lats - transform.f) / transform.e

    col0 = np.floor(col).astype(int)
    row0 = np.floor(row).astype(int)
    col1 = col0 + 1
    row1 = row0 + 1
    fcol = col - col0
    frow = row - row0

    n_rows, n_cols = band.shape
    valid = (col0 >= 0) & (col1 < n_cols) & (row0 >= 0) & (row1 < n_rows)

    c0 = np.clip(col0, 0, n_cols - 1)
    c1 = np.clip(col1, 0, n_cols - 1)
    r0 = np.clip(row0, 0, n_rows - 1)
    r1 = np.clip(row1, 0, n_rows - 1)

    top = band[r0, c0] * (1 - fcol) + band[r0, c1] * fcol
    bottom = band[r1, c0] * (1 - fcol) + band[r1, c1] * fcol
    interp = top * (1 - frow) + bottom * frow

    result = np.full(lats.shape, np.nan)
    result[valid] = interp[valid]
    # a NaN corner (nodata pixel) poisons the interpolated value too
    result[np.isnan(result) & valid] = np.nan
    return result


def align_records_with_dem(records: list[SubterraRecord], dem_path: str | Path) -> list[SubterraRecord]:
    """
    Sets `record.elevation` to the DEM's ground-surface elevation at each
    record's (lat, lon), and — when the record has a `depth` — stores the
    resulting absolute elevation of the sensed feature
    (surface elevation - depth) in `record.metadata["absolute_elevation_m"]`.

    Two SEPARATE compatibility concerns, only one of which is checked:
    - HORIZONTAL CRS (checked below): whether the DEM's (lat, lon) grid
      uses the same coordinate reference system as `record.latitude`/
      `record.longitude`.
    - VERTICAL DATUM (NOT checked, NOT converted): whether the DEM's
      elevation VALUES (e.g. Copernicus GLO-30/COP30's EGM2008 geoid
      heights) share a common vertical reference with any other elevation
      source a caller might combine with this one. This function only
      ever uses ONE elevation source (the DEM itself) internally, so no
      cross-source vertical mismatch is possible in what it computes
      today -- but if a second independent elevation source (e.g. a GPS
      antenna height, typically WGS84 ellipsoidal) is ever combined with
      `record.elevation` downstream, they must first be reconciled to a
      common vertical datum; this function has no way to detect or warn
      about that at the point such a combination happens.
    """
    try:
        import rasterio
    except ImportError as e:
        raise MissingDependencyError(
            "rasterio is required for DEM alignment. Install with: pip install rasterio"
        ) from e

    dem_path = Path(dem_path)
    if not dem_path.exists():
        raise FileNotFoundError(f"DEM file not found: {dem_path}")

    with rasterio.open(str(dem_path)) as ds:
        band = ds.read(1).astype(float)
        if ds.nodata is not None:
            band[band == ds.nodata] = np.nan
        transform = ds.transform
        dem_crs = ds.crs

    logger.info(
        "DEM alignment: vertical datum is NOT validated or converted -- elevation values are used "
        "as-is from the DEM (e.g. COP30 reports EGM2008 geoid heights, not WGS84 ellipsoidal height). "
        "If a second elevation source is ever combined with this one, reconcile datums first."
    )

    if not records:
        return records

    # A DEM lookup needs a real geographic position. Records without one are
    # skipped rather than sampled at a placeholder coordinate.
    positioned = [r for r in records if has_geographic_coordinates(r)]
    if not positioned:
        logger.warning(
            f"DEM alignment: none of the {len(records)} record(s) carry a geographic "
            f"position, so no elevation can be looked up. Nothing was changed."
        )
        return records
    if len(positioned) < len(records):
        logger.warning(
            f"DEM alignment: {len(records) - len(positioned)} of {len(records)} record(s) "
            f"have no geographic position and were skipped."
        )
    records_to_align = positioned
    lats = np.array([r.latitude for r in records_to_align])
    lons = np.array([r.longitude for r in records_to_align])

    if dem_crs and dem_crs.to_epsg() not in (4326, None):
        # The DEM's own grid is in a different (typically projected) CRS --
        # e.g. AHN's EPSG:28992 (Dutch RD New, metres). `sample_dem_bilinear`
        # indexes the raster in the DEM's OWN units, so comparing raw WGS84
        # degree values against it always misses: a record's real (lat, lon)
        # is a small number of degrees, the DEM's transform origin is in
        # metres in the hundreds of thousands, so bilinear sampling reads
        # far outside the raster's bounds on every point and returns NaN for
        # all of them. Confirmed live against a real AHN tile: 0 of 160,768
        # real, correctly-decoded record positions matched before this fix,
        # despite the exact same file/DEM pair matching successfully in
        # `scripts/four_tu_topographic_correction_audit.py`, which already
        # reprojects with this SAME rasterio.warp.transform call -- reused
        # here, not reimplemented.
        from rasterio.warp import transform as rio_transform
        eastings, northings = rio_transform("EPSG:4326", dem_crs, lons.tolist(), lats.tolist())
        sample_lats, sample_lons = np.array(northings), np.array(eastings)
    else:
        sample_lats, sample_lons = lats, lons

    elevations = sample_dem_bilinear(band, transform, sample_lats, sample_lons)

    n_aligned = 0
    # zip against the FILTERED list: `elevations` was sampled from it, so
    # zipping against `records` would assign one record's elevation to another.
    for r, elev in zip(records_to_align, elevations):
        if not np.isnan(elev):
            if r.elevation is not None and "pre_dem_elevation_m" not in r.metadata:
                # This record already carried an elevation before DEM
                # alignment -- e.g. 4TU's own per-trace antenna GNSS
                # reading, parsed at ingest into `record.elevation`. That
                # value is about to be overwritten with the DEM's GROUND
                # elevation below; preserving it here is what lets a later
                # topographic/air-gap correction (`preprocessing.
                # topographic_correction`) recover BOTH elevations for the
                # same record instead of only ever seeing the DEM's.
                # Guarded so a second `align_dem` call never clobbers the
                # real original with an already-DEM-derived value.
                r.metadata["pre_dem_elevation_m"] = r.elevation
            r.elevation = float(elev)
            r.metadata["dem_vertical_datum_verified"] = False
            n_aligned += 1
            if r.depth is not None:
                r.metadata["absolute_elevation_m"] = float(elev) - r.depth

    logger.info(f"DEM alignment: assigned elevation to {n_aligned}/{len(records)} records from {dem_path.name}")
    if n_aligned == 0:
        logger.warning(
            "DEM alignment matched 0 records — the DEM tile likely doesn't cover this dataset's "
            "bounding box. Fetch a DEM for the dataset's actual lat/lon extent."
        )
    return records
