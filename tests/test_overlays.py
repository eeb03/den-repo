"""
Cross-sensor overlays.

The thing being protected here is that layers are NOT flattened. A viewer
must be able to see which numbers a sensor measured and which a transform
produced, and a layer that cannot be placed on Earth must stay visibly
unplaced rather than acquiring a default coordinate.

So the tests assert, in order of importance:

  - every layer keeps its native CRS and native extent;
  - a WGS84 extent, when present, is marked derived -- except for a layer
    that was already geographic, which is marked measured;
  - a layer with no declared CRS is NOT placeable, however plausible its
    numbers, and makes the whole composition `not_relatable`;
  - horizontal overlap never implies a vertical relationship.
"""
import glob
import os
from pathlib import Path

import pytest

from schemas.overlays import (
    LayerExtent, OverlayLayer, SpatialRelationship, build_layer, compose,
)
from schemas.provenance import ProvenanceClass
from schemas.spatial import (
    AxisKind, CRSKind, CRSProvenance, GeographicPosition, LocalCartesianPosition,
    NoPosition, OdometryPosition, ProjectedPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame

GPR_DIR = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted/01")
AHN = Path("datasets/raw/pdok_ahn/dtm_05m/AHN_DTM_05m_site01.tif")
REAL = pytest.mark.skipif(not (GPR_DIR.exists() and AHN.exists()),
                          reason="4TU site 01 or AHN not present locally")


def _frame(ref, fid="ds:f", modality=SensorType.GPR):
    return SurveyFrame.model_construct(
        frame_id=fid, dataset_id="ds", modality=modality, source_format="test",
        source_file="f", spatial_ref=ref,
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="instrument time-zero", positive_down=True),
        assumptions=[], source_metadata={})


def _records(position_factory, n=5, fid="ds:f"):
    return [SubterraRecord(dataset_id="ds", sensor_type=SensorType.GPR,
                           position=position_factory(i), frame_id=fid,
                           signal=[1.0], metadata={}) for i in range(n)]


# --- native coordinates survive ---

def test_a_projected_layer_keeps_its_native_extent_and_crs():
    ref = SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:28992",
                     crs_provenance=CRSProvenance.DECLARED_BY_SOURCE, name="declared",
                     horizontal_units="m")
    recs = _records(lambda i: ProjectedPosition(easting=255000.0 + i,
                                                northing=473300.0 + i))
    layer = build_layer(_frame(ref), recs)
    assert layer.extent.native_crs == "EPSG:28992"
    assert layer.extent.native_kind == "projected"
    assert layer.extent.native_min_x == 255000.0
    assert layer.extent.native_max_y == 473304.0


def test_a_projected_layers_map_position_is_marked_derived():
    ref = SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:28992",
                     crs_provenance=CRSProvenance.DECLARED_BY_SOURCE, name="declared",
                     horizontal_units="m")
    layer = build_layer(_frame(ref), _records(
        lambda i: ProjectedPosition(easting=255000.0 + i, northing=473300.0 + i)))
    assert layer.extent.wgs84_provenance == ProvenanceClass.DERIVED
    assert "own coordinates are unchanged" in layer.extent.wgs84_basis
    assert 52.0 < layer.extent.wgs84_min_lat < 53.0


def test_a_geographic_layer_is_not_relabelled_as_derived():
    """It was already geographic; claiming a transform happened would be false."""
    ref = SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                     crs_provenance=CRSProvenance.INFERRED, name="inferred",
                     horizontal_units="deg")
    layer = build_layer(_frame(ref), _records(
        lambda i: GeographicPosition(lat=52.0 + i * 1e-4, lon=6.0)))
    assert layer.extent.wgs84_provenance == ProvenanceClass.MEASURED
    assert "no transform applied" in layer.extent.wgs84_basis


# --- what cannot be placed stays unplaced ---

