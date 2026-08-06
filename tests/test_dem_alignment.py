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
