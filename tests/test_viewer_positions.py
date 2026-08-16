"""
The 3D viewer plots only records that have a position.

WHY THIS EXISTS. `/api/datasets/{id}/points` returns `lat: 0.0, lon: 0.0`
for a record whose position is absent, and states that per point via
`position_kind`. That is a deliberate contract -- see
`test_frame_read_path.py::test_points_endpoint_distinguishes_placeholder_from_real_coordinates`,
"(0,0) in lat/lon must be identifiable as 'no position', not a location".

`visualization/viewer.html` previously ignored the field and plotted the
placeholder, which put every unpositioned record at null island, labelled
it `lat: 0.000000, lon: 0.000000`, and dragged the local-metre origin
toward (0,0) for any real points loaded alongside.

SCOPE, as with test_thin_client.py: there is no JavaScript toolchain in
this repository, so this asserts the page's static structure and the API
guarantee it leans on. A rendering bug is still possible. What is caught is
the regression that matters -- the filter being removed, or a placing view
going back to the unfiltered list.
"""
import re
from pathlib import Path

import pytest

PAGE = Path("visualization/viewer.html")


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text()


@pytest.fixture(scope="module")
def script(page: str) -> str:
    """The inline script with comments and string literals removed."""
    body = page.split("<script>", 1)[-1]
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    body = re.sub(r"//[^\n]*", " ", body)
    body = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body)
    body = re.sub(r"'(?:[^'\\]|\\.)*'", "''", body)
    body = re.sub(r"`(?:[^`\\]|\\.)*`", "``", body)
    return body


def test_the_viewer_is_still_served(client_app):
    r = client_app.get("/viewer")
    assert r.status_code == 200
    assert 'id="plot"' in r.text


@pytest.fixture()
def client_app():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def test_the_page_filters_points_on_position_kind(page, script):
    """The filter itself must exist and key on the API's own field."""
    assert "geographicPoints" in script
    # asserted on the raw page: the comparison value is the literal the API
    # returns, and stripping string literals would erase exactly that.
    assert re.search(
        r'position_kind\s*===\s*"geographic"', page
    ), "the filter no longer compares position_kind against 'geographic'"


def test_every_placing_view_reads_the_filtered_set(script):
    """
    The point cloud, the local-metre origin and the focus bounding box all
    place things on Earth, so all three must read geoPoints. A regression
    here is a view quietly going back to plotting placeholders.
    """
    # the scatter3d render
    assert re.search(r"let\s+points\s*=\s*data\.geoPoints", script)
    # the reference point for local-metre conversion
    assert re.search(r"for\s*\(const pt of data\.geoPoints\)", script)
    # the focus bounding box, both branches
    assert "flatMap(d => d.geoPoints)" in script
    assert re.search(r"allTraces\[sel\]\.geoPoints", script)


def test_no_placing_view_still_reads_the_unfiltered_list(script):
    """
    `data.points` is legitimately used for the DEPTH bounds, which do not
    need a position. It must not be used for anything geographic.
    """
    geographic_uses = re.findall(
        r"toLocalMeters\([^)]*\)|computeBBox\(([^)]*)\)", script
    )
    assert "data.points" not in " ".join(str(g) for g in geographic_uses)
    # the only surviving raw-points loop is the depth scan
    raw_loops = re.findall(r"for\s*\(const pt of data\.points\)", script)
    assert len(raw_loops) == 1, (
        "expected exactly one non-geographic use of data.points (the depth "
        f"bounds); found {len(raw_loops)}"
    )


def test_excluded_records_are_counted_not_silently_dropped(script):
    """An empty plot and a partly-plotted one must not look alike."""
    assert "excludedNoPosition" in script


def test_the_page_states_when_nothing_can_be_placed(page):
    assert "Nothing to plot" in page
    assert "carry no geographic position" in page


# --- Phase 7, nineteenth slice: the B-scan claim in the empty-scene status
# --- is a GPR-trace claim, gated the same way the React panes already are ---

def test_the_bscan_still_works_sentence_survives_for_the_gpr_path(page):
    """The GPR path keeps the original sentence verbatim -- this is a gate,
    not a deletion."""
    assert (
        "the B-scan view still works because it is indexed by trace, "
        "not by coordinate."
    ) in page


def test_the_empty_scene_status_does_not_unconditionally_claim_the_bscan_works(script):
    """
    The B-scan clause must not simply be concatenated into the status every
    time -- it has to be conditional on the same off-GPR signal the
    candidates API already reports (slices 4, 10-16), reused rather than a
    second composition definition invented here.
    """
    render_fn = re.split(r"\bfunction render\(", script)[1].split("function ")[0]
    assert "candidateAnalysisDoesNotApply" in render_fn
    assert re.search(r"\.every\(d => d\.candidateAnalysisDoesNotApply\)", render_fn)
    assert re.search(r"allDoesNotApply\s*\?", render_fn), (
        "the B-scan clause must be behind a conditional on allDoesNotApply, "
        "not always appended"
    )


