"""
Tests for `scripts.four_tu_topographic_correction_audit`.

SYNTHETIC RASTERS/FIXTURES ONLY, same discipline as
`tests/test_dem_alignment.py` and the BAM audit tests: these pin the
ARITHMETIC (deviation from the line's own median, the material/negligible
threshold, nodata handling) against known, hand-computable numbers -- never
the real 4TU result, which only running the audit against the real archive
and DEM tiles can produce (see
`artifacts/4tu/topographic_correction_audit.json`).
"""
from __future__ import annotations

import numpy as np
import pytest

from ingestion.four_tu_velocity import C_M_PER_NS
from scripts.four_tu_topographic_correction_audit import (
    AuditError,
    TracePoint,
    classify_material,
    height_above_ground,
    run_audit,
)


def _write_tiny_geotiff(path, west, north, pixel_size, size, value, nodata=None):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    transform = from_origin(west, north, pixel_size, pixel_size)
    data = np.full((size, size), value, dtype="float32")
    with rasterio.open(
        str(path), "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform, nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return path


def _point(trace_index, lat, lon, antenna_elevation_m):
    return TracePoint(trace_index, lat, lon, antenna_elevation_m, two_way_time_ns=0.0)


class TestHeightAboveGround:
    def test_flat_ground_deviation_reflects_only_antenna_variation(self, tmp_path):
        """A perfectly flat, constant-elevation DEM: any variation in
        height-above-ground must come entirely from the antenna's own
        elevation changes, and deviation is centred on the line's median."""
        dem_path = _write_tiny_geotiff(tmp_path / "flat.tif", west=6.0, north=52.5,
                                       pixel_size=0.001, size=50, value=10.0)
        lat, lon = 52.48, 6.02  # comfortably inside the tile
        points = [
            _point(0, lat, lon, 20.0),
            _point(1, lat, lon, 20.1),  # +0.1 m antenna elevation
            _point(2, lat, lon, 19.9),  # -0.1 m antenna elevation
        ]
        result = height_above_ground(points, dem_path)
        assert result["n_valid"] == 3
        dev = result["per_trace_deviation_m"]
        # ground is constant (10.0), so height_above_ground is 10.0, 10.1, 9.9;
        # median 10.0 -> deviations 0.0, +0.1, -0.1
        assert dev[0] == pytest.approx(0.0, abs=1e-6)
        assert dev[1] == pytest.approx(0.1, abs=1e-6)
        assert dev[2] == pytest.approx(-0.1, abs=1e-6)

    def test_a_constant_datum_offset_between_sources_cancels_out(self, tmp_path):
        """The whole point of using deviation-from-median rather than the
        absolute height-above-ground: a constant vertical-datum bias
        between the DEM and the antenna elevation must not appear in the
        deviation at all."""
        dem_path = _write_tiny_geotiff(tmp_path / "flat.tif", west=6.0, north=52.5,
                                       pixel_size=0.001, size=50, value=10.0)
        lat, lon = 52.48, 6.02
        # antenna elevations carry a large, arbitrary +1000 m constant bias
        # relative to the DEM's own datum, plus the same real +-0.1 m signal.
        points = [
            _point(0, lat, lon, 1020.0),
            _point(1, lat, lon, 1020.1),
            _point(2, lat, lon, 1019.9),
        ]
        result = height_above_ground(points, dem_path)
        dev = result["per_trace_deviation_m"]
        assert dev[0] == pytest.approx(0.0, abs=1e-6)
        assert dev[1] == pytest.approx(0.1, abs=1e-6)
        assert dev[2] == pytest.approx(-0.1, abs=1e-6)

    def test_a_nodata_cell_is_excluded_not_blended_into_a_garbage_value(self, tmp_path):
        """
        Regression test for a real bug this audit's own development run
        hit: without masking the DEM's nodata sentinel to NaN before
        bilinear interpolation, a point near a nodata cell blends a real
        elevation with the sentinel (here 3.4e38, matching the real AHN
        product) into a physically absurd multi-order-of-magnitude value
        instead of a clean exclusion.
        """
        rasterio = pytest.importorskip("rasterio")
        from rasterio.transform import from_origin

        nodata_value = 3.4028234663852886e38
        size = 10
        transform = from_origin(6.0, 52.5, 0.001, 0.001)
        data = np.full((size, size), 10.0, dtype="float32")
        data[0, 0] = nodata_value  # one corner cell is nodata
        dem_path = tmp_path / "with_nodata.tif"
        with rasterio.open(
            str(dem_path), "w", driver="GTiff", height=size, width=size, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform, nodata=nodata_value,
        ) as dst:
            dst.write(data, 1)

        # a point whose bilinear neighbourhood includes the nodata corner
        lat, lon = 52.5 - 0.0002, 6.0 + 0.0002
        points = [_point(0, lat, lon, 20.0)]
        result = height_above_ground(points, dem_path)
        # excluded entirely (NaN after interpolation), not a garbage number
        assert result["n_valid"] == 0

    def test_points_outside_the_tile_are_excluded(self, tmp_path):
        dem_path = _write_tiny_geotiff(tmp_path / "flat.tif", west=6.0, north=52.5,
                                       pixel_size=0.001, size=10, value=10.0)
        points = [_point(0, 60.0, 6.0, 20.0)]  # far outside the tile
        result = height_above_ground(points, dem_path)
        assert result["n_valid"] == 0


class TestClassifyMaterial:
    def test_a_correction_smaller_than_the_sample_interval_is_not_material(self):
        # deviation of 1 cm -> two-way air time = 2*0.01/C_M_PER_NS ~= 0.0667 ns
        deviation = {0: 0.01, 1: -0.01}
        result = classify_material(deviation, sample_interval_ns=1.0)
        assert result["material"] is False

    def test_a_correction_larger_than_the_sample_interval_is_material(self):
        # deviation of 0.5 m -> two-way air time = 2*0.5/C_M_PER_NS ~= 3.34 ns
        deviation = {0: 0.5, 1: -0.5}
        result = classify_material(deviation, sample_interval_ns=1.0)
        assert result["material"] is True

    def test_the_correction_arithmetic_matches_the_stated_formula(self):
        deviation = {0: 0.1}
        result = classify_material(deviation, sample_interval_ns=0.01)
        expected_ns = 2 * 0.1 / C_M_PER_NS
        assert result["per_trace_correction_ns"][0] == pytest.approx(expected_ns, abs=1e-9)

    def test_no_deviation_data_is_reported_honestly_not_material(self):
        result = classify_material({}, sample_interval_ns=1.0)
        assert result["material"] is False
        assert "reason" in result


class TestRunAudit:
    def test_missing_segy_file_raises_audit_error(self, tmp_path):
        with pytest.raises(AuditError):
            run_audit("nonexistent", "does/not/exist.sgy", "site01")
