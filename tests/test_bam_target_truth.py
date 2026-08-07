"""The transcribed BAM target truth.

`benchmark/bam_pk266_targets.json` is the first target ground truth Subterra
holds -- the identity, geometry, position and depth of things actually in a
medium, as opposed to where the instrument was. It was typed in by hand from
publications, because the data repository ships no geometry file at all.

That origin is exactly why it needs guarding. These tests check the properties
that make it usable and honest:

  * every target carries a position AND the source that position came from,
    so no number in it can be mistaken for something Subterra measured;
  * the frame is declared, in mm, with no CRS and no vertical datum claimed --
    depth here is measured from a physical surface, not an elevation;
  * the empty specimen is attested empty rather than merely blank;
  * the published disagreement between the two sources is still recorded.

They do NOT test the radar data, which is gitignored and not present in CI.
"""
import json
from pathlib import Path

import pytest

TRUTH = Path(__file__).resolve().parents[1] / "benchmark" / "bam_pk266_targets.json"


@pytest.fixture(scope="module")
def truth():
    return json.loads(TRUTH.read_text())


@pytest.fixture(scope="module")
def targets(truth):
    pk266 = next(s for s in truth["specimens"] if s["id"] == "Pk266")
    return pk266["targets"]


# --- the file says where it came from ---

def test_it_declares_itself_transcribed_not_measured(truth):
    assert truth["provenance_class"] == "transcribed_from_publication"


def test_the_repository_is_recorded_as_carrying_no_target_geometry(truth):
    assert truth["sources"]["data_repository"]["contains_target_geometry"] is False


def test_every_source_is_identified_by_doi(truth):
    for name, src in truth["sources"].items():
        assert src.get("doi"), f"source {name} has no DOI"


# --- every coordinate is attributable ---

def test_every_target_has_a_position_and_a_depth(targets):
    assert len(targets) == 4
    for t in targets:
        assert isinstance(t["x_mm"], (int, float))
        assert isinstance(t["centre_depth_mm"], (int, float))


def test_no_coordinate_is_stated_without_naming_its_source(targets):
    """A number whose origin is unrecorded is indistinguishable from one made up."""
    for t in targets:
        assert t["x_source"], f"{t['target_id']} x has no source"
        assert t["centre_depth_source"], f"{t['target_id']} depth has no source"


def test_every_target_has_identity_and_geometry(targets):
    for t in targets:
        assert t["type"] and t["material"] and t["orientation"]
        g = t["geometry"]
        assert g["shape"] == "cylinder"
        assert 0 < g["inner_diameter_mm"] < g["outer_diameter_mm"]


def test_targets_sit_inside_the_specimen(truth, targets):
    pk266 = next(s for s in truth["specimens"] if s["id"] == "Pk266")
    length = pk266["dimensions_mm"]["length_x"]
    deepest_step = max(pk266["step_thicknesses_mm"])
    for t in targets:
        assert 0 <= t["x_mm"] <= length
        assert 0 < t["centre_depth_mm"] < deepest_step


def test_target_ids_are_unique(targets):
    ids = [t["target_id"] for t in targets]
    assert len(set(ids)) == len(ids)


# --- the frame is declared, and claims nothing it cannot support ---

def test_the_frame_is_local_millimetres_with_no_crs_asserted(truth):
    f = truth["coordinate_frame"]
    assert f["kind"] == "local_cartesian"
    assert f["units"] == "mm"
    assert f["crs"] is None and f["crs_provenance"] == "none"


def test_no_vertical_datum_is_claimed(truth):
    """Depth from a specimen surface is not an elevation, and must not pretend to be."""
    f = truth["coordinate_frame"]
    assert f["vertical_datum"] is None
    assert "not an elevation" in f["vertical_datum_note"]


def test_the_shared_frame_claim_carries_its_evidence(truth):
    f = truth["coordinate_frame"]
    assert f["shared_with_radar"] is True
    assert "5 mm steps" in f["shared_with_radar_evidence"]


def test_target_x_lands_on_an_actual_scanner_grid_node(targets):
    """The scanner grid is 0..2000 mm in 5 mm steps; association needs no interpolation."""
    for t in targets:
        assert t["x_mm"] % 5 == 0


# --- absence is attested, not assumed ---

def test_the_control_specimen_is_attested_empty_not_merely_blank(truth):
    pk050 = next(s for s in truth["specimens"] if s["id"] == "Pk050")
    assert pk050["role"] == "negative_control"
    assert pk050["targets"] == []
    assert pk050["empty_is_attested"] is True
    assert "does not contain any embedded elements" in pk050["empty_attestation"]


def test_the_control_does_not_overclaim_to_be_featureless(truth):
    """Its step back walls are real reflectors; a false-alarm rate must account for them."""
    pk050 = next(s for s in truth["specimens"] if s["id"] == "Pk050")
    assert "not featureless" in pk050["back_wall_note"]


def test_the_undigitised_specimen_is_excluded_with_a_reason(truth):
    pk401 = next(s for s in truth["specimens"] if s["id"] == "Pk401")
    assert pk401["not_acquired"] is True
    assert "digitis" in pk401["reason"]


# --- the disagreement between sources survives ---

def test_the_cover_versus_centre_discrepancy_is_still_recorded(truth):
    q = next(q for q in truth["open_questions"] if q["id"] == "cover-vs-centre-reference")
    assert q["magnitude_mm"] == 3.5
    assert q["resolution_route"]


def test_both_published_depths_are_kept_and_differ_by_the_inner_radius(targets):
    """The two sources disagree by exactly 30 mm. Neither was edited to agree."""
    for t in targets:
        gap = round(t["centre_depth_mm"] - t["concrete_cover_mm"], 6)
        assert gap == 30.0, f"{t['target_id']}: sources now differ by {gap}, not 30.0"
        assert t["concrete_cover_tolerance_mm"] > 0
