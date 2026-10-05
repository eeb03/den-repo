"""
The Yesan distance-scale investigation is reproducible arithmetic, and it does
NOT unlock scoring: characterising the 2.8% mechanism says nothing about which
scale a (still missing) target list uses.
"""
from benchmark.targets import MANIFEST_DIR, Capability, load_manifest
from scripts.yesan_scale_hypotheses import hypotheses, observed_ratio, rational_calibration


def test_the_authors_dx_is_an_exact_whole_pulse_per_whole_metre_calibration():
    rc = rational_calibration()
    assert rc["as_fraction"] == "3116/9"
    assert rc["dx_as_fraction_m"] == "27/3116"
    assert rc["relative_error_of_fraction"] < 1e-11
    assert rc["chance_probability_upper_bound"] < 1e-5
    assert {"metres": 9, "pulses": 3116} == {k: rc["whole_metre_whole_pulse_candidates"][0][k]
                                             for k in ("metres", "pulses")}


def test_the_observed_ratio_is_the_2_8_percent():
    assert abs(observed_ratio() - 1.027993) < 1e-6


def test_every_competing_explanation_has_a_verdict_and_only_recalibration_is_accepted():
    verdicts = {h["id"]: h["verdict"] for h in hypotheses()}
    accepted = [k for k, v in verdicts.items() if v.startswith("ACCEPT")]
    assert accepted == ["H2-field-recalibration"]
    assert verdicts["H10-which-is-physical"] == "UNRESOLVED"
    for hid in ("H1-header-rounding", "H3-constant-offset", "H4-slope-distance",
                "H5-projection-scale", "H8-parser-error"):
        assert verdicts[hid] == "REJECT"


def test_characterising_the_scale_does_not_unlock_any_yesan_metric():
    m = load_manifest(MANIFEST_DIR / "yesan-fullscale.targets.json")
    r = m.readiness()
    assert r["status"] == "not_scoring_ready"
    blocked = r["frames"]["yesan:line-A"][Capability.DETECTION_MATCHING.value]
    assert any("yesan-distance-scale" in x for x in blocked)
    assert any("yesan-line-registration" in x for x in blocked)
    q = next(q for q in m.open_questions if q.id == "yesan-distance-scale")
    assert "27/3116" in q.statement
