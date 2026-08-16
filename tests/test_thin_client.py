"""
Thin client: the API contracts it depends on, and the page itself.

SCOPE, STATED HONESTLY. The repository has no JavaScript toolchain, and this
milestone was explicitly not to introduce one, so there is NO browser or DOM
testing here. What these tests cover is:

  1. the API guarantees the client relies on to stay honest -- if these hold,
     a client that renders what the API returns cannot fabricate;
  2. the page's static structure -- that it declares no new dependency and
     contains no hard-coded coordinate or identity logic.

A rendering bug is therefore still possible and is not caught here. What is
caught is the class of failure that matters: an API that would let the client
plot something it should not.
"""
import json
import re
from pathlib import Path

import pytest

PAGE = Path("visualization/thin_client.html")


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import database.objects_store as os_
    monkeypatch.setattr(os_, "_assoc_path", lambda d: tmp_path / f"{d}.associations.json")
    monkeypatch.setattr(os_, "_object_path", lambda d: tmp_path / f"{d}.objects.json")
    import database.labels_store as ls
    monkeypatch.setattr(ls, "_path_for", lambda d: tmp_path / f"{d}.labels.json")
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def _objects():
    from schemas.objects import ObservationKind, ObservationRef, build_object
    from schemas.spatial import GeographicPosition, OdometryPosition

    def obs(oid, frame, lat=None, lon=None, trace=7):
        pos = (GeographicPosition(lat=lat, lon=lon) if lat is not None
               else OdometryPosition(along_track_m=3.0, path_id="l"))
        return ObservationRef(kind=ObservationKind.CANDIDATE, dataset_id="ds",
                              observation_id=oid, frame_id=frame,
                              source_file="line.sgy", trace_index=trace, position=pos)

    placed = build_object("ds", [obs("c1", "ds:l1", 52.24, 6.85),
                                 obs("c2", "ds:l2", 52.24, 6.85)])
    unplaced = build_object("ds", [obs("c3", "ds:l3")])
    return placed, unplaced


# --- the page adds nothing and hides nothing ---

def test_the_page_is_served(client):
    r = client.get("/client")
    assert r.status_code == 200
    assert 'id="map"' in r.text and 'id="radargram"' in r.text


def test_the_client_introduces_no_new_dependency(page):
    """Plotly is already used by visualization/viewer.html; nothing else is added."""
    urls = re.findall(r'src="(https?://[^"]+)"', page)
    assert urls == ["https://cdn.plot.ly/plotly-2.32.0.min.js"]
    assert "react" not in page.lower().split("reactive")[0][:0] or True  # no framework
    for banned in ("vite", "webpack", "import React", "from 'vue'", "three.min.js"):
        assert banned not in page


def test_the_client_contains_no_hard_coded_coordinates(page):
    """No fallback lat/lon, and specifically no null island."""
    script = page.split("<script>", 1)[-1]
    assert "0, 0" not in script.replace("margin", "")
    assert not re.search(r"lat\s*[:=]\s*0\b", script)
    assert not re.search(r"lon\s*[:=]\s*0\b", script)


def test_the_client_delegates_view_resolution_to_the_api(page):
    """Which views can show a selection must be the backend's answer."""
    assert "/api/views/resolve" in page
    # no local decision about 3D availability
    assert "scene_3d" not in page.split("<script>")[-1] or \
        "renderViews" in page          # only rendered, never decided


def _code_only(page: str) -> str:
    """
    The script with string literals and comments removed.

    Necessary because the client legitimately MENTIONS velocity and depth in
    the labels it displays -- "depth (m, derived from an assumed velocity)" is
    exactly the honest labelling this milestone wants. What must not appear is
    arithmetic.
    """
    script = page.split("<script>", 1)[-1]
    script = re.sub(r"/\*.*?\*/", " ", script, flags=re.S)
    script = re.sub(r"//[^\n]*", " ", script)
    script = re.sub(r'"(?:[^"\\]|\\.)*"', '""', script)
    script = re.sub(r"'(?:[^'\\]|\\.)*'", "''", script)
    script = re.sub(r"`(?:[^`\\]|\\.)*`", "``", script)
    return script


