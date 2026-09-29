"""
Generic target scoring (benchmark/target_scoring.py): matching, gates, metrics.

Synthetic manifests and artifacts only -- the BAM migration and the real blind
run have their own files. Each test pins one rule: one-to-one matching, the
order-independence of the result, and every place scoring must refuse rather
than produce a number the declared evidence cannot support.
"""
import copy
import random

import pytest

from benchmark.predictions import (
    AcquisitionLine, Prediction, PredictionArtifact, TimingProvenance,
)
from benchmark.target_scoring import MatchRule, ScoringBlocked, by_frequency, score
from benchmark.targets import load_manifest_dict

RULE = MatchRule(name="fixed-0.5m", radius_kind="fixed", radius=0.5)


def line_frame(**kw):
    f = {"frame_id": "line-A", "kind": "survey_line", "units": "m", "line_id": "A",
         "origin": "peg A0", "origin_status": "declared", "units_status": "declared",
         "registration_to_radar": "declared", "registration_note": "wheel zeroed at A0"}
    f.update(kw)
    return f


def utm_frame(**kw):
    f = {"frame_id": "utm", "kind": "projected", "units": "m", "crs": "EPSG:32633",
         "origin": "EPSG:32633", "origin_status": "declared", "units_status": "declared",
         "registration_to_radar": "declared", "registration_note": "RTK antenna"}
    f.update(kw)
    return f


def tgt(tid, coords, frame="line-A", material="PVC", depth=0.8, grade="independently_verified",
        basis="seeded_placement", independent=True, geometry="point"):
    t = {"target_id": tid, "object_class": "pipe", "material": material,
         "locations": [{"frame_id": frame, "geometry": geometry, "coordinates": list(coords)}],
         "depths": ([{"value": depth, "units": "m", "measured_to": "top",
                      "reference_surface": "ground", "method": "tape_at_placement"}]
                    if depth is not None else []),
         "evidence": {"basis": basis, "grade": grade, "independent_of_gpr": independent,
                      "source": "placement log"}}
    return t


def manifest(targets, frames=None, exhaustive=True, questions=()):
    return load_manifest_dict({
        "schema": "subterra.targets.v1", "dataset_id": "site", "title": "t",
        "truth_source": {"citation": "log"},
        "exhaustive": {"value": exhaustive, "statement": "stated"},
        "frames": frames or [line_frame(), utm_frame()],
        "depth_reference_surfaces": [{"surface_id": "ground", "description": "ground"}],
        "open_questions": list(questions), "targets": targets})


def artifact(preds, frame_id="line-A", lines=None, crs=None, units="m", timing=None,
             freq=None, dataset="site"):
    lines = lines or [AcquisitionLine("A", (0.0,), (90.0,))]
    return PredictionArtifact(
        dataset_id=dataset, acquisition_id="acq", frame_id=frame_id, frame_units=units,
        frame_crs=crs, detector={"name": "d"}, preprocessing={}, input_sha256="x",
        timing=timing or TimingProvenance(), lines=tuple(lines),
        predictions=tuple(Prediction(prediction_id=pid, line_id=line, position=tuple(pos),
                                     radar_depth=rd)
                          for pid, line, pos, rd in [(*p, None)[:4] for p in preds]),
        antenna_frequency_mhz=freq)


# ---------------------------------------------------------------------------
# chainage matching
# ---------------------------------------------------------------------------

def test_a_prediction_within_tolerance_matches():
    r = score(artifact([("p1", "A", (12.3,))]), manifest([tgt("T1", (12.5,))]), RULE)
    assert r["counts"]["true_positives"] == 1
    assert r["counts"]["false_positives"] == 0
    assert r["metrics"]["recall"] == 1.0


def test_a_prediction_outside_tolerance_is_a_miss_and_a_false_positive():
    r = score(artifact([("p1", "A", (13.1,))]), manifest([tgt("T1", (12.5,))]), RULE)
    assert r["counts"]["true_positives"] == 0
    assert r["counts"]["false_negatives"] == 1
    assert r["counts"]["false_positives"] == 1


def test_two_predictions_near_one_target_count_once():
    r = score(artifact([("p1", "A", (12.6,)), ("p2", "A", (12.3,))]),
              manifest([tgt("T1", (12.5,))]), RULE)
    assert r["counts"]["true_positives"] == 1
    assert r["counts"]["duplicate_detections"] == 1
    assert r["counts"]["false_positives"] == 1
    assert r["matches"][0]["prediction_id"] == "p1"      # the nearer one


