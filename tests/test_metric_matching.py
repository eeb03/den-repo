"""
Object-level metric matching (benchmark.metric_matching). Every manifest here
is SYNTHETIC test geometry, not truth for anything.
"""
import pytest

from benchmark.metric_matching import (
    Candidate, MatchingBlocked, Tolerance, candidates_from_artifact, horizontal_tolerance_m,
    match_objects, project_onto_polyline,
)
from benchmark.predictions import AcquisitionLine, Prediction, PredictionArtifact, TimingProvenance
from benchmark.targets import load_manifest_dict

EV = {"basis": "seeded_placement", "grade": "independently_verified",
      "independent_of_gpr": True, "source": "synthetic fixture"}
B1 = Tolerance(name="pas128-b1-like", horizontal_m=0.15, depth_fraction=0.15,
               source="secondary-source reading of PAS 128 QL-B1; test only")


def manifest(units="m", registration="declared", scale=1.0):
    def s(p):
        return [c * scale for c in p]
    return load_manifest_dict({
        "schema": "subterra.targets.v1", "dataset_id": "synthetic", "title": "synthetic",
        "truth_source": {"provenance_class": "synthetic_test_fixture"},
        "exhaustive": {"value": True, "statement": "synthetic"},
        "frames": [{"frame_id": "site", "kind": "local_cartesian", "units": units,
                    "origin": "CP1", "origin_status": "declared", "units_status": "declared",
                    "registration_to_radar": registration}],
        "depth_reference_surfaces": [{"surface_id": "ground", "description": "synthetic"}],
        "open_questions": [],
        "targets": [
            {"target_id": "pipe", "object_class": "pipe",
             "locations": [{"frame_id": "site", "geometry": "segment", "start": s([0, 0]),
                            "end": s([10, 0]), "uncertainty": 0.01 * scale}],
             "depths": [{"value": 0.8 * scale, "units": units, "measured_to": "top",
                         "reference_surface": "ground", "method": "tape_at_placement"}],
             "evidence": EV},
            {"target_id": "stone-a", "object_class": "stone",
             "dimensions": {"units": units, "length": 0.3 * scale},
             "locations": [{"frame_id": "site", "geometry": "point", "coordinates": s([5, 5]),
                            "uncertainty": 0.01 * scale}],
             "depths": [{"value": 0.5 * scale, "units": units, "measured_to": "top",
                         "reference_surface": "ground", "method": "tape_at_placement"}],
             "evidence": EV},
            {"target_id": "stone-b", "object_class": "stone",
             "locations": [{"frame_id": "site", "geometry": "point", "coordinates": s([5, 5.25]),
                            "uncertainty": 0.01 * scale}],
             "evidence": EV},
        ]})


GROUPS = {"pipe": "linear", "stone-a": "compact", "stone-b": "compact"}
EMPTY = [("e1", [(8, 4), (10, 4), (10, 6), (8, 6)])]


def run(cands, **kw):
    args = dict(coverage_radius_m=0.5, min_length_fraction=0.5, empty_areas=EMPTY)
    args.update(kw)
    return match_objects(manifest(), "site", cands, GROUPS, B1, **args)


def C(i, x, y, d=None):
    return Candidate(candidate_id=i, x=x, y=y, depth_m=d)


def test_linear_detected_length_fraction():
    r = run([C(f"p{i}", i + 0.5, 0.05) for i in range(6)])     # cover 0..6 of 10 m
    pipe = r["per_target"]["pipe"]
    assert pipe["detected_length_fraction"] == pytest.approx(0.6)
    assert pipe["detected"] and pipe["n_candidates"] == 6
    r = run([C("p0", 0.5, 0.05), C("p1", 1.5, 0.05)])
    assert r["per_target"]["pipe"]["detected_length_fraction"] == pytest.approx(0.2)
    assert not r["per_target"]["pipe"]["detected"]


def test_a_candidate_beyond_tolerance_does_not_match():
    r = run([C("far", 5.0, 0.2)])          # 0.20 m > 0.15 m
    assert r["per_target"]["pipe"]["n_candidates"] == 0
    assert r["unverified_candidates"] == ["far"]


def test_a_candidate_counts_once_for_the_nearest_target():
    # stone-a tolerance 0.15 + 0.15 (half size off: add_half_size False) -> 0.15; stone-b 0.15
    r = run([C("mid", 5.0, 5.12)])          # 0.12 from a, 0.13 from b
    assert r["per_target"]["stone-a"]["matched_candidate"] == "mid"
    assert r["per_target"]["stone-b"]["detected"] is False
    assert r["counts"]["compact"] == {"n": 2, "detected": 1}


def test_compact_duplicates_are_not_extra_detections():
    r = run([C("s1", 5.0, 4.95), C("s2", 5.02, 5.0)])
    a = r["per_target"]["stone-a"]
    assert a["matched_candidate"] == "s2" and a["duplicates"] == ["s1"]
    assert r["false_alarms"]["n"] == 0


