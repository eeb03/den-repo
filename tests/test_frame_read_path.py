"""
Frames are read back and surfaced, not just written.

Until now every dataset persisted SurveyFrames that nothing ever loaded,
and `/{id}/info` reported a hardcoded `"coordinate_system": "EPSG:4326
(WGS84 lat/lon)"` -- a CRS the endpoint asserted without ever checking it
against the data. A GeoTIFF ingested in UTM, or a SEG-Y whose positions are
projected, both got the same confident wrong answer.

These tests pin that the endpoint now reports what the dataset's own frames
declare, and that datasets ingested before frames existed still get an
answer via reconstruction.
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from database.frames_store import load_frames, save_frames, synthesize_frames_from_records
from schemas.spatial import (
    AxisKind, CRSKind, CRSProvenance, GeographicPosition, ProjectedPosition, SpatialRef,
    VerticalAxis,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame


def _records(n=4, projected=False):
    def pos(i):
        return (ProjectedPosition(easting=501134.0 + i, northing=4544705.0 + i)
                if projected else GeographicPosition(lat=41.0 + i * 1e-4, lon=15.0 + i * 1e-4))
    return [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.GPR,
            latitude=41.0 + i * 1e-4, longitude=15.0 + i * 1e-4,
            position=pos(i), frame_id="ds:line", depth=0.5, signal=[1.0],
            metadata={"source_file": "line.SGY", "trace_index": i, "sample_index": 0,
                      "position_source": "segy_header"},
        )
        for i in range(n)
    ]


def _frame(**kw):
    base = dict(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy", source_file="line.SGY",
        spatial_ref=SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:32633", horizontal_units="m",
                               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="time-zero", positive_down=True),
    )
    base.update(kw)
    return SurveyFrame(**base)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    from configs import settings as settings_mod
    monkeypatch.setattr(type(settings_mod.settings), "processed_dir",
                        property(lambda self: tmp_path))
    return tmp_path


# --- the store round-trips what ingest writes ---

def test_persisted_frames_are_readable(isolated_store):
    save_frames("ds", [_frame()])
    loaded = load_frames("ds")
    assert len(loaded) == 1
    assert loaded[0].spatial_ref.code == "EPSG:32633"
    assert loaded[0].vertical_axis.kind == AxisKind.TWO_WAY_TIME_NS


def test_pre_frame_datasets_fall_back_to_reconstruction(isolated_store):
    """A dataset ingested before frames existed must still yield provenance."""
    assert load_frames("never-ingested") == []
    reconstructed = synthesize_frames_from_records(_records())
    assert len(reconstructed) == 1
    assert reconstructed[0].assumption("frame_reconstructed").value is True


def test_reconstruction_reports_the_real_position_kind(isolated_store):
    """Reconstruction reads record positions rather than guessing a CRS."""
    geo = synthesize_frames_from_records(_records(projected=False))[0]
    proj = synthesize_frames_from_records(_records(projected=True))[0]
    assert geo.spatial_ref.kind == CRSKind.GEOGRAPHIC
    assert proj.spatial_ref.kind == CRSKind.PROJECTED
    # Records never stored a CRS code, so none is invented.
    assert proj.spatial_ref.code is None


# --- the endpoint reports frames instead of a hardcoded claim ---

def _info(monkeypatch, records, frames, dataset_sensor="gpr"):
    """Drives /{id}/info with stubbed storage and a stubbed Dataset row."""
    import api.routes.datasets as mod

    class _Row:
        id, name, sensor_type, original_format = "ds", "d", dataset_sensor, "segy"
        source = license = None
        record_count, quality_score, has_ground_truth = len(records), 1.0, False
        extra_metadata = {}

    class _Q:
        def filter(self, *a): return self
        def first(self): return _Row()

    class _DB:
        def query(self, *a): return _Q()

    monkeypatch.setattr(mod, "load_records", lambda _id: records)
    monkeypatch.setattr(mod, "load_frames", lambda _id: frames)
    app.dependency_overrides[mod.get_db] = lambda: _DB()
    try:
        return TestClient(app).get("/api/datasets/ds/info").json()
    finally:
        app.dependency_overrides.clear()


def test_info_reports_the_frames_declared_crs_not_a_hardcoded_one(monkeypatch):
    body = _info(monkeypatch, _records(projected=True), [_frame()])
    assert body["coordinate_system"] == "EPSG:32633"
    assert body["coordinate_system"] != "EPSG:4326 (WGS84 lat/lon)"


def test_info_exposes_survey_frame_provenance(monkeypatch):
    body = _info(monkeypatch, _records(projected=True), [_frame()])
    assert len(body["survey_frames"]) == 1
    frame = body["survey_frames"][0]
    assert frame["source_file"] == "line.SGY"
    assert frame["source_format"] == "segy"
    assert frame["spatial_ref"]["code"] == "EPSG:32633"
    assert frame["vertical_axis"]["kind"] == "two_way_time_ns"


def test_info_counts_where_positions_actually_came_from(monkeypatch):
    body = _info(monkeypatch, _records(n=4, projected=True), [_frame()])
    assert body["position_sources"] == {"segy_header": 4}


def test_info_lists_every_ref_when_a_dataset_mixes_them(monkeypatch):
    """A multi-line dataset must not be summarised to one CRS it doesn't have."""
    other = _frame(frame_id="ds:line2", source_file="line2.SGY",
                   spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                                          horizontal_units="deg",
                                          crs_provenance=CRSProvenance.DECLARED_BY_SOURCE))
    body = _info(monkeypatch, _records(projected=True), [_frame(), other])
    assert body["coordinate_system"] == ["EPSG:32633", "EPSG:4326"]
    assert len(body["survey_frames"]) == 2


