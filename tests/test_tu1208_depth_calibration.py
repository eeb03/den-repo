"""
The TU1208 time-zero/velocity experiment reaches a verdict without fabricating one.

WHAT THIS EXPERIMENT COULD HAVE GOT WRONG, and what each group of tests holds:

    LEAKAGE      The failure the stage exists to prevent. A surveyed depth may
                 not be used to choose the reflector that is then said to
                 confirm it. Since no reflector is chosen at all, the test is
                 that no arrival time exists anywhere in the pipeline, and that
                 the association decision reads only published geometry.

    FABRICATION  With zero observations, a fitted t0 or velocity would be a
                 number with nothing behind it. The artifact must carry nulls
                 and a stated reason, not a plausible default.

    MATH         The identifiability result is the stage's main finding, so the
                 closed-form covariance is checked against a direct linear
                 solve rather than trusted.

    FIREWALL     Nothing here may touch 4TU.
"""
import json
import math
from pathlib import Path

import pytest

from benchmark import tu1208_truth as truth
from scripts import tu1208_depth_calibration as experiment

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = REPO_ROOT / truth.ARCHIVE_ROOT


@pytest.fixture(scope="module")
def result():
    return experiment.build(ARCHIVE)


# ---------------------------------------------------------------------------
# leakage: a depth never chooses its own evidence
# ---------------------------------------------------------------------------

def _executable_source(path: Path) -> str:
    """
    The module's code with docstrings and comments removed.

    Needed because this file's prose is full of the words the tests forbid --
    it explains at length that nothing picks a reflector. Searching the raw
    text would flag the explanation and miss a real call.
    """
    import ast
    import io
    import tokenize

    text = path.read_text()
    tree = ast.parse(text)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    kept = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and token.string.strip("\"'") in docstrings:
            continue
        kept.append(token.string)
    return " ".join(kept)


def test_no_arrival_time_is_picked_anywhere():
    """
    The moment a reflector is picked, the only available basis for picking it
    would be the surveyed depth. So nothing picks -- checked against the CODE,
    not the prose that promises it.
    """
    code = _executable_source(REPO_ROOT / "scripts/tu1208_depth_calibration.py").lower()
    for banned in ("argmax", "argmin", "find_peaks", "envelope", "hilbert",
                   "correlate", "numpy", "scipy", "signal"):
        assert banned not in code, f"{banned!r} suggests a reflector was chosen"


def test_the_association_decision_reads_only_published_geometry(result):
    for entry in result["association"]:
        assert "published acquisition geometry only" in entry["basis"]
        assert "no reflector was inspected" in entry["basis"]


def test_every_target_is_unresolved_and_says_what_is_missing(result):
    attempts = result["association"]
    assert len(attempts) == 36
    assert all(a["status"] == "UNRESOLVED" for a in attempts)
    for entry in attempts:
        assert entry["missing"], "an unresolved target must name what it lacks"
    missing = {m for a in attempts for m in a["missing"]}
    assert missing == {
        "the target's transverse offset from a named site reference",
        "the profile's along-line origin in that same reference",
    }


def test_the_surveyed_depths_are_carried_but_never_consumed(result):
    """
    The depths travel in the artifact so a reader can see what was at stake.
    They must not have entered any computation, and with zero observations
    there is no computation for them to enter.
    """
    depths = {round(a["surveyed_depth_m"], 3) for a in result["association"]}
    assert depths == {-0.80, -1.20, -1.83, -1.70, -2.40, -0.90, -1.50, -2.10,
                      -1.15, -1.56, -2.20}
    assert result["verdict"]["fitted_t0_ns"] is None
    assert result["verdict"]["fitted_velocity_m_per_ns"] is None


# ---------------------------------------------------------------------------
# fabrication: no number without a measurement
# ---------------------------------------------------------------------------

def test_the_verdict_is_blocked_and_reports_no_parameters(result):
    v = result["verdict"]
    assert v["status"] == experiment.BLOCKED
    assert v["gate_1_association"]["status"] == experiment.BLOCKED
    assert v["gate_1_association"]["n_resolved"] == 0
    assert v["fitted_t0_ns"] is None
    assert v["fitted_velocity_m_per_ns"] is None
    assert v["held_out_depth_error_m"] is None
    assert "no measurement behind it" in v["why_no_numbers"]


def test_no_held_out_error_is_invented_from_zero_observations(result):
    """
    A held-out split of an empty set is not a small number, it is undefined.
    Reporting 0.0 m would read as a perfect prediction.
    """
    assert result["verdict"]["held_out_depth_error_m"] is None
    assert "held_out_predictions" not in result


