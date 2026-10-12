"""
Simulation scenarios, truth and the B-scan assessor (roadmap M1a).

None of this needs gprMax: the solver only runs inside docker/gprmax. What
is pinned here is everything around it -- that the rendered input is the
scene we think it is, that the predicted travel times are right geometry,
and that the assessor both passes a correct B-scan and FAILS a wrong one.
The B-scans below are analytic fixtures (Ricker pulses placed at known
times), clearly synthetic, standing in for solver output.
"""
import math
from dataclasses import replace

import numpy as np
import pytest

from simulation.analysis import assess_against_truth, pick_peaks
from simulation.scenario import (
    C0, REFERENCE_CYLINDER_2D, SCENARIOS, CircularTarget, ScenarioError, Soil,
    to_gprmax_input, validate,
)
from simulation.truth import (
    TRUTH_MODEL_VERSION, build_truth_manifest, internal_reflection_time,
    predicted_two_way_times, ricker_peak_delay, specular_path_length,
)

S = REFERENCE_CYLINDER_2D


# --- scenario rendering ---------------------------------------------------

def test_reference_scene_renders_the_published_gprmax_example():
    """Every command of gprMax 4.0.0's examples/gpr/basic/cylinder_Bscan_2D.in,
    modulo the wavelet's identifier name."""
    text = to_gprmax_input(S)
    expected = [
        "#domain_mode: TM",
        "#domain: 0.24 0.21 inf",
        "#dx_dy_dz: 0.002 0.002 0.002",
        "#time_window: 3e-09",
        "#material: 6 0 1 0 half_space",
        "#waveform: ricker 1 1.5e+09 src_wavelet",
        "#hertzian_dipole: z 0.04 0.17 inf src_wavelet",
        "#rx: 0.08 0.17 inf",
        "#src_steps: 0.002 0 0",
        "#rx_steps: 0.002 0 0",
        "#box: 0 0 0 0.24 0.17 inf half_space",
        "#cylinder: 0.12 0.08 0 0.12 0.08 inf 0.01 pec",
    ]
    lines = text.splitlines()
    for line in expected:
        assert line in lines, line


def test_registry_contains_reference_and_ids_match():
    assert SCENARIOS[S.scenario_id] is S


def test_fingerprint_is_stable_and_sensitive():
    assert S.fingerprint() == replace(S).fingerprint()
    assert S.fingerprint() != replace(S, n_traces=59).fingerprint()


@pytest.mark.parametrize("change, message", [
    (dict(targets=(CircularTarget("T1", "pipe", 0.12, 0.165, 0.01),)), "not entirely below"),
    (dict(targets=(CircularTarget("T1", "pipe", 0.12, 0.015, 0.01),)), "absorbing boundary"),
    (dict(n_traces=200), "antenna positions"),
    (dict(surface_y=0.205), "surface"),
    (dict(targets=(CircularTarget("T1", "pipe", 0.10, 0.08, 0.01),
                   CircularTarget("T1", "pipe", 0.14, 0.08, 0.01))), "duplicate"),
])
def test_validate_rejects_scenes_it_cannot_vouch_for(change, message):
    with pytest.raises(ScenarioError, match=message):
        validate(replace(S, **change))
    with pytest.raises(ScenarioError):
        to_gprmax_input(replace(S, **change))


# --- truth -----------------------------------------------------------------

def test_soil_velocity_is_c_over_root_permittivity():
    assert S.soil.velocity == pytest.approx(C0 / math.sqrt(6.0))


def test_symmetric_specular_point_is_the_top_of_the_circle():
    t = S.targets[0]
    half_offset = 0.02
    tx, rx = (t.centre_x - half_offset, S.surface_y), (t.centre_x + half_offset, S.surface_y)
    depth_to_top = S.surface_y - (t.centre_y + t.radius)
    expected = 2 * math.hypot(half_offset, depth_to_top)
    assert specular_path_length(tx, rx, t) == pytest.approx(expected, abs=1e-6)


