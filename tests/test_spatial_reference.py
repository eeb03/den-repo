"""
The spatial reference workflow.

WHAT THESE DEFEND. Stage 8 lets a person assert how a dataset relates to the
physical world, which is the most dangerous kind of write this platform has:
every one of these declarations, taken as a measurement, would put a
reconstruction somewhere nobody surveyed. So the tests are mostly about the
distinctions that must survive a user typing into a box:

    coordinates exist        != coordinates are correct
    a CRS is declared        != a CRS is validated
    a time axis exists       != a physical depth exists
    a DEM exists             != a usable surface reference exists
    relative geometry exists != absolute geolocation exists

Six datasets are constructed, one per spatial state the brief names, because the
six datasets actually held are unresolved for the same reasons and a corpus-only
suite would pass with most of this broken.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import spatial as service
from api.main import app
from database.models import Dataset, FusionSample, SpatialDeclaration
from database.session import Base, get_db
from schemas.spatial import (
    AxisKind,
    CRSKind,
    CRSProvenance,
    GeographicPosition,
    NoPosition,
    OdometryPosition,
    ProjectedPosition,
    SpatialRef,
    VerticalAxis,
    VerticalDatum,
)
from schemas.spatial_reference import (
    DeclarationKind,
    SpatialDimension,
    assess_spatial_reference,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame

pytestmark = pytest.mark.real_auth

PASSWORD = "spatial-workflow-password"

GEOGRAPHIC = SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                        crs_provenance=CRSProvenance.DECLARED_BY_SOURCE, horizontal_units="deg")
PROJECTED_UNDECLARED = SpatialRef(kind=CRSKind.PROJECTED)
ACQUISITION = SpatialRef(kind=CRSKind.ACQUISITION,
                         origin_description="along-track distance from line start")
INFERRED = SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:32635",
                      crs_provenance=CRSProvenance.INFERRED)

TIME_AXIS = VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                         origin="instrument time zero", positive_down=True, n_samples=512)
DEPTH_DERIVED = VerticalAxis(kind=AxisKind.DEPTH_M, units="m", origin="instrument time zero",
                             positive_down=True,
                             conversion={"method": "constant_velocity", "v": 0.1})
SURFACE_BARE = VerticalAxis(kind=AxisKind.NONE, units="", origin="unrecorded",
                            positive_down=True)
SURFACE_GOOD = VerticalAxis(
    kind=AxisKind.ELEVATION_M, units="m", origin="NAP", positive_down=False,
    vertical_datum=VerticalDatum(code="NAP", provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                                 name="NAP"))


def frame(frame_id="d:line1", *, crs=GEOGRAPHIC, axis=TIME_AXIS, dataset_id="d",
          n_positions=10, assumptions=None, geo_tie=None):
    return SurveyFrame(
        frame_id=frame_id, dataset_id=dataset_id, modality=SensorType.GPR,
        source_format="segy", source_file=f"{frame_id}.sgy",
        spatial_ref=crs, vertical_axis=axis, n_positions=n_positions,
        assumptions=assumptions or [], geo_tie=geo_tie)


def record(i, position=None, dataset_id="d"):
    return SubterraRecord(
        dataset_id=dataset_id, sensor_type=SensorType.GPR,
        position=position or GeographicPosition(lat=52.0 + i * 1e-4, lon=4.3),
        latitude=getattr(position, "lat", 52.0 + i * 1e-4),
        longitude=getattr(position, "lon", 4.3),
        frame_id=f"{dataset_id}:line1", signal=[0.1, 0.2],
        metadata={"source_file": "line1.sgy", "trace_index": i})


def geo_records(n=4, dataset_id="d"):
    return [record(i, GeographicPosition(lat=52.0 + i * 1e-4, lon=4.3), dataset_id)
            for i in range(n)]


def odometry_records(n=5, dataset_id="d", path_id=None):
    return [
        SubterraRecord(
            dataset_id=dataset_id, sensor_type=SensorType.GPR,
            position=OdometryPosition(along_track_m=i * 2.0, path_id=path_id),
            latitude=None, longitude=None, frame_id=f"{dataset_id}:line1",
            signal=[0.1, 0.2], metadata={"source_file": "line1.sgy", "trace_index": i})
        for i in range(n)]


def assess(frames, records, surface=None, declarations=None, stale=None):
    return assess_spatial_reference("d", frames, records, surface_frames=surface,
                                    declarations=declarations, stale_products=stale)


def state_of(result, dimension):
    return result.dimension(dimension).state


# ---------------------------------------------------------------------------
# the six spatial states the brief names
# ---------------------------------------------------------------------------

def test_dataset_a_fully_declared_horizontal_reference():
    result = assess([frame(crs=GEOGRAPHIC)], geo_records())
    assert state_of(result, SpatialDimension.HORIZONTAL_POSITION) == "available"
    assert state_of(result, SpatialDimension.CRS) == "declared"


def test_dataset_b_horizontal_but_no_vertical_reference():
    result = assess([frame(crs=GEOGRAPHIC)], geo_records())
    assert state_of(result, SpatialDimension.CRS) == "declared"
    assert state_of(result, SpatialDimension.VERTICAL_REFERENCE) == "missing"
    vertical = result.dimension(SpatialDimension.VERTICAL_REFERENCE)
    assert vertical.action == DeclarationKind.VERTICAL_DATUM
    assert vertical.missing


def test_dataset_c_no_horizontal_position():
    records = [record(i, NoPosition(reason="the format provides none")) for i in range(3)]
    result = assess([frame(crs=SpatialRef(kind=CRSKind.UNKNOWN))], records)
    assert state_of(result, SpatialDimension.HORIZONTAL_POSITION) == "missing"
    assert result.dimension(SpatialDimension.HORIZONTAL_POSITION).action == \
        DeclarationKind.GEO_TIE


# ---------------------------------------------------------------------------
# assess_horizontal names the recorded position_source, verbatim
# ---------------------------------------------------------------------------

def _record_with_source(i, position, source, dataset_id="d"):
    r = record(i, position, dataset_id)
    if source is not None:
        r.metadata["position_source"] = source
    return r


def test_the_reason_names_a_single_position_source_verbatim():
    records = [_record_with_source(i, None, "gssi_dzg_gnss") for i in range(4)]
    result = assess([frame(crs=GEOGRAPHIC)], records)
    reason = result.dimension(SpatialDimension.HORIZONTAL_POSITION).reason
    assert "gssi_dzg_gnss" in reason
    # Never paraphrased into a category.
    assert "GNSS" not in reason


def test_a_record_with_no_position_source_key_is_reported_as_such_not_invented_as_none():
    records = [_record_with_source(i, None, None) for i in range(3)]
    result = assess([frame(crs=GEOGRAPHIC)], records)
    reason = result.dimension(SpatialDimension.HORIZONTAL_POSITION).reason
    assert "position source: no declared position source" in reason
    # The literal string "none" is itself a real position_source value some
    # converters write (see gssi_converter.py) to mean "attempted and could
    # not derive one" -- a missing key must not be reported the same way.
    assert "position source: none" not in reason


def test_more_than_one_source_is_named_with_counts():
    records = (
        [_record_with_source(i, None, "gssi_dzg_gnss") for i in range(3)]
        + [_record_with_source(i + 3, None, "segy_header") for i in range(2)]
    )
    result = assess([frame(crs=GEOGRAPHIC)], records)
    reason = result.dimension(SpatialDimension.HORIZONTAL_POSITION).reason
    assert "gssi_dzg_gnss (3)" in reason
    assert "segy_header (2)" in reason


def test_a_wheel_odometry_source_does_not_promote_a_position_to_geographic():
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR,
            position=OdometryPosition(along_track_m=i * 2.0, path_id=None),
            latitude=None, longitude=None, frame_id="d:line1",
            signal=[0.1, 0.2],
            metadata={"source_file": "line1.sgy", "trace_index": i,
                     "position_source": "mala_wheel_odometry"})
        for i in range(4)
    ]
    result = assess([frame(crs=ACQUISITION)], records)
    dimension = result.dimension(SpatialDimension.HORIZONTAL_POSITION)
    # Vocabulary is unchanged by the source: odometry positions are still
    # "partial" (they exist but are not geographic), never "available".
    assert dimension.state == "partial"
    assert "mala_wheel_odometry" in dimension.reason


def test_a_gnss_source_does_not_promote_a_non_geographic_position_either():
    """A record can claim a GNSS source in its metadata while its actual
    stored position is not geographic (e.g. a fix that failed to parse).
    The declared source names evidence provenance; it is not itself a
    position, so it cannot promote the state."""
    records = [
        SubterraRecord(
            dataset_id="d", sensor_type=SensorType.GPR,
            position=OdometryPosition(along_track_m=i * 2.0, path_id=None),
            latitude=None, longitude=None, frame_id="d:line1",
            signal=[0.1, 0.2],
            metadata={"source_file": "line1.sgy", "trace_index": i,
                     "position_source": "gssi_dzg_gnss"})
        for i in range(4)
    ]
    result = assess([frame(crs=ACQUISITION)], records)
    assert result.dimension(SpatialDimension.HORIZONTAL_POSITION).state == "partial"


def test_kmz_fallback_stays_whatever_position_kind_the_record_actually_has():
    records = [_record_with_source(i, None, "kmz_fallback") for i in range(3)]
    result = assess([frame(crs=GEOGRAPHIC)], records)
    dimension = result.dimension(SpatialDimension.HORIZONTAL_POSITION)
    assert dimension.state == "available"
    assert "kmz_fallback" in dimension.reason


def test_a_missing_horizontal_position_still_names_its_source():
    records = [
        _record_with_source(i, NoPosition(reason="the format provides none"), "none")
        for i in range(3)
    ]
    result = assess([frame(crs=SpatialRef(kind=CRSKind.UNKNOWN))], records)
    dimension = result.dimension(SpatialDimension.HORIZONTAL_POSITION)
    assert dimension.state == "missing"
    assert "position source: none" in dimension.reason


def test_dataset_d_relative_frame_becomes_available_with_a_tie():
    """Relative geometry existing is not absolute geolocation existing."""
    from ingestion.geo_tie import apply_geo_tie, build_geo_tie
    from schemas.spatial import ControlPoint

    records = odometry_records()
    before = assess([frame(crs=ACQUISITION)], records)
    assert state_of(before, SpatialDimension.HORIZONTAL_POSITION) == "partial"
    assert state_of(before, SpatialDimension.CRS) == "missing"

    tie = build_geo_tie(
        [ControlPoint(along_track_m=0.0, lat=52.0, lon=4.3),
         ControlPoint(along_track_m=8.0, lat=52.0005, lon=4.3005)],
        supplied_by="site survey")
    apply_geo_tie(records, tie)

    after = assess([frame(crs=ACQUISITION, geo_tie=tie)], records)
    assert state_of(after, SpatialDimension.HORIZONTAL_POSITION) == "available"
    assert after.dimension(SpatialDimension.HORIZONTAL_POSITION).provenance == "registered"


def test_dataset_e_time_axis_without_a_validated_depth_conversion():
    result = assess([frame(axis=TIME_AXIS)], geo_records())
    depth = result.dimension(SpatialDimension.DEPTH_CONVERSION)
    assert depth.state == "unavailable"
    assert "time zero is when the instrument fired" in depth.reason
    assert depth.action == DeclarationKind.DEPTH_CONVERSION


def test_dataset_f_a_dem_that_exists_but_cannot_anchor_anything():
    """
    The Lazaresti case, constructed: a surface frame with no elevation axis and
    no datum. Linking it must NOT make it a surface reference.
    """
    surface = frame("dem:tile", crs=GEOGRAPHIC, axis=SURFACE_BARE)
    result = assess([frame()], geo_records(), surface=[surface])
    reference = result.dimension(SpatialDimension.SURFACE_REFERENCE)
    assert reference.state == "unvalidated"
    assert "not an elevation" in " ".join(reference.detail["problems"])
    assert "re-ingesting" in " ".join(reference.missing)


def test_a_surface_model_with_an_elevation_axis_and_a_datum_is_available():
    result = assess([frame()], geo_records(),
                    surface=[frame("dem:good", axis=SURFACE_GOOD)])
    assert state_of(result, SpatialDimension.SURFACE_REFERENCE) == "available"


# ---------------------------------------------------------------------------
# assess_surface names the linked surface, verbatim
# ---------------------------------------------------------------------------

def test_the_available_reason_names_the_linked_dataset_and_its_recorded_codes():
    result = assess([frame()], geo_records(),
                    surface=[frame("dem:tile", crs=GEOGRAPHIC, axis=SURFACE_GOOD,
                                   dataset_id="dem")])
    reason = result.dimension(SpatialDimension.SURFACE_REFERENCE).reason
    assert "dem" in reason
    assert "NAP" in reason
    assert "EPSG:4326" in reason
    # Never paraphrased into a model name or a category.
    assert "COP30" not in reason
    assert "terrain model" not in reason.lower()


def test_the_unvalidated_reason_still_names_the_linked_dataset():
    result = assess([frame()], geo_records(),
                    surface=[frame("dem:tile", crs=GEOGRAPHIC, axis=SURFACE_BARE,
                                   dataset_id="dem")])
    dimension = result.dimension(SpatialDimension.SURFACE_REFERENCE)
    # Naming the dataset does not promote the state.
    assert dimension.state == "unvalidated"
    assert "dem" in dimension.reason


def test_more_than_one_surface_frame_names_distinct_codes_as_a_sorted_list():
    good_a = frame("dem:a", crs=SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:32633",
                                           crs_provenance=CRSProvenance.DECLARED_BY_SOURCE),
                   axis=SURFACE_GOOD, dataset_id="dem")
    good_b = frame("dem:b", crs=SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:32634",
                                           crs_provenance=CRSProvenance.DECLARED_BY_SOURCE),
                   axis=SURFACE_GOOD, dataset_id="dem")
    result = assess([frame()], geo_records(), surface=[good_a, good_b])
    reason = result.dimension(SpatialDimension.SURFACE_REFERENCE).reason
    assert "EPSG:32633" in reason
    assert "EPSG:32634" in reason


# ---------------------------------------------------------------------------
# the distinctions that must not collapse
# ---------------------------------------------------------------------------

def test_declared_is_not_validated():
    result = assess([frame(crs=GEOGRAPHIC)], geo_records())
    crs = result.dimension(SpatialDimension.CRS)
    assert crs.state == "declared"
    assert crs.detail["validated"] is False
    assert "not verify" in crs.detail["validation_note"]


def test_an_inferred_crs_is_not_reported_as_declared():
    result = assess([frame(crs=INFERRED)], geo_records())
    assert state_of(result, SpatialDimension.CRS) == "inferred"


def test_projected_coordinates_without_a_projection_are_unresolved():
    """A plausible-looking easting is not evidence of a UTM zone."""
    records = [record(i, ProjectedPosition(easting=412588.4, northing=5090851.4))
               for i in range(3)]
    result = assess([frame(crs=PROJECTED_UNDECLARED)], records)
    assert state_of(result, SpatialDimension.CRS) == "unresolved"
    assert result.dimension(SpatialDimension.CRS).action == DeclarationKind.CRS


def test_a_source_stated_depth_is_declared_not_measured():
    """
    A CSV `depth` column is somebody's computation done before the file reached
    us. Calling it measured would claim an instrument observed it.
    """
    direct = VerticalAxis(kind=AxisKind.DEPTH_M, units="m", origin="ground surface",
                          positive_down=True)
    result = assess([frame(axis=direct)], geo_records())
    depth = result.dimension(SpatialDimension.DEPTH_CONVERSION)
    assert depth.state == "declared"
    assert depth.provenance == "declared_by_source"


def test_a_derived_depth_is_never_reported_as_measured():
    result = assess([frame(axis=DEPTH_DERIVED)], geo_records())
    depth = result.dimension(SpatialDimension.DEPTH_CONVERSION)
    assert depth.state == "derived"
    assert depth.provenance == "derived"
    assert "assumption about the subsurface" in depth.reason


def test_orientation_is_never_inferred_from_a_track_bearing():
    result = assess([frame()], geo_records())
    orientation = result.dimension(SpatialDimension.ORIENTATION)
    assert orientation.state == "missing"
    assert "not how the sensor was oriented" in orientation.reason


def test_every_unresolved_dimension_names_what_is_missing():
    for frames, records in (
        ([frame(crs=SpatialRef(kind=CRSKind.UNKNOWN))],
         [record(i, NoPosition(reason="none")) for i in range(3)]),
        ([frame(crs=PROJECTED_UNDECLARED)], geo_records()),
        ([frame(crs=GEOGRAPHIC, axis=TIME_AXIS)], geo_records()),
    ):
        for dimension in assess(frames, records).dimensions:
            assert dimension.reason
            if not dimension.resolved:
                assert dimension.missing, f"{dimension.dimension} is open with nothing missing"


# ---------------------------------------------------------------------------
# declaration validation
# ---------------------------------------------------------------------------

def test_a_user_declared_crs_is_always_supplied_by_caller():
    """A user cannot assert that the SOURCE declared something."""
    value = service.validate_declaration(
        DeclarationKind.CRS, {"code": "EPSG:32635", "kind": "projected"})
    assert value["crs_provenance"] == CRSProvenance.SUPPLIED_BY_CALLER.value


def test_a_crs_code_is_refused_for_a_frame_that_cannot_have_one():
    with pytest.raises(service.DeclarationError) as exc:
        service.validate_declaration(
            DeclarationKind.CRS, {"code": "EPSG:32635", "kind": "acquisition"})
    assert "GeoTie" in str(exc.value)


@pytest.mark.parametrize("velocity", [0.0, 0.005, 0.31, 3.0, "fast", None, float("nan")])
def test_an_implausible_velocity_is_refused(velocity):
    with pytest.raises(service.DeclarationError):
        service.validate_declaration(
            DeclarationKind.DEPTH_CONVERSION, {"velocity_m_per_ns": velocity})


def test_a_plausible_velocity_is_recorded_as_derived():
    value = service.validate_declaration(
        DeclarationKind.DEPTH_CONVERSION, {"velocity_m_per_ns": 0.1})
    assert value["derived"] is True
    assert value["velocity_m_per_ns"] == 0.1


def test_an_antenna_offset_has_no_default():
    """Assuming zero is a physical claim that the antenna was on the ground."""
    with pytest.raises(service.DeclarationError):
        service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {})


def test_an_antenna_offset_states_what_it_is_measured_between():
    """
    Stage 12 stopped defaulting the reference point. It used to fall back to
    "sensor phase centre", which quietly answered a question the caller had not
    been asked -- and a phase-centre height is not an axis-origin offset.
    """
    with pytest.raises(service.DeclarationError) as exc:
        service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {"offset_m": 0.35})
    assert "measured_from is required" in str(exc.value)

    value = service.validate_declaration(DeclarationKind.ANTENNA_OFFSET, {
        "offset_m": 0.35, "measured_from": "depth_axis_origin",
        "evidence": "field_measurement"})
    assert value["measured_from"] == "depth_axis_origin"
    assert value["measured_to"] == "ground surface"
    assert value["verified"] is False


def test_a_one_point_geo_tie_is_refused():
    with pytest.raises(service.DeclarationError) as exc:
        service.validate_declaration(DeclarationKind.GEO_TIE, {
            "control_points": [{"along_track_m": 0.0, "lat": 52.0, "lon": 4.3}],
            "supplied_by": "someone"})
    assert "two control points" in str(exc.value)


def test_a_two_point_tie_is_usable_but_never_verified():
    value = service.validate_declaration(DeclarationKind.GEO_TIE, {
        "control_points": [{"along_track_m": 0.0, "lat": 52.0, "lon": 4.3},
                           {"along_track_m": 10.0, "lat": 52.001, "lon": 4.301}],
        "supplied_by": "site survey"})
    assert value["verified"] is False
    assert value["rms_residual_m"] is None


def test_an_orientation_declaration_requires_a_heading_and_a_reference():
    with pytest.raises(service.DeclarationError):
        service.validate_declaration(DeclarationKind.ORIENTATION, {})
    with pytest.raises(service.DeclarationError):
        service.validate_declaration(DeclarationKind.ORIENTATION, {"heading_deg": 47.0})
    with pytest.raises(service.DeclarationError) as exc:
        service.validate_declaration(
            DeclarationKind.ORIENTATION, {"heading_deg": 47.0, "reference": "moon_north"})
    assert "reference must be one of" in str(exc.value)


def test_an_orientation_heading_has_no_default_reference():
    """True, magnetic and grid north disagree by amounts that vary with
    location and date; assuming one would misattribute the difference."""
    with pytest.raises(service.DeclarationError):
        service.validate_declaration(DeclarationKind.ORIENTATION, {"heading_deg": 0.0})


def test_an_orientation_heading_must_be_a_compass_bearing():
    with pytest.raises(service.DeclarationError):
        service.validate_declaration(
            DeclarationKind.ORIENTATION, {"heading_deg": 360.0, "reference": "true_north"})
    with pytest.raises(service.DeclarationError):
        service.validate_declaration(
            DeclarationKind.ORIENTATION, {"heading_deg": -1.0, "reference": "true_north"})

    value = service.validate_declaration(
        DeclarationKind.ORIENTATION, {"heading_deg": 0.0, "reference": "grid_north"})
    assert value == {"heading_deg": 0.0, "reference": "grid_north"}


def test_orientation_is_recorded_as_a_claim_not_a_measurement():
    assumption = service._assumption_for(
        DeclarationKind.ORIENTATION, {"heading_deg": 47.0, "reference": "true_north"},
        "field notes 2020")
    assert assumption.key == "declared_orientation"
    assert assumption.value == {"heading_deg": 47.0, "reference": "true_north"}
    assert assumption.verified is False
    assert "declaration, not a measurement" in assumption.basis


# ---------------------------------------------------------------------------
# the API
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "data_root", tmp_path)
    for name in ("processed", "raw", "metadata"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'spatial.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    try:
        yield Session, tmp_path
    finally:
        app.dependency_overrides.clear()


def signed_in(email="owner@example.test") -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/register",
                       json={"email": email, "password": PASSWORD}).status_code == 201
    return client


def seed(Session, client=None, dataset_id="d", *, frames=None, records=None,
         owner=True, name="Site 01"):
    from database.frames_store import save_frames
    from database.records_store import save_records

    rows = records if records is not None else geo_records(dataset_id=dataset_id)
    save_records(dataset_id, rows)
    save_frames(dataset_id, frames or [frame(f"{dataset_id}:line1", dataset_id=dataset_id)])

    owner_id = None
    if owner and client is not None:
        owner_id = client.get("/api/auth/me").json()["user"]["id"]
    session = Session()
    session.add(Dataset(id=dataset_id, name=name, sensor_type="gpr",
                        original_format="segy", record_count=len(rows), owner_id=owner_id))
    session.commit()
    session.close()


def declare(client, dataset_id, kind, value, supplied_by="site survey 2019-03-20"):
    return client.post(f"/api/spatial/{dataset_id}/declarations", json={
        "kind": kind.value, "value": value, "supplied_by": supplied_by})


def test_the_spatial_endpoint_reports_every_dimension(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client)

    body = client.get("/api/spatial/d").json()
    assert {d["dimension"] for d in body["dimensions"]} == {d.value for d in SpatialDimension}
    for dimension in body["dimensions"]:
        assert dimension["reason"]


def test_the_vocabulary_names_the_orientation_declaration(env):
    client = signed_in()
    body = client.get("/api/spatial/vocabulary").json()
    kinds = {k["value"] for k in body["declaration_kinds"]}
    assert DeclarationKind.ORIENTATION.value in kinds


def test_declaring_a_vertical_datum_moves_the_question_to_the_depth_origin(env):
    """
    Stage 12 corrected this. A datum alone used to resolve the dimension, but a
    subsurface axis also needs its zero placed against the ground -- so with the
    datum given and the origin unplaced, the workflow asks for the offset next
    rather than reporting a vertical reference it does not have.
    """
    Session, _ = env
    client = signed_in()
    seed(Session, client)

    before = client.get("/api/spatial/d").json()
    assert _state(before, "vertical_reference") == "missing"

    response = declare(client, "d", DeclarationKind.VERTICAL_DATUM, {"code": "NAP"})
    assert response.status_code == 201
    # The response carries the recalculated state, so inspect -> resolve ->
    # recalculate is one motion.
    after = response.json()["spatial_reference"]
    assert _state(after, "vertical_reference") == "unresolved"
    vertical = next(d for d in after["dimensions"]
                    if d["dimension"] == "vertical_reference")
    assert vertical["action"] == DeclarationKind.ANTENNA_OFFSET.value
    assert any("depth-axis origin" in m for m in vertical["missing"])

    # And once the origin is placed too, the dimension is settled.
    resolved = declare(client, "d", DeclarationKind.ANTENNA_OFFSET, {
        "offset_m": 0.45, "measured_from": "depth_axis_origin",
        "evidence": "field_measurement"})
    assert resolved.status_code == 201
    assert _state(resolved.json()["spatial_reference"], "vertical_reference") == "declared"
    assert _state(client.get("/api/spatial/d").json(), "vertical_reference") == "declared"


def test_declaring_an_orientation_resolves_the_dimension_and_names_it_verbatim(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client)

    before = client.get("/api/spatial/d").json()
    assert _state(before, "orientation") == "missing"
    orientation = next(d for d in before["dimensions"] if d["dimension"] == "orientation")
    assert orientation["action"] == DeclarationKind.ORIENTATION.value

    response = declare(client, "d", DeclarationKind.ORIENTATION,
                       {"heading_deg": 47.0, "reference": "true_north"})
    assert response.status_code == 201
    after = response.json()["spatial_reference"]
    assert _state(after, "orientation") == "available"
    reason = next(d for d in after["dimensions"] if d["dimension"] == "orientation")["reason"]
    # Named verbatim -- the number and the reference, never a compass word
    # and never "along-track" or "bearing".
    assert "47.0" in reason
    assert "true_north" in reason
    assert "northeast" not in reason.lower()
    assert "bearing" not in reason.lower()

    assert _state(client.get("/api/spatial/d").json(), "orientation") == "available"


def test_geographic_positions_alone_do_not_declare_an_orientation(env):
    """A line of positions implies a bearing, not an orientation -- the two
    are different questions, and this dimension answers the second one."""
    Session, _ = env
    client = signed_in()
    seed(Session, client)

    assert _state(client.get("/api/spatial/d").json(), "orientation") == "missing"


def test_an_orientation_declaration_does_not_touch_the_other_dimensions(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client)

    before = client.get("/api/spatial/d").json()
    response = declare(client, "d", DeclarationKind.ORIENTATION,
                       {"heading_deg": 90.0, "reference": "magnetic_north"})
    after = response.json()["spatial_reference"]

    for dimension in ("horizontal_position", "crs", "vertical_reference",
                      "depth_conversion", "surface_reference", "survey_geometry"):
        assert _state(before, dimension) == _state(after, dimension)


def _state(body, dimension):
    return next(d["state"] for d in body["dimensions"] if d["dimension"] == dimension)


def test_a_declaration_is_recorded_with_its_author(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client)
    declare(client, "d", DeclarationKind.VERTICAL_DATUM, {"code": "NAP"},
            supplied_by="PDOK documentation for AHN")

    log = client.get("/api/spatial/d/declarations").json()
    assert log["count"] == 1
    assert log["declarations"][0]["supplied_by"] == "PDOK documentation for AHN"
    assert log["declarations"][0]["active"] is True


def test_a_correction_supersedes_rather_than_erasing(env):
    """"What did we think the datum was, and who said so" must stay answerable."""
    Session, _ = env
    client = signed_in()
    seed(Session, client)

    declare(client, "d", DeclarationKind.VERTICAL_DATUM, {"code": "NAP"}, "first guess")
    declare(client, "d", DeclarationKind.VERTICAL_DATUM, {"code": "EPSG:5709"}, "corrected")

    log = client.get("/api/spatial/d/declarations").json()
    assert log["count"] == 2
    active = [d for d in log["declarations"] if d["active"]]
    superseded = [d for d in log["declarations"] if not d["active"]]
    assert len(active) == 1 and active[0]["supplied_by"] == "corrected"
    assert len(superseded) == 1 and superseded[0]["superseded_by"] == active[0]["id"]


def test_a_declaration_becomes_an_unverified_assumption_on_the_frame(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client)
    declare(client, "d", DeclarationKind.VERTICAL_DATUM, {"code": "NAP"}, "the surveyor")

    from database.frames_store import load_frames

    assumptions = load_frames("d")[0].assumptions
    declared = next(a for a in assumptions if a.key == "declared_vertical_datum")
    assert declared.verified is False
    assert "SUPPLIED BY CALLER" in declared.basis
    assert "the surveyor" in declared.basis


def test_a_velocity_cannot_be_declared_for_a_dataset_with_no_time_axis(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client, frames=[frame("d:line1", axis=SURFACE_GOOD)])

    response = declare(client, "d", DeclarationKind.DEPTH_CONVERSION,
                       {"velocity_m_per_ns": 0.1})
    assert response.status_code == 409
    assert "no frame carries a measured time axis" in response.json()["detail"]
    # and nothing was logged, because nothing was applied
    assert client.get("/api/spatial/d/declarations").json()["count"] == 0


def test_a_geo_tie_registers_without_overwriting_the_measurement(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client, frames=[frame("d:line1", crs=ACQUISITION)],
         records=odometry_records())

    response = declare(client, "d", DeclarationKind.GEO_TIE, {
        "control_points": [{"along_track_m": 0.0, "lat": 52.0, "lon": 4.3},
                           {"along_track_m": 8.0, "lat": 52.0005, "lon": 4.3005}],
        "supplied_by": "site survey"})
    assert response.status_code == 201

    from database.records_store import load_records

    for record_row in load_records("d"):
        # The acquisition's own coordinate is untouched.
        assert record_row.position.kind == "odometry"
        assert record_row.registered_position is not None
        assert record_row.registered_position.kind == "geographic"


def test_linking_an_unusable_dem_does_not_make_it_a_surface_reference(env):
    """The Lazaresti case, end to end."""
    Session, _ = env
    client = signed_in()
    seed(Session, client, "survey")
    seed(Session, client, "dem", frames=[frame("dem:tile", dataset_id="dem", axis=SURFACE_BARE)],
         records=geo_records(dataset_id="dem"), name="COP30 DEM")

    response = declare(client, "survey", DeclarationKind.SURFACE_REFERENCE,
                       {"surface_dataset_id": "dem"})
    assert response.status_code == 201
    assert _state(response.json()["spatial_reference"], "surface_reference") == "unvalidated"


def test_linking_a_usable_dem_names_it_in_the_reason(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client, "survey")
    seed(Session, client, "good_dem",
        frames=[frame("good_dem:tile", dataset_id="good_dem", axis=SURFACE_GOOD)],
        records=geo_records(dataset_id="good_dem"), name="a DEM")

    response = declare(client, "survey", DeclarationKind.SURFACE_REFERENCE,
                       {"surface_dataset_id": "good_dem"})
    assert response.status_code == 201
    after = response.json()["spatial_reference"]
    assert _state(after, "surface_reference") == "available"
    reason = next(d for d in after["dimensions"]
                 if d["dimension"] == "surface_reference")["reason"]
    assert "good_dem" in reason
    assert "NAP" in reason


def test_changing_a_spatial_reference_marks_downstream_products_stale(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client)

    session = Session()
    session.add(FusionSample(id="f1", radius_m=10.0, dataset_ids=["d"],
                             created_at=datetime.utcnow() - timedelta(days=1)))
    session.commit()
    session.close()

    assert client.get("/api/spatial/d").json()["has_stale_products"] is False
    declare(client, "d", DeclarationKind.VERTICAL_DATUM, {"code": "NAP"})

    body = client.get("/api/spatial/d").json()
    assert body["has_stale_products"] is True
    assert any("f1" in product for product in body["stale_products"])


def test_nothing_is_recomputed_automatically():
    """
    Re-running fusion silently would hide the very change being reported.

    Read the CALLS, not the prose: a substring search over the source trips on
    the word "recomputed" in the docstring explaining why it does not recompute,
    and proves nothing either way.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(service.stale_products).lstrip())
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    assert not called & {"run_pipeline", "save_records", "save_frames", "fuse_datasets"}