def test_no_velocity_constant_is_smuggled_in_as_a_default():
    """
    The one velocity in the module is a scale factor for expressing a slope
    standard error as a fraction, and it is named and documented as such.
    """
    source = (REPO_ROOT / "scripts/tu1208_depth_calibration.py").read_text()
    assert source.count("0.1") >= 1
    assert "_REFERENCE_V_FOR_SCALING" in source
    assert "not fitted, not declared" in source
    for banned in ("0.033", "velocity_m_per_ns =", "epsr /", "sqrt(epsr)"):
        assert banned not in source


def test_the_modelled_permittivities_are_not_turned_into_a_velocity():
    """
    Converting the authors' FDTD permittivities into velocities would produce a
    number that looks measured and is not. c/sqrt(eps) appears nowhere.
    """
    source = (REPO_ROOT / "scripts/tu1208_depth_calibration.py").read_text()
    assert "299792458" not in source
    assert "0.2998" not in source
    assert "permittivity" not in source.lower() or "modelled_permittivit" not in source


def test_no_synthetic_radargram_or_target_is_created():
    source = (REPO_ROOT / "scripts/tu1208_depth_calibration.py").read_text()
    for banned in ("random", "normal(", "linspace", "synthetic", "simulate", "np.zeros"):
        assert banned not in source.lower()


# ---------------------------------------------------------------------------
# the model is stated, and stays stated
# ---------------------------------------------------------------------------

def test_the_model_is_recorded_verbatim_and_t0_is_not_the_ground(result):
    assert result["model"] == "t_measured = t0 + 2 * d / v"
    assert "not the ground-surface time" in result["model_note"]
    assert "assumes the ground surface is time zero" in result["model_note"]


# ---------------------------------------------------------------------------
# identifiability: the stage's actual finding
# ---------------------------------------------------------------------------

def test_the_closed_form_covariance_matches_a_direct_solve():
    """
    The confounding number is the headline, so the algebra is checked rather
    than trusted: build (X'X)^-1 by hand for a known design and compare.
    """
    depths = [0.80, 1.20, 1.83]
    lev = experiment.leverage("check", depths)

    x = [2.0 * d for d in depths]
    n = len(x)
    sx, sxx = sum(x), sum(v * v for v in x)
    det = n * sxx - sx * sx
    # (X'X)^-1 = [[sxx, -sx], [-sx, n]] / det
    var_b0, var_b1, cov = sxx / det, n / det, -sx / det
    expected = cov / math.sqrt(var_b0 * var_b1)

    assert lev.t0_slope_correlation == pytest.approx(expected, abs=1e-12)
    assert lev.t0_se_ns_per_ns_noise == pytest.approx(math.sqrt(var_b0), rel=1e-12)


def test_every_pipe_grouping_is_confounded(result):
    """
    THE FINDING. All four media have their shallowest target at 0.80 m or
    deeper, so no reflector anchors t0 near d=0 and a shift in t0 is absorbed
    by a change in velocity.
    """
    by_group = {lv["group"]: lv for lv in result["leverage"]}
    for group in ("silt", "limestone", "gneiss_14_20", "gneiss_0_20"):
        lev = by_group[group]
        assert lev["n_depths"] == 3
        assert abs(lev["t0_slope_correlation"]) > 0.94
        assert lev["identifiable"] is False
        assert "confounded" in lev["verdict"]


def test_pooling_reduces_noise_but_not_confounding(result):
    """
    A real and slightly counter-intuitive result worth pinning: more targets
    shrink the standard errors and leave the coupling where it was, because
    the coupling is a shape property of the depth set, not a count.
    """
    by_group = {lv["group"]: lv for lv in result["leverage"]}
    silt, pooled = by_group["silt"], by_group["all-pipe-layers-pooled"]

    assert pooled["n_depths"] > silt["n_depths"]
    assert pooled["t0_se_ns_per_ns_noise"] < silt["t0_se_ns_per_ns_noise"]
    assert abs(pooled["t0_slope_correlation"]) > 0.94


def test_the_widest_grouping_is_the_only_marginally_separable_one(result):
    """
    The multilayer interfaces span 3.10 m and still only reach -0.89 -- and
    those depths are DERIVED and cross five materials, so a single velocity is
    wrong there by construction. Marginal separability is not usability.
    """
    by_group = {lv["group"]: lv for lv in result["leverage"]}
    ml = by_group["multilayer-interfaces-derived"]
    assert ml["depth_span_m"] == pytest.approx(3.10, abs=0.01)
    assert abs(ml["t0_slope_correlation"]) < 0.9
    separable = [lv for lv in result["leverage"] if lv["identifiable"]]
    assert [lv["group"] for lv in separable] == ["multilayer-interfaces-derived"]