def test_a_projected_layer_with_no_declared_crs_is_not_placeable():
    ref = SpatialRef(kind=CRSKind.PROJECTED, code=None,
                     crs_provenance=CRSProvenance.NONE, name="undeclared",
                     horizontal_units="m")
    layer = build_layer(_frame(ref), _records(
        lambda i: ProjectedPosition(easting=255000.0 + i, northing=473300.0 + i)))
    assert layer.extent.is_placeable is False
    assert "nothing is inferred from the magnitude" in layer.extent.wgs84_basis
    # ...but its own numbers are still carried
    assert layer.extent.native_min_x == 255000.0


@pytest.mark.parametrize("kind,factory", [
    (CRSKind.ACQUISITION, lambda i: OdometryPosition(along_track_m=float(i), path_id="l")),
    (CRSKind.ENGINEERING, lambda i: LocalCartesianPosition(x=float(i), y=0.0)),
])
def test_odometry_and_local_layers_are_not_placeable(kind, factory):
    ref = SpatialRef(kind=kind, name="acquisition-only", horizontal_units="m")
    layer = build_layer(_frame(ref), _records(factory))
    assert layer.extent.is_placeable is False
    assert "until someone supplies a tie" in layer.extent.wgs84_basis


def test_an_unplaceable_layer_makes_the_composition_not_relatable():
    good = build_layer(
        _frame(SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                          crs_provenance=CRSProvenance.INFERRED, name="g",
                          horizontal_units="deg"), fid="ds:g"),
        _records(lambda i: GeographicPosition(lat=52.0, lon=6.0), fid="ds:g"))
    bad = build_layer(
        _frame(SpatialRef(kind=CRSKind.ACQUISITION, name="odometry",
                          horizontal_units="m"), fid="ds:o"),
        _records(lambda i: OdometryPosition(along_track_m=float(i), path_id="l"),
                 fid="ds:o"))
    c = compose([good, bad])
    assert c.spatial_relationship == SpatialRelationship.NOT_RELATABLE
    assert c.unplaceable_layers == ["ds:o"]
    assert "no amount of processing resolves it" in c.spatial_basis.lower()
    assert any("must not be drawn at a default coordinate" in n for n in c.notes)


def test_a_layer_with_no_positions_at_all_is_not_placeable():
    ref = SpatialRef(kind=CRSKind.UNKNOWN, name="none")
    layer = build_layer(_frame(ref), _records(
        lambda i: NoPosition(reason="the headers are (0, 0)")))
    assert layer.extent.is_placeable is False
    assert layer.extent.n_positions_sampled == 0


# --- relationships ---

def _placeable(fid, lat, lon):
    ref = SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                     crs_provenance=CRSProvenance.INFERRED, name="g",
                     horizontal_units="deg")
    return build_layer(_frame(ref, fid=fid),
                       _records(lambda i: GeographicPosition(lat=lat, lon=lon), fid=fid))


def test_overlapping_layers_are_co_registered():
    c = compose([_placeable("a", 52.0, 6.0), _placeable("b", 52.0, 6.0)])
    assert c.spatial_relationship == SpatialRelationship.CO_REGISTERED


def test_separated_layers_are_disjoint_not_co_registered():
    c = compose([_placeable("a", 52.0, 6.0), _placeable("b", 51.0, 4.0)])
    assert c.spatial_relationship == SpatialRelationship.DISJOINT
    assert "expecting them to align is not" in c.spatial_basis


def test_the_suggested_view_is_labelled_a_hint_not_a_coordinate_system():
    c = compose([_placeable("a", 52.0, 6.0), _placeable("b", 51.0, 4.0)])
    assert c.suggested_view["min_lat"] == 51.0
    assert "NOT a coordinate system the layers were converted into" in \
        c.suggested_view["basis"]


def test_a_composition_of_one_placeable_layer_is_co_registered():
    assert compose([_placeable("a", 52.0, 6.0)]).spatial_relationship == \
        SpatialRelationship.CO_REGISTERED


# --- vertical is a separate question ---

