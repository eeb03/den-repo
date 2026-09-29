"""
The generic buried-target schema (benchmark/targets.py) and its manifest.

Physical truth only. Every rule below exists to stop one specific way a
benchmark gets quietly corrupted: a depth with no reference surface, a
coordinate with no CRS, a radar-derived number filed as truth, an operator's
reading of a radargram graded as if somebody had dug the object up.
"""
import copy

import pytest

from benchmark.ground_truth import EvidenceBasis
from benchmark.targets import (
    AbsoluteElevation, Dimensions, Frame, ManifestError, MeasuredTo, PhysicalDepth,
    PointLocation, SegmentLocation, TargetEvidence, load_manifest_dict,
)
from schemas.segmentation import EvidenceGrade


def evidence(**kw):
    base = dict(basis=EvidenceBasis.SEEDED_PLACEMENT, grade=EvidenceGrade.A_INDEPENDENTLY_VERIFIED,
                independent_of_gpr=True, source="placement log", established_by="field team")
    base.update(kw)
    return TargetEvidence(**base)


def manifest(**overrides):
    m = {
        "schema": "subterra.targets.v1",
        "dataset_id": "demo-site",
        "title": "demo",
        "truth_source": {"citation": "field log 2026", "provenance_class": "field_record"},
        "exhaustive": {"value": True, "statement": "every object placed is listed"},
        "frames": [
            {"frame_id": "line-A", "kind": "survey_line", "units": "m", "line_id": "A",
             "origin": "start peg A0", "origin_status": "declared", "units_status": "declared",
             "registration_to_radar": "declared",
             "registration_note": "wheel zeroed on peg A0"},
            {"frame_id": "utm", "kind": "projected", "units": "m", "crs": "EPSG:32633",
             "origin": "EPSG:32633", "origin_status": "declared", "units_status": "declared",
             "registration_to_radar": "declared", "registration_note": "RTK on antenna"},
        ],
        "depth_reference_surfaces": [
            {"surface_id": "ground", "description": "undisturbed ground surface at the target"},
        ],
        "open_questions": [],
        "targets": [
            {"target_id": "T1", "object_class": "pipe", "material": "PVC",
             "dimensions": {"shape": "cylinder", "outer_diameter": 0.11, "units": "m"},
             "locations": [{"frame_id": "line-A", "geometry": "point", "coordinates": [12.5],
                            "uncertainty": 0.05}],
             "depths": [{"value": 0.8, "units": "m", "measured_to": "top",
                         "reference_surface": "ground", "method": "tape_at_placement",
                         "uncertainty": 0.02, "source": "placement log"}],
             "evidence": {"basis": "seeded_placement", "grade": "independently_verified",
                          "independent_of_gpr": True, "source": "placement log",
                          "established_by": "field team"}},
        ],
    }
    m.update(overrides)
    return m


def target(**overrides):
    t = copy.deepcopy(manifest()["targets"][0])
    t.update(overrides)
    return t


# ---------------------------------------------------------------------------
# valid records
# ---------------------------------------------------------------------------

def test_a_valid_chainage_target_loads():
    m = load_manifest_dict(manifest())
    t = m.targets[0]
    assert t.locations[0].frame_id == "line-A"
    assert t.locations[0].coordinates == (12.5,)
    assert t.depths[0].measured_to is MeasuredTo.TOP
    assert t.depths[0].reference_surface == "ground"


def test_a_valid_projected_xy_target_loads():
    m = load_manifest_dict(manifest(targets=[target(locations=[
        {"frame_id": "utm", "geometry": "point", "coordinates": [281945.3, 4686506.2],
         "uncertainty": 0.02}])]))
    assert m.frame("utm").crs == "EPSG:32633"


def test_unknown_dimensions_and_material_stay_unknown():
    m = load_manifest_dict(manifest(targets=[target(material=None, dimensions=None)]))
    assert m.targets[0].material is None
    assert m.targets[0].dimensions is None


def test_an_independently_surveyed_elevation_is_optional_and_carries_its_datum():
    m = load_manifest_dict(manifest(targets=[target(absolute_elevation={
        "value": 201.3, "units": "m", "vertical_datum": "EPSG:3855",
        "measured_to": "top", "method": "survey_instrument", "uncertainty": 0.03,
        "source": "total station"})]))
    assert m.targets[0].absolute_elevation.vertical_datum == "EPSG:3855"


# ---------------------------------------------------------------------------
# refused records
# ---------------------------------------------------------------------------

def test_a_depth_without_a_reference_surface_is_refused():
    t = target()
    del t["depths"][0]["reference_surface"]
    with pytest.raises(ManifestError, match="reference_surface"):
        load_manifest_dict(manifest(targets=[t]))


def test_a_depth_referring_to_an_undeclared_surface_is_refused():
    t = target()
    t["depths"][0]["reference_surface"] = "trench datum"
    with pytest.raises(ManifestError, match="trench datum"):
        load_manifest_dict(manifest(targets=[t]))


def test_projected_coordinates_without_a_crs_are_refused():
    frames = manifest()["frames"]
    del frames[1]["crs"]
    with pytest.raises(ManifestError, match="crs"):
        load_manifest_dict(manifest(frames=frames))


def test_a_local_frame_may_not_claim_a_crs():
    with pytest.raises(ManifestError, match="crs"):
        Frame(frame_id="f", kind="local_cartesian", units="mm", crs="EPSG:4326",
              origin="corner", origin_status="declared", units_status="declared",
              registration_to_radar="declared")


