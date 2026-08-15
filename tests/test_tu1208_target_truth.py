"""
The TU1208 transcription says what the paper says, and nothing else.

THREE KINDS OF TEST LIVE HERE, and they are not the same kind of claim.

    FIDELITY   the stored value equals the published value. These are the
               depths, counts, offsets and file names, pinned literally, so
               that a later edit to the transcription is a visible diff in a
               test rather than a quiet change to ground truth.

    SEPARATION nothing in the detection or anomaly machinery can supply or
               alter a truth value, and modelled material properties cannot be
               mistaken for surveyed geometry. This is the constraint the whole
               stage exists to protect: TU1208's depths are independent
               evidence, and independence is a property of the wiring, not an
               intention.

    RESTRAINT  values the paper does not publish stay unpublished. The failure
               mode being guarded is not an error, it is a plausible-looking
               zero -- a transverse offset of 0.0 reads as "on the axis" and a
               pipe diameter of 0 reads as "a line", and both are fabrications.
"""
import importlib
import json
from pathlib import Path

import pytest

from benchmark import tu1208_truth as truth

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = REPO_ROOT / truth.ARCHIVE_ROOT


# ---------------------------------------------------------------------------
# fidelity: the depths, verified against the published sections
# ---------------------------------------------------------------------------

#: Figure -> published pipe-layer depths, shallowest first. Transcribed from the
#: transversal sections of the TU1208 paper (doi:10.3390/rs10040530). Written out
#: here a second time ON PURPOSE: a test that read them from the same JSON it is
#: checking would pass no matter what the JSON said.
PUBLISHED_PIPE_DEPTHS = {
    "silt":         ("Figure 6",  [-0.80, -1.20, -1.83]),
    "limestone":    ("Figure 9",  [-1.20, -1.70, -2.40]),
    "gneiss_14_20": ("Figure 11", [-0.90, -1.50, -2.10]),
    "gneiss_0_20":  ("Figure 13", [-1.15, -1.56, -2.20]),
}


@pytest.mark.parametrize("region_id", sorted(PUBLISHED_PIPE_DEPTHS))
def test_the_pipe_layer_depths_are_the_published_ones(region_id):
    figure, depths = PUBLISHED_PIPE_DEPTHS[region_id]
    assert truth.pipe_layer_depths(region_id) == depths
    assert truth.region(region_id)["figure"] == figure


def test_the_two_gneiss_regions_are_not_collapsed_into_one():
    """
    They are different media at different depths. Merging them would produce a
    single 'gneiss' with six depths and a velocity fitted across two materials,
    which is the exact error the three-medium structure exists to prevent.
    """
    assert truth.pipe_layer_depths("gneiss_14_20") != truth.pipe_layer_depths("gneiss_0_20")
    materials = {truth.region("gneiss_14_20")["host_material"],
                 truth.region("gneiss_0_20")["host_material"]}
    assert len(materials) == 2


def test_each_pipe_bearing_region_has_three_distinct_depths():
    """Three depths in one medium is what makes a later t0/v fit over-determined."""
    for region_id in PUBLISHED_PIPE_DEPTHS:
        depths = truth.pipe_layer_depths(region_id)
        assert len(depths) == 3
        assert len(set(depths)) == 3


def test_the_target_count_matches_the_published_composition():
    """4 regions x 3 layers x 3 pipes; the paper states three pipes per layer."""
    pipes = truth.pipe_targets()
    assert len(pipes) == 36
    assert truth.summary()["n_pipe_layers"] == 12
    for region_id in PUBLISHED_PIPE_DEPTHS:
        assert len(truth.pipe_targets(region_id)) == 9


def test_the_pipe_identities_follow_the_published_laying_order():
    """
    'an empty steel pipe, a PVC pipe full of water, and an empty PVC pipe (this
    is the laying order in all layers, starting from the longitudinal axis)'.
    """
    for region_id in PUBLISHED_PIPE_DEPTHS:
        for layer in (1, 2, 3):
            got = [p.identity for p in truth.pipe_targets(region_id)
                   if p.layer == layer]
            assert got == ["empty steel pipe", "PVC pipe full of water", "empty PVC pipe"]


