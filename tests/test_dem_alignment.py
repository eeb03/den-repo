import numpy as np
import pytest

from preprocessing.dem_alignment import sample_dem_bilinear
from schemas.subterra_record import SubterraRecord, SensorType


class FakeAffine:
    """Minimal north-up affine transform stand-in (mirrors rasterio's Affine interface subset used here)."""
    def __init__(self, a, c, e, f):
        self.a, self.c, self.e, self.f = a, c, e, f


def _make_linear_dem(n_rows=10, n_cols=10, pixel_size=0.001, west=25.0, north=46.0):
    transform = FakeAffine(a=pixel_size, c=west, e=-pixel_size, f=north)
    band = np.zeros((n_rows, n_cols))
    for r in range(n_rows):
        for c in range(n_cols):
            band[r, c] = 100 + c * 10 + r * 5
    return band, transform, pixel_size, west, north


def test_bilinear_exact_pixel_corner_matches():
    band, transform, pixel_size, west, north = _make_linear_dem()
    row, col = 3, 4
    lon = west + col * pixel_size
    lat = north + row * (-pixel_size)
    val = sample_dem_bilinear(band, transform, [lat], [lon])[0]
    assert abs(val - band[row, col]) < 1e-9


def test_bilinear_midpoint_is_average_of_neighbors():
    band, transform, pixel_size, west, north = _make_linear_dem()
    row, col = 3, 4
    lat = north + row * (-pixel_size)
    lon = west + col * pixel_size + pixel_size / 2
    val = sample_dem_bilinear(band, transform, [lat], [lon])[0]
    expected = (band[row, col] + band[row, col + 1]) / 2
    assert abs(val - expected) < 1e-9


def test_bilinear_out_of_bounds_returns_nan():
    band, transform, *_ = _make_linear_dem()
    val = sample_dem_bilinear(band, transform, [50.0], [30.0])[0]
    assert np.isnan(val)


def test_bilinear_handles_multiple_points_vectorized():
    band, transform, pixel_size, west, north = _make_linear_dem()
    lats = [north, north - pixel_size, 90.0]  # last one out of bounds
    lons = [west, west + pixel_size, -180.0]
    vals = sample_dem_bilinear(band, transform, lats, lons)
    assert not np.isnan(vals[0])
    assert not np.isnan(vals[1])
    assert np.isnan(vals[2])


def _write_tiny_geotiff(path, west, north, pixel_size, size, value):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    transform = from_origin(west, north, pixel_size, pixel_size)
    data = np.full((size, size), value, dtype="float32")
    with rasterio.open(
        str(path), "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


def test_align_records_with_dem_gives_shared_elevation_and_depth_varying_absolute_elevation(tmp_path):
    """
    Regression coverage for the real multi-sample-per-trace GPR shape:
    several depth samples sharing ONE (lat, lon) position (one trace) must
    get the SAME DEM surface elevation but a DIFFERENT absolute_elevation_m
    (surface - depth) that varies correctly with each sample's own real depth.
    """
    from preprocessing.dem_alignment import align_records_with_dem

    dem_path = _write_tiny_geotiff(tmp_path / "flat.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)

    lat, lon = 41.0 - 0.03, 15.0 + 0.03  # comfortably inside the tile
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR, latitude=lat, longitude=lon,
            depth=d, signal=[1.0], metadata={"trace_index": 0, "source_file": "line.SGY"},
        )
        for d in [0.0, 1.0, 2.0, 3.0, 4.0]
    ]

    aligned = align_records_with_dem(records, dem_path)

    elevations = {r.elevation for r in aligned}
    assert len(elevations) == 1  # same position -> same surface elevation
    surface_elev = aligned[0].elevation
    assert surface_elev is not None
    for r in aligned:
        assert abs(r.metadata["absolute_elevation_m"] - (surface_elev - r.depth)) < 1e-6


def test_align_records_with_dem_flags_vertical_datum_as_unverified(tmp_path):
    """DEM elevation values (e.g. COP30's EGM2008 geoid heights) are used as-is, with no vertical-datum check or conversion -- must be visible in metadata, distinct from the horizontal CRS check."""
    from preprocessing.dem_alignment import align_records_with_dem

    dem_path = _write_tiny_geotiff(tmp_path / "flat2.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR, latitude=41.0 - 0.03, longitude=15.0 + 0.03,
            depth=1.0, signal=[1.0],
        )
    ]

    aligned = align_records_with_dem(records, dem_path)

    assert aligned[0].elevation is not None
    assert aligned[0].metadata["dem_vertical_datum_verified"] is False