def test_info_still_works_for_a_dataset_with_no_stored_frames(monkeypatch):
    """Reconstruction keeps the endpoint useful for pre-frame datasets."""
    body = _info(monkeypatch, _records(projected=False), [])
    assert len(body["survey_frames"]) == 1
    assert body["survey_frames"][0]["assumptions"][0]["key"] == "frame_reconstructed"


def test_info_surfaces_frame_assumptions(monkeypatch):
    """Assumptions must reach the consumer, not stay buried in storage."""
    from schemas.spatial import Assumption
    f = _frame(assumptions=[Assumption(key="gpr_velocity", value=0.1,
                                       basis="assumed default", verified=False)])
    body = _info(monkeypatch, _records(projected=True), [f])
    assumptions = body["survey_frames"][0]["assumptions"]
    assert assumptions[0]["key"] == "gpr_velocity"
    assert assumptions[0]["verified"] is False


# --- provenance also reaches /points and /trace_grid -------------------------
#
# /info was the first consumer; a caller plotting points or georeferencing a
# radargram column needs the same information, otherwise it has no way to tell
# a real coordinate from the legacy (0, 0) placeholder.

def _endpoint(monkeypatch, url, records, frames):
    import api.routes.datasets as mod

    class _Row:
        id, name, sensor_type, original_format = "ds", "d", "gpr", "segy"
        source = license = None
        record_count, quality_score, has_ground_truth = len(records), 1.0, False
        extra_metadata = {}

    class _Q:
        def filter(self, *a): return self
        def first(self): return _Row()

    class _DB:
        def query(self, *a): return _Q()

    monkeypatch.setattr(mod, "load_records", lambda _id: records)
    monkeypatch.setattr(mod, "load_frames", lambda _id: frames)
    app.dependency_overrides[mod.get_db] = lambda: _DB()
    try:
        return TestClient(app).get(url).json()
    finally:
        app.dependency_overrides.clear()


def _trace_records(n_traces=6, n_depths=30, geographic=False):
    from schemas.spatial import GeographicPosition, NoPosition
    recs = []
    for t in range(n_traces):
        for d in range(n_depths):
            pos = (GeographicPosition(lat=41.0 + t * 1e-4, lon=15.0 + t * 1e-4)
                   if geographic else NoPosition(reason="headers are (0, 0)"))
            recs.append(SubterraRecord(
                dataset_id="ds", sensor_type=SensorType.GPR,
                latitude=41.0 + t * 1e-4 if geographic else 0.0,
                longitude=15.0 + t * 1e-4 if geographic else 0.0,
                position=pos, frame_id="ds:line", depth=round(d * 0.01, 6), signal=[1.0],
                metadata={"source_file": "line.SGY", "trace_index": t, "sample_index": d,
                          "velocity_m_per_ns": 0.1,
                          "position_source": "segy_header" if geographic else "none"},
            ))
    return recs


