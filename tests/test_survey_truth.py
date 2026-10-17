"""
Controlled-survey ground truth (benchmark.survey_truth): what a survey must
prove before it can be scored, and the refusals that keep truth honest.

Every fixture here is SYNTHETIC: invented geometry for testing the schema,
not a real site and not truth for anything.
"""
import copy
import json
from pathlib import Path

import pytest

from benchmark.survey_truth import (
    BRIEF_REQUIREMENTS, Requirements, eligibility, load_survey_truth, load_survey_truth_dict,
    point_in_polygon, polygon_area, truth_digest, verify_digest,
)
from benchmark.targets import ManifestError

EXAMPLE = Path(__file__).parent / "fixtures" / "survey_truth_example.json"


def evidence(**kw):
    e = {"basis": "seeded_placement", "grade": "independently_verified",
         "independent_of_gpr": True, "source": "synthetic burial log (test fixture)"}
    e.update(kw)
    return e


def doc():
    return json.loads(EXAMPLE.read_text())


def test_the_example_loads_and_every_object_is_eligible():
    truth = load_survey_truth(EXAMPLE)
    rep = eligibility(truth)
    assert rep["ineligible"] == []
    assert rep["eligible_objects"] == {"linear": 1, "compact": 1}
    assert rep["eligible_empty_area_m2"] == pytest.approx(4.0)
    assert rep["control"]["ok"]
    assert rep["requirements"] == BRIEF_REQUIREMENTS.as_dict()


def test_the_digest_ignores_formatting_and_key_order_but_not_content():
    d = doc()
    reordered = json.loads(json.dumps(d, sort_keys=True, indent=4))
    assert truth_digest(d) == truth_digest(reordered)
    changed = copy.deepcopy(d)
    changed["objects"][0]["axis"]["vertices"][1][0] += 0.01
    assert truth_digest(changed) != truth_digest(d)


def test_a_sealed_digest_refuses_edited_truth():
    d = doc()
    sealed = truth_digest(d)
    load_survey_truth_dict(d, sealed_digest=sealed)
    d["custody"]["sealed_by"] = "someone else"
    with pytest.raises(ManifestError, match="does not match the sealed digest"):
        load_survey_truth_dict(d, sealed_digest=sealed)
    with pytest.raises(ManifestError):
        verify_digest(d, sealed)


def test_a_linear_object_must_give_its_axis():
    d = doc()
    del d["objects"][0]["axis"]
    with pytest.raises(ManifestError, match="surveyed axis polyline"):
        load_survey_truth_dict(d)


def test_class_group_is_declared_never_inferred():
    d = doc()
    d["objects"][1]["class_group"] = "stone"
    with pytest.raises(ManifestError, match="class_group"):
        load_survey_truth_dict(d)


def test_every_target_needs_a_survey_object_entry():
    d = doc()
    d["objects"].pop(1)
    with pytest.raises(ManifestError, match="without a survey object entry"):
        load_survey_truth_dict(d)


def test_an_axis_must_agree_with_the_targets_own_end_points():
    d = doc()
    d["objects"][0]["axis"]["vertices"][-1] = [8.0, 3.5]
    with pytest.raises(ManifestError, match="not an end vertex"):
        load_survey_truth_dict(d)


def test_an_empty_area_containing_a_target_is_refused():
    d = doc()
    d["verified_empty_areas"][0]["polygon"] = [[0.5, 1.5], [3.5, 1.5], [3.5, 2.5], [0.5, 2.5]]
    with pytest.raises(ManifestError, match="cannot be both empty and occupied|crosses the area"):
        load_survey_truth_dict(d)


def test_emptiness_needs_excavation_not_a_survey_or_a_record():
    for basis in ("independent_survey", "construction_record", "operator_radar_interpretation"):
        d = doc()
        d["verified_empty_areas"][0]["evidence"] = evidence(
            basis=basis, grade="measurement_associated",
            independent_of_gpr=basis != "operator_radar_interpretation")
        with pytest.raises(ManifestError):
            load_survey_truth_dict(d)


def test_a_self_intersecting_polygon_is_refused():
    d = doc()
    d["verified_empty_areas"][0]["polygon"] = [[6, 6], [8, 8], [8, 6], [6, 8]]
    with pytest.raises(ManifestError, match="simple"):
        load_survey_truth_dict(d)


def test_a_radar_quantity_cannot_enter_the_document():
    d = doc()
    d["objects"][0]["two_way_time_ns"] = 12.0
    with pytest.raises(ManifestError, match="radar quantity"):
        load_survey_truth_dict(d)


def test_the_embedded_manifest_keeps_its_own_rules():
    d = doc()
    d["targets_manifest"]["targets"][0]["evidence"] = evidence(
        basis="operator_radar_interpretation", independent_of_gpr=False)
    with pytest.raises(ManifestError, match="operator's radar interpretation"):
        load_survey_truth_dict(d)


