"""
The KEC testbed evidence for Yesan: what it settles, and what it must not be
allowed to settle.

It settles where the testbed's objects were BUILT. It does not settle which
2021 radar trace is above them, and the 2017-18 processing parameters in the
same report were never measured on the 2021 files. These tests pin both halves.
"""
import json

import pytest

from benchmark.predictions import AcquisitionLine, Prediction, PredictionArtifact, TimingProvenance
from benchmark.target_scoring import MatchRule, ScoringBlocked, score
from benchmark.targets import MANIFEST_DIR, Capability, load_manifest
from evidence import yesan_kec as y

PATH = MANIFEST_DIR / "yesan-fullscale.targets.json"


def test_the_sheet_interval_is_exactly_27_m_over_3116_intervals():
    assert abs(27 / 3116 - 0.0086649550706) < 1e-12


def test_tables_reconcile_with_the_drawn_objects_except_the_approach_slab():
    r = y.reconciliation()
    for sec, total in (("asphalt", 40), ("concrete", 42)):
        assert r[sec]["stated_total"] == r[sec]["table_row_sum"] == r[sec]["drawn"] == total
        assert r[sec]["type_differences"] == {}
    slab = r["approach_slab"]
    # kept as found: three different numbers, and the gap is steel plates
    assert (slab["stated_total"], slab["table_row_sum"], slab["drawn"]) == (38, 36, 34)
    assert slab["type_differences"] == {"steel_plate": (8, 6)}


def test_every_target_row_cites_its_page_table_and_figure():
    for r in y.load_targets():
        assert r["source_document"] == "KEC EXTRI-2018-40-534.9607"
        assert r["source_pdf_page"] and r["source_printed_page"]
        assert r["source_table"] in ("4.6", "4.7", "4.8")
        assert r["source_figure"] in ("4.5", "4.7", "4.10")
        assert r["evidence_level"] == "authoritative_testbed_design"
        assert r["applies_to_2021_survey"] == "not_established"
        assert r["depth_basis"] in ("kec_text", "kec_table_single_value", "kec_figure_reading")


def test_a_table_single_value_depth_matches_its_table_row():
    """A depth labelled as the table's value must be that value, not a figure reading."""
    rows = {(t["section"], t["object_type"], t["size_m"]): t for t in y.load_tables()}
    for r in y.load_targets():
        if r["depth_basis"] != "kec_table_single_value":
            continue
        t = rows[(r["section"], r["object_type"], r["size_m"])]
        assert t["depth_min_m"] == t["depth_max_m"], r["target_id"]
        assert float(r["depth_m"]) == pytest.approx(float(t["depth_min_m"])), r["target_id"]


def test_testbed_chainage_is_section_offset_plus_position():
    for r in y.load_targets():
        off = y.SECTIONS[r["section"]]
        assert float(r["testbed_position_m"]) == pytest.approx(off + float(r["section_position_m"]))
        assert 0 <= float(r["section_position_m"]) <= y.SECTION_LENGTH_M


def test_the_start_and_end_plates_are_on_line_b_at_the_ends():
    t = {r["target_id"]: r for r in y.load_targets()}
    start, end = t["AS-B01"], t["CO-B24"]
    assert start["line"] == end["line"] == "B"
    assert (float(start["extent_start_m"]), float(start["extent_end_m"])) == (0.0, 0.5)
    assert (float(end["extent_start_m"]), float(end["extent_end_m"])) == (89.5, 90.0)
    # line A has no start plate
    assert not any(r["object_type"] == "steel_plate" and r["line"] == "A"
                   and float(r["testbed_position_m"]) < 1.0 for r in y.load_targets())


def test_manifest_targets_are_generated_from_the_csv_without_drift():
    on_disk = json.loads(PATH.read_text())["targets"]
    assert on_disk == y.manifest_targets()