def test_predicted_times_form_a_hyperbola_with_apex_over_the_target():
    times = predicted_two_way_times(S, S.targets[0])
    apex = int(np.argmin(times))
    midpoint = (S.tx_x(apex) + S.rx_x(apex)) / 2
    assert midpoint == pytest.approx(S.targets[0].centre_x, abs=S.step)
    assert np.all(np.diff(times[: apex + 1]) <= 1e-15)
    assert np.all(np.diff(times[apex:]) >= -1e-15)


def test_truth_manifest_separates_geometry_from_prediction():
    truth = build_truth_manifest(S)
    assert truth["truth_kind"] == "simulated_exact_by_construction"
    assert truth["frame"]["kind"] == "model_local_cartesian"
    t = truth["targets"][0]
    assert t["geometry"]["depth_to_top_m"] == pytest.approx(0.080)
    assert t["predicted"]["model"] == "straight_ray_single_medium_specular"
    assert len(t["predicted"]["two_way_time_s"]) == S.n_traces
    assert truth["wavelet"]["peak_delay_s"] == pytest.approx(math.sqrt(2) / 1.5e9)
    assert truth["truth_model_version"] == TRUTH_MODEL_VERSION
    # A PEC target has one event, and it is the v1 prediction verbatim.
    assert set(t["predicted_events"]) == {"top"}
    assert t["predicted_events"]["top"]["two_way_time_s"] == t["predicted"]["two_way_time_s"]


# --- internal (bottom) reflection of a dielectric target --------------------

ROCK = Soil(name="rock_T1", relative_permittivity=12.0, conductivity=0.001)
S_ROCK = replace(S, targets=(replace(S.targets[0], label="rock", material="rock_T1"),),
                 materials=(ROCK,))


def test_zero_offset_internal_echo_is_top_plus_the_diameter_twice():
    """Vertically above the centre, the far-wall echo is the top echo plus a
    round trip through the full diameter at the inside velocity."""
    t = S_ROCK.targets[0]
    above = (t.centre_x, S.surface_y)
    v_out, v_in = S.soil.velocity, ROCK.velocity
    expected = 2 * (S.surface_y - t.centre_y - t.radius) / v_out + 4 * t.radius / v_in
    assert internal_reflection_time(above, above, t, v_out, v_in) == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("eps_in, half", [(12.0, 0.01), (1.0, 0.04)])  # slower inside (rock), faster (void)
def test_offset_internal_echo_matches_fermat_on_the_symmetric_path(eps_in, half):
    """Antennas symmetric about the centre: the path reflects at the very
    bottom of the circle, so it is twice the least-time path from tx to that
    point through the circle wall -- an independent brute-force check of the
    shooting, Snell and mirror steps together."""
    t = S_ROCK.targets[0]
    tx, rx = (t.centre_x - half, S.surface_y), (t.centre_x + half, S.surface_y)
    v_out, v_in = S.soil.velocity, C0 / math.sqrt(eps_in)
    theta = np.linspace(0.0, np.pi, 2_000_001)[1:-1]
    px, py = t.centre_x + t.radius * np.cos(theta), t.centre_y + t.radius * np.sin(theta)
    bottom = (t.centre_x, t.centre_y - t.radius)
    one_way = (np.hypot(px - tx[0], py - tx[1]) / v_out
               + np.hypot(px - bottom[0], py - bottom[1]) / v_in)
    k = int(one_way.argmin())
    assert 0 < k < theta.size - 1, "an endpoint minimum is not a ray; pick another geometry"
    assert internal_reflection_time(tx, rx, t, v_out, v_in) == pytest.approx(
        2 * one_way.min(), rel=1e-7)


def test_no_internal_ray_reaches_a_receiver_outside_the_exit_fan():
    """A slow rock is a converging lens: with antennas 8 cm apart over this
    1 cm-radius rock, every once-reflected exit ray lands within 3 cm of the
    centre, so the receiver at +4 cm has no internal event (None, not a
    made-up time)."""
    t = S_ROCK.targets[0]
    tx, rx = (t.centre_x - 0.04, S.surface_y), (t.centre_x + 0.04, S.surface_y)
    assert internal_reflection_time(tx, rx, t, S.soil.velocity, ROCK.velocity) is None