def test_the_does_not_apply_signal_reads_the_existing_candidates_endpoint(page, script):
    """No new field, no client-side composition parsing: the same
    status/status_reason shape GET /api/candidates/{id} already returns.
    Checked against the raw page -- `script` strips string-literal content,
    which is exactly what "blocked" / "does not apply" are.
    """
    assert re.search(r"/candidates/\$\{datasetId\}", page)
    assert re.search(r'status\s*===\s*"blocked"', page)
    assert 'includes("does not apply")' in page
    # not a new definition of composition -- no survey_frames/sensor_type read
    assert "survey_frames" not in script
    assert "sensor_type" not in re.split(
        r"async function fetchDatasetDoesNotApply", script
    )[1].split("async function")[0]


def test_the_does_not_apply_flag_is_fetched_once_at_load_not_on_every_render(script):
    """render() must stay synchronous with respect to this signal: it reads
    a value already cached on allTraces, it does not fetch it."""
    load_fn = script.split("async function loadDatasets")[1].split("function ")[0]
    assert "fetchDatasetDoesNotApply" in load_fn

    render_fn = re.split(r"\bfunction render\(", script)[1].split("function ")[0]
    assert "fetchDatasetDoesNotApply" not in render_fn


def test_the_bscan_view_is_not_position_filtered(script):
    """
    The B-scan is indexed by trace and depth and carries no coordinate, so
    it must keep working for a dataset with no positions at all. It reads
    the trace grid, never the point list.
    """
    bscan = script.split("async function renderBscan")[1].split("async function")[0]
    assert "geoPoints" not in bscan
    assert "fetchDatasetTraceGrid" in bscan


# --- Phase 7, twentieth slice: the B-scan option itself is a GPR-trace
# --- invitation, gated the same way the empty-scene sentence already is ---

def test_the_bscan_option_still_appears_in_the_page_source(page):
    """A runtime gate, not a deletion -- the GPR path and the fail-closed
    default both still need this option in the page."""
    assert 'value="bscan"' in page
    assert 'id="bscanOption"' in page


def test_load_datasets_gates_the_bscan_option_reusing_the_cached_flag(page):
    """
    No second fetch: the same candidateAnalysisDoesNotApply flag slice 19
    already caches on allTraces, only read here, not re-derived. Checked
    against the raw page -- `script` strips "bscanOption" and "bscan" as
    string-literal content, which is exactly what this test needs to see.
    """
    load_fn = page.split("async function loadDatasets")[1].split("\nfunction ")[0]
    assert "bscanOption" in load_fn
    assert "candidateAnalysisDoesNotApply" in load_fn
    assert re.search(r"\.every\(d => d\.candidateAnalysisDoesNotApply\)", load_fn)
    # switches away from the bscan view before render() rather than leaving
    # a hidden option selected
    assert re.search(r'viewMode\s*===\s*"bscan"', load_fn)


def test_the_bscan_option_gate_is_absent_from_render_and_view_mode_change(page):
    """
    render() and onViewModeChange() must not hide/show the option or
    refetch -- the gate is applied once per load, in loadDatasets, and nowhere
    else. Sibling to the slice 19 test pinning fetchDatasetDoesNotApply's
    absence from render(): this pins the option-visibility write specifically.
    """
    render_fn = re.split(r"\bfunction render\(", page)[1].split("\nfunction ")[0]
    assert "bscanOption" not in render_fn

    view_mode_change_fn = page.split("function onViewModeChange")[1].split(
        "async function renderHeatmap"
    )[0]
    assert "bscanOption" not in view_mode_change_fn


def test_the_viewer_introduces_no_new_dependency(page):
    """Unchanged from before: Plotly and nothing else."""
    urls = re.findall(r'src="(https?://[^"]+)"', page)
    assert urls == ["https://cdn.plot.ly/plotly-2.32.0.min.js"]


# --- the API guarantee the filter leans on ---------------------------------

def test_the_api_marks_an_absent_position_so_the_viewer_can_exclude_it(monkeypatch):
    """
    If this contract ever changed -- lat/lon becoming null, or position_kind
    disappearing -- the viewer's filter would silently drop everything or
    nothing. This pins the field the filter reads.
    """
    from tests.test_frame_read_path import _endpoint, _frame, _trace_records

    body = _endpoint(monkeypatch, "/api/datasets/ds/points",
                     _trace_records(geographic=False), [_frame()])
    assert body["position_kinds"] == {"none": len(body["points"])}
    for point in body["points"]:
        assert point["position_kind"] == "none"
        # the placeholder the viewer must not plot
        assert point["lat"] == 0.0 and point["lon"] == 0.0


def test_a_positioned_record_is_marked_geographic_and_survives_the_filter(monkeypatch):
    from tests.test_frame_read_path import _endpoint, _frame, _trace_records

    body = _endpoint(monkeypatch, "/api/datasets/ds/points",
                     _trace_records(geographic=True), [_frame()])
    assert body["points"], "expected positioned records"
    assert all(p["position_kind"] == "geographic" for p in body["points"])
    assert not all(p["lat"] == 0.0 for p in body["points"])