def test_one_prediction_between_two_targets_counts_once_for_the_nearer():
    r = score(artifact([("p1", "A", (12.9,))]),
              manifest([tgt("T1", (12.5,)), tgt("T2", (13.2,))]), RULE)
    assert r["counts"]["true_positives"] == 1
    assert r["matches"][0]["target_id"] == "T2"
    assert r["counts"]["false_negatives"] == 1


def test_an_exact_tie_is_broken_by_target_id_not_by_order():
    targets = [tgt("T2", (13.0,)), tgt("T1", (12.0,))]
    r = score(artifact([("p1", "A", (12.5,))]), manifest(targets), RULE)
    assert r["matches"][0]["target_id"] == "T1"


def test_the_result_does_not_depend_on_manifest_or_prediction_order():
    targets = [tgt(f"T{i}", (10.0 + 3 * i,)) for i in range(6)]
    preds = [(f"p{i}", "A", (10.0 + 1.5 * i,)) for i in range(12)]
    first = score(artifact(preds), manifest(targets), RULE)
    for seed in range(5):
        rng = random.Random(seed)
        t2, p2 = copy.deepcopy(targets), list(preds)
        rng.shuffle(t2)
        rng.shuffle(p2)
        again = score(artifact(p2), manifest(t2), RULE)
        assert again["matches"] == first["matches"]
        assert again["counts"] == first["counts"]


def test_chainage_from_another_line_is_never_compared():
    art = artifact([("p1", "B", (12.5,))], lines=[AcquisitionLine("B", (0.0,), (90.0,))])
    with pytest.raises(ScoringBlocked, match="chainage origins"):
        score(art, manifest([tgt("T1", (12.5,))]), RULE)


def test_an_unregistered_line_refuses_matching():
    m = manifest([tgt("T1", (12.5,))], frames=[line_frame(
        registration_to_radar="unresolved", registration_note="0 m trace not tied to peg")])
    with pytest.raises(ScoringBlocked, match="not registered"):
        score(artifact([("p1", "A", (12.5,))]), m, RULE)


def test_an_open_question_blocking_matching_refuses_it():
    q = {"id": "line-registration", "statement": "0 m unproven",
         "blocks": ["detection_matching"], "resolution_route": "authors"}
    with pytest.raises(ScoringBlocked, match="line-registration"):
        score(artifact([("p1", "A", (12.5,))]), manifest([tgt("T1", (12.5,))],
                                                      questions=[q]), RULE)


# ---------------------------------------------------------------------------
# XY matching and frames
# ---------------------------------------------------------------------------

def utm_art(preds, crs="EPSG:32633", **kw):
    return artifact(preds, frame_id="utm", crs=crs,
                    lines=[AcquisitionLine("A", (281900.0, 4686500.0), (282000.0, 4686500.0))],
                    **kw)


def test_projected_xy_matching_uses_physical_distance():
    r = score(utm_art([("p1", "A", (281950.24, 4686500.32))]),
              manifest([tgt("T1", (281950.0, 4686500.0), frame="utm")]), RULE)
    assert r["counts"]["true_positives"] == 1
    assert r["matches"][0]["distance"] == pytest.approx(0.4)


def test_a_crs_mismatch_refuses_matching():
    with pytest.raises(ScoringBlocked, match="CRS mismatch"):
        score(utm_art([("p1", "A", (281950.0, 4686500.0))], crs="EPSG:32632"),
              manifest([tgt("T1", (281950.0, 4686500.0), frame="utm")]), RULE)


def test_predictions_in_an_undeclared_frame_are_refused():
    with pytest.raises(ScoringBlocked, match="does not declare"):
        score(artifact([("p1", "A", (1.0,))], frame_id="line-Z"),
              manifest([tgt("T1", (12.5,))]), RULE)


def test_a_units_mismatch_is_refused():
    with pytest.raises(ScoringBlocked, match="units mismatch"):
        score(artifact([("p1", "A", (12500.0,))], units="mm"),
              manifest([tgt("T1", (12.5,))]), RULE)


def test_a_geographic_frame_is_representable_but_not_matchable():
    geo = {"frame_id": "wgs", "kind": "geographic", "units": "m", "crs": "EPSG:4326",
           "origin": "EPSG:4326", "origin_status": "declared", "units_status": "declared",
           "registration_to_radar": "declared"}
    m = manifest([tgt("T1", (12.35, 42.30), frame="wgs")], frames=[geo])
    art = artifact([("p1", "A", (12.35, 42.30))], frame_id="wgs", crs="EPSG:4326",
                   lines=[AcquisitionLine("A", (12.3, 42.3), (12.4, 42.3))])
    with pytest.raises(ScoringBlocked, match="geodesic"):
        score(art, m, RULE)


