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


def test_align_records_with_dem_preserves_a_pre_existing_elevation(tmp_path):
    """
    A record that already carries its own elevation (e.g. 4TU's antenna GNSS
    reading, parsed at ingest) must not lose it silently when DEM alignment
    overwrites `record.elevation` with ground-surface elevation -- the prior
    value survives in metadata for a later topographic correction to read.
    """
    from preprocessing.dem_alignment import align_records_with_dem

    dem_path = _write_tiny_geotiff(tmp_path / "flat3.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR, latitude=41.0 - 0.03, longitude=15.0 + 0.03,
            elevation=251.4, depth=1.0, signal=[1.0],
        )
    ]

    aligned = align_records_with_dem(records, dem_path)

    assert aligned[0].elevation == pytest.approx(250.0)
    assert aligned[0].metadata["pre_dem_elevation_m"] == pytest.approx(251.4)


def test_align_records_with_dem_running_twice_does_not_clobber_the_original(tmp_path):
    """A second align_dem call must not overwrite the preserved original with the now-DEM-derived value from the first call."""
    from preprocessing.dem_alignment import align_records_with_dem

    dem_path = _write_tiny_geotiff(tmp_path / "flat4.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR, latitude=41.0 - 0.03, longitude=15.0 + 0.03,
            elevation=251.4, depth=1.0, signal=[1.0],
        )
    ]

    once = align_records_with_dem(records, dem_path)
    twice = align_records_with_dem(once, dem_path)

    assert twice[0].metadata["pre_dem_elevation_m"] == pytest.approx(251.4)


def test_align_records_with_dem_leaves_no_prior_elevation_field_absent(tmp_path):
    """The common case -- a sensor with no elevation of its own -- must stay a no-op for pre_dem_elevation_m: nothing existed to preserve."""
    from preprocessing.dem_alignment import align_records_with_dem

    dem_path = _write_tiny_geotiff(tmp_path / "flat5.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR, latitude=41.0 - 0.03, longitude=15.0 + 0.03,
            depth=1.0, signal=[1.0],
        )
    ]

    aligned = align_records_with_dem(records, dem_path)

    assert "pre_dem_elevation_m" not in aligned[0].metadata


def _write_projected_geotiff(path, epsg, west, north, pixel_size, size, value):
    """A GeoTIFF in a PROJECTED CRS (metres), unlike _write_tiny_geotiff's EPSG:4326 tiles."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    transform = from_origin(west, north, pixel_size, pixel_size)
    data = np.full((size, size), value, dtype="float32")
    with rasterio.open(
        str(path), "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs=f"EPSG:{epsg}", transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


def test_align_records_with_dem_reprojects_a_dem_in_a_projected_crs(tmp_path):
    """
    Regression test for a real bug caught live: a DEM in a projected CRS
    (e.g. AHN's EPSG:28992, Dutch RD New, metres) was being sampled with raw
    WGS84 degree values, which fall nowhere near a transform whose origin is
    in the hundreds of thousands of metres -- every real point missed, 0
    aligned, even though the record's real position is genuinely covered by
    the tile once reprojected correctly.
    """
    pytest.importorskip("rasterio")
    from rasterio.warp import transform as rio_transform

    from preprocessing.dem_alignment import align_records_with_dem

    lon, lat = 6.851548258463541, 52.23896484375
    easting, northing = rio_transform("EPSG:4326", "EPSG:28992", [lon], [lat])
    dem_path = _write_projected_geotiff(
        tmp_path / "rd_new.tif", epsg=28992,
        west=easting[0] - 50, north=northing[0] + 50, pixel_size=1.0, size=200, value=12.3,
    )
    records = [SubterraRecord(
        dataset_id="d", sensor_type=SensorType.GPR, latitude=lat, longitude=lon,
        depth=1.0, signal=[1.0],
    )]

    aligned = align_records_with_dem(records, dem_path)

    assert aligned[0].elevation == pytest.approx(12.3)


def test_align_records_with_dem_still_works_for_an_unprojected_dem(tmp_path):
    """The common case (EPSG:4326, e.g. OpenTopography output) must be unaffected by the reprojection branch."""
    from preprocessing.dem_alignment import align_records_with_dem

    dem_path = _write_tiny_geotiff(tmp_path / "wgs84.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)
    records = [SubterraRecord(
        dataset_id="d", sensor_type=SensorType.GPR, latitude=41.0 - 0.03, longitude=15.0 + 0.03,
        depth=1.0, signal=[1.0],
    )]

    aligned = align_records_with_dem(records, dem_path)

    assert aligned[0].elevation == pytest.approx(250.0)


def test_align_records_with_dem_with_count_reports_zero_when_nothing_matched(tmp_path):
    """
    Regression test for a real reporting bug: a record that already carries
    an elevation of its own (e.g. an antenna reading) before alignment ever
    runs must not make the count claim it was aligned when the DEM tile
    does not actually cover it.
    """
    from preprocessing.dem_alignment import align_records_with_dem_with_count

    dem_path = _write_tiny_geotiff(tmp_path / "elsewhere.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)
    records = [SubterraRecord(
        dataset_id="d", sensor_type=SensorType.GPR,
        latitude=60.0, longitude=30.0,  # nowhere near the tile
        elevation=99.0, depth=1.0, signal=[1.0],
    )]

    aligned, n_aligned = align_records_with_dem_with_count(records, dem_path)

    assert n_aligned == 0
    assert aligned[0].elevation == pytest.approx(99.0)  # untouched, not silently claimed aligned
    assert "pre_dem_elevation_m" not in aligned[0].metadata


def test_align_records_with_dem_with_count_reports_the_real_match_count(tmp_path):
    from preprocessing.dem_alignment import align_records_with_dem_with_count

    dem_path = _write_tiny_geotiff(tmp_path / "here.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR,
                       latitude=41.0 - 0.03, longitude=15.0 + 0.03, depth=1.0, signal=[1.0]),
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR,
                       latitude=60.0, longitude=30.0, depth=1.0, signal=[1.0]),  # outside the tile
    ]

    aligned, n_aligned = align_records_with_dem_with_count(records, dem_path)

    assert n_aligned == 1
    assert aligned[0].elevation == pytest.approx(250.0)
    assert aligned[1].elevation is None


def test_align_records_with_dem_wrapper_still_returns_a_plain_list(tmp_path):
    """Backward compatibility for every existing caller of align_records_with_dem."""
    from preprocessing.dem_alignment import align_records_with_dem

    dem_path = _write_tiny_geotiff(tmp_path / "plain.tif", west=15.0, north=41.0, pixel_size=0.01, size=10, value=250.0)
    records = [SubterraRecord(
        dataset_id="d", sensor_type=SensorType.GPR,
        latitude=41.0 - 0.03, longitude=15.0 + 0.03, depth=1.0, signal=[1.0],
    )]

    result = align_records_with_dem(records, dem_path)

    assert isinstance(result, list)
    assert result[0].elevation == pytest.approx(250.0)


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
