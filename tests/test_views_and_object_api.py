"""
Synchronized views and the viewer-facing object API.

The thing being protected: a view that cannot locate a selection must say so,
with the reason and what is missing. It must never return a default coordinate,
and it must never invent a Z.

`scene_3d` is unresolvable for every dataset currently held, and that is
asserted rather than treated as a temporary gap -- absolute elevation needs a
vertical registration that `docs/vertical-reference-site01.md` established does
not exist.
"""
import pytest

from schemas.spatial import (
    AxisKind, CRSKind, CRSProvenance, GeographicPosition, LocalCartesianPosition, NoPosition,
    OdometryPosition, ProjectedPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SensorType
from schemas.survey_frame import SurveyFrame
from schemas.views import Selection, SelectionKind, ViewKind, resolve


def _sel(**kw):
    base = dict(kind=SelectionKind.CANDIDATE, dataset_id="ds", selection_id="c1",
                frame_id="ds:line", source_file="line.sgy", trace_index=42,
                trace_range=(40, 44), depth_range_m=(1.1, 1.3),
                position=GeographicPosition(lat=52.24, lon=6.85))
    base.update(kw)
    return Selection(**base)


def _views(res):
    return {v.view: v for v in res.views}


# --- what resolves ---

def test_a_fully_specified_geographic_selection_resolves_all_but_3d():
    r = resolve(_sel())
    assert r.resolvable_views == ["map", "radargram", "depth_slice", "metadata"]


def test_map_resolution_carries_the_selections_own_coordinates():
    v = _views(resolve(_sel()))[ViewKind.MAP]
    assert v.coordinates == {"lat": 52.24, "lon": 6.85}


def test_radargram_resolution_carries_frame_and_trace():
    v = _views(resolve(_sel()))[ViewKind.RADARGRAM]
    assert v.coordinates["frame_id"] == "ds:line"
    assert v.coordinates["trace_index"] == 42
    assert v.coordinates["trace_range"] == [40, 44]


def test_metadata_always_resolves_since_it_needs_only_identifiers():
    for sel in (_sel(), _sel(position=NoPosition(reason="none"), frame_id=None,
                             trace_index=None, trace_range=None, depth_range_m=None)):
        assert _views(resolve(sel))[ViewKind.METADATA].resolved is True


# --- what does not, and why ---

def test_scene_3d_is_unresolvable_and_says_exactly_why():
    v = _views(resolve(_sel()))[ViewKind.SCENE_3D]
    assert v.resolved is False
    assert "instrument time-zero, not the ground surface" in v.reason
    assert "no source declares a vertical datum" in v.reason
    assert v.missing == ["an established vertical relationship (absolute elevation)"]


def test_scene_3d_stays_unresolvable_even_with_a_vertical_assessment():
    """registration_required is the answer for every dataset held."""
    vertical = {"kind": "registration_required",
                "absolute_elevation_available": False,
                "missing": ["a declared vertical datum for the acquisition elevations"]}
    v = _views(resolve(_sel(), vertical=vertical))[ViewKind.SCENE_3D]
    assert v.resolved is False
    assert "registration_required" in v.reason
    assert v.missing == vertical["missing"]


def test_scene_3d_would_resolve_if_a_vertical_relationship_ever_existed():
    """The path is not hard-coded shut; it is shut by the data."""
    v = _views(resolve(_sel(), vertical={"kind": "absolute_elevation",
                                         "absolute_elevation_available": True}))
    assert v[ViewKind.SCENE_3D].resolved is True


@pytest.mark.parametrize("position,fragment", [
    (OdometryPosition(along_track_m=3.0, path_id="l"),
     "which has no defined location on Earth"),
    (LocalCartesianPosition(x=1.0, y=2.0), "no defined location on Earth"),
    (ProjectedPosition(easting=255000.0, northing=473300.0), "no defined location"),
])
def test_a_non_geographic_selection_cannot_be_mapped(position, fragment):
    v = _views(resolve(_sel(position=position)))[ViewKind.MAP]
    assert v.resolved is False
    assert fragment in v.reason
    assert v.coordinates == {}          # no default coordinate is emitted


def test_an_absent_position_reports_its_own_reason():
    v = _views(resolve(_sel(position=NoPosition(
        reason="the headers are (0, 0)"))))[ViewKind.MAP]
    assert v.resolved is False
    assert "(0, 0)" in v.reason


def test_a_selection_with_no_frame_cannot_open_a_radargram():
    v = _views(resolve(_sel(frame_id=None)))[ViewKind.RADARGRAM]
    assert v.resolved is False
    assert v.missing == ["frame_id"]


def test_a_frame_without_a_trace_cannot_be_highlighted():
    v = _views(resolve(_sel(trace_index=None, trace_range=None)))[ViewKind.RADARGRAM]
    assert v.resolved is False
    assert "only meaningful within one acquisition" in v.reason


# --- Phase 7, sixth slice: radargram does not apply to an off-gpr composition ---

def test_off_gpr_composition_names_it_and_says_does_not_apply_even_with_a_frame():
    """A frame_id and a trace_index are present -- the composition gate must
    still win, and the old "names no frame" / "needs a trace index" reasons
    must not appear."""
    v = _views(resolve(_sel(), recorded_modalities=["lidar"]))[ViewKind.RADARGRAM]
    assert v.resolved is False
    assert "lidar" in v.reason
    assert "does not apply" in v.reason
    assert "names no frame" not in v.reason
    assert "needs a trace index" not in v.reason
    assert v.coordinates == {}


def test_off_gpr_composition_applies_even_with_no_frame_id_at_all():
    """The point of loading frames for composition regardless of frame_id:
    an object/label selection with no frame gets the SAME does-not-apply
    reason, not the frame-less reason."""
    v = _views(resolve(_sel(frame_id=None, trace_index=None, trace_range=None),
                       recorded_modalities=["lidar"]))[ViewKind.RADARGRAM]
    assert v.resolved is False
    assert "lidar" in v.reason
    assert "does not apply" in v.reason
    assert v.missing != ["frame_id"]


def test_gpr_or_mixed_composition_is_unaffected():
    gpr = _views(resolve(_sel(), recorded_modalities=["gpr"]))[ViewKind.RADARGRAM]
    mixed = _views(resolve(_sel(), recorded_modalities=["gpr", "lidar"]))[ViewKind.RADARGRAM]
    default = _views(resolve(_sel()))[ViewKind.RADARGRAM]
    assert gpr.resolved is mixed.resolved is default.resolved is True
    assert gpr.coordinates == mixed.coordinates == default.coordinates
    for v in (gpr, mixed):
        for invented in ("fused", "aligned", "ready for fusion", "multi-modal"):
            assert invented not in (v.reason or "").lower()


def test_empty_composition_keeps_todays_frame_and_trace_reasons():
    no_frame = _views(resolve(_sel(frame_id=None),
                              recorded_modalities=[]))[ViewKind.RADARGRAM]
    assert no_frame.resolved is False
    assert no_frame.missing == ["frame_id"]

    no_trace = _views(resolve(_sel(trace_index=None, trace_range=None),
                              recorded_modalities=[]))[ViewKind.RADARGRAM]
    assert no_trace.resolved is False
    assert "only meaningful within one acquisition" in no_trace.reason


def test_no_depth_means_no_depth_slice():
    v = _views(resolve(_sel(depth_range_m=None)))[ViewKind.DEPTH_SLICE]
    assert v.resolved is False
    assert "only when a propagation velocity was supplied" in v.reason


def test_a_time_axis_frame_cannot_be_depth_sliced():
    """Slicing a time axis by depth would be slicing time."""
    frame = SurveyFrame.model_construct(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy", source_file="line.sgy",
        spatial_ref=SpatialRef(kind=CRSKind.UNKNOWN, name="n"),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="instrument time-zero", positive_down=True,
                                   conversion=None),
        assumptions=[], source_metadata={})
    v = _views(resolve(_sel(), frame=frame))[ViewKind.DEPTH_SLICE]
    assert v.resolved is False
    assert "would be slicing time" in v.reason


