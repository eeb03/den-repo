"""
M2 adapter migration: every converter emits a SurveyFrame, and coordinates
are represented honestly rather than forced into latitude/longitude.

The LAS section pins a REAL BUG that existed before M2: LASConverter wrote
`latitude=y, longitude=x` straight from the file, so any point cloud in a
projected CRS failed ingest with two pydantic range errors. The path had no
test coverage at all, so nothing caught it. `test_projected_las_*` below is
that missing coverage.
"""
import csv

import numpy as np
import pytest

from converters.csv_converter import CSVConverter
from converters.registry import get_converter
from schemas.spatial import AxisKind, CRSKind, CRSProvenance, PositionKind
from schemas.subterra_record import SensorType

laspy = pytest.importorskip("laspy", reason="laspy not installed")
rasterio = pytest.importorskip("rasterio", reason="rasterio not installed")

# WGS 84 / UTM zone 33N -- the projection covering the INGV-UNISA site.
UTM33N_WKT = (
    'PROJCS["WGS 84 / UTM zone 33N",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",15],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1],AUTHORITY["EPSG","32633"]]'
)
WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]'
)

# Real UTM 33N coordinates near the INGV site (41.05N, 15.01E).
UTM_XY = [(501134.03, 4544705.58), (501140.00, 4544710.00), (501150.00, 4544720.00)]


def _write_las(path, xy, wkt=None, z=120.0):
    """Synthetic LAS fixture. Written with an explicit WKT VLR rather than
    laspy's add_crs(), which requires pyproj (not a dependency here)."""
    from laspy.vlrs.known import WktCoordinateSystemVlr

    xs = np.array([p[0] for p in xy], dtype=float)
    ys = np.array([p[1] for p in xy], dtype=float)
    header = laspy.LasHeader(version="1.4", point_format=6)
    header.offsets = np.array([xs.min(), ys.min(), 0.0])
    header.scales = np.array([0.01, 0.01, 0.01])
    if wkt:
        header.vlrs.append(WktCoordinateSystemVlr(wkt))
    las = laspy.LasData(header)
    las.x, las.y = xs, ys
    las.z = np.full(len(xy), z)
    las.write(str(path))
    return path


# --------------------------------------------------------------------------
# LAS -- the migration that fixes a live bug
# --------------------------------------------------------------------------

@pytest.fixture
def projected_las(tmp_path):
    return _write_las(tmp_path / "utm.las", UTM_XY, wkt=UTM33N_WKT)


def test_projected_las_ingested_at_all(projected_las):
    """
    REGRESSION: before M2 this raised `2 validation errors for SubterraRecord`
    because a UTM northing of 4,544,705 fails `latitude <= 90`.
    """
    from converters.las_converter import LASConverter
    result = LASConverter().load(projected_las, dataset_id="ds", sensor_type=SensorType.LIDAR)
    assert len(result.records) == len(UTM_XY)


def test_projected_las_keeps_native_coordinates_in_position(projected_las):
    from converters.las_converter import LASConverter
    result = LASConverter().load(projected_las, dataset_id="ds", sensor_type=SensorType.LIDAR)
    p = result.records[0].position
    assert p.kind == PositionKind.PROJECTED
    assert (p.easting, p.northing) == pytest.approx(UTM_XY[0], abs=0.01)


def test_projected_las_does_not_put_easting_northing_into_lat_lon(projected_las):
    """The specific defect: projected values must never land in the lat/lon fields."""
    from converters.las_converter import LASConverter
    r = LASConverter().load(projected_las, dataset_id="ds", sensor_type=SensorType.LIDAR).records[0]
    assert -90 <= r.latitude <= 90 and -180 <= r.longitude <= 180
    assert r.latitude != UTM_XY[0][1] and r.longitude != UTM_XY[0][0]
    # reprojected to the real location of the INGV site
    assert r.latitude == pytest.approx(41.0536, abs=0.01)
    assert r.longitude == pytest.approx(15.0135, abs=0.01)


def test_projected_las_frame_records_crs_and_reprojection(projected_las):
    from converters.las_converter import LASConverter
    frame = LASConverter().load(projected_las, dataset_id="ds", sensor_type=SensorType.LIDAR).frames[0]
    assert frame.spatial_ref.kind == CRSKind.PROJECTED
    assert frame.spatial_ref.code == "EPSG:32633"
    assert frame.spatial_ref.horizontal_units == "m"
    assert frame.assumption("crs").verified is True
    reproj = frame.assumption("reprojection")
    assert reproj is not None and "EPSG:4326" in reproj.value and reproj.verified is True
    assert frame.source_metadata["crs_wkt"] is not None


