"""
The synthetic-data interface and the background-removal benchmark (roadmap
M1a). Analytic fixtures only -- no solver, no corpus on disk.
"""
import math

import numpy as np
import pytest

from benchmark.detection import detect_line
from interpretation.anomaly_candidates import find_anomaly_candidates
from preprocessing.spatial_grid import anomaly_grid_from_traces, preprocess_trace_local_anomaly
from preprocessing.trace_processing import process_gpr_traces
from simulation.background_benchmark import ARMS, _filters_then_ring, digitise, score_scene
from simulation.interface import (
    AcquisitionKind, SyntheticLine, to_subterra_records, volume_eligibility,
)
from simulation.scenario import REFERENCE_CYLINDER_2D as S
from simulation.truth import build_truth_manifest

DT = 4e-12
N = 700


def _ricker(t, f):
    z = (math.pi * f * t) ** 2
    return (1 - 2 * z) * np.exp(-z)


def _line(with_target=True, n_samples=N, compact=False) -> SyntheticLine:
    """The reference scene as an analytic line. `compact` keeps the echo on
    only the two traces at the apex: the production ring statistic saturates
    on anything >= 3 traces wide (measured 2026-08-06), so a test of the
    SCORING needs an echo the detector can see at all."""
    truth = build_truth_manifest(S)
    t = np.arange(n_samples) * DT
    f = S.centre_frequency
    direct = 3.0 * _ricker(t - 0.9e-9, f)
    pred = truth["targets"][0]["predicted"]["two_way_time_s"]
    # Seeded noise at 2% of the target amplitude: a noise-free fixture has
    # zero ring variance away from the hyperbola, which the ring statistic
    # (correctly) marks unreliable, so nothing could ever be detected.
    noise = np.random.default_rng(0).normal(0.0, 0.02, (S.n_traces, n_samples))
    apex = truth["targets"][0]["predicted"]["apex_trace"]
    on = [with_target and (not compact or apex - 1 <= i <= apex) for i in range(S.n_traces)]
    traces = np.stack([direct - (o * _ricker(t - p, f)) for o, p in zip(on, pred)]) + noise
    tx, rx = np.asarray(truth["antennas"]["tx_x_m"]), np.asarray(truth["antennas"]["rx_x_m"])
    return SyntheticLine(
        scenario_id="analytic_reference", acquisition_kind=AcquisitionKind.INDEPENDENT_2D_PROFILE,
        traces=traces, background=np.stack([direct] * S.n_traces), dt_s=DT, time_offset_s=0.0,
        midpoint_x_m=(tx + rx) / 2, soil_velocity_m_per_s=S.soil.velocity, truth=truth,
    )


# --- interface ---------------------------------------------------------------

def test_independent_profiles_can_never_be_stacked_into_a_volume():
    ok, reason = volume_eligibility(AcquisitionKind.INDEPENDENT_2D_PROFILE)
    assert not ok and "fabricate" in reason
    assert volume_eligibility(AcquisitionKind.GRIDDED_3D_VOLUME)[0]


def test_records_are_local_unlabelled_and_carry_a_declared_velocity():
    line = _line(n_samples=40)
    records = to_subterra_records(line, "sim_ds")
    assert len(records) == S.n_traces * 40
    r = records[41]  # trace 1, sample 1
    assert r.latitude is None and r.longitude is None
    assert r.position.kind == "local_cartesian" and r.position.x == pytest.approx(line.midpoint_x_m[1])
    assert r.ground_truth.value == "none"
    assert r.metadata["simulated"] is True
    assert r.metadata["velocity_source"] == "declared"
    assert r.depth == pytest.approx(DT * S.soil.velocity / 2)
    assert r.metadata["acquisition_kind"] == "independent_2d_profile"


def test_record_path_and_array_path_find_the_same_candidates():
    """The interface reaches the platform's record-based interpretation
    unchanged: same component count and the same peak cells as the array
    path the benchmark uses."""
    line = digitise(_line(compact=True), 20)
    records = to_subterra_records(line, "sim_ds")
    processed = preprocess_trace_local_anomaly(process_gpr_traces(records))
    via_records = find_anomaly_candidates(processed, source_file=line.scenario_id)
    via_array = detect_line(line.traces, line.scenario_id, 0)
    assert via_array, "fixture must produce candidates for the comparison to mean anything"
    assert len(via_records) == len(via_array)
    record_traces = sorted(tuple(c.evidence.trace_range) for c in via_records)
    array_traces = sorted((min(d.trace_indices), max(d.trace_indices)) for d in via_array)
    assert record_traces == array_traces


