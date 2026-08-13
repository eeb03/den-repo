"""
The shallow-anchor audit reaches "no", and the maths behind it is checked.

THE CORRECTION THIS STAGE MAKES. Stage 24 concluded that a reflector at
0.1-0.2 m was the missing constraint. It is not. The confounding between t0 and
velocity is SCALE-INVARIANT -- it depends on the coefficient of variation of the
depth set and not on depth -- so a set of shallow targets is exactly as
degenerate as a set of deep ones. The tests below pin that, because the wrong
version of it would send a real acquisition after the wrong data.

    LAW          corr = -1/sqrt(1+CV^2), verified against the closed-form
                 covariance and against scaling.
    RANKING      the candidate designs are ordered by what they actually buy,
                 and "multiple shallow reflectors" must come out worst.
    INTEGRITY    no synthetic signal, no parameter transfer, and timing
                 metadata is never promoted to a physical time zero.
    FIREWALL     4TU's blocked dimensions stay blocked.
"""
import json
import math
from pathlib import Path

import pytest

from scripts import stage25_shallow_anchor_audit as audit

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def result():
    return audit.build()


# ---------------------------------------------------------------------------
# the law, and the correction it forces
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("depths", [
    [0.80, 1.20, 1.83],
    [0.0944, 0.1514, 0.2146, 0.2745],
    [0.15, 2.00],
    [1.0, 1.0, 3.0, 7.5],
])
def test_the_correlation_equals_the_coefficient_of_variation_law(depths):
    """corr = -1/sqrt(1+CV^2) is the whole argument, so it is checked, not asserted."""
    lev = audit.leverage("check", depths, "test")
    expected = -1.0 / math.sqrt(1.0 + lev.coefficient_of_variation ** 2)
    assert lev.corr_t0_slope == pytest.approx(expected, abs=1e-12)


def test_the_correlation_matches_a_direct_ols_covariance():
    depths = [0.80, 1.20, 1.83]
    lev = audit.leverage("check", depths, "test")

    x = [2.0 * d for d in depths]
    n = len(x)
    sx, sxx = sum(x), sum(v * v for v in x)
    det = n * sxx - sx * sx
    var_b0, var_b1, cov = sxx / det, n / det, -sx / det

    assert lev.corr_t0_slope == pytest.approx(cov / math.sqrt(var_b0 * var_b1), abs=1e-12)
    assert lev.t0_se_ns_per_ns_noise == pytest.approx(math.sqrt(var_b0), rel=1e-12)


@pytest.mark.parametrize("factor", [0.1, 10.0, 100.0])
def test_the_confounding_is_scale_invariant(factor):
    """
    THE CORRECTION. If this were false, "go shallower" would be a fix. It is
    true, so depth magnitude buys nothing at all.
    """
    base = [0.0944, 0.1514, 0.2146, 0.2745]
    a = audit.leverage("a", base, "test")
    b = audit.leverage("b", [d * factor for d in base], "test")
    assert a.corr_t0_slope == pytest.approx(b.corr_t0_slope, abs=1e-12)


def test_bam_shallow_targets_are_no_better_than_tu1208_deep_ones(result):
    """
    BAM's ducts are an order of magnitude shallower and just as confounded.
    This is the concrete refutation of the stage 24 recommendation.
    """
    by_name = {r["name"]: r for r in result["identifiability"]["real_depth_sets"]}
    bam = by_name["BAM Pk266 ducts"]
    silt = by_name["TU1208 silt"]

    assert max(bam["depths_m"]) < min(silt["depths_m"]), "BAM really is shallower"
    assert abs(bam["corr_t0_slope"]) > 0.93
    assert abs(bam["corr_t0_slope"] - silt["corr_t0_slope"]) < 0.02


def test_the_correlation_is_always_negative_for_positive_depths(result):
    """
    Structural: mean(2d) > 0, so t0 and velocity are never independent under
    this model. No target geometry makes them so.
    """
    for row in (result["identifiability"]["real_depth_sets"]
                + result["identifiability"]["candidate_designs"]):
        assert row["corr_t0_slope"] < 0
    floor = result["identifiability"]["structural_floor"]["two_level_floor"]
    assert floor == pytest.approx(-1.0 / math.sqrt(2.0))


def test_a_two_level_design_cannot_beat_the_structural_floor():
    """Even with the shallow point at zero, two levels bottom out at -1/sqrt(2)."""
    for deep in (0.5, 2.0, 10.0, 1000.0):
        lev = audit.leverage("two-level", [0.0, deep], "test")
        assert lev.corr_t0_slope >= -1.0 / math.sqrt(2.0) - 1e-12