def test_geographic_las_is_used_directly(tmp_path):
    from converters.las_converter import LASConverter
    path = _write_las(tmp_path / "geo.las", [(15.0135, 41.0536)], wkt=WGS84_WKT)
    r = LASConverter().load(path, dataset_id="ds", sensor_type=SensorType.LIDAR).records[0]
    assert r.position.kind == PositionKind.GEOGRAPHIC
    assert (r.latitude, r.longitude) == pytest.approx((41.0536, 15.0135), abs=1e-4)


def test_las_without_crs_but_in_range_is_treated_as_wgs84_unverified(tmp_path):
    from converters.las_converter import LASConverter
    path = _write_las(tmp_path / "nocrs.las", [(15.0135, 41.0536)], wkt=None)
    result = LASConverter().load(path, dataset_id="ds", sensor_type=SensorType.LIDAR)
    assert result.records[0].position.kind == PositionKind.GEOGRAPHIC
    crs = result.frames[0].assumption("crs")
    assert crs.verified is False and "ASSUMED" in crs.basis


def test_projected_las_without_crs_fails_with_an_explicit_message(tmp_path):
    """
    Still unrepresentable while latitude/longitude are required -- but the
    error must say why, instead of a bare pydantic range failure.
    """
    from converters.las_converter import LASConverter
    path = _write_las(tmp_path / "utm_nocrs.las", UTM_XY, wkt=None)
    with pytest.raises(ValueError, match="declares no coordinate system"):
        LASConverter().load(path, dataset_id="ds", sensor_type=SensorType.LIDAR)


def test_las_convert_matches_load_records(projected_las):
    from converters.las_converter import LASConverter
    c = LASConverter()
    a = c.convert(projected_las, dataset_id="ds", sensor_type=SensorType.LIDAR)
    b = c.load(projected_las, dataset_id="ds", sensor_type=SensorType.LIDAR).records
    assert [r.to_flat_dict() for r in a] == [r.to_flat_dict() for r in b]


def test_las_frame_provenance(projected_las):
    from converters.las_converter import LASConverter
    frame = LASConverter().load(projected_las, dataset_id="ds", sensor_type=SensorType.LIDAR).frames[0]
    assert frame.frame_id == "ds:utm"
    assert frame.source_format == "las"
    assert frame.position_index_name == "point_index"
    assert frame.vertical_axis.kind == AxisKind.ELEVATION_M
    assert frame.vertical_axis.positive_down is False
    assert frame.n_positions == len(UTM_XY)


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

@pytest.fixture
def sample_csv(tmp_path):
    path = tmp_path / "survey.csv"
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lat", "lon", "depth", "reading"])
        w.writerow([41.05, 15.01, 1.5, 10.0])
        w.writerow([41.06, 15.02, 2.5, 12.0])
    return path


def test_csv_emits_a_frame_with_assumed_crs(sample_csv):
    result = CSVConverter().load(sample_csv, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)
    frame = result.frames[0]
    assert frame.frame_id == "ds:survey"
    assert frame.spatial_ref.kind == CRSKind.GEOGRAPHIC
    crs = frame.assumption("crs")
    assert crs.verified is False and "ASSUMED" in crs.basis


def test_csv_frame_reports_the_depth_axis_and_detected_columns(sample_csv):
    frame = CSVConverter().load(sample_csv, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER).frames[0]
    assert frame.vertical_axis.kind == AxisKind.DEPTH_M
    assert frame.source_metadata["detected_columns"]["latitude"] == "lat"
    assert frame.n_positions == 2


def test_csv_records_are_geographic_and_linked_to_the_frame(sample_csv):
    result = CSVConverter().load(sample_csv, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)
    assert {r.frame_id for r in result.records} == {"ds:survey"}
    assert {r.position.kind for r in result.records} == {PositionKind.GEOGRAPHIC}


def test_csv_convert_matches_load_records(sample_csv):
    c = CSVConverter()
    a = c.convert(sample_csv, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)
    b = c.load(sample_csv, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER).records
    assert [r.to_flat_dict() for r in a] == [r.to_flat_dict() for r in b]


def test_csv_without_depth_column_reports_no_vertical_axis(tmp_path):
    path = tmp_path / "flat.csv"
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lat", "lon", "reading"])
        w.writerow([41.05, 15.01, 10.0])
    frame = CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.GRAVITY).frames[0]
    assert frame.vertical_axis.kind == AxisKind.NONE