# ---------------------------------------------------------------------------
# access control
# ---------------------------------------------------------------------------

def test_another_user_cannot_read_or_declare(env):
    Session, _ = env
    owner = signed_in("owner@example.test")
    seed(Session, owner)
    intruder = signed_in("intruder@example.test")

    assert intruder.get("/api/spatial/d").status_code == 404
    assert intruder.get("/api/spatial/d/declarations").status_code == 404
    assert declare(intruder, "d", DeclarationKind.VERTICAL_DATUM,
                   {"code": "NAP"}).status_code == 404


def test_an_unauthenticated_caller_cannot_reach_the_spatial_api(env):
    Session, _ = env
    owner = signed_in()
    seed(Session, owner)

    anonymous = TestClient(app)
    assert anonymous.get("/api/spatial/d").status_code == 401
    assert declare(anonymous, "d", DeclarationKind.VERTICAL_DATUM,
                   {"code": "NAP"}).status_code == 401


def test_system_reference_data_can_be_inspected_but_not_re_referenced(env):
    Session, _ = env
    client = signed_in()
    seed(Session, None, owner=False, name="Published corpus")

    assert client.get("/api/spatial/d").status_code == 200
    assert declare(client, "d", DeclarationKind.VERTICAL_DATUM,
                   {"code": "NAP"}).status_code == 403


