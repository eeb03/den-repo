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