# --------------------------------------------------------------------------
# GeoTIFF -- eager reprojection preserved, native CRS no longer discarded
# --------------------------------------------------------------------------

def _write_geotiff(path, crs, transform, width=6, height=6):
    from rasterio.transform import from_origin
    with rasterio.open(
        str(path), "w", driver="GTiff", width=width, height=height, count=1,
        dtype="float32", crs=crs, transform=transform,
    ) as ds:
        ds.write(np.arange(width * height, dtype="float32").reshape(height, width), 1)
    return path


@pytest.fixture
def utm_geotiff(tmp_path):
    from rasterio.transform import from_origin
    return _write_geotiff(tmp_path / "dem_utm.tif", "EPSG:32633",
                          from_origin(501000.0, 4545000.0, 10.0, 10.0))


@pytest.fixture
def wgs84_geotiff(tmp_path):
    from rasterio.transform import from_origin
    return _write_geotiff(tmp_path / "dem_wgs.tif", "EPSG:4326",
                          from_origin(15.0, 41.1, 0.001, 0.001))


def test_geotiff_still_reprojects_eagerly_to_wgs84(utm_geotiff):
    """Backward compatibility: downstream raster consumers still get lat/lon."""
    from converters.geotiff_converter import GeoTIFFConverter
    result = GeoTIFFConverter().load(utm_geotiff, dataset_id="ds",
                                     sensor_type=SensorType.LIDAR, stride=1)
    r = result.records[0]
    assert r.position.kind == PositionKind.GEOGRAPHIC
    assert -90 <= r.latitude <= 90 and -180 <= r.longitude <= 180
    assert r.latitude == pytest.approx(41.05, abs=0.2)


def test_geotiff_frame_preserves_the_native_crs(utm_geotiff):
    """The native CRS used to be discarded into a per-record metadata string."""
    from converters.geotiff_converter import GeoTIFFConverter
    frame = GeoTIFFConverter().load(utm_geotiff, dataset_id="ds",
                                    sensor_type=SensorType.LIDAR, stride=1).frames[0]
    assert frame.source_metadata["native_crs_epsg"] == 32633
    assert "32633" in frame.source_metadata["native_crs"]
    assert frame.spatial_ref.kind == CRSKind.GEOGRAPHIC   # describes the RECORDS
    assert frame.spatial_ref.code == "EPSG:4326"
    reproj = frame.assumption("reprojection")
    assert reproj is not None and "EPSG:4326" in reproj.value and reproj.verified is True


def test_geotiff_already_in_wgs84_records_no_reprojection(wgs84_geotiff):
    from converters.geotiff_converter import GeoTIFFConverter
    frame = GeoTIFFConverter().load(wgs84_geotiff, dataset_id="ds",
                                    sensor_type=SensorType.SATELLITE, stride=1).frames[0]
    assert frame.assumption("reprojection") is None
    assert frame.assumption("crs").value == "EPSG:4326"


def test_geotiff_convert_matches_load_records(utm_geotiff):
    from converters.geotiff_converter import GeoTIFFConverter
    c = GeoTIFFConverter()
    a = c.convert(utm_geotiff, dataset_id="ds", sensor_type=SensorType.LIDAR, stride=2)
    b = c.load(utm_geotiff, dataset_id="ds", sensor_type=SensorType.LIDAR, stride=2).records
    assert [r.to_flat_dict() for r in a] == [r.to_flat_dict() for r in b]


# --------------------------------------------------------------------------
# every registered converter now emits frames
# --------------------------------------------------------------------------

def test_all_registered_converters_emit_at_least_one_frame_and_link_records(sample_csv, utm_geotiff, projected_las):
    cases = [
        (sample_csv, SensorType.MAGNETOMETER, {}),
        (utm_geotiff, SensorType.LIDAR, {"stride": 1}),
        (projected_las, SensorType.LIDAR, {}),
    ]
    for path, sensor, kw in cases:
        result = get_converter(path).load(path, dataset_id="ds", sensor_type=sensor, **kw)
        assert len(result.frames) == 1, f"{path.name} emitted no frame"
        assert result.frames[0].source_file == path.name
        assert {r.frame_id for r in result.records} == {result.frames[0].frame_id}