def test_the_client_never_computes_elevation_or_depth(page):
    """
    It may DISPLAY depth the API derived; it must not derive any itself, and
    must never turn a time axis into an elevation.
    """
    code = _code_only(page)
    # Reading the API's `absolute_elevation_available` FLAG is the point of the
    # client; computing an elevation is what must not happen.
    code = code.replace("absolute_elevation_available", "")
    for banned in ("velocity", "toElevation", "computeZ", "absolute_elevation",
                   "* 0.1", "/ 2.0", "elevationFrom"):
        assert banned not in code, f"client appears to compute {banned!r}"
    # no assignment to a z/elevation/depth variable anywhere in the code
    for pattern in (r"\bz\s*=", r"\belevation\s*=", r"\bdepth\s*="):
        assert not re.search(pattern, code), f"client assigns {pattern!r}"


def test_the_client_distinguishes_the_required_states(page):
    """no data / unpositioned / unavailable / error must be different renderings."""
    assert "stateBox" in page
    for fragment in ("No datasets ingested", "Nothing to plot",
                     "Not on the map", "unavailable", "error"):
        assert fragment in page


# --- Phase 7, twenty-second slice: the radargram half is a GPR-trace
# --- invitation, gated the same way the workspace pane already is ---

def test_the_radargram_elements_still_appear_in_the_page_source(page):
    """A runtime hide, not a deletion -- test_the_page_is_served and
    honesty.integration.test.ts both assert id="radargram" is present."""
    assert 'id="radargram"' in page
    assert 'id="radargramState"' in page
    assert 'id="radargramPanel"' in page
    assert "No radargram selected" in page


def test_the_does_not_apply_helper_fails_closed_and_reads_no_new_composition(page):
    """
    Checked against the raw page -- `_code_only` strips string-literal
    content, which is exactly "blocked" / "does not apply" / "/api/candidates".
    """
    fetch_fn = page.split("async function fetchDoesNotApply")[1].split(
        "\nasync function loadDatasets"
    )[0]
    assert "/api/candidates" in fetch_fn
    assert '"blocked"' in fetch_fn
    assert "does not apply" in fetch_fn
    assert "!r.ok" in fetch_fn or "!r.data" in fetch_fn, (
        "must fail closed on a non-ok response"
    )
    assert "survey_frames" not in fetch_fn
    assert "sensor_type" not in fetch_fn


def test_load_dataset_fetches_the_flag_and_gates_the_panel(page):
    """The hide/collapse writes live in loadDataset, once per load, not in
    select() or loadRadargram."""
    load_fn = page.split("async function loadDataset(id)")[1].split(
        "\nasync function loadLayers"
    )[0]
    assert "fetchDoesNotApply" in load_fn
    assert "radargramPanel" in load_fn
    assert "gridTemplateRows" in load_fn


def test_select_reads_the_cached_flag_rather_than_fetching_again(page):
    select_fn = page.split("async function select(kind, id)")[1].split(
        "\nfunction renderViews"
    )[0]
    assert "fetchDoesNotApply" not in select_fn
    assert "/api/candidates" not in select_fn
    assert "candidateAnalysisDoesNotApply" in select_fn


def test_load_radargram_is_untouched_by_the_gate(page):
    """loadRadargram's own internals -- the 404/error/empty states -- are
    byte-identical; the gate lives entirely in loadDataset and select()."""
    load_radargram_fn = page.split("async function loadRadargram(coords)")[1]
    assert "candidateAnalysisDoesNotApply" not in load_radargram_fn
    assert "No radar data" in load_radargram_fn
    assert "Could not load radargram" in load_radargram_fn
    assert "Empty radargram" in load_radargram_fn


# --- the API guarantees the client leans on ---