def test_a_nonexistent_dataset_is_a_404(env):
    Session, _ = env
    client = signed_in()
    assert client.get("/api/spatial/nope").status_code == 404


# ---------------------------------------------------------------------------
# integrity
# ---------------------------------------------------------------------------

def test_the_assessment_computes_no_coordinate_elevation_or_depth():
    """
    It reads what frames declare and reports it. A module that computed a
    position would be the thing this whole stage exists to prevent.
    """
    import inspect

    from schemas import spatial_reference

    source = inspect.getsource(spatial_reference)
    for forbidden in ("haversine", "np.polyfit", "* 0.5", "velocity *", "/ 2"):
        assert forbidden not in source


def test_declaring_never_rewrites_a_measured_position(env):
    Session, _ = env
    client = signed_in()
    seed(Session, client)

    from database.records_store import _path_for

    before = _path_for("d").read_bytes()
    declare(client, "d", DeclarationKind.CRS, {"code": "EPSG:32635", "kind": "projected"})
    declare(client, "d", DeclarationKind.VERTICAL_DATUM, {"code": "NAP"})
    assert _path_for("d").read_bytes() == before, "a declaration modified the records"


def test_the_migration_creates_the_table_on_a_pre_stage_8_database(tmp_path):
    from sqlalchemy import inspect as sa_inspect

    from database.migrations import run_migrations

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Dataset.__table__.create(bind=engine)
    assert "spatial_declarations" not in sa_inspect(engine).get_table_names()

    run_migrations(engine)
    assert "spatial_declarations" in sa_inspect(engine).get_table_names()
    # idempotent
    run_migrations(engine)