def test_a_dataset_mismatch_is_refused():
    with pytest.raises(ScoringBlocked, match="dataset"):
        score(artifact([("p1", "A", (12.5,))], dataset="other"),
              manifest([tgt("T1", (12.5,))]), RULE)


def test_a_prediction_artifact_cannot_stand_in_for_truth():
    art = artifact([("p1", "A", (12.5,))])
    with pytest.raises(ScoringBlocked, match="TargetManifest"):
        score(art, art, RULE)


def test_a_half_dimension_rule_refuses_a_target_of_unknown_size():
    rule = MatchRule(name="half-od", radius_kind="half_dimension", dimension="outer_diameter")
    with pytest.raises(ScoringBlocked, match="outer_diameter"):
        score(artifact([("p1", "A", (12.5,))]), manifest([tgt("T1", (12.5,))]), rule)


# ---------------------------------------------------------------------------
# gated metrics
# ---------------------------------------------------------------------------

def test_precision_is_refused_when_the_truth_is_not_exhaustive():
    r = score(artifact([("p1", "A", (12.5,)), ("p2", "A", (40.0,))]),
              manifest([tgt("T1", (12.5,))], exhaustive=False), RULE)
    assert r["metrics"]["recall"] == 1.0
    assert r["metrics"]["precision"] is None
    assert r["counts"]["false_positives"] is None
    assert "not attested exhaustive" in r["gates"]["false_positives"]["reasons"][0]


def test_precision_recall_f1_and_rates_when_supported():
    preds = [("p1", "A", (12.5,)), ("p2", "A", (40.0,)), ("p3", "A", (70.0,))]
    r = score(artifact(preds), manifest([tgt("T1", (12.5,)), tgt("T2", (30.0,))]), RULE)
    m = r["metrics"]
    assert (m["precision"], m["recall"]) == (pytest.approx(1 / 3), 0.5)
    assert m["f1"] == pytest.approx(2 * (1 / 3) * 0.5 / (1 / 3 + 0.5))
    assert m["false_positives_per_line"] == 2.0
    assert m["false_alarms_per_metre"] == pytest.approx(2 / 90.0)
    assert m["localization_error"]["mean_abs"] == pytest.approx(0.0)


def test_per_metre_and_localisation_are_refused_on_prose_units_and_unverified_origin():
    m = manifest([tgt("T1", (12.5,))], frames=[line_frame(
        units_status="documentation_prose", origin_status="unverified")])
    r = score(artifact([("p1", "A", (12.4,))]), m, RULE)
    assert r["metrics"]["false_alarms_per_metre"] is None
    assert r["metrics"]["localization_error"] is None
    reasons = " ".join(r["gates"]["localization_error"]["reasons"])
    assert "origin is unverified" in reasons and "documentation_prose" in reasons


def test_depth_scoring_is_refused_without_time_zero_velocity_and_reference():
    art = artifact([("p1", "A", (12.5,), 0.9)])
    r = score(art, manifest([tgt("T1", (12.5,))]), RULE)
    assert r["metrics"]["depth_error"] is None
    reasons = " ".join(r["gates"]["depth_scoring"]["reasons"])
    assert "time-zero" in reasons and "velocity" in reasons and "reference surface" in reasons


def test_a_converter_default_velocity_does_not_unlock_depth():
    timing = TimingProvenance(time_zero_status="declared", velocity_m_per_ns=0.1,
                              velocity_source="converter_default",
                              depth_reference_surface="ground", depth_units="m")
    r = score(artifact([("p1", "A", (12.5,), 0.9)], timing=timing),
              manifest([tgt("T1", (12.5,))]), RULE)
    assert r["metrics"]["depth_error"] is None
    assert "converter_default" in " ".join(r["gates"]["depth_scoring"]["reasons"])


def _declared_timing(**kw):
    base = dict(time_zero_status="declared", velocity_m_per_ns=0.12, velocity_source="declared",
                depth_reference_surface="ground", depth_units="m")
    base.update(kw)
    return TimingProvenance(**base)


def _depth_gate(timing):
    r = score(artifact([("p1", "A", (12.5,), 0.9)], timing=timing),
              manifest([tgt("T1", (12.5,))]), RULE)
    return r["gates"]["depth_scoring"], r["metrics"]["depth_error"]


def test_a_derived_time_zero_does_not_unlock_depth():
    """A same-survey direct-wave pick is an estimate, not a declaration."""
    gate, err = _depth_gate(_declared_timing(time_zero_status="derived"))
    assert gate["available"] is False and err is None
    assert "time-zero" in " ".join(gate["reasons"])