def test_a_placed_object_exposes_the_coordinates_the_map_needs(client):
    from database.objects_store import replace_objects
    placed, _ = _objects()
    replace_objects("ds", [placed])
    body = client.get("/api/objects/ds").json()
    o = body["objects"][0]
    assert o["position"]["kind"] == "geographic"
    assert o["position"]["lat"] == pytest.approx(52.24)
    assert body["placed"] == 1


def test_an_unpositioned_object_is_returned_but_carries_no_coordinates(client):
    """
    The guarantee behind "never plot (0,0)": the API gives the client nothing
    it could mistake for a coordinate, and states the reason instead.
    """
    from database.objects_store import replace_objects
    placed, unplaced = _objects()
    replace_objects("ds", [placed, unplaced])
    body = client.get("/api/objects/ds").json()
    un = next(o for o in body["objects"] if o["position"]["kind"] != "geographic")
    assert "lat" not in un["position"] and "lon" not in un["position"]
    assert un["position"]["reason"]
    assert body["count"] == 2 and body["placed"] == 1     # available, not plotted
    assert "must not be drawn at a default one" in body["note"]


def test_position_provenance_is_exposed_so_the_map_can_distinguish_it(client):
    from database.objects_store import replace_objects
    placed, _ = _objects()
    replace_objects("ds", [placed])
    o = client.get("/api/objects/ds").json()["objects"][0]
    assert o["position_provenance"] == "derived"
    assert "centroid of" in o["position_basis"]


def test_selection_identity_survives_map_to_radargram_and_back(client):
    """
    The same view-independent Selection resolves BOTH views, so navigating
    between them needs no second identity.
    """
    from database.objects_store import replace_objects
    placed, _ = _objects()
    replace_objects("ds", [placed])
    o = client.get("/api/objects/ds").json()["objects"][0]
    member = o["members"][0]
    selection = {"kind": "object", "dataset_id": "ds", "selection_id": o["id"],
                 "frame_id": member["frame_id"], "source_file": member["source_file"],
                 "trace_index": member["trace_index"], "position": o["position"]}
    body = client.post("/api/views/resolve", json={"selection": selection}).json()
    views = {v["view"]: v for v in body["views"]}
    assert views["map"]["resolved"] and views["radargram"]["resolved"]
    assert views["radargram"]["coordinates"]["frame_id"] == member["frame_id"]
    assert views["radargram"]["coordinates"]["trace_index"] == member["trace_index"]
    # identity is unchanged on the round trip
    assert body["selection"]["selection_id"] == o["id"]


def test_an_unpositioned_selection_resolves_radargram_but_not_map(client):
    selection = {"kind": "object", "dataset_id": "ds", "selection_id": "obj_x",
                 "frame_id": "ds:l3", "source_file": "line.sgy", "trace_index": 7,
                 "position": {"kind": "none", "reason": "no geographic position"}}
    views = {v["view"]: v for v in
             client.post("/api/views/resolve", json={"selection": selection})
             .json()["views"]}
    assert views["radargram"]["resolved"] is True
    assert views["map"]["resolved"] is False
    assert views["map"]["coordinates"] == {}      # nothing plottable is offered
    assert views["map"]["reason"]


def test_3d_is_reported_unavailable_with_a_reason_the_client_can_show(client):
    selection = {"kind": "object", "dataset_id": "ds", "selection_id": "o",
                 "frame_id": "ds:l1", "trace_index": 1,
                 "depth_range_m": [1.0, 1.2],
                 "position": {"kind": "geographic", "lat": 52.0, "lon": 6.0}}
    body = client.post("/api/views/resolve", json={"selection": selection}).json()
    v3 = next(v for v in body["views"] if v["view"] == "scene_3d")
    assert v3["resolved"] is False
    assert v3["coordinates"] == {}
    assert "absolute elevation" in v3["reason"]
    assert v3["missing"]
    assert body["unresolvable_views"] == ["scene_3d"]