def test_dielectric_targets_predict_both_events_and_pec_only_the_top():
    t = build_truth_manifest(S_ROCK)["targets"][0]
    top = np.asarray(t["predicted_events"]["top"]["two_way_time_s"])
    internal = np.array([np.nan if x is None else x for x in t["predicted_events"]["internal"]["two_way_time_s"]])
    assert np.all(internal[np.isfinite(internal)] > top[np.isfinite(internal)])
    assert abs(t["predicted_events"]["internal"]["apex_trace"] - t["predicted"]["apex_trace"]) <= 1
    void = replace(S, targets=(replace(S.targets[0], label="void", material="free_space"),))
    assert "internal" in build_truth_manifest(void)["targets"][0]["predicted_events"]


# --- assessor ----------------------------------------------------------------

DT = 2e-12
N_SAMPLES = 1500


def _ricker(t, f):
    z = (math.pi * f * t) ** 2
    return (1 - 2 * z) * np.exp(-z)


def _analytic_bscan(arrivals, amps):
    """Ricker pulses peaking at the given times, plus an identical direct wave
    on every trace that background removal must take away."""
    t = np.arange(N_SAMPLES) * DT
    f = S.centre_frequency
    direct = 3.0 * _ricker(t - 1.2e-9, f)
    cols = [direct - a * _ricker(t - arr, f) for arr, a in zip(arrivals, amps)]
    return np.stack(cols, axis=1)


def _amps(truth):
    apex = truth["targets"][0]["predicted"]["apex_trace"]
    return [1.0 / (1 + 0.05 * abs(i - apex)) for i in range(S.n_traces)]


def test_assessor_passes_a_bscan_that_matches_its_truth():
    truth = build_truth_manifest(S)
    predicted = truth["targets"][0]["predicted"]["two_way_time_s"]
    verdict = assess_against_truth(_analytic_bscan(predicted, _amps(truth)), DT, 0.0, truth)
    assert verdict["pass"], verdict["checks"]
    # Not zero: mean-trace removal subtracts the hyperbola's own average and
    # pulls the apex pick late. Measured on this fixture: -0.3 ps without
    # background removal, +15.7 ps with it, ~5% of the tolerance. Bounded
    # here so a picker change that worsens it is caught.
    assert abs(verdict["checks"]["apex_time"]["error_s"]) < 0.1 * verdict["checks"]["apex_time"]["tolerance_s"]


def test_assessor_fails_a_bscan_shifted_by_one_period():
    truth = build_truth_manifest(S)
    shifted = [p + 1 / S.centre_frequency for p in truth["targets"][0]["predicted"]["two_way_time_s"]]
    verdict = assess_against_truth(_analytic_bscan(shifted, _amps(truth)), DT, 0.0, truth)
    assert not verdict["pass"]
    assert not verdict["checks"]["apex_time"]["pass"]


def test_assessor_fails_when_the_apex_is_in_the_wrong_place():
    """A hyperbola displaced 8 traces sideways: its kinematic vertex is wrong."""
    truth = build_truth_manifest(S)
    predicted = np.asarray(truth["targets"][0]["predicted"]["two_way_time_s"])
    shifted = np.roll(predicted, 8)
    shifted[:8] = predicted[0]
    verdict = assess_against_truth(_analytic_bscan(shifted, _amps(truth)), DT, 0.0, truth)
    assert not verdict["checks"]["apex_trace"]["pass"]


