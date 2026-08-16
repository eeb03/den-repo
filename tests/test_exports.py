"""
Export framework.

Two things are protected here:

  1. Nothing is silently dropped. Every exporter reports what it skipped and
     why, so exporting 100 objects and receiving 40 features tells you which
     60 could not be placed.
  2. No format emits a coordinate it does not have. GeoJSON skips rather than
     writing a null geometry; CZML omits height rather than sending 0, which
     Cesium draws at sea level; 3D Tiles refuses outright, because it needs an
     absolute elevation that no held dataset has.
"""
import csv as _csv
import io

import pytest

from exports.exporters import (
    EXPORT_FORMATS, ExportRefused, export_csv, export_czml, export_geojson,
    export_json, export_objects, export_3d_tiles,
)
from schemas.objects import ObservationKind, ObservationRef, build_object
from schemas.spatial import GeographicPosition, OdometryPosition


def _obs(oid, frame="ds:l1", lat=None, lon=None):
    pos = (GeographicPosition(lat=lat, lon=lon) if lat is not None
           else OdometryPosition(along_track_m=3.0, path_id="l"))
    return ObservationRef(kind=ObservationKind.CANDIDATE, dataset_id="ds",
                          observation_id=oid, frame_id=frame, position=pos)


@pytest.fixture()
def objects():
    placed = build_object("ds", [_obs("c1", "ds:l1", 52.0, 6.0),
                                 _obs("c2", "ds:l2", 52.0, 6.0)])
    unplaced = build_object("ds", [_obs("c3", "ds:l3")])
    return [placed, unplaced]


# --- full-fidelity formats keep everything ---

def test_json_export_keeps_every_object_including_unplaced(objects):
    payload, report = export_json(objects)
    assert payload["count"] == 2
    assert report["skipped"] == []
    assert "nothing was transformed" in payload["crs"]


def test_csv_names_the_position_kind_so_an_easting_is_not_read_as_a_longitude(objects):
    payload, report = export_csv(objects)
    rows = list(_csv.DictReader(io.StringIO(payload)))
    assert len(rows) == 2
    kinds = {r["position_kind"] for r in rows}
    assert kinds == {"geographic", "none"}
    unplaced = next(r for r in rows if r["position_kind"] == "none")
    assert unplaced["lat"] == "" and unplaced["position_absent_reason"]


def test_csv_of_nothing_is_empty_not_a_header_of_lies():
    payload, report = export_csv([])
    assert payload == "" and report["written"] == 0


# --- geojson skips rather than inventing a geometry ---

def test_geojson_exports_only_placeable_features(objects):
    doc, report = export_geojson(objects)
    assert len(doc["features"]) == 1
    assert report["written"] == 1
    assert doc["features"][0]["geometry"]["coordinates"] == [6.0, 52.0]  # lon, lat


def test_geojson_reports_what_it_skipped_and_why(objects):
    doc, report = export_geojson(objects)
    assert doc["skipped_count"] == 1
    skipped = report["skipped"][0]
    assert skipped["position_kind"] == "none"
    assert "cannot be placed on Earth" in skipped["reason"]


def test_no_geojson_feature_ever_has_a_null_geometry(objects):
    doc, _ = export_geojson(objects)
    assert all(f["geometry"] is not None and f["geometry"]["coordinates"]
               for f in doc["features"])


def test_geojson_marks_its_coordinates_derived(objects):
    doc, _ = export_geojson(objects)
    props = doc["features"][0]["properties"]
    assert props["coordinate_provenance"] == "derived"
    assert "centroid of" in props["coordinate_basis"]
    assert "RFC 7946" in doc["crs_note"]


# --- czml omits height rather than sending sea level ---

def test_czml_omits_height_and_says_why(objects):
    packets, report = export_czml(objects)
    doc = packets[0]
    assert doc["id"] == "document"
    assert "Heights are OMITTED" in doc["description"]
    feature = packets[1]
    assert feature["position"]["heightReference"] == "CLAMP_TO_GROUND"
    assert report["written"] == 1