def test_a_cross_frame_depth_slice_needs_a_shared_vertical_reference():
    v = _views(resolve(_sel(), cross_frame_slice=True))[ViewKind.DEPTH_SLICE]
    assert v.resolved is False
    assert "share a vertical reference" in v.reason


def test_no_unresolved_view_ever_returns_coordinates():
    """The invariant a client depends on: absent means absent."""
    for sel in (_sel(), _sel(position=NoPosition(reason="x")),
                _sel(frame_id=None), _sel(depth_range_m=None)):
        for v in resolve(sel).views:
            if not v.resolved:
                assert v.coordinates == {}
                assert v.reason


# --- API ---

@pytest.fixture()
def client(tmp_path, monkeypatch):
    import database.objects_store as os_
    monkeypatch.setattr(os_, "_assoc_path", lambda d: tmp_path / f"{d}.associations.json")
    monkeypatch.setattr(os_, "_object_path", lambda d: tmp_path / f"{d}.objects.json")
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def test_the_view_vocabulary_states_what_each_view_requires(client):
    body = client.get("/api/views/vocabulary").json()
    by_view = {v["value"]: v for v in body["views"]}
    assert "absolute elevation" in by_view["scene_3d"]["requires"]
    assert any("never a default coordinate" in r for r in body["rules"])
    assert any("scene_3d is unresolvable" in r for r in body["rules"])


def test_resolving_a_selection_over_the_api_reports_both_lists(client):
    r = client.post("/api/views/resolve", json={"selection": _sel().model_dump(mode="json")})
    body = r.json()
    assert body["resolvable_views"] == ["map", "radargram", "depth_slice", "metadata"]
    assert body["unresolvable_views"] == ["scene_3d"]


# --- Phase 7, sixth slice: the live route actually computes and passes ---
# --- composition, not only the pure `resolve()` helper -------------------