def test_every_manifest_target_is_testbed_truth_and_none_is_grade_a():
    m = load_manifest(PATH)
    assert len(m.targets) == len(y.load_targets())
    for t in m.targets:
        assert t.evidence.basis.value == "construction_record"
        assert t.evidence.grade.value == "measurement_associated"
        assert t.evidence.independent_of_gpr
        assert not t.evidence.verified_by_subterra
        assert all(loc.frame_id.startswith("yesan:testbed-") for loc in t.locations)


def test_the_testbed_frames_are_declared_but_not_registered_to_the_radar():
    m = load_manifest(PATH)
    for ln in ("A", "B"):
        f = m.frame(f"yesan:testbed-{ln}")
        assert f.origin_status == "declared"
        assert f.registration_to_radar == "unresolved"
    for ln in ("A", "B"):
        assert m.frame(f"yesan:line-{ln}").registration_to_radar == "unresolved"


def test_scoring_in_the_testbed_frame_is_refused():
    """Real targets now exist; the gate must still refuse on the registration."""
    m = load_manifest(PATH)
    art = PredictionArtifact(
        dataset_id="yesan-fullscale", acquisition_id="DAT_0074_B5", frame_id="yesan:testbed-B",
        frame_units="m", detector={}, preprocessing={}, input_sha256="x",
        timing=TimingProvenance(), lines=(AcquisitionLine("B", (0.0,), (90.0,)),),
        predictions=(Prediction(prediction_id="p1", line_id="B", position=(20.0,)),))
    with pytest.raises(ScoringBlocked) as exc:
        score(art, m, MatchRule(name="r", radius_kind="fixed", radius=0.5))
    assert "yesan-testbed-to-2021-registration" in str(exc.value)
    for cap in Capability:
        ok, reasons = m.capability(cap, "yesan:testbed-B")
        assert not ok and reasons, cap


def test_earlier_survey_processing_is_never_transferable_to_2021():
    assert y.SUPPORTING_ONLY
    assert all(f.classification == "supporting_only_2021" for f in y.SUPPORTING_ONLY)
    assert not any(f.transferable_to_2021 for f in y.SUPPORTING_ONLY + y.TESTBED_FACTS)
    ids = {f.id for f in y.SUPPORTING_ONLY}
    assert {"kec-time-zero", "kec-migration-velocity", "kec-antenna-separation"} <= ids
    # and none of it reached a target, frame or depth surface (the provenance
    # note that says it was left out is allowed to name it)
    d = json.loads(PATH.read_text())
    carried = json.dumps([d["targets"], d["frames"], d["depth_reference_surfaces"]])
    assert "0.075" not in carried and "0.75E+8" not in carried and "time_zero" not in carried


def test_the_2021_registration_components_are_not_overclaimed():
    s = {c.component: c.status for c in y.REGISTRATION_STATUS}
    assert s["physical testbed 0 m reference"] == "SOLVED FOR TESTBED"
    assert s["constructed target coordinates / distances"] == "SOLVED FOR TESTBED"
    assert s["line A / line B geometry"] == "SOLVED FOR TESTBED"
    assert s["2021 survey direction"] == "PARTIALLY SOLVED"
    for still in ("2021 trace-to-distance scale",
                  "meaning of the 27 m / 3116-interval calibration",
                  "whether 2021 target positions are expected in the same distance frame",
                  "exact 2021 trace-to-testbed transformation"):
        assert s[still] == "STILL UNKNOWN", still
    assert "SOLVED FOR 2021 SURVEY" not in s.values()


def test_rhee_disagreements_stay_explicit():
    rows = y.load_comparison()
    bad = {r["kec_target_id"]: r for r in rows if r["agreement"].startswith("DISAGREE")}
    assert len(rows) == 74 and len(bad) == 26
    assert bad["AS-A07"]["agreement"].startswith("DISAGREE_depth")
    assert bad["CO-D01"]["agreement"].startswith("DISAGREE_position")
    assert bad["AS-B01"]["agreement"].startswith("DISAGREE_position")
    # the manifest uses KEC as read, not a value moved toward Rhee
    t = {r["target_id"]: r for r in y.load_targets()}
    assert float(t["CO-D01"]["section_position_m"]) == pytest.approx(4.6)