def test_horizontal_overlap_does_not_imply_a_vertical_relationship():
    gpr = _frame(SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                            crs_provenance=CRSProvenance.INFERRED, name="g",
                            horizontal_units="deg"), fid="ds:gpr")
    surface = SurveyFrame.model_construct(
        frame_id="ds:dem", dataset_id="ds", modality=SensorType.LIDAR,
        source_format="geotiff", source_file="d",
        spatial_ref=SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:28992",
                               crs_provenance=CRSProvenance.DECLARED_BY_SOURCE,
                               name="declared", horizontal_units="m"),
        vertical_axis=VerticalAxis(kind=AxisKind.ELEVATION_M, units="m",
                                   origin="raster band 1 value", positive_down=False),
        assumptions=[], source_metadata={})
    c = compose([_placeable("a", 52.0, 6.0)],
                subsurface_frame=gpr, surface_frame=surface)
    assert c.vertical_relationship["absolute_elevation_available"] is False
    assert any("says nothing about depth" in n for n in c.notes)


# --- real multi-sensor data ---

@REAL
def test_real_gpr_and_ahn_compose_without_either_being_flattened():
    from converters.geotiff_converter import GeoTIFFConverter
    from converters.segy_converter import SEGYConverter
    f = sorted(glob.glob(str(GPR_DIR / "**/*.sgy"), recursive=True),
               key=os.path.getsize)[0]
    g = SEGYConverter().load(Path(f), dataset_id="gpr", sensor_type=SensorType.GPR,
                             coordinate_encoding="ieee_nmea", velocity_m_per_ns=0.0999)
    a = GeoTIFFConverter().load(AHN, dataset_id="ahn", sensor_type=SensorType.LIDAR,
                                stride=60, reproject=False)
    lg = build_layer(g.frames[0], g.records[:3000])
    la = build_layer(a.frames[0], a.records)

    # each keeps its own reference
    assert lg.extent.native_kind == "geographic"
    assert la.extent.native_kind == "projected" and la.extent.native_crs == "EPSG:28992"
    assert la.extent.native_min_x > 250_000            # still RD metres, not degrees
    assert la.extent.wgs84_provenance == ProvenanceClass.DERIVED

    c = compose([lg, la], subsurface_frame=g.frames[0], surface_frame=a.frames[0])
    assert c.spatial_relationship == SpatialRelationship.CO_REGISTERED
    assert c.vertical_relationship["kind"] == "registration_required"
    assert any("DERIVED by transforming" in n for n in c.notes)


@REAL
def test_a_real_layer_reports_its_unknowns():
    from converters.segy_converter import SEGYConverter
    f = sorted(glob.glob(str(GPR_DIR / "**/*.sgy"), recursive=True),
               key=os.path.getsize)[0]
    g = SEGYConverter().load(Path(f), dataset_id="gpr", sensor_type=SensorType.GPR,
                             coordinate_encoding="ieee_nmea")
    layer = build_layer(g.frames[0], g.records[:1000])
    assert any("vertical datum" in u for u in layer.unknowns)
    assert layer.provenance_summary["weakest_class"] == "unavailable"


# --- API ---

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def test_the_vocabulary_says_which_relationships_are_safe_to_draw(client):
    body = client.get("/api/overlays/vocabulary").json()
    unsafe = {r["value"] for r in body["spatial_relationships"]
              if not r["safe_to_draw_together"]}
    assert unsafe == {"not_relatable"}
    assert any("nothing is flattened server-side" in r for r in body["rules"])
    assert any("says nothing about depth" in r for r in body["rules"])


def test_layers_for_an_unknown_dataset_is_a_404(client):
    assert client.get("/api/overlays/no-such-dataset/layers").status_code == 404


def test_composing_with_no_matching_frames_is_a_404(client):
    r = client.post("/api/overlays/compose",
                    json={"datasets": ["no-such-dataset"]})
    assert r.status_code == 404