def _lidar_frame(**kw):
    base = dict(
        frame_id="ds:tile", dataset_id="ds", modality=SensorType.LIDAR,
        source_format="geotiff", source_file="tile.tif",
        spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326", horizontal_units="degree",
                               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER),
        vertical_axis=VerticalAxis(kind=AxisKind.DEPTH_M, units="m",
                                   origin="surface", positive_down=True),
    )
    base.update(kw)
    return SurveyFrame(**base)


def test_off_gpr_dataset_over_the_api_says_does_not_apply(client, monkeypatch):
    import api.routes.views as mod

    monkeypatch.setattr(mod, "load_frames", lambda _id: [_lidar_frame()])
    monkeypatch.setattr(mod, "load_records", lambda _id: [])

    r = client.post("/api/views/resolve", json={"selection": _sel().model_dump(mode="json")})
    body = r.json()
    assert r.status_code == 200
    radargram = next(v for v in body["views"] if v["view"] == "radargram")
    assert radargram["resolved"] is False
    assert "lidar" in radargram["reason"]
    assert "does not apply" in radargram["reason"]
    assert "names no frame" not in radargram["reason"]
    assert "trace index" not in radargram["reason"]
    assert "radargram" in body["unresolvable_views"]


def test_off_gpr_object_selection_with_no_frame_id_over_the_api(client, monkeypatch):
    """The route must load frames for composition even when the selection
    itself carries no frame_id -- an object/label pin on a LiDAR dataset."""
    import api.routes.views as mod

    monkeypatch.setattr(mod, "load_frames", lambda _id: [_lidar_frame()])
    monkeypatch.setattr(mod, "load_records", lambda _id: [])

    sel = _sel(kind=SelectionKind.OBJECT, frame_id=None, source_file=None,
               trace_index=None, trace_range=None)
    r = client.post("/api/views/resolve", json={"selection": sel.model_dump(mode="json")})
    radargram = next(v for v in r.json()["views"] if v["view"] == "radargram")
    assert radargram["resolved"] is False
    assert "does not apply" in radargram["reason"]
    assert radargram["missing"] != ["frame_id"]


def test_gpr_dataset_over_the_api_is_unaffected(client, monkeypatch):
    import api.routes.views as mod

    monkeypatch.setattr(mod, "load_frames", lambda _id: [
        SurveyFrame(
            frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
            source_format="segy", source_file="line.sgy",
            spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326", horizontal_units="degree",
                               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER),
            vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                       origin="time-zero", positive_down=True),
        )
    ])
    monkeypatch.setattr(mod, "load_records", lambda _id: [])

    r = client.post("/api/views/resolve", json={"selection": _sel().model_dump(mode="json")})
    body = r.json()
    radargram = next(v for v in body["views"] if v["view"] == "radargram")
    assert radargram["resolved"] is True
    assert radargram["coordinates"]["frame_id"] == "ds:line"


def test_the_object_vocabulary_says_which_status_is_a_real_thing(client):
    body = client.get("/api/objects/vocabulary").json()
    real = {s["value"] for s in body["object_statuses"] if s["is_real_thing"]}
    assert real == {"attested"}
    assert any("UNVALIDATED" in r for r in body["rules"])
    assert any("NOT a probability" in r for r in body["rules"])


def test_resolving_objects_with_no_associations_is_a_404(client):
    r = client.post("/api/objects/none/resolve", json={"min_score": 1.0})
    assert r.status_code == 404


def test_associations_round_trip_and_resolve_into_objects(client):
    from tests.test_objects_and_tracking import _assoc
    a = _assoc("a", "b", frame_a="ds:l1", frame_b="ds:l2")
    w = client.post("/api/objects/ds/associations",
                    json={"associations": [a.model_dump(mode="json")]})
    assert w.status_code == 200
    got = client.get("/api/objects/ds/associations").json()
    assert got["count"] == 1 and got["independent_count"] == 1

    r = client.post("/api/objects/ds/resolve", json={"min_score": 1.0}).json()
    assert r["objects_created"] == 1
    # two independent acquisitions -> corroborated, not attested
    assert r["by_status"]["corroborated"] == 1
    assert r["by_status"]["attested"] == 0


def test_re_resolving_at_a_higher_threshold_replaces_the_object_set(client):
    from tests.test_objects_and_tracking import _assoc
    client.post("/api/objects/ds/associations", json={"associations": [
        _assoc("a", "b", frame_a="ds:l1", frame_b="ds:l2", score=1.0).model_dump(mode="json"),
        _assoc("b", "c", frame_a="ds:l2", frame_b="ds:l3", score=0.5).model_dump(mode="json"),
    ]})
    loose = client.post("/api/objects/ds/resolve", json={"min_score": 0.0}).json()
    assert loose["objects_created"] == 1          # a-b-c in one group
    strict = client.post("/api/objects/ds/resolve", json={"min_score": 0.9}).json()
    assert strict["objects_created"] == 2         # a-b, and c alone
    listed = client.get("/api/objects/ds").json()
    assert listed["count"] == 2                   # replaced, not merged
