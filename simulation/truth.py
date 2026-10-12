"""
Exact truth for a simulated scene, plus the reflection times it predicts.

Two kinds of statement live here and are kept apart in the manifest:

* GEOMETRY -- target positions, radii, depths. True by construction: the
  solver was told to put the object exactly there.
* PREDICTED TRAVEL TIMES -- what straight-ray, single-medium kinematics says
  the reflection apex should be. This is a MODEL of the simulation, not part
  of it, and `analysis.py` measures how well the solver agrees with it.
  Agreement validates the pipeline; it does not upgrade the prediction into
  truth.
"""
from __future__ import annotations

import math

import numpy as np

from simulation.scenario import CircularTarget, Scenario2D, validate

# Angular samples on the target circle when locating the specular point.
# 0.05 degree spacing: for the radii simulated here the residual path error is
# far below one solver cell.
_ANGLE_SAMPLES = 7200


def ricker_peak_delay(centre_frequency: float) -> float:
    """gprMax's Ricker wavelet peaks at chi = sqrt(2) / f after t = 0."""
    return math.sqrt(2.0) / centre_frequency


def specular_path_length(
    tx: tuple[float, float], rx: tuple[float, float], target: CircularTarget
) -> float:
    """Shortest tx -> circle surface -> rx path (Fermat: the specular ray)."""
    theta = np.linspace(0.0, 2.0 * np.pi, _ANGLE_SAMPLES, endpoint=False)
    px = target.centre_x + target.radius * np.cos(theta)
    py = target.centre_y + target.radius * np.sin(theta)
    path = np.hypot(px - tx[0], py - tx[1]) + np.hypot(px - rx[0], py - rx[1])
    return float(path.min())


def predicted_two_way_times(s: Scenario2D, target: CircularTarget) -> np.ndarray:
    """Predicted reflection peak time (s) for every trace, wavelet delay included."""
    v = s.soil.velocity
    delay = ricker_peak_delay(s.centre_frequency)
    times = [
        specular_path_length((s.tx_x(i), s.surface_y), (s.rx_x(i), s.surface_y), target) / v + delay
        for i in range(s.n_traces)
    ]
    return np.asarray(times)


def build_truth_manifest(s: Scenario2D) -> dict:
    validate(s)
    targets = []
    for t in s.targets:
        times = predicted_two_way_times(s, t)
        apex = int(np.argmin(times))
        targets.append({
            "target_id": t.target_id,
            "label": t.label,
            "material": t.material,
            "geometry": {
                "shape": "circular_cross_section",
                "centre_x_m": t.centre_x,
                "centre_y_m": t.centre_y,
                "radius_m": t.radius,
                "depth_to_top_m": s.surface_y - (t.centre_y + t.radius),
                "depth_to_centre_m": s.surface_y - t.centre_y,
            },
            "predicted": {
                "model": "straight_ray_single_medium_specular",
                "two_way_time_s": times.tolist(),
                "apex_trace": apex,
                "apex_time_s": float(times[apex]),
            },
        })
    return {
        "scenario_id": s.scenario_id,
        "scenario_fingerprint": s.fingerprint(),
        "truth_kind": "simulated_exact_by_construction",
        "frame": {
            "kind": "model_local_cartesian",
            "units": "m",
            "x": "along-survey, domain origin",
            "y": "up, domain origin; ground surface at surface_y",
            "surface_y_m": s.surface_y,
            "note": "Not a geographic frame. No CRS applies.",
        },
        "medium": {
            "soil": s.soil.name,
            "relative_permittivity": s.soil.relative_permittivity,
            "conductivity_s_per_m": s.soil.conductivity,
            "velocity_m_per_s": s.soil.velocity,
        },
        "wavelet": {
            "type": "ricker",
            "centre_frequency_hz": s.centre_frequency,
            "peak_delay_s": ricker_peak_delay(s.centre_frequency),
        },
        "antennas": {
            "tx_x_m": [s.tx_x(i) for i in range(s.n_traces)],
            "rx_x_m": [s.rx_x(i) for i in range(s.n_traces)],
            "height_above_surface_m": 0.0,
        },
        "targets": targets,
    }