# --------------------------------------------------------------------------
# UNRESOLVED PROVENANCE: SEG-Y header positions vs the KMZ survey track
# --------------------------------------------------------------------------
#
# FOLLOW-UP REQUIRED (not resolved by M2, deliberately):
#
#   Validate SEG-Y SourceX/SourceY positions against the KMZ-derived survey
#   track before treating either as authoritative georeferencing.
#
# What is known:
#   - ingestion/kmz_georeference.py documents these headers as ONE static
#     placeholder repeated on every trace of a file.
#   - M1 measured 67 distinct (easting, northing) header pairs across the 72
#     traces of C1T_7,5_0001.SGY. They vary. Both claims cannot be right.
#
# What the validation must do:
#   1. Reproject header easting/northing (UTM 33N) to WGS84 for one line.
#   2. Compare against that line's KMZ polyline: total length, point-to-path
#      residuals, and monotonicity of along-track distance vs trace_index.
#   3. Check both KMZ orderings. A materially better fit in one direction
#      would independently settle the KMZ direction assumption, which
#      georeference_records_by_trace currently records as unverified.
#   4. Only then decide which source populates `position`, and whether the
#      frame's spatial_ref should become GEOGRAPHIC.
#
# Until that is done, ingest keeps BOTH sources and reconciles neither. The
# tests below pin that contract so it cannot drift silently.

def test_kmz_georeferencing_promotes_the_position_and_keeps_header_values():
    """
    M3: a KMZ track is a real geographic position, so it sets `position`.
    The header easting/northing survive in metadata rather than being lost.
    """
    from ingestion.kmz_georeference import georeference_records_by_trace
    from schemas.subterra_record import SubterraRecord
    from schemas.spatial import ProjectedPosition

    records = [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.GPR,
            latitude=0.0, longitude=0.0,
            position=ProjectedPosition(easting=501134.03 + t, northing=4544705.58 + t),
            frame_id="ds:line", depth=0.1 * s, signal=[1.0],
            metadata={"source_file": "line.SGY", "trace_index": t, "sample_index": s},
        )
        for t in range(4) for s in range(2)
    ]
    before = [(r.position.easting, r.position.northing) for r in records]
    for r, (e, n) in zip(records, before):
        r.metadata["segy_x"], r.metadata["segy_y"] = e, n

    georeference_records_by_trace(records, [(15.0, 41.0), (15.01, 41.01)])

    assert all(r.latitude is not None and r.longitude is not None for r in records)
    assert all(r.position.kind == PositionKind.GEOGRAPHIC for r in records)
    # the file's own coordinates are preserved, not discarded
    assert [(r.metadata["segy_x"], r.metadata["segy_y"]) for r in records] == before


def test_the_discrepancy_is_recordable_as_an_unresolved_assumption():
    """
    The architecture must be able to express "two sources disagree and we
    have not settled it" without picking a winner. That is what the ingest
    route attaches when KMZ georeferencing is applied.
    """
    from schemas.spatial import Assumption, SpatialRef, VerticalAxis
    from schemas.survey_frame import SurveyFrame

    frame = SurveyFrame(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy", source_file="line.SGY",
        spatial_ref=SpatialRef(kind=CRSKind.PROJECTED),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="time-zero", positive_down=True),
    )
    frame.assumptions.append(Assumption(
        key="position_source_discrepancy",
        value="latitude/longitude from KMZ track; record.position from the file's own header",
        basis="UNRESOLVED: the two position sources have not been cross-validated.",
        verified=False,
    ))

    recorded = frame.assumption("position_source_discrepancy")
    assert recorded is not None
    assert recorded.verified is False
    assert "UNRESOLVED" in recorded.basis
    # The frame still describes the file's own CRS -- KMZ has not been
    # promoted to authoritative.
    assert frame.spatial_ref.kind == CRSKind.PROJECTED


# --- CSV projected columns ---------------------------------------------------
#
# A CSV declares no coordinate system, and `x`/`y` are lon/lat in one table
# and projected easting/northing in the next. Reading the projected case as
# lon/lat used to fail with an opaque "2 validation errors for
# SubterraRecord" from the schema's range check -- the same defect
# LASConverter had, in a converter that ships by default.

UTM_ROWS = [(501134.03, 4544705.58), (501140.00, 4544710.00), (501150.00, 4544720.00)]


def _csv(tmp_path, name, header, rows):
    path = tmp_path / name
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(list(r) + [1.0])
    return path


def test_projected_xy_without_a_crs_is_rejected_with_a_useful_message(tmp_path):
    """REGRESSION: this used to raise a bare pydantic range error."""
    path = _csv(tmp_path, "utm.csv", ["x", "y", "signal"], UTM_ROWS)
    with pytest.raises(ValueError, match="outside WGS84 lon/lat range"):
        CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)