def test_czml_skips_unplaceable_objects_with_a_reason(objects):
    _, report = export_czml(objects)
    assert len(report["skipped"]) == 1
    assert report["skipped"][0]["reason"]


# --- 3d tiles refuses ---

def test_3d_tiles_refuses_for_every_dataset_currently_held(objects):
    with pytest.raises(ExportRefused) as e:
        export_3d_tiles(objects)
    msg = str(e.value)
    assert "absolute elevation" in msg
    assert "instrument time-zero" in msg
    assert "would fabricate" in msg
    assert "vertical-reference-site01.md" in msg


def test_3d_tiles_refusal_names_what_would_unblock_it(objects):
    with pytest.raises(ExportRefused) as e:
        export_3d_tiles(objects)
    assert "Supply a vertical registration" in str(e.value)


def test_3d_tiles_is_not_hard_coded_shut(objects):
    """With a real vertical relationship it fails for a DIFFERENT reason."""
    with pytest.raises(ExportRefused) as e:
        export_3d_tiles(objects, vertical={"absolute_elevation_available": True})
    assert "not implemented" in str(e.value)
    assert "fabricate" not in str(e.value)


# --- Phase 7, ninth slice: off-gpr default refusal names the composition,
# --- still applies (same rule as scene_3d) --------------------------------

def test_off_gpr_default_refusal_names_the_composition_and_still_applies(objects):
    with pytest.raises(ExportRefused) as e:
        export_3d_tiles(objects, recorded_modalities=["lidar"])
    msg = str(e.value)
    assert "lidar" in msg
    assert "applies to it" in msg
    assert "does not apply" not in msg
    assert "GPR depth" not in msg
    assert "instrument time-zero" not in msg
    assert "propagation velocity" not in msg
    assert "would fabricate" in msg
    assert "vertical-reference-site01.md" in msg
    assert "Supply a vertical registration" in msg


def test_off_gpr_with_a_real_absolute_elevation_still_hits_not_implemented(objects):
    with pytest.raises(ExportRefused) as e:
        export_3d_tiles(objects, recorded_modalities=["lidar"],
                        vertical={"absolute_elevation_available": True})
    assert "not implemented" in str(e.value)
    assert "lidar" not in str(e.value)


def test_off_gpr_with_a_real_unresolved_vertical_is_byte_identical(objects):
    vertical = {"absolute_elevation_available": False, "kind": "registration_required"}
    with pytest.raises(ExportRefused) as with_composition:
        export_3d_tiles(objects, recorded_modalities=["lidar"], vertical=vertical)
    with pytest.raises(ExportRefused) as without:
        export_3d_tiles(objects, vertical=vertical)
    assert str(with_composition.value) == str(without.value)


@pytest.mark.parametrize("composition", [["gpr"], ["gpr", "lidar"], [], None])
def test_gpr_mixed_empty_and_omitted_keep_the_time_zero_sentence(objects, composition):
    with pytest.raises(ExportRefused) as e:
        export_3d_tiles(objects, recorded_modalities=composition)
    with pytest.raises(ExportRefused) as default:
        export_3d_tiles(objects)
    assert "instrument time-zero" in str(e.value)
    assert str(e.value) == str(default.value)


# --- dispatch ---

@pytest.mark.parametrize("fmt", ["json", "csv", "geojson", "czml"])
def test_every_non_refusing_format_dispatches(objects, fmt):
    payload, report = export_objects(objects, fmt)
    assert payload is not None
    assert "written" in report and "skipped" in report


def test_an_unknown_format_is_refused():
    with pytest.raises(ValueError) as e:
        export_objects([], "shapefile")
    assert "unknown export format" in str(e.value)