def test_multiple_shallow_reflectors_is_the_worst_candidate_design(result):
    """
    Design B is what stage 24's wording would have produced. It comes out worse
    than the real TU1208 targets, which is why the wording had to be corrected.
    """
    designs = {r["name"]: r for r in result["identifiability"]["candidate_designs"]}
    b = designs["B: multiple shallow reflectors"]
    worst = max(designs.values(), key=lambda r: abs(r["corr_t0_slope"]))
    assert worst["name"] == b["name"]
    assert abs(b["corr_t0_slope"]) > 0.95


def test_a_direct_system_delay_measurement_is_the_strongest_design(result):
    """
    An observation at d = 0 constrains t0 without going through velocity, which
    is the only thing that genuinely breaks the degeneracy rather than easing it.
    """
    designs = {r["name"]: r for r in result["identifiability"]["candidate_designs"]}
    best = min(designs.values(), key=lambda r: abs(r["corr_t0_slope"]))
    assert best["name"].startswith("C+")
    assert best["has_direct_t0_observation"] is True
    assert abs(best["corr_t0_slope"]) < 0.65
    assert best["t0_se_ns_per_ns_noise"] < 0.6


# ---------------------------------------------------------------------------
# the inventory answers "no", with reasons
# ---------------------------------------------------------------------------

def test_nothing_held_constrains_t0_or_velocity(result):
    assert result["answer"] == "no"
    assert result["n_constraining_t0"] == 0
    assert result["n_constraining_velocity"] == 0
    for candidate in result["inventory"]:
        assert candidate["constrains_t0"] is False
        assert candidate["constrains_velocity"] is False
        assert candidate["reason"], "a verdict without a reason is an opinion"


def test_timing_metadata_is_never_promoted_to_a_physical_time_zero(result):
    """
    The central category error this stage guards. DelayRecordingTime and
    rhf_position are recording metadata; neither may become t0.
    """
    by_feature = {c["feature"]: c for c in result["inventory"]}

    delay = by_feature["DelayRecordingTime"]
    assert delay["verdict"] == "RULED OUT"
    assert delay["constrains_t0"] is False
    assert "RECORDING-START offset" in delay["reason"]
    assert "not a propagation path" in delay["reason"]

    rhf = by_feature["rhf_position"]
    assert rhf["verdict"] == "RULED OUT"
    assert "not set" in rhf["reason"]


def test_the_delay_ruling_rests_on_a_physical_check_not_an_opinion(result):
    """
    Ruled out because reading it as an air gap implies 0.00-2.00 m antenna
    heights against the author's "a few centimetres", and 9 files carry zero.
    """
    delay = next(c for c in result["inventory"] if c["feature"] == "DelayRecordingTime")
    assert "2.00 m" in delay["reason"]
    assert "few centimetres" in delay["reason"]
    assert "9 of 751" in delay["reason"]


def test_the_undocumented_mala_fields_are_unresolved_not_invented(result):
    """
    The vendor's own format specification does not list them. Unresolved is the
    honest state: a vendor answer could still make them usable.
    """
    mala = next(c for c in result["inventory"] if "SIGNAL POSITION" in c["feature"])
    assert mala["verdict"].startswith("UNRESOLVED")
    assert mala["constrains_t0"] is False
    assert "DOES NOT LIST" in mala["reason"]
    assert "1053.5" in mala["reason"], "the incoherence is quantified, not asserted"


def test_bam_association_is_credited_without_crediting_identifiability(result):
    """
    BAM genuinely has published association, and that is worth recording. It
    still does not anchor t0, and the two must not be conflated.
    """
    ducts = next(c for c in result["inventory"] if "tendon ducts" in c["feature"])
    assert ducts["identifiable_without_depth"] is True
    assert ducts["constrains_t0"] is False
    assert "IDENTIFIABILITY STILL FAILS" in ducts["verdict"]


def test_no_calibration_artefact_exists_anywhere_in_the_holdings(result):
    absent = next(c for c in result["inventory"] if c["verdict"] == "ABSENT")
    assert "CMP" in absent["feature"]
    assert absent["truth_source"] == "absent"


# ---------------------------------------------------------------------------
# integrity
# ---------------------------------------------------------------------------

