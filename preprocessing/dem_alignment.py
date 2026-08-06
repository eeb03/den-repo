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

    if dem_crs and dem_crs.to_epsg() not in (4326, None):
        logger.warning(
            f"DEM CRS is {dem_crs} (not EPSG:4326). align_records_with_dem assumes lat/lon "
            f"input matches the DEM's coordinate system; reproject the DEM first if this is wrong."
        )

    if not records:
        return records

    lats = np.array([r.latitude for r in records])
    lons = np.array([r.longitude for r in records])
    elevations = sample_dem_bilinear(band, transform, lats, lons)

    n_aligned = 0
    for r, elev in zip(records, elevations):
        if not np.isnan(elev):
            r.elevation = float(elev)
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