def test_a_single_depth_cannot_determine_two_parameters():
    lev = experiment.leverage("degenerate", [-1.20])
    assert lev.identifiable is False
    assert "fewer than two depths" in lev.verdict


def test_repeated_depths_leave_the_slope_undetermined():
    lev = experiment.leverage("degenerate", [-1.20, -1.20, -1.20])
    assert lev.identifiable is False
    assert "undetermined" in lev.verdict


# ---------------------------------------------------------------------------
# instrument evidence
# ---------------------------------------------------------------------------

def test_the_header_time_zero_is_not_usable_across_the_corpus(result):
    """
    The obvious shortcut. GSSI's rhf_position holds ~99 ns against 60-85 ns
    windows on the 1999 profiles: a delay longer than the recording window is
    not a delay.
    """
    evidence = result["instrument_time_evidence"]
    assert evidence["n_files"] == 67
    assert evidence["n_with_usable_header_time_zero"] <= 1
    reasons = {f["header_time_zero_reason"] for f in evidence["files"]}
    assert any("against a" in r and "window" in r for r in reasons)
    assert any("carries no time-zero field" in r for r in reasons)


def test_an_along_track_scale_does_not_rescue_the_association(result):
    """
    45 of 67 files do carry a trace spacing. It still does not place a target,
    because the ORIGIN of the along-track axis is unpublished for all 67.
    """
    evidence = result["instrument_time_evidence"]
    assert evidence["n_with_along_track_scale"] > 0
    assert all(a["status"] == "UNRESOLVED" for a in result["association"])


# ---------------------------------------------------------------------------
# firewall
# ---------------------------------------------------------------------------

def test_the_experiment_writes_no_declaration(result):
    assert result["declarations_written"] == []
    assert result["fourtu_state_touched"] is False


def test_the_experiment_cannot_reach_declaration_or_readiness_machinery():
    source = (REPO_ROOT / "scripts/tu1208_depth_calibration.py").read_text()
    for banned in ("api.spatial", "apply_declaration", "record_declaration",
                   "DeclarationKind", "save_frames", "save_records",
                   "readiness", "VerticalDatum", "DepthOriginOffset"):
        assert banned not in source, f"{banned!r} would let the experiment mutate state"


def test_the_experiment_reads_no_4tu_data_and_imports_no_4tu_module():
    """
    The prose says it touches no 4TU state; this checks the code. A 4TU import
    or path is the only way that promise could quietly stop being true.
    """
    code = _executable_source(REPO_ROOT / "scripts/tu1208_depth_calibration.py").lower()
    for banned in ("evidence.fourtu_author", "fourtu_truth", "fourtu_scoring",
                   "datasets/raw/4tu", "96303227"):
        assert banned not in code, f"{banned!r} reaches 4TU"


def test_no_tu1208_parameter_can_be_copied_into_4tu(result):
    """
    There is nothing to copy: the experiment produced no parameter. This is the
    firewall holding by construction rather than by discipline.
    """
    assert result["verdict"]["fitted_t0_ns"] is None
    assert result["verdict"]["fitted_velocity_m_per_ns"] is None


def test_the_4tu_author_evidence_still_reports_its_blockers():
    """
    4TU's depth origin, velocity and subsurface elevation were blocked before
    this stage and must be blocked after it.
    """
    from evidence.fourtu_author import REASSESSMENT

    by_dimension = {d.dimension: d for d in REASSESSMENT}
    for dimension in ("depth-axis origin relative to ground",
                      "propagation velocity",
                      "vertical registration of subsurface points",
                      "absolute elevation of a subsurface reflector"):
        assert by_dimension[dimension].after.startswith("BLOCKED"), dimension


# ---------------------------------------------------------------------------
# reproducibility
# ---------------------------------------------------------------------------

def test_the_result_is_deterministic_and_serialisable(result):
    again = experiment.build(ARCHIVE)
    stable = json.dumps({k: v for k, v in result.items() if k != "generated_utc"},
                        sort_keys=True)
    stable_again = json.dumps({k: v for k, v in again.items() if k != "generated_utc"},
                              sort_keys=True)
    assert stable == stable_again
    assert json.loads(json.dumps(result))


def test_the_result_pins_the_truth_version_it_was_run_against(result):
    """
    A verdict about TU1208 is only interpretable alongside the transcription it
    used. If Stage 23's truth changes, this artifact is stale and says so.
    """
    assert result["truth_version"] == truth.truth_version()
    assert result["truth_version"].startswith("tu1208-")