def test_no_synthetic_signal_or_geometry_is_created():
    """
    Candidate designs are DEPTH SETS fed to closed-form algebra. Nothing
    generates a trace, an amplitude or a site.
    """
    source = (REPO_ROOT / "scripts/stage25_shallow_anchor_audit.py").read_text()
    for banned in ("random", "np.", "numpy", "gauss", "noise(", "simulate_signal",
                   "trace =", "amplitude"):
        assert banned not in source, f"{banned!r} suggests synthetic data"


def test_no_velocity_or_time_zero_value_is_produced(result):
    blob = json.dumps(result)
    assert "fitted" not in blob.lower()
    source = (REPO_ROOT / "scripts/stage25_shallow_anchor_audit.py").read_text()
    assert "velocity_m_per_ns" not in source
    # The only physical constant present is the speed of light in air, used to
    # convert a header delay into the antenna height it would imply.
    assert source.count("C_AIR_M_PER_NS") >= 1
    assert "0.2998" in source


def test_no_parameter_is_transferred_between_datasets(result):
    """
    A dataset may validate the machinery. That never authorises copying its t0
    or velocity anywhere. Since no dataset yields either, there is nothing to
    copy -- and no code path that could.
    """
    source = (REPO_ROOT / "scripts/stage25_shallow_anchor_audit.py").read_text()
    for banned in ("copy_from", "apply_to", "fitted_t0", "fitted_velocity"):
        assert banned not in source

    # No output field carries a parameter value that could be copied onward.
    # `t0_se_ns_per_ns_noise` is a standard error per unit noise, which is a
    # property of a depth set and not a value belonging to any dataset.
    for row in (result["identifiability"]["real_depth_sets"]
                + result["identifiability"]["candidate_designs"]):
        assert set(row) == {"name", "kind", "depths_m", "n",
                            "coefficient_of_variation", "corr_t0_slope",
                            "t0_se_ns_per_ns_noise", "has_direct_t0_observation", "note"}
    assert result["declarations_written"] == []
    assert result["datasets_modified"] == []


def test_the_audit_cannot_reach_declaration_or_dataset_machinery():
    source = (REPO_ROOT / "scripts/stage25_shallow_anchor_audit.py").read_text()
    for banned in ("api.spatial", "apply_declaration", "record_declaration",
                   "save_frames", "save_records", "DeclarationKind", "readiness"):
        assert banned not in source


# ---------------------------------------------------------------------------
# 4TU firewall
# ---------------------------------------------------------------------------

def test_4tu_blocked_dimensions_remain_blocked():
    from evidence.fourtu_author import REASSESSMENT

    by_dimension = {d.dimension: d for d in REASSESSMENT}
    for dimension in ("depth-axis origin relative to ground",
                      "propagation velocity",
                      "vertical registration of subsurface points",
                      "absolute elevation of a subsurface reflector"):
        assert by_dimension[dimension].after.startswith("BLOCKED"), dimension


def test_the_4tu_elevation_datum_did_not_drag_any_other_dimension_with_it():
    """
    Stage 21 established the acquisition-elevation datum. That is one dimension,
    and it must not have promoted the depth chain.
    """
    from evidence.fourtu_author import REASSESSMENT

    datum = next(d for d in REASSESSMENT
                 if d.dimension == "vertical datum of the GNSS elevation")
    assert "DECLARED on the platform" in datum.after
    assert "ACQUISITION ELEVATION and not to the vertical axis" in datum.detail


def test_an_acquisition_elevation_datum_still_cannot_resolve_a_depth_axis():
    """The spatial assessment's own rule, re-checked from this stage's angle."""
    from schemas.spatial import AcquisitionElevationDatum, CRSProvenance, VerticalDatum

    declared = AcquisitionElevationDatum(
        datum=VerticalDatum(code="WGS84 ellipsoidal",
                            provenance=CRSProvenance.SUPPLIED_BY_CALLER),
        field="SEG-Y bytes 45-48")
    assert not hasattr(declared, "origin_offset")
    assert not hasattr(declared, "velocity")


def test_the_audit_makes_no_claim_about_4tu_readiness(result):
    blob = json.dumps(result)
    assert "READY" not in blob
    assert "UNBLOCKED" not in blob


# ---------------------------------------------------------------------------
# reproducibility
# ---------------------------------------------------------------------------

def test_the_audit_is_deterministic(result):
    again = audit.build()
    strip = lambda d: json.dumps({k: v for k, v in d.items() if k != "generated_utc"},  # noqa: E731
                                 sort_keys=True)
    assert strip(result) == strip(again)