# --- background benchmark ------------------------------------------------------

def test_arms_differ_only_in_the_background_step():
    traces = _line().traces
    production = anomaly_grid_from_traces(traces)
    rebuilt = _filters_then_ring(traces - traces.mean(axis=0))
    np.testing.assert_allclose(production, rebuilt, equal_nan=True, atol=1e-9)


def test_native_solver_sampling_hides_even_a_compact_echo():
    """At ~170 samples per period the echo fills the 5/15-sample depth ring,
    so the production detector misses even an echo it sees once digitised."""
    assert 1 / (S.centre_frequency * DT) > 150
    assert not score_scene(_line(compact=True), "target_free_reference_oracle")["targets"][0]["detected"]
    assert score_scene(digitise(_line(compact=True), 20), "target_free_reference_oracle")["targets"][0]["detected"]


def test_a_full_width_hyperbola_saturates_the_production_ring():
    """The whole-scan hyperbola: no arm reaches a detection, oracle included.
    Pinned so the benchmark's reading of low recall cannot be mistaken for a
    background-removal effect."""
    line = digitise(_line(), 20)
    assert all(not score_scene(line, arm)["targets"][0]["detected"] for arm in ARMS)


def test_digitising_keeps_the_time_window_and_sets_the_sampling():
    line = _line()
    d = digitise(line, 20)
    assert d.traces.shape[1] * d.dt_s == pytest.approx(line.traces.shape[1] * line.dt_s)
    assert 1 / (S.centre_frequency * d.dt_s) == pytest.approx(20, rel=0.02)
    assert d.background.shape == d.traces.shape


def test_oracle_arm_finds_the_target_where_it_is():
    result = score_scene(digitise(_line(compact=True), 20), "target_free_reference_oracle")
    (target,) = result["targets"]
    assert target["detected"]
    wavelength = S.soil.velocity / S.centre_frequency
    assert abs(target["lateral_error_m"]) <= wavelength
    assert abs(target["depth_error_wavelengths"]) < 0.5


def test_an_empty_line_gives_the_oracle_nothing_to_detect():
    line = _line(with_target=False)
    truth = dict(line.truth, targets=[])
    line = SyntheticLine(**{**line.__dict__, "truth": truth})
    result = score_scene(line, "target_free_reference_oracle")
    assert result["n_detections"] == 0 and result["targets"] == []


def test_every_arm_runs_and_reports_the_same_fields():
    line = _line()
    keys = {frozenset(score_scene(line, arm)) for arm in ARMS}
    assert len(keys) == 1


# --- detector comparison (candidate detectors; production unchanged) ---------

import dataclasses  # noqa: E402

from benchmark.hyperbola_stack import VELOCITY_GRID, estimate_time_zero, hyperbola_stack  # noqa: E402
from simulation.background_benchmark import score_located  # noqa: E402
from simulation.detector_comparison import (  # noqa: E402
    BACKGROUNDS, CONFIGS, _locate, add_noise, config_id, detector_grid, target_attributes,
)


def _detect(line, det, cfg=None, arm="target_free_reference_oracle", threshold=3.0):
    cfg = CONFIGS[det][0] if cfg is None else cfg
    tz = estimate_time_zero(line.traces, line.dt_s, line.time_offset_s)
    z, v_hat = detector_grid(det, cfg, BACKGROUNDS[arm](line), line, tz, S.centre_frequency)
    return score_located(line, _locate(line, z, v_hat, threshold))


HYP45 = {"cone_half_angle_deg": 45.0, "tolerance_periods": 0.0}