@pytest.mark.parametrize("basis", ["assumed_default", "estimated_from_same_survey"])
def test_a_velocity_that_is_an_assumption_or_a_same_survey_estimate_does_not_unlock_depth(basis):
    """Even labelled "declared": the basis says what the number rests on. A velocity
    fitted to the same radar data is not independent of the depths it would be judged on."""
    gate, err = _depth_gate(_declared_timing(velocity_basis=basis))
    assert gate["available"] is False and err is None
    assert basis in " ".join(gate["reasons"])


@pytest.mark.parametrize("basis", ["user_declared", "literature", "independent_measurement"])
def test_a_stated_velocity_basis_with_declared_time_zero_and_reference_unlocks_depth(basis):
    gate, err = _depth_gate(_declared_timing(velocity_basis=basis))
    assert gate["available"] is True and err is not None


def test_a_missing_reference_keeps_depth_locked_even_with_everything_else():
    gate, _ = _depth_gate(_declared_timing(depth_reference_surface=None,
                                           velocity_basis="independent_measurement"))
    assert gate["available"] is False


def test_an_artifact_without_a_velocity_basis_still_loads():
    """velocity_basis is optional: artifacts written before it existed are unchanged."""
    assert TimingProvenance().velocity_basis is None


def test_depth_error_when_every_declaration_is_present():
    timing = TimingProvenance(time_zero_status="measured", velocity_m_per_ns=0.1,
                              velocity_source="declared", depth_reference_surface="ground",
                              depth_units="m")
    r = score(artifact([("p1", "A", (12.5,), 0.9)], timing=timing),
              manifest([tgt("T1", (12.5,), depth=0.8)]), RULE)
    assert r["gates"]["depth_scoring"]["available"] is True
    assert r["metrics"]["depth_error"]["mean_signed_error"] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# breakdowns and evidence
# ---------------------------------------------------------------------------

def test_breakdowns_group_by_known_metadata():
    targets = [tgt("T1", (12.5,), material="PVC", depth=0.5),
               tgt("T2", (30.0,), material="steel", depth=1.0)]
    r = score(artifact([("p1", "A", (12.5,))]), manifest(targets), RULE)
    b = r["breakdowns"]
    assert b["material"]["groups"]["PVC"]["recall"] == 1.0
    assert b["material"]["groups"]["steel"]["recall"] == 0.0
    assert list(b["physical_depth"]["groups"]) == ["0.5", "1.0"]


def test_no_subgroup_statistic_when_metadata_is_missing():
    targets = [tgt("T1", (12.5,), material=None, depth=None), tgt("T2", (30.0,))]
    r = score(artifact([("p1", "A", (12.5,))]), manifest(targets), RULE)
    assert r["breakdowns"]["material"]["available"] is False
    assert "T1" in r["breakdowns"]["material"]["reason"]
    assert r["breakdowns"]["physical_depth"]["available"] is False


def test_frequency_breakdown_only_groups_known_frequencies():
    m = manifest([tgt("T1", (12.5,))])
    a = score(artifact([("p1", "A", (12.5,))], freq=250.0), m, RULE)
    b = score(artifact([], freq=None), m, RULE)
    out = by_frequency([a, b])
    assert list(out["groups"]) == ["250.0"]
    assert out["unknown_frequency"] == ["acq"]


def test_operator_interpreted_truth_is_labelled_as_not_independent():
    t = tgt("T1", (12.5,), grade="operator_reviewed", basis="operator_radar_interpretation",
            independent=False)
    r = score(artifact([("p1", "A", (12.5,))]), manifest([t]), RULE)
    assert r["evidence"]["truth_class"].startswith("NOT_INDEPENDENT")
    assert r["evidence"]["n_independent_physical"] == 0


def test_a_linear_target_is_an_opportunity_on_every_line_it_crosses():
    lines = [AcquisitionLine(f"L{i}", (0.0, float(i)), (10.0, float(i))) for i in range(4)]
    seg = {"target_id": "D1", "object_class": "duct", "material": "steel",
           "locations": [{"frame_id": "utm", "geometry": "segment",
                          "start": [5.0, 0.0], "end": [5.0, 2.0]}],
           "evidence": {"basis": "construction_record", "grade": "independently_verified",
                        "independent_of_gpr": True, "source": "as-built"}}
    art = artifact([("p1", "L0", (5.2, 0.0)), ("p2", "L3", (5.0, 3.0))], frame_id="utm",
                   crs="EPSG:32633", lines=lines)
    r = score(art, manifest([seg]), RULE)
    assert r["counts"]["opportunities"] == 3        # lines 0-2 cross it; line 3 does not
    assert r["counts"]["true_positives"] == 1