def test_the_multilayer_region_is_recorded_as_attested_empty_of_targets():
    """'There are five layers and no targets' is a statement, not a blank field."""
    region = truth.region("multilayer")
    assert region["targets_attested_absent"] is True
    assert region["absence_attestation"] == "There are five layers and no targets."
    assert region["pipe_layers"] == []
    assert "not a control for 'no reflector'" in region["absence_caveat"]


def test_the_multilayer_thicknesses_are_the_published_ones():
    layers = truth.material_layers()
    assert [layer.thickness_m for layer in layers] == [0.80, 0.60, 0.60, 1.30, 0.60]
    assert [layer.material for layer in layers] == [
        "limestone", "gneiss 0/20 gravel", "gneiss 14/20 gravel", "limestone", "silt"]


def test_the_acquisition_line_offsets_are_the_published_ones():
    assert truth.acquisition_line_offset(1) == 1.25
    assert truth.acquisition_line_offset(2) == 3.75
    assert truth.acquisition_line_offset(3) == 6.25
    assert truth.acquisition_line_offset(4) == 8.75
    assert truth.acquisition_line_offset(5) is None, "only four line positions are published"


# ---------------------------------------------------------------------------
# fidelity: the files
# ---------------------------------------------------------------------------

def test_all_67_published_profiles_are_present_on_disk():
    resolved = truth.resolve_files(ARCHIVE)
    assert len(resolved) == 67
    assert all(path.exists() for path in resolved.values())


def test_every_profile_resolves_into_the_region_directory_the_paper_assigns():
    """`resolve_files` raises on a region disagreement; this pins the counts."""
    resolved = truth.resolve_files(ARCHIVE)
    directories = {r["id"]: r["archive_directory"] for r in truth.regions()}
    counts = {}
    for profile in truth.profiles():
        parent = resolved[profile.published_file_name].parent.name
        assert parent == directories[profile.region_id]
        counts[profile.region_id] = counts.get(profile.region_id, 0) + 1
    assert counts == {"silt": 15, "multilayer": 4, "limestone": 15,
                      "gneiss_14_20": 15, "gneiss_0_20": 18}


def test_the_published_names_and_the_archive_names_genuinely_differ():
    """
    The fold is not cosmetic paranoia. If paper and archive ever agreed exactly,
    this test failing would say the normalisation is no longer earning its
    place -- and until then it documents which names actually disagree.
    """
    resolved = truth.resolve_files(ARCHIVE)
    differing = {name: path.name for name, path in resolved.items() if name != path.name}
    assert differing, "expected at least one paper/archive name discrepancy"
    assert differing["200MHz_Limestone_2.dzt"] == "200MHz-Limestone_2.dzt"
    assert differing["900MHz_Limestone2_rev.dzt"] == "900MHz_Limestone_2_rev.dzt"


def test_a_missing_archive_file_is_an_error_not_a_silent_gap(tmp_path):
    empty = tmp_path / "Database_2018"
    (empty / "SILT").mkdir(parents=True)
    with pytest.raises(truth.TU1208TruthError, match="no archive file"):
        truth.resolve_files(empty)


def test_the_dual_line_silt_file_keeps_both_lines():
    """
    200MHz_Silt_h2h1.dzt holds line 2 then line 1 in one file. Recording it
    under a single line would lose half of what it covers.
    """
    profile = next(p for p in truth.profiles()
                   if p.published_file_name == "200MHz_Silt_h2h1.dzt")
    assert profile.lines == (1, 2)
    assert profile.line_offsets_m == (1.25, 3.75)
    assert "discontinuity in the data" in profile.note


def test_profiles_whose_length_the_paper_prints_as_NA_have_no_length():
    """
    Counted by hand from the (Profile Length [m]) column of Tables 3-7:
    silt 3, multilayer 2, limestone 4, gneiss 14/20 3, gneiss 0/20 8.
    """
    unscaled = [p for p in truth.profiles() if not p.has_metric_scale]
    assert len(unscaled) == 20
    by_region = {}
    for p in unscaled:
        by_region[p.region_id] = by_region.get(p.region_id, 0) + 1
    assert by_region == {"silt": 3, "multilayer": 2, "limestone": 4,
                         "gneiss_14_20": 3, "gneiss_0_20": 8}
    assert all(p.profile_length_m is None for p in unscaled)