def test_hyperbola_stack_finds_the_full_width_hyperbola_the_ring_cannot():
    line = digitise(_line(), 20)
    assert not _detect(line, "ring")["targets"][0]["detected"]
    (target,) = _detect(line, "hyperbola_stack", HYP45)["targets"]
    assert target["detected"]
    wavelength = S.soil.velocity / S.centre_frequency
    assert abs(target["lateral_error_m"]) <= wavelength / 2
    assert abs(target["depth_error_wavelengths"]) < 0.5
    # A velocity is estimated (localisation), but this fixture is a shallow,
    # 4 cm-offset target (depth 9 cm): the zero-offset point model is biased
    # here by construction, so only the sign of a real estimate is pinned.
    assert target["velocity_error_fraction"] is not None


def test_detectors_never_read_truth():
    """Every detector runs, unchanged, on a line whose truth, soil velocity
    and target-free twin are garbage: none of them is an inference input."""
    line = digitise(_line(), 20)
    blind = dataclasses.replace(line, truth={}, soil_velocity_m_per_s=float("nan"),
                                background=np.full_like(line.background, np.nan))
    tz = estimate_time_zero(line.traces, line.dt_s, line.time_offset_s)
    for det, cfgs in CONFIGS.items():
        for arm in ("mean_trace_subtraction", "no_background_removal"):
            z1, _ = detector_grid(det, cfgs[0], BACKGROUNDS[arm](line), line, tz, S.centre_frequency)
            z2, _ = detector_grid(det, cfgs[0], BACKGROUNDS[arm](blind), blind, tz, S.centre_frequency)
            np.testing.assert_array_equal(z1, z2)


def test_time_zero_comes_from_the_direct_wave_in_the_data():
    line = digitise(_line(), 20)
    tz = estimate_time_zero(line.traces, line.dt_s, line.time_offset_s)
    assert abs(tz - 0.9e-9) <= 2 * line.dt_s  # the fixture's direct-wave delay


def test_hyperbola_stack_ignores_flat_events():
    """Direct wave only, no background removal: a flat event stacks equally
    along hyperbola and flat line, so the one-sided contrast stays quiet."""
    line = digitise(_line(with_target=False), 20)
    line = dataclasses.replace(line, truth=dict(line.truth, targets=[]))
    result = _detect(line, "hyperbola_stack", HYP45, arm="no_background_removal")
    assert result["n_detections"] == 0


def test_hyperbola_stack_orientation_and_velocity_grid():
    line = digitise(_line(), 20)
    z, v_hat = hyperbola_stack(line.traces, line.midpoint_x_m, line.dt_s, line.time_offset_s,
                               estimate_time_zero(line.traces, line.dt_s, line.time_offset_s),
                               S.centre_frequency, cone_half_angle_deg=30.0, tolerance_periods=0.25)
    assert z.shape == v_hat.shape == (line.traces.shape[1], line.traces.shape[0])
    assert set(np.unique(v_hat[np.isfinite(v_hat)])) <= set(VELOCITY_GRID)
    assert np.nanmin(z) >= 0.0


def test_tolerance_needs_the_nominal_frequency():
    line = digitise(_line(), 20)
    with pytest.raises(ValueError):
        hyperbola_stack(line.traces, line.midpoint_x_m, line.dt_s, line.time_offset_s, 1e-9,
                        None, tolerance_periods=0.25)


def test_search_space_is_the_preregistered_one():
    assert [config_id("ring_widened", c) for c in CONFIGS["ring_widened"]][0] == "ring_widened[t5-9,d5-15]"
    assert len(CONFIGS["ring_widened"]) == 6 and len(CONFIGS["hyperbola_stack"]) == 6
    assert CONFIGS["ring"] == [{}]


def test_noise_is_seeded_and_never_touches_the_twin():
    line = digitise(_line(), 20)
    a, b = add_noise(line, 1e-3, 1), add_noise(line, 1e-3, 1)
    np.testing.assert_array_equal(a.traces, b.traces)
    assert not np.array_equal(a.traces, line.traces)
    np.testing.assert_array_equal(a.background, line.background)
    assert not np.array_equal(add_noise(line, 1e-3, 2).traces, a.traces)
    assert add_noise(line, None, 0) is line


def test_target_attributes():
    line = digitise(_line(), 20)
    (a,) = target_attributes(line).values()
    assert a["strength"] in {"weak", "moderate", "strong"} and a["overlapping"] is False
    assert a["label"] == S.targets[0].label