def test_a_geographic_frame_is_refused_for_planar_truth():
    d = doc()
    d["targets_manifest"]["frames"].append({
        "frame_id": "wgs84", "kind": "geographic", "units": "m", "origin": "datum",
        "origin_status": "declared", "units_status": "declared",
        "registration_to_radar": "declared", "crs": "EPSG:4326"})
    d["control_points"][0]["frame_id"] = "wgs84"
    with pytest.raises(ManifestError, match="planar"):
        load_survey_truth_dict(d)


def test_custody_must_be_recorded():
    d = doc()
    d["custody"]["statement"] = ""
    with pytest.raises(ManifestError, match="custody"):
        load_survey_truth_dict(d)


# --- valid is not eligible ---------------------------------------------------

def test_sparse_axis_vertices_are_ineligible_not_refused():
    d = doc()
    d["objects"][0]["axis"]["vertices"] = [[1.0, 2.0], [7.0, 2.0]]
    rep = eligibility(load_survey_truth_dict(d))
    pipe = rep["objects"]["pipe-1"]
    assert not pipe["eligible"]
    assert any("vertex spacing 6.00 m" in r for r in pipe["reasons"])
    assert rep["eligible_objects"]["linear"] == 0


def test_unstated_uncertainty_is_ineligible():
    d = doc()
    d["targets_manifest"]["targets"][1]["locations"][0]["uncertainty"] = None
    rep = eligibility(load_survey_truth_dict(d))
    assert any("not stated" in r for r in rep["objects"]["stone-1"]["reasons"])


def test_grade_c_or_d_truth_is_listed_but_never_eligible():
    d = doc()
    d["targets_manifest"]["targets"][1]["evidence"] = evidence(
        basis="construction_record", grade="weak_unsuitable")
    rep = eligibility(load_survey_truth_dict(d))
    assert not rep["objects"]["stone-1"]["eligible"]
    assert "stone-1" in rep["ineligible"]


def test_a_shallow_excavation_does_not_certify_emptiness():
    d = doc()
    d["verified_empty_areas"][0]["excavation_depth"]["value"] = 0.8
    rep = eligibility(load_survey_truth_dict(d))
    assert rep["eligible_empty_area_m2"] == 0
    assert any("less than 1.5 m" in r for r in rep["verified_empty_areas"]["empty-1"]["reasons"])


def test_requirements_are_a_parameter_and_are_reported():
    strict = Requirements(max_vertex_spacing_m=0.25)
    rep = eligibility(load_survey_truth(EXAMPLE), strict)
    assert rep["requirements"]["max_vertex_spacing_m"] == 0.25
    assert not rep["objects"]["pipe-1"]["eligible"]


def test_too_few_good_control_points_is_reported():
    d = doc()
    d["control_points"][2]["uncertainty"] = 0.05
    rep = eligibility(load_survey_truth_dict(d))
    assert not rep["control"]["ok"]


def test_mm_frames_convert_to_metres():
    d = doc()
    frame = d["targets_manifest"]["frames"][0]
    frame["units"] = "mm"
    scale = 1000.0

    def scale_xy(p):
        return [c * scale for c in p]
    for t in d["targets_manifest"]["targets"]:
        for loc in t["locations"]:
            for k in ("coordinates", "start", "end"):
                if k in loc:
                    loc[k] = scale_xy(loc[k])
            loc["uncertainty"] *= scale
    d["objects"][0]["axis"]["vertices"] = [scale_xy(v) for v in d["objects"][0]["axis"]["vertices"]]
    d["objects"][0]["axis"]["vertex_uncertainty"] *= scale
    for c in d["control_points"]:
        c["coordinates"] = scale_xy(c["coordinates"])
        c["uncertainty"] *= scale
    a = d["verified_empty_areas"][0]
    a["polygon"] = [scale_xy(v) for v in a["polygon"]]
    rep = eligibility(load_survey_truth_dict(d))
    assert rep["ineligible"] == []
    assert rep["eligible_empty_area_m2"] == pytest.approx(4.0)


def test_geometry_helpers():
    sq = [(0, 0), (2, 0), (2, 2), (0, 2)]
    assert polygon_area(sq) == 4
    assert point_in_polygon((1, 1), sq) and point_in_polygon((2, 1), sq)
    assert not point_in_polygon((3, 1), sq)


def test_the_truth_side_imports_no_detector():
    import ast
    tree = ast.parse(Path("benchmark/survey_truth.py").read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.startswith(("interpretation", "preprocessing")) or
                   m in ("benchmark.detection", "benchmark.predictions",
                         "benchmark.blind_detection") for m in mods), mods