def test_the_rejection_names_the_remedy(tmp_path):
    path = _csv(tmp_path, "utm.csv", ["x", "y", "signal"], UTM_ROWS)
    with pytest.raises(ValueError) as exc:
        CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)
    assert "crs='EPSG:...'" in str(exc.value)
    assert "somewhere it is not" in str(exc.value)


def test_an_explicit_crs_preserves_native_coordinates(tmp_path):
    path = _csv(tmp_path, "utm.csv", ["x", "y", "signal"], UTM_ROWS)
    result = CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER,
                                 crs="EPSG:32633")
    p = result.records[0].position
    assert p.kind == PositionKind.PROJECTED
    assert (p.easting, p.northing) == pytest.approx(UTM_ROWS[0])


def test_an_explicit_crs_derives_usable_latitude_longitude(tmp_path):
    path = _csv(tmp_path, "utm.csv", ["x", "y", "signal"], UTM_ROWS)
    r = CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER,
                            crs="EPSG:32633").records[0]
    assert r.latitude == pytest.approx(41.0536, abs=0.001)
    assert r.longitude == pytest.approx(15.0135, abs=0.001)


def test_csv_crs_is_recorded_as_caller_supplied(tmp_path):
    path = _csv(tmp_path, "utm.csv", ["x", "y", "signal"], UTM_ROWS)
    frame = CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER,
                                crs="EPSG:32633").frames[0]
    assert frame.spatial_ref.kind == CRSKind.PROJECTED
    assert frame.spatial_ref.code == "EPSG:32633"
    assert frame.spatial_ref.crs_provenance == CRSProvenance.SUPPLIED_BY_CALLER
    assert "DECLARES NO CRS" in frame.spatial_ref.name
    a = frame.assumption("crs_supplied_by_caller")
    assert a is not None and "NOT inferred from the data" in a.basis


def test_an_invalid_csv_crs_fails_explicitly(tmp_path):
    path = _csv(tmp_path, "utm.csv", ["x", "y", "signal"], UTM_ROWS)
    for bad in ("not-a-crs", ""):
        with pytest.raises(ValueError, match="crs"):
            CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER,
                                crs=bad)


def test_named_geographic_columns_are_unaffected(tmp_path):
    """lat/lon columns keep their existing behaviour exactly."""
    path = _csv(tmp_path, "geo.csv", ["lat", "lon", "signal"], [(41.05, 15.01)])
    result = CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)
    r = result.records[0]
    assert r.position.kind == PositionKind.GEOGRAPHIC
    assert (r.latitude, r.longitude) == (41.05, 15.01)
    assert result.frames[0].spatial_ref.crs_provenance == CRSProvenance.INFERRED


def test_ambiguous_xy_in_range_is_read_as_geographic_but_flagged(tmp_path):
    """
    x/y values inside WGS84 range stay readable, but the frame says plainly
    that these column names are ambiguous -- they are easting/northing in
    plenty of tables.
    """
    path = _csv(tmp_path, "xy.csv", ["x", "y", "signal"], [(15.01, 41.05)])
    result = CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)
    assert result.records[0].position.kind == PositionKind.GEOGRAPHIC
    assert "AMBIGUOUS x/y names" in result.frames[0].spatial_ref.name
    assert "Supply crs= explicitly" in result.frames[0].assumption("crs").basis


def test_a_geographic_crs_may_also_be_declared(tmp_path):
    path = _csv(tmp_path, "geo.csv", ["lat", "lon", "signal"], [(41.05, 15.01)])
    result = CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER,
                                 crs="EPSG:4326")
    assert result.records[0].position.kind == PositionKind.GEOGRAPHIC
    assert result.frames[0].spatial_ref.crs_provenance == CRSProvenance.SUPPLIED_BY_CALLER


def test_malformed_rows_are_still_skipped_with_projected_columns(tmp_path):
    path = tmp_path / "mixed.csv"
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["x", "y", "signal"])
        w.writerow([501134.03, 4544705.58, 1.0])
        w.writerow(["bad", 4544710.00, 2.0])
        w.writerow([501150.00, 4544720.00, 3.0])
    result = CSVConverter().load(path, dataset_id="ds", sensor_type=SensorType.MAGNETOMETER,
                                 crs="EPSG:32633")
    assert len(result.records) == 2
    assert result.records[1].position.easting == pytest.approx(501150.00)