def test_points_endpoint_reports_position_kind_per_record(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/points", _records(projected=True), [_frame()])
    assert all(p["position_kind"] == "projected" for p in body["points"])
    assert body["position_kinds"] == {"projected": 4}


def test_points_endpoint_reports_position_source(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/points", _records(projected=True), [_frame()])
    assert all(p["position_source"] == "segy_header" for p in body["points"])


def test_points_endpoint_distinguishes_placeholder_from_real_coordinates(monkeypatch):
    """(0,0) in lat/lon must be identifiable as 'no position', not a location."""
    body = _endpoint(monkeypatch, "/api/datasets/ds/points", _trace_records(geographic=False),
                     [_frame()])
    assert body["position_kinds"] == {"none": len(body["points"])}
    assert all(p["lat"] == 0.0 and p["position_kind"] == "none" for p in body["points"])


def test_trace_grid_reports_the_lines_survey_frame(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/trace_grid",
                     _trace_records(geographic=True), [_frame()])
    frame = body["survey_frame"]
    assert frame is not None
    assert frame["spatial_ref"]["code"] == "EPSG:32633"
    assert frame["vertical_axis"]["kind"] == "two_way_time_ns"


def test_trace_grid_reports_per_trace_position_kind(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/trace_grid",
                     _trace_records(geographic=False), [_frame()])
    assert set(body["trace_position_kind"]) == {"none"}
    assert len(body["trace_position_kind"]) == body["n_traces"]


def test_trace_grid_falls_back_to_a_reconstructed_frame(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/trace_grid",
                     _trace_records(geographic=True), [])
    assert body["survey_frame"] is not None
    keys = [a["key"] for a in body["survey_frame"]["assumptions"]]
    assert "frame_reconstructed" in keys


# --- odometry surfaced so an IDS line can actually be plotted ----------------
#
# Along-track distance is the ONLY coordinate a wheel-encoder acquisition
# has. Without it in the API, such a line cannot be plotted at all: the
# grid's columns are evenly spaced in trace INDEX, not in metres.

def _odometry_records(n_traces=5, n_depths=20, spacing=0.024):
    from schemas.spatial import OdometryPosition
    return [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.GPR,
            latitude=0.0, longitude=0.0,
            position=OdometryPosition(along_track_m=t * spacing, path_id="line"),
            frame_id="ds:line", depth=round(d * 0.01, 6), signal=[1.0],
            metadata={"source_file": "line.dt", "trace_index": t, "sample_index": d,
                      "position_source": "ids_wheel_odometry",
                      "velocity_m_per_ns": 0.1},
        )
        for t in range(n_traces) for d in range(n_depths)
    ]


def test_points_endpoint_exposes_along_track_distance(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/points", _odometry_records(), [_frame()])
    vals = sorted({p["along_track_m"] for p in body["points"]})
    # exact set equality is wrong here: 3 * 0.024 is 0.07200000000000001
    assert vals == pytest.approx([0.0, 0.024, 0.048, 0.072, 0.096])
    assert body["position_kinds"] == {"odometry": len(body["points"])}


def test_points_endpoint_reports_the_line_length(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/points", _odometry_records(), [_frame()])
    assert body["along_track_extent_m"] == pytest.approx(4 * 0.024)


def test_points_along_track_is_null_for_non_odometry_records(monkeypatch):
    """A geographic dataset has no along-track coordinate, and must not invent one."""
    body = _endpoint(monkeypatch, "/api/datasets/ds/points", _records(projected=True), [_frame()])
    assert all(p["along_track_m"] is None for p in body["points"])
    assert body["along_track_extent_m"] is None


def test_trace_grid_exposes_per_trace_along_track(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/trace_grid", _odometry_records(), [_frame()])
    assert body["trace_along_track"] == pytest.approx([0.0, 0.024, 0.048, 0.072, 0.096])
    assert len(body["trace_along_track"]) == body["n_traces"]
    assert body["along_track_extent_m"] == pytest.approx(4 * 0.024)


def test_trace_grid_reports_which_traces_are_geographic(monkeypatch):
    """A caller georeferencing a column must know before trusting trace_lat/lon."""
    body = _endpoint(monkeypatch, "/api/datasets/ds/trace_grid", _odometry_records(), [_frame()])
    assert body["trace_geographic"] == [False] * body["n_traces"]
    assert set(body["trace_position_kind"]) == {"odometry"}


def test_trace_grid_along_track_is_null_for_unpositioned_lines(monkeypatch):
    body = _endpoint(monkeypatch, "/api/datasets/ds/trace_grid",
                     _trace_records(geographic=False), [_frame()])
    assert all(v is None for v in body["trace_along_track"])
    assert body["along_track_extent_m"] is None


def test_trace_grid_along_track_matches_the_grid_width(monkeypatch):
    """One value per column, so a caller can use it directly as the x axis."""
    body = _endpoint(monkeypatch, "/api/datasets/ds/trace_grid",
                     _odometry_records(n_traces=7), [_frame()])
    assert len(body["trace_along_track"]) == len(body["grid"][0]) == body["n_traces"]