# ---------------------------------------------------------------------------
# separation: truth cannot come from, or reach, a detector
# ---------------------------------------------------------------------------

def test_the_truth_modules_import_nothing_that_produces_a_detection():
    """
    Ground truth must not be reachable from the thing it judges. An import is
    the cheapest path for that to happen and the easiest to check.
    """
    forbidden = ("interpretation", "preprocessing", "benchmark.detection",
                 "benchmark.scoring", "benchmark.association", "detector")
    for module in ("benchmark/tu1208_truth.py", "benchmark/tu1208_targets.json"):
        text = (REPO_ROOT / module).read_text()
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text


def test_no_detector_or_anomaly_module_can_reach_the_tu1208_truth():
    """
    The reverse direction. If a detector imported this, a target depth could
    become a feature, and the benchmark would be measuring itself.
    """
    offenders = []
    for path in list((REPO_ROOT / "interpretation").rglob("*.py")) + \
                list((REPO_ROOT / "preprocessing").rglob("*.py")):
        text = path.read_text()
        if "tu1208" in text.lower():
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_the_truth_module_exposes_no_way_to_write_a_value():
    """
    Every dataclass here is frozen. A mutable truth object could be edited by
    whatever holds it, and the edit would not show up in the version hash.
    """
    pipe = truth.pipe_targets("silt")[0]
    with pytest.raises(Exception):
        pipe.depth_m = -99.0
    permittivity = truth.modelled_permittivities()[0]
    with pytest.raises(Exception):
        permittivity.relative_permittivity = 1.0


def test_modelled_permittivity_is_not_geometry_and_is_not_a_velocity():
    """
    Surveyed depth and a number obtained by matching an FDTD model are different
    kinds of knowledge. They are different types, reached by different calls,
    and the caveat travels with the number.
    """
    perms = truth.modelled_permittivities()
    assert {p.region_id for p in perms} == {"silt", "limestone", "gneiss_14_20", "gneiss_0_20"}
    for p in perms:
        assert p.evidence_type == "modelled"
        assert p.is_a_velocity is False
        assert p.authors_caveat
        assert not hasattr(p, "depth_m")
    assert {p.relative_permittivity for p in perms} == {13, 6, 3, 5.5}


def test_no_velocity_or_time_zero_is_computed_anywhere_in_this_stage():
    """
    The stage brief forbids both. `m/ns`, a permittivity-to-velocity conversion
    and any t0 arithmetic would all leave a trace in the source.
    """
    source = (REPO_ROOT / "benchmark/tu1208_truth.py").read_text()
    for banned in ("m_per_ns", "m/ns", "299792458", "0.2998", "sqrt", "time_zero", "t0 ="):
        assert banned not in source, f"{banned!r} suggests a velocity or time-zero calculation"


def test_the_depths_are_not_exposed_as_detector_labels():
    """
    A target depth is evidence, not a class. Nothing here yields a label, a
    score, or a y-value, and the pipe target carries no such field.
    """
    pipe = truth.pipe_targets("silt")[0]
    for banned in ("label", "score", "y", "is_positive", "class_"):
        assert not hasattr(pipe, banned)
    assert not any(name.startswith(("label", "score")) for name in dir(truth))


# ---------------------------------------------------------------------------
# restraint: what is unknown stays unknown
# ---------------------------------------------------------------------------

def test_an_unpublished_pipe_diameter_is_none_and_never_zero():
    for pipe in truth.pipe_targets():
        assert pipe.diameter_mm is None, "no diameter is published for these pipes"
        assert pipe.length_m == 2.5


def test_an_unavailable_transverse_offset_is_none_and_never_zero():
    """0.0 would read as 'on the longitudinal axis', which is a claim."""
    for pipe in truth.pipe_targets():
        assert pipe.transverse_offset_m is None


def test_a_depth_whose_object_is_unsettled_names_no_object():
    """
    Three depths are printed among symbols the text says sit at two depths.
    Picking one would be indistinguishable in the data from having known.
    """
    uncertain = [d for d in truth.published_depths() if not d.object_certain]
    assert uncertain, "the transcription should retain the unsettled cases"
    for entry in uncertain:
        assert entry.object is None
        assert entry.candidates, "an unsettled entry still records what it might be"