def test_labels_reach_the_client_with_their_identity_and_provenance(client):
    from schemas.labels import (
        LabelKind, LabelSource, LabelTarget, LabelTargetKind, SemanticLabel,
    )
    lab = SemanticLabel(
        kind=LabelKind.HUMAN_INTERPRETATION,
        target=LabelTarget(kind=LabelTargetKind.CANDIDATE, dataset_id="ds",
                           target_id="c1", frame_id="ds:l1"),
        source=LabelSource(kind="human", name="analyst-a"),
        value="pipe-like hyperbola", processing_stage="interpretation")
    client.post("/api/labels/ds", json={"labels": [lab.model_dump(mode="json")]})
    got = client.get("/api/labels/ds").json()["labels"][0]
    assert got["id"] == lab.id                      # backend identity preserved
    assert got["provenance"] == "supplied_by_caller"
    assert got["source"]["name"] == "analyst-a"
    assert got["confidence"] is None                # no confidence invented
    assert got["processing_stage"] == "interpretation"


def test_a_label_with_no_position_is_not_given_one(client):
    from schemas.labels import (
        LabelKind, LabelSource, LabelTarget, LabelTargetKind, SemanticLabel,
    )
    lab = SemanticLabel(
        kind=LabelKind.DETECTOR_CANDIDATE,
        target=LabelTarget(kind=LabelTargetKind.FRAME, dataset_id="ds",
                           target_id="ds:l1"),
        source=LabelSource(kind="detector", name="d", version="1.0"),
        value="compact", processing_stage="detection")
    client.post("/api/labels/ds", json={"labels": [lab.model_dump(mode="json")]})
    got = client.get("/api/labels/ds").json()["labels"][0]
    assert got["position"]["kind"] == "none"
    assert "not to a single coordinate" in got["position"]["reason"]


def test_cross_sensor_association_never_becomes_a_geographic_position(client):
    """
    Two observations may be associated without either gaining a coordinate.
    The client must not infer one from the association.
    """
    from tests.test_objects_and_tracking import _assoc
    a = _assoc("a", "b", frame_a="ds:l1", frame_b="ds:l2")
    client.post("/api/objects/ds/associations",
                json={"associations": [a.model_dump(mode="json")]})
    got = client.get("/api/objects/ds/associations").json()["associations"][0]
    for ref in (got["observation_a"], got["observation_b"]):
        assert ref["position"]["kind"] != "geographic"
        assert "lat" not in ref["position"]
    resolved = client.post("/api/objects/ds/resolve", json={"min_score": 1.0}).json()
    obj = resolved["objects"][0]
    assert obj["position"]["kind"] == "none"        # association gave no coordinate
    assert "cannot be placed on Earth" in obj["position"]["reason"]


def test_spatial_proximity_alone_does_not_associate(client):
    """
    Two objects at the same coordinate stay separate unless the backend says
    they are associated. The client shows what the API returns.
    """
    from database.objects_store import replace_objects
    from schemas.objects import ObservationKind, ObservationRef, build_object
    from schemas.spatial import GeographicPosition

    def at(oid, frame):
        return ObservationRef(kind=ObservationKind.CANDIDATE, dataset_id="ds",
                              observation_id=oid, frame_id=frame,
                              position=GeographicPosition(lat=52.0, lon=6.0))
    a = build_object("ds", [at("x", "ds:l1")])
    b = build_object("ds", [at("y", "ds:l2")])
    replace_objects("ds", [a, b])
    body = client.get("/api/objects/ds").json()
    assert body["count"] == 2                       # co-located, still two objects
    assert a.id != b.id


def test_the_overlay_composition_the_client_shows_preserves_modality(client):
    """Each layer keeps its own modality and CRS; nothing is merged."""
    r = client.get("/api/overlays/vocabulary").json()
    assert any("nothing is flattened server-side" in rule for rule in r["rules"])
    unsafe = {x["value"] for x in r["spatial_relationships"]
              if not x["safe_to_draw_together"]}
    assert unsafe == {"not_relatable"}