def test_apex_is_kinematic_not_the_strongest_return():
    """The gen_s0_00004 finding: an interface antenna's two oblique lobes make
    the strongest returns land far from the apex. Correct times must still
    pass, and the v1 amplitude rule is kept only as a failing diagnostic."""
    truth = build_truth_manifest(S)
    predicted = truth["targets"][0]["predicted"]["two_way_time_s"]
    apex = truth["targets"][0]["predicted"]["apex_trace"]
    lobes = [0.8 + 0.2 * math.exp(-((abs(i - apex) - 15) / 4) ** 2) for i in range(S.n_traces)]
    bscan = _analytic_bscan(predicted, lobes)
    background = _analytic_bscan([0.0] * S.n_traces, [0.0] * S.n_traces)
    verdict = assess_against_truth(bscan, DT, 0.0, truth, background)
    assert verdict["pass"], verdict["checks"]
    assert verdict["checks"]["apex_trace"]["method"] == "kinematic_vertex_v2"
    assert not verdict["diagnostics"]["amplitude_apex_v1_would_pass"]


def test_an_unrecovered_target_is_a_failed_verdict_not_a_crash():
    """Picks on a downward-opening cap -- no hyperbola -- fail the apex check
    with a reason instead of raising."""
    truth = build_truth_manifest(S)
    cap = [2.4e-9 - 0.3e-9 * ((i - 30) / 30) ** 2 for i in range(S.n_traces)]
    verdict = assess_against_truth(_analytic_bscan(cap, [1.0] * S.n_traces), DT, 0.0, truth)
    check = verdict["checks"]["apex_trace"]
    assert not verdict["pass"] and not check["pass"]
    assert check["measured"] is None and "hyperbola" in check["failure"]


def test_picks_on_the_internal_echo_pass_v3_and_are_recorded_as_failing_v2():
    """The gen_s0_00013 case, analytically: the far-wall echo is the stronger
    one. v3 scores it; the top-only v2 verdict stays on record as a fail."""
    truth = build_truth_manifest(S_ROCK)
    internal = truth["targets"][0]["predicted_events"]["internal"]["two_way_time_s"]
    top = truth["targets"][0]["predicted"]["two_way_time_s"]
    bscan = _analytic_bscan(internal, [1.0] * S.n_traces) + _analytic_bscan(top, [0.55] * S.n_traces) \
        - _analytic_bscan([0.0] * S.n_traces, [0.0] * S.n_traces)
    background = _analytic_bscan([0.0] * S.n_traces, [0.0] * S.n_traces)
    verdict = assess_against_truth(bscan, DT, 0.0, truth, background)
    assert verdict["scored_event"] == "internal"
    assert verdict["pass"], verdict["checks"]
    assert verdict["diagnostics"]["top_only_v2_rule"]["pass"] is False


def test_picks_matching_neither_event_still_fail():
    truth = build_truth_manifest(S_ROCK)
    top = truth["targets"][0]["predicted"]["two_way_time_s"]
    late = [x + 4 / S.centre_frequency for x in top]  # beyond the internal echo too
    background = _analytic_bscan([0.0] * S.n_traces, [0.0] * S.n_traces)
    verdict = assess_against_truth(_analytic_bscan(late, [1.0] * S.n_traces), DT, 0.0, truth, background)
    assert not verdict["pass"]


def test_assessor_still_reads_truth_written_by_model_v1():
    truth = build_truth_manifest(S)
    for t in truth["targets"]:
        del t["predicted_events"]
    bscan = _analytic_bscan(truth["targets"][0]["predicted"]["two_way_time_s"], _amps(truth))
    verdict = assess_against_truth(bscan, DT, 0.0, truth)
    assert verdict["pass"] and verdict["scored_event"] == "top"


def test_time_offset_is_applied_to_picks():
    truth = build_truth_manifest(S)
    bscan = _analytic_bscan(truth["targets"][0]["predicted"]["two_way_time_s"], _amps(truth))
    t0, _ = pick_peaks(bscan, DT, 0.0)
    t1, _ = pick_peaks(bscan, DT, 5e-10)
    assert np.allclose(t1 - t0, 5e-10)


def test_assessor_refuses_mismatched_trace_count():
    truth = build_truth_manifest(S)
    with pytest.raises(ValueError, match="traces"):
        assess_against_truth(np.zeros((10, 3)), DT, 0.0, truth)