def test_the_format_list_is_exactly_what_dispatch_accepts():
    assert set(EXPORT_FORMATS) == {"json", "csv", "geojson", "czml", "3d_tiles"}


# --- API ---

@pytest.fixture()
def client(tmp_path, monkeypatch, objects):
    import database.objects_store as os_
    monkeypatch.setattr(os_, "_assoc_path", lambda d: tmp_path / f"{d}.associations.json")
    monkeypatch.setattr(os_, "_object_path", lambda d: tmp_path / f"{d}.objects.json")
    os_.replace_objects("ds", objects)
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def test_the_format_list_says_which_carry_full_provenance(client):
    body = client.get("/api/exports/formats").json()
    full = {f["value"] for f in body["formats"] if f["carries_full_provenance"]}
    assert full == {"json", "csv"}
    assert "nothing is silently dropped" in body["rule"]


def test_exporting_geojson_over_the_api_reports_the_skip(client):
    body = client.get("/api/exports/ds/objects?format=geojson").json()
    assert body["report"]["written"] == 1
    assert len(body["report"]["skipped"]) == 1


def test_exporting_csv_returns_text_with_counts_in_headers(client):
    r = client.get("/api/exports/ds/objects?format=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["X-Subterra-Written"] == "2"
    assert r.headers["X-Subterra-Skipped"] == "0"


def test_requesting_3d_tiles_is_a_409_with_the_reason(client):
    r = client.get("/api/exports/ds/objects?format=3d_tiles")
    assert r.status_code == 409          # well-formed request, data cannot support it
    assert "absolute elevation" in r.json()["detail"]
    # This dataset has objects and no stored frames or records, so the
    # composition is empty and the default time-zero sentence still fires.
    assert "instrument time-zero" in r.json()["detail"]


def test_requesting_3d_tiles_over_the_api_for_an_off_gpr_dataset(client, monkeypatch):
    import api.routes.exports as mod
    from schemas.spatial import AxisKind, CRSKind, CRSProvenance, SpatialRef, VerticalAxis
    from schemas.subterra_record import SensorType
    from schemas.survey_frame import SurveyFrame

    lidar_frame = SurveyFrame(
        frame_id="ds:tile", dataset_id="ds", modality=SensorType.LIDAR,
        source_format="geotiff", source_file="tile.tif",
        spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326", horizontal_units="degree",
                               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER),
        vertical_axis=VerticalAxis(kind=AxisKind.DEPTH_M, units="m",
                                   origin="surface", positive_down=True),
    )
    monkeypatch.setattr(mod, "load_frames", lambda _id: [lidar_frame])
    monkeypatch.setattr(mod, "load_records", lambda _id: [])

    r = client.get("/api/exports/ds/objects?format=3d_tiles")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "lidar" in detail
    assert "instrument time-zero" not in detail


def test_requesting_3d_tiles_over_the_api_for_a_gpr_dataset_keeps_the_reason(client, monkeypatch):
    import api.routes.exports as mod
    from schemas.spatial import AxisKind, CRSKind, CRSProvenance, SpatialRef, VerticalAxis
    from schemas.subterra_record import SensorType
    from schemas.survey_frame import SurveyFrame

    gpr_frame = SurveyFrame(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy", source_file="line.sgy",
        spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326", horizontal_units="degree",
                               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="time-zero", positive_down=True),
    )
    monkeypatch.setattr(mod, "load_frames", lambda _id: [gpr_frame])
    monkeypatch.setattr(mod, "load_records", lambda _id: [])

    r = client.get("/api/exports/ds/objects?format=3d_tiles")
    assert r.status_code == 409
    assert "instrument time-zero" in r.json()["detail"]


def test_an_unknown_format_over_the_api_is_a_400(client):
    assert client.get("/api/exports/ds/objects?format=shapefile").status_code == 400


def test_exporting_a_dataset_with_no_objects_is_a_404(client):
    assert client.get("/api/exports/nothing/objects").status_code == 404