def test_the_certain_and_uncertain_depths_are_both_kept():
    depths = truth.published_depths()
    assert len(depths) == 18
    certain = [d for d in depths if d.object_certain]
    assert len(certain) == 11
    assert {d.object for d in certain} >= {
        "hemispherical cavity of expanded polystyrene", "dolmen (upper)", "dolmen (lower)"}


def test_derived_interface_depths_are_marked_derived():
    """
    Cumulative sums of published thicknesses are legitimate and are not surveyed
    target depths. The type keeps them apart and every instance says so.
    """
    interfaces = truth.interface_depths()
    assert [i.depth_m for i in interfaces] == [-0.80, -1.40, -2.00, -3.30, -3.90]
    assert all(i.derived for i in interfaces)
    assert all("cumulative sum" in i.derivation for i in interfaces)
    assert all(i.verified_by_subterra is False for i in interfaces)


def test_the_depth_datum_caveat_is_carried_and_is_not_quantified():
    """
    The sections omit the surface layers actually built on top of them. A later
    depth comparison that did not carry this would be wrong by at least 0.10 m.
    """
    doc = json.loads((REPO_ROOT / "benchmark/tu1208_targets.json").read_text())
    caveat = doc["depth_datum_caveat"]
    assert caveat["quantified"] is False
    assert "10-cm surface layer" in caveat["statement"]
    assert "asphalt wearing course" in caveat["statement"]


def test_every_transcribed_value_carries_its_provenance():
    doc = json.loads((REPO_ROOT / "benchmark/tu1208_targets.json").read_text())
    assert doc["provenance_class"] == "transcribed_from_publication"
    assert doc["verified_by_subterra"] is False
    for region in doc["regions"]:
        assert region["figure"]
        assert isinstance(region["pdf_page_index"], int)
    for pipe in truth.pipe_targets():
        assert pipe.provenance == "transcribed_from_publication"
        assert pipe.verified_by_subterra is False
        assert pipe.figure


def test_verified_by_subterra_is_false_everywhere():
    """
    Subterra excavated nothing and surveyed nothing. Any True here would be a
    claim about work this project did not do.
    """
    text = (REPO_ROOT / "benchmark/tu1208_targets.json").read_text()
    assert '"verified_by_subterra": true' not in text.lower()
    for obj in (list(truth.pipe_targets()) + list(truth.published_depths())
                + list(truth.modelled_permittivities()) + list(truth.interface_depths())):
        assert obj.verified_by_subterra is False


def test_the_gaps_are_enumerated_rather_than_left_implicit():
    doc = json.loads((REPO_ROOT / "benchmark/tu1208_targets.json").read_text())
    quantities = {u["quantity"] for u in doc["unavailable"]}
    assert "pipe diameter" in quantities
    assert "along-line origin of any profile" in quantities
    assert "vertical datum, CRS, absolute surface elevation" in quantities
    for entry in doc["unavailable"]:
        assert entry["reason"], "an unavailable quantity states why"
    assert {q["id"] for q in doc["open_questions"]} >= {
        "pipe-depth-reference-surface", "depth-datum-vs-antenna-surface",
        "spacing-to-pipe-assignment"}


def test_no_geographic_coordinate_is_manufactured_from_a_site_offset():
    frame = json.loads((REPO_ROOT / "benchmark/tu1208_targets.json").read_text())["coordinate_frame"]
    assert frame["crs"] is None
    assert frame["vertical_datum"] is None
    assert frame["geographic_conversion"].startswith("NOT SUPPORTED")
    assert frame["shared_with_radar"] is False


# ---------------------------------------------------------------------------
# identity: the version tracks the truth, and only the truth
# ---------------------------------------------------------------------------

def test_the_version_survives_a_round_trip_through_json():
    doc = json.loads(truth.TRUTH_FILE.read_text())
    assert json.loads(json.dumps(doc)) == doc
    assert truth.truth_version() == truth.truth_version()