def test_a_chainage_frame_needs_a_line_and_an_origin():
    with pytest.raises(ManifestError, match="line_id"):
        Frame(frame_id="f", kind="survey_line", units="m", origin="peg",
              origin_status="declared", units_status="declared", registration_to_radar="declared")
    with pytest.raises(ManifestError, match="origin"):
        Frame(frame_id="f", kind="survey_line", units="m", line_id="A", origin="",
              origin_status="declared", units_status="declared", registration_to_radar="declared")


def test_negative_uncertainty_is_refused():
    with pytest.raises(ManifestError, match="uncertainty"):
        PointLocation(frame_id="line-A", coordinates=(1.0,), uncertainty=-0.1)


@pytest.mark.parametrize("field", ["outer_diameter", "length", "width", "height"])
def test_impossible_dimensions_are_refused(field):
    with pytest.raises(ManifestError, match=field):
        Dimensions(units="m", **{field: 0.0 if field == "height" else -1.0})


def test_a_target_needs_a_location():
    with pytest.raises(ManifestError, match="location"):
        load_manifest_dict(manifest(targets=[target(locations=[])]))


def test_two_disagreeing_locations_in_one_frame_are_refused():
    t = target(locations=[
        {"frame_id": "line-A", "geometry": "point", "coordinates": [12.5], "uncertainty": 0.05},
        {"frame_id": "line-A", "geometry": "point", "coordinates": [14.0], "uncertainty": 0.05}])
    with pytest.raises(ManifestError, match="disagree"):
        load_manifest_dict(manifest(targets=[t]))


def test_a_location_in_an_undeclared_frame_is_refused():
    t = target(locations=[{"frame_id": "nowhere", "geometry": "point", "coordinates": [1.0]}])
    with pytest.raises(ManifestError, match="nowhere"):
        load_manifest_dict(manifest(targets=[t]))


def test_coordinates_must_match_the_frame_dimension():
    t = target(locations=[{"frame_id": "line-A", "geometry": "point", "coordinates": [1.0, 2.0]}])
    with pytest.raises(ManifestError, match="coordinate"):
        load_manifest_dict(manifest(targets=[t]))


def test_an_elevation_without_a_datum_is_refused():
    with pytest.raises(ManifestError, match="vertical_datum"):
        AbsoluteElevation(value=201.3, units="m", vertical_datum="", measured_to="top",
                          method="survey_instrument")


def test_duplicate_target_ids_are_refused():
    with pytest.raises(ManifestError, match="T1"):
        load_manifest_dict(manifest(targets=[target(), target()]))


# ---------------------------------------------------------------------------
# radar-derived depth can never become truth
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["gpr", "radar_velocity", "two_way_time", "hyperbola_fit"])
def test_a_radar_method_is_not_a_physical_depth_method(method):
    with pytest.raises(ManifestError, match="method"):
        PhysicalDepth(value=0.5, units="m", measured_to="top", reference_surface="ground",
                      method=method)


@pytest.mark.parametrize("key", ["two_way_time_ns", "velocity_m_per_ns", "radar_depth",
                                 "predicted_depth"])
def test_radar_quantities_in_a_target_are_refused_by_name(key):
    with pytest.raises(ManifestError, match=key):
        load_manifest_dict(manifest(targets=[target(**{key: 1.0})]))


def test_an_unknown_target_field_is_refused_rather_than_ignored():
    with pytest.raises(ManifestError, match="colour"):
        load_manifest_dict(manifest(targets=[target(colour="red")]))


# ---------------------------------------------------------------------------
# evidence: operator interpretation is never independent truth
# ---------------------------------------------------------------------------

def test_operator_interpretation_cannot_be_independent_of_gpr():
    with pytest.raises(ManifestError, match="independent"):
        evidence(basis=EvidenceBasis.OPERATOR_RADAR_INTERPRETATION,
                 grade=EvidenceGrade.C_OPERATOR_REVIEWED, independent_of_gpr=True)


@pytest.mark.parametrize("grade", [EvidenceGrade.A_INDEPENDENTLY_VERIFIED,
                                   EvidenceGrade.B_MEASUREMENT_ASSOCIATED])
def test_operator_interpretation_cannot_carry_grade_a_or_b(grade):
    with pytest.raises(ManifestError, match="grade"):
        evidence(basis=EvidenceBasis.OPERATOR_RADAR_INTERPRETATION, grade=grade,
                 independent_of_gpr=False)


def test_grade_a_requires_independence_from_the_radar():
    with pytest.raises(ManifestError, match="independent"):
        evidence(independent_of_gpr=False)


def test_not_recorded_is_not_evidence_for_a_target():
    with pytest.raises(ManifestError, match="not_recorded"):
        evidence(basis=EvidenceBasis.NOT_RECORDED)


def test_evidence_needs_a_source():
    with pytest.raises(ManifestError, match="source"):
        evidence(source="")


def test_an_unresolved_depth_point_must_name_its_open_question():
    t = target()
    t["depths"][0]["measured_to"] = "unresolved"
    with pytest.raises(ManifestError, match="open_question"):
        load_manifest_dict(manifest(targets=[t]))
    t["depths"][0]["open_question"] = "which-point"
    m = load_manifest_dict(manifest(
        targets=[t], open_questions=[{"id": "which-point", "statement": "s",
                                      "blocks": ["depth_scoring"], "resolution_route": "r"}]))
    assert m.targets[0].depths[0].measured_to is MeasuredTo.UNRESOLVED


def test_a_segment_location_describes_a_linear_object():
    seg = SegmentLocation(frame_id="f", start=(250.0, 0.0), end=(250.0, 800.0))
    assert seg.distance_to((260.0, 400.0)) == pytest.approx(10.0)
    assert seg.distance_to((250.0, 900.0)) == pytest.approx(100.0)