def test_target_free_reference_removes_the_mean_trace_ghost():
    """The reference-scene failure, reproduced analytically: a hyperbola that
    spans the whole scan. Subtracting the mean trace leaves a ghost that wins
    on the flanks; subtracting the exact target-free twin does not."""
    truth = build_truth_manifest(S)
    predicted = truth["targets"][0]["predicted"]["two_way_time_s"]
    amps = [1.0 / (1 + 0.15 * abs(i - truth["targets"][0]["predicted"]["apex_trace"])) for i in range(S.n_traces)]
    bscan = _analytic_bscan(predicted, amps)
    background = _analytic_bscan([0.0] * S.n_traces, [0.0] * S.n_traces)  # direct wave only
    verdict = assess_against_truth(bscan, DT, 0.0, truth, background)
    assert verdict["background_method"] == "target_free_reference"
    assert verdict["pass"], verdict["checks"]
    assert verdict["checks"]["hyperbola_shape"]["rms_error_s"] < 2 * DT


def test_background_must_match_the_bscan_shape():
    truth = build_truth_manifest(S)
    with pytest.raises(ValueError, match="background shape"):
        assess_against_truth(np.zeros((N_SAMPLES, S.n_traces)), DT, 0.0, truth,
                             np.zeros((N_SAMPLES, 3)))


# --- rescore -----------------------------------------------------------------

def _stored_artifact(tmp_path, validation):
    import json
    from simulation.run_gprmax import _sha256
    out = tmp_path / S.scenario_id
    out.mkdir()
    truth = build_truth_manifest(S)
    bscan = _analytic_bscan(truth["targets"][0]["predicted"]["two_way_time_s"], _amps(truth))
    background = _analytic_bscan([0.0] * S.n_traces, [0.0] * S.n_traces)
    np.savez_compressed(out / "bscan.npz", data=bscan, dt=DT, time_offset=0.0, background=background)
    (out / "truth.json").write_text(json.dumps(truth))
    (out / "validation.json").write_text(json.dumps(validation))
    (out / "manifest.json").write_text(json.dumps({
        "scenario": S.to_dict(), "scenario_fingerprint": S.fingerprint(),
        "files": {"validation.json": _sha256(out / "validation.json")},
    }))
    return out


def test_rescore_archives_the_old_verdict_and_rescores(tmp_path):
    import json
    from simulation.analysis import ANALYSIS_VERSION
    from simulation.run_gprmax import rescore
    out = _stored_artifact(tmp_path, {"pass": False, "note": "v1 verdict"})
    manifest = rescore(out)
    assert manifest["analysis_version"] == ANALYSIS_VERSION
    assert manifest["validation_pass"] is True
    assert manifest["superseded_validations"] == [{"analysis_version": 1, "pass": False}]
    assert json.loads((out / "validation_history" / "validation_v1.json").read_text())["note"] == "v1 verdict"


def test_rescore_rebuilds_truth_from_an_older_model_and_archives_it(tmp_path):
    import json
    from simulation.run_gprmax import _sha256, rescore
    out = _stored_artifact(tmp_path, {"pass": True, "analysis_version": 2})
    old = json.loads((out / "truth.json").read_text())
    del old["truth_model_version"]
    for t in old["targets"]:
        del t["predicted_events"]
    (out / "truth.json").write_text(json.dumps(old))
    manifest = rescore(out)
    assert manifest["truth_model_version"] == TRUTH_MODEL_VERSION
    assert manifest["superseded_truth"] == [{"truth_model_version": 1}]
    assert "predicted_events" not in json.loads((out / "truth_history" / "truth_v1.json").read_text())["targets"][0]
    assert manifest["files"]["truth.json"] == _sha256(out / "truth.json")


def test_rescore_refuses_a_stale_scene_without_touching_it(tmp_path):
    import json
    from simulation.run_gprmax import rescore
    out = _stored_artifact(tmp_path, {"pass": False})
    m = json.loads((out / "manifest.json").read_text())
    m["scenario_fingerprint"] = "0" * 64
    (out / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(RuntimeError, match="fingerprint"):
        rescore(out)
    assert not (out / "validation_history").exists()