def test_provenance_survives_serialisation(tmp_path):
    """A transcription that loses its origin in transit is an anonymous number."""
    import dataclasses

    pipe = truth.pipe_targets("silt")[0]
    blob = json.dumps(dataclasses.asdict(pipe))
    back = json.loads(blob)
    assert back["provenance"] == "transcribed_from_publication"
    assert back["verified_by_subterra"] is False
    assert back["depth_m"] == -0.80
    assert back["diameter_mm"] is None


def test_reordering_the_records_does_not_change_the_version(tmp_path, monkeypatch):
    before = truth.truth_version()

    doc = json.loads(truth.TRUTH_FILE.read_text())
    doc["regions"] = list(reversed(doc["regions"]))
    doc["profiles"] = list(reversed(doc["profiles"]))
    for region in doc["regions"]:
        region["pipe_layers"] = list(reversed(region["pipe_layers"]))
        region["other_published_depths"] = list(reversed(region.get("other_published_depths", [])))
    doc["unavailable"] = list(reversed(doc["unavailable"]))
    doc["open_questions"] = list(reversed(doc["open_questions"]))

    shuffled = tmp_path / "tu1208_targets.json"
    shuffled.write_text(json.dumps(doc))
    monkeypatch.setattr(truth, "TRUTH_FILE", shuffled)
    assert truth.truth_version() == before


def test_changing_a_transcribed_depth_changes_the_version(tmp_path, monkeypatch):
    before = truth.truth_version()

    doc = json.loads(truth.TRUTH_FILE.read_text())
    silt = next(r for r in doc["regions"] if r["id"] == "silt")
    silt["pipe_layers"][0]["depth_m"] = -0.81

    edited = tmp_path / "tu1208_targets.json"
    edited.write_text(json.dumps(doc))
    monkeypatch.setattr(truth, "TRUTH_FILE", edited)
    assert truth.truth_version() != before


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda d: d["regions"][0].__setitem__(
        "modelled_permittivity", {**d["regions"][0]["modelled_permittivity"],
                                  "relative_permittivity": 99}), id="permittivity"),
    pytest.param(lambda d: d["profiles"][0].__setitem__("region", "limestone"), id="file-region"),
    pytest.param(lambda d: d["unavailable"].pop(), id="a-gap-removed"),
    pytest.param(lambda d: d["open_questions"].pop(), id="an-open-question-dropped"),
    pytest.param(lambda d: d.__setitem__("verified_by_subterra", True), id="verification-claimed"),
])
def test_changing_any_part_of_the_truth_changes_the_version(mutate, tmp_path, monkeypatch):
    before = truth.truth_version()
    doc = json.loads(truth.TRUTH_FILE.read_text())
    mutate(doc)
    edited = tmp_path / "tu1208_targets.json"
    edited.write_text(json.dumps(doc))
    monkeypatch.setattr(truth, "TRUTH_FILE", edited)
    assert truth.truth_version() != before


def test_the_version_does_not_move_with_anything_about_a_detector():
    """
    A benchmark whose identity changed when the detector changed could not be
    used to compare detectors. The hash reads only transcribed truth.
    """
    content = truth.truth_content()
    blob = json.dumps(content).lower()
    for name in ("threshold", "detector", "estimator", "zscore", "candidate"):
        assert name not in blob


def test_the_transcription_does_not_make_tu1208_ready():
    """
    Transcribing a depth resolves no spatial dimension. TU1208 has no CRS, no
    vertical datum and no absolute surface elevation, and none of that changed.
    """
    doc = json.loads(truth.TRUTH_FILE.read_text())
    assert "readiness" not in doc
    assert "READY" not in json.dumps(doc)
    source = (REPO_ROOT / "benchmark/tu1208_truth.py").read_text()
    assert "readiness" not in source.lower()


def test_the_stage_14_ground_truth_system_was_not_forked():
    """One truth architecture. This module adds a transcription, not a rival."""
    ground_truth = importlib.import_module("benchmark.ground_truth")
    assert hasattr(ground_truth, "TruthLabel")
    assert not hasattr(truth, "TruthLabel"), "labels belong to benchmark.ground_truth"
    assert not hasattr(truth, "EvaluationUnit")
