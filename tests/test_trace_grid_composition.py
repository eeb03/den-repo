"""
Phase 7, fifth slice: a radargram / trace-depth grid is a GPR-trace view.

`GET /{id}/trace_grid` already answered 400 for a dataset whose records carry
no trace_index/depth metadata -- "not genuine multi-sample GPR trace data".
That is correct for a genuine shape mismatch on a GPR line, but it is the
wrong reason for a dataset that was never GPR at all: a LiDAR/DEM dataset has
no B-scan to draw not because something is missing, but because the concept
does not apply to it. These tests pin the composition gate added ahead of
`build_trace_depth_grid_for_records`, using the same `frame_modalities` /
`identity.recorded_modalities` definition the report, signal-chain route and
candidates API already share -- and that GPR, mixed, and empty compositions
are unaffected.
"""
from fastapi.testclient import TestClient

from api.main import app
from schemas.spatial import AxisKind, CRSKind, CRSProvenance, GeographicPosition, SpatialRef, VerticalAxis
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame

client = TestClient(app)


def _gpr_records(n_traces=6, n_depths=10, source_file="line.SGY"):
    recs = []
    for t in range(n_traces):
        for d in range(n_depths):
            recs.append(SubterraRecord(
                dataset_id="ds", sensor_type=SensorType.GPR,
                latitude=41.0 + t * 1e-4, longitude=15.0 + t * 1e-4,
                position=GeographicPosition(lat=41.0 + t * 1e-4, lon=15.0 + t * 1e-4),
                frame_id="ds:line", depth=round(d * 0.01, 6), signal=[1.0],
                metadata={"source_file": source_file, "trace_index": t, "sample_index": d,
                          "velocity_m_per_ns": 0.1, "position_source": "segy_header"},
            ))
    return recs


def _lidar_records(n=10, source_file="tile.tif"):
    return [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.LIDAR,
            latitude=41.0 + i * 1e-4, longitude=15.0 + i * 1e-4,
            position=GeographicPosition(lat=41.0 + i * 1e-4, lon=15.0 + i * 1e-4),
            depth=0.0, signal=[1.0],
            metadata={"source_file": source_file, "trace_index": i})
        for i in range(n)
    ]


def _frame(modality=SensorType.GPR, source_file="line.SGY", frame_id="ds:line"):
    return SurveyFrame(
        frame_id=frame_id, dataset_id="ds", modality=modality,
        source_format="segy", source_file=source_file,
        spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326", horizontal_units="degree",
                               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="time-zero", positive_down=True),
    )


def _call(monkeypatch, records, frames):
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
        return client.get("/api/datasets/ds/trace_grid")
    finally:
        app.dependency_overrides.pop(mod.get_db, None)


def test_off_gpr_composition_names_it_and_says_does_not_apply(monkeypatch):
    resp = _call(monkeypatch, _lidar_records(), [_frame(modality=SensorType.LIDAR, source_file="tile.tif")])
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "lidar" in detail
    assert "does not apply" in detail
    assert "not genuine multi-sample" not in detail


def test_gpr_composition_is_unaffected(monkeypatch):
    resp = _call(monkeypatch, _gpr_records(), [_frame()])
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_traces"] == 6
    for invented in ("fused", "aligned", "ready for fusion", "multi-modal"):
        assert invented not in str(body).lower()


def test_mixed_composition_with_gpr_present_is_unaffected(monkeypatch):
    mixed_records = _gpr_records() + _lidar_records(source_file="tile.tif")
    mixed_frames = [_frame(), _frame(modality=SensorType.LIDAR, source_file="tile.tif", frame_id="ds:tile")]
    resp = _call(monkeypatch, mixed_records, mixed_frames)
    assert resp.status_code == 200
    assert resp.json()["source_file"] == "line.SGY"


def test_gpr_present_but_shape_mismatched_keeps_the_original_not_genuine_reason(monkeypatch):
    """gpr IS in the composition here (reconstructed from the records' own
    sensor_type, since no frame file exists) -- the gate must not fire, and
    the original shape-mismatch reason must still be the one reported. A
    truly empty composition cannot occur once records exist: reconstruction
    always yields at least one frame per source_file from the records'
    own sensor_type, same as every other Phase 7 slice observed."""
    bare_records = [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.GPR,
            latitude=41.0, longitude=15.0,
            position=GeographicPosition(lat=41.0, lon=15.0),
            depth=None, signal=[1.0],
            metadata={"source_file": "line.SGY"})
        for _ in range(3)
    ]
    resp = _call(monkeypatch, bare_records, [])
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "does not apply" not in detail
