"""
Attested-empty locations: places independently documented to hold NO object.

The DRC seeded field documents two kinds (Baur et al. 2023, JCWD 27.3):
  * control holes -- "dug at various depths and filled with the goal of
    decoupling a signature resulting from soil displacement or disturbance
    from one resulting from the items themselves";
  * an "Empty" class -- "nothing buried in this location".

They are not targets. A detector that ignores them has missed nothing, so
they can never be false negatives; a detector that fires on one has made a
documented false alarm, reported separately as a control response. And an
ordinary patch of ground with no known target is NOT attested empty: only a
listed location is.
"""
import copy

import pytest

from benchmark.predictions import AcquisitionLine, Prediction, PredictionArtifact, TimingProvenance
from benchmark.target_scoring import MatchRule, ScoringBlocked, score
from benchmark.targets import (
    AttestedEmptyLocation, EmptyKind, ManifestError, load_manifest_dict,
)

FRAME = {"frame_id": "grid", "kind": "local_cartesian", "units": "m",
         "origin": "centre of cell A1", "origin_status": "declared", "units_status": "declared",
         "registration_to_radar": "declared", "registration_note": "cart GNSS"}
EVIDENCE = {"basis": "seeded_placement", "grade": "measurement_associated",
            "independent_of_gpr": True, "source": "placement table"}


def base(targets=(), empties=(), exhaustive=True):
    return {"schema": "subterra.targets.v1", "dataset_id": "field", "title": "t",
            "truth_source": {"citation": "c"},
            "exhaustive": {"value": exhaustive, "statement": "every cell listed"},
            "frames": [FRAME],
            "depth_reference_surfaces": [{"surface_id": "ground", "description": "ground"}],
            "open_questions": [], "targets": list(targets),
            "attested_empty_locations": list(empties)}


def control_hole(lid="F2", x=10.0, y=1.5, depth=14):
    return {"location_id": lid, "kind": "control_hole",
            "locations": [{"frame_id": "grid", "geometry": "point", "coordinates": [x, y]}],
            "hole_depth": {"value": depth, "units": "cm", "measured_to": "bottom",
                           "reference_surface": "ground", "method": "tape_at_placement"},
            "evidence": dict(EVIDENCE), "notes": "dug and refilled; nothing placed"}


def empty_cell(lid="A14", x=0.0, y=19.5):
    return {"location_id": lid, "kind": "undisturbed_empty",
            "locations": [{"frame_id": "grid", "geometry": "point", "coordinates": [x, y]}],
            "evidence": dict(EVIDENCE)}


def target(tid="A1", x=0.0, y=0.0):
    return {"target_id": tid, "object_class": "mine",
            "locations": [{"frame_id": "grid", "geometry": "point", "coordinates": [x, y]}],
            "evidence": dict(EVIDENCE)}


def artifact(preds, lines=None):
    lines = lines or [AcquisitionLine("L0", (-1.0, 1.5), (12.0, 1.5)),
                      AcquisitionLine("L1", (-1.0, 0.0), (12.0, 0.0))]
    return PredictionArtifact(
        dataset_id="field", acquisition_id="a", frame_id="grid", frame_units="m",
        detector={}, preprocessing={}, input_sha256="x", timing=TimingProvenance(),
        lines=tuple(lines),
        predictions=tuple(Prediction(prediction_id=pid, line_id=ln, position=pos)
                          for pid, ln, pos in preds))


RULE = MatchRule(name="r", radius_kind="fixed", radius=0.3, control_radius=0.3)


# --- schema ------------------------------------------------------------------

def test_a_control_hole_and_an_empty_cell_load_as_their_own_kinds():
    m = load_manifest_dict(base([target()], [control_hole(), empty_cell()]))
    kinds = {e.location_id: e.kind for e in m.attested_empty_locations}
    assert kinds == {"F2": EmptyKind.CONTROL_HOLE, "A14": EmptyKind.UNDISTURBED_EMPTY}
    assert m.attested_empty_locations[0].hole_depth.value == 14


def test_an_attested_empty_location_is_not_a_target():
    m = load_manifest_dict(base([target()], [control_hole()]))
    assert [t.target_id for t in m.targets] == ["A1"]
    assert not isinstance(m.attested_empty_locations[0], type(m.targets[0]))


def test_evidence_and_a_source_are_required():
    e = control_hole()
    del e["evidence"]
    with pytest.raises(ManifestError, match="evidence"):
        load_manifest_dict(base(empties=[e]))
    e = control_hole()
    e["evidence"]["source"] = ""
    with pytest.raises(ManifestError, match="source"):
        load_manifest_dict(base(empties=[e]))