def test_false_alarms_only_inside_verified_empty_areas():
    r = run([C("in", 9.0, 5.0), C("out", 3.0, 8.0)])
    assert r["false_alarms"]["candidates"] == ["in"]
    assert r["false_alarms"]["verified_empty_area_m2"] == pytest.approx(4.0)
    assert r["unverified_candidates"] == ["out"]


def test_order_of_inputs_cannot_change_the_result():
    cands = [C("x1", 5.0, 5.1), C("x2", 5.0, 5.2), C("x3", 2.0, 0.1), C("x4", 9.0, 5.0)]
    assert run(cands) == run(list(reversed(cands)))


def test_depth_is_reported_and_never_gates_detection():
    r = run([C("s", 5.0, 5.0, d=0.9)])     # true top 0.5, tolerance 0.075
    a = r["per_target"]["stone-a"]
    assert a["detected"]
    assert a["depth"]["error_m"] == pytest.approx(0.4) and a["depth"]["within"] is False


def test_depth_dependent_and_half_size_tolerances():
    m = manifest()
    pipe = next(t for t in m.targets if t.target_id == "pipe")
    stone = next(t for t in m.targets if t.target_id == "stone-a")
    grow = Tolerance(name="grow", horizontal_m=0.10, horizontal_depth_fraction=0.25,
                     add_half_size=True)
    assert horizontal_tolerance_m(pipe, "linear", grow) == pytest.approx(0.20)
    assert horizontal_tolerance_m(stone, "compact", grow) == pytest.approx(0.125 + 0.15)
    nodepth = next(t for t in m.targets if t.target_id == "stone-b")
    with pytest.raises(MatchingBlocked, match="no depth"):
        horizontal_tolerance_m(nodepth, "compact", grow)


def test_frame_units_are_converted_to_metres():
    r1 = run([C("p", 5.0, 0.1)])
    r2 = match_objects(manifest(units="mm", scale=1000.0), "site", [C("p", 5000.0, 100.0)],
                       GROUPS, B1, coverage_radius_m=0.5, min_length_fraction=0.5)
    assert r1["per_target"]["pipe"]["n_candidates"] == r2["per_target"]["pipe"]["n_candidates"] == 1


def test_unregistered_frame_is_refused():
    with pytest.raises(MatchingBlocked, match="not supported"):
        match_objects(manifest(registration="unresolved"), "site", [], GROUPS, B1,
                      coverage_radius_m=0.5, min_length_fraction=0.5)


def test_class_groups_must_be_declared():
    with pytest.raises(MatchingBlocked, match="class group"):
        match_objects(manifest(), "site", [], {"pipe": "linear"}, B1,
                      coverage_radius_m=0.5, min_length_fraction=0.5)


def test_excluded_targets_absorb_candidates_but_are_not_scored():
    r = run([C("s", 5.0, 5.0)], include_ids={"pipe", "stone-b"})
    assert r["excluded_targets"] == ["stone-a"]
    assert r["counts"]["compact"] == {"n": 1, "detected": 0}
    assert r["false_alarms"]["n"] == 0 and r["unverified_candidates"] == []


def test_a_surveyed_polyline_replaces_the_segment():
    bend = {"pipe": [(0, 0), (5, 0), (5, 5)]}
    r = run([C("b", 5.05, 3.0)], axes=bend)
    assert r["per_target"]["pipe"]["n_candidates"] == 1
    assert r["per_target"]["pipe"]["axis_length_m"] == pytest.approx(10.0)


def test_projection_chainage():
    d, s = project_onto_polyline((5, 1), [(0, 0), (10, 0)])
    assert d == pytest.approx(1) and s == pytest.approx(5)


def artifact(**timing):
    return PredictionArtifact(
        dataset_id="synthetic", acquisition_id="a", frame_id="site", frame_units="m",
        detector={"name": "synthetic"}, preprocessing={}, input_sha256="0" * 64,
        timing=TimingProvenance(**timing),
        lines=(AcquisitionLine(line_id="L1", start=(0.0, 0.0), end=(10.0, 0.0)),),
        predictions=(Prediction(prediction_id="q1", line_id="L1", position=(5.0, 0.05),
                                radar_depth=0.7),))


def test_artifact_adapter_carries_depth_only_with_declared_basis():
    m = manifest()
    (c,) = candidates_from_artifact(artifact(), m)
    assert c.depth_m is None
    (c,) = candidates_from_artifact(artifact(velocity_source="measured", velocity_m_per_ns=0.1,
                                             depth_reference_surface="ground", depth_units="m"), m)
    assert c.depth_m == pytest.approx(0.7)
    bad = artifact()
    object.__setattr__(bad, "frame_units", "mm")
    with pytest.raises(MatchingBlocked, match="units"):
        candidates_from_artifact(bad, m)