def test_operator_interpretation_cannot_attest_emptiness():
    e = control_hole()
    e["evidence"] = {"basis": "operator_radar_interpretation", "grade": "operator_reviewed",
                     "independent_of_gpr": False, "source": "looked at the radargram"}
    with pytest.raises(ManifestError, match="independent"):
        load_manifest_dict(base(empties=[e]))


def test_only_undisturbed_empty_may_omit_a_hole_depth_and_it_may_not_have_one():
    e = empty_cell()
    e["hole_depth"] = control_hole()["hole_depth"]
    with pytest.raises(ManifestError, match="hole_depth"):
        load_manifest_dict(base(empties=[e]))


def test_an_unknown_kind_or_field_is_refused():
    e = control_hole()
    e["kind"] = "nothing"
    with pytest.raises(ManifestError, match="kind"):
        load_manifest_dict(base(empties=[e]))
    e = control_hole()
    e["object_class"] = "empty"
    with pytest.raises(ManifestError, match="object_class"):
        load_manifest_dict(base(empties=[e]))


def test_ids_may_not_collide_with_targets():
    with pytest.raises(ManifestError, match="A1"):
        load_manifest_dict(base([target("A1")], [control_hole("A1")]))


def test_existing_manifests_without_the_field_still_load():
    d = base([target()])
    del d["attested_empty_locations"]
    assert load_manifest_dict(d).attested_empty_locations == ()


def test_the_dataclass_refuses_a_missing_location():
    with pytest.raises(ManifestError, match="location"):
        AttestedEmptyLocation(location_id="x", dataset_id="d", kind="control_hole",
                              locations=(), evidence=None)


# --- scoring -----------------------------------------------------------------

def test_an_ignored_control_hole_is_never_a_false_negative():
    m = load_manifest_dict(base([target("A1", 0.0, 0.0)], [control_hole("F2", 10.0, 1.5)]))
    r = score(artifact([("p1", "L1", (0.1, 0.0))]), m, RULE)
    assert r["counts"]["opportunities"] == 1
    assert r["counts"]["false_negatives"] == 0
    assert r["controls"]["locations_in_frame"] == 1
    assert r["controls"]["locations_with_a_response"] == 0


def test_a_prediction_at_a_control_hole_is_reported_as_a_control_response():
    m = load_manifest_dict(base([target("A1", 0.0, 0.0)], [control_hole("F2", 10.0, 1.5)]))
    r = score(artifact([("p1", "L1", (0.1, 0.0)), ("p2", "L0", (10.1, 1.5))]), m, RULE)
    c = r["controls"]
    assert c["locations_with_a_response"] == 1
    assert c["responses"][0]["location_id"] == "F2"
    assert c["responses"][0]["prediction_ids"] == ["p2"]
    assert c["by_kind"]["control_hole"] == {"locations": 1, "with_a_response": 1}
    # still exactly one false positive in the headline count -- not two
    assert r["counts"]["false_positives"] == 1
    assert r["counts"]["false_positives_at_attested_empty"] == 1


def test_a_prediction_matched_to_a_target_is_not_a_control_response():
    m = load_manifest_dict(base([target("A1", 10.0, 1.5)], [control_hole("F2", 10.2, 1.5)]))
    r = score(artifact([("p1", "L0", (10.05, 1.5))]), m, RULE)
    assert r["counts"]["true_positives"] == 1
    assert r["controls"]["locations_with_a_response"] == 0


def test_unlisted_background_is_not_treated_as_attested_empty():
    m = load_manifest_dict(base([target("A1", 0.0, 0.0)], []))
    r = score(artifact([("p1", "L0", (6.0, 1.5))]), m, RULE)
    assert r["controls"]["locations_in_frame"] == 0
    assert r["counts"]["false_positives_at_attested_empty"] == 0
    assert r["counts"]["false_positives"] == 1


def test_control_analysis_needs_a_declared_control_radius():
    m = load_manifest_dict(base([target()], [control_hole()]))
    rule = MatchRule(name="r", radius_kind="fixed", radius=0.3)
    r = score(artifact([("p1", "L1", (0.1, 0.0))]), m, rule)
    assert r["controls"]["available"] is False
    assert "control_radius" in r["controls"]["reason"]


def test_control_responses_are_reported_even_when_precision_is_gated():
    m = load_manifest_dict(base([target("A1", 0.0, 0.0)], [control_hole("F2", 10.0, 1.5)],
                                exhaustive=False))
    r = score(artifact([("p2", "L0", (10.1, 1.5))]), m, RULE)
    assert r["counts"]["false_positives"] is None
    assert r["controls"]["locations_with_a_response"] == 1
