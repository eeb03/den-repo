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

PREDICTED EVENTS, and why a dielectric target has two (truth model v2).

* "top" -- the specular reflection off the outside of the circle. The only
  event a PEC target has, and the only one truth model v1 predicted.
* "internal" -- added after gen_s0_00013: energy that refracts INTO a
  dielectric target (rock, void), reflects once off its far wall and
  refracts back out. Its apex is the "bottom of the rock" echo. It is
  traced exactly through the circle (Snell at entry and exit, mirror at the
  far wall), not estimated as 4 r / v_inside, because the antennas are
  offset and the circle is a lens. Rays that totally internally reflect at
  entry or exit carry no internal event and are excluded.

Neither event says which is STRONGER; that depends on the contrast and the
antenna pattern, and on gen_s0_00013 the internal one won (1.00 vs 0.55).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq

from simulation.scenario import C0, CircularTarget, Scenario2D, validate

# Bumped whenever a predicted event is added or changed; stored truth from an
# older model is rebuilt on rescore, the old file archived.
TRUTH_MODEL_VERSION = 2

# Angular samples on the target circle when locating the specular point.
# 0.05 degree spacing: for the radii simulated here the residual path error is
# far below one solver cell.
_ANGLE_SAMPLES = 7200

# Take-off angles sampled across the circle's angular width when shooting
# internal-reflection rays; each bracketed root is then refined exactly.
_SHOOT_SAMPLES = 4001

# Materials a ray cannot enter. Every other target material is dielectric.
_OPAQUE_MATERIALS = frozenset({"pec"})


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


def target_velocity(s: Scenario2D, target: CircularTarget) -> float | None:
    """Velocity inside the target, or None for a target a ray cannot enter."""
    if target.material in _OPAQUE_MATERIALS:
        return None
    if target.material == "free_space":
        return C0
    return {m.name: m for m in s.materials}[target.material].velocity


def _refract(d: np.ndarray, n: np.ndarray, eta: float) -> np.ndarray:
    """Snell, vector form, row-wise. n is the unit normal facing the incident
    ray and eta = v_transmitted / v_incident. NaN rows on total internal
    reflection."""
    cos_i = -np.sum(n * d, axis=1, keepdims=True)
    k = 1.0 - eta ** 2 * (1.0 - cos_i ** 2)
    with np.errstate(invalid="ignore"):
        out = eta * d + (eta * cos_i - np.sqrt(k)) * n
    out[(k < 0.0)[:, 0]] = np.nan
    return out


def _far_hit(p: np.ndarray, d: np.ndarray, c: np.ndarray) -> np.ndarray:
    """From points ON the circle, travelling inward along d: the other side."""
    return p + d * (-2.0 * np.sum((p - c) * d, axis=1, keepdims=True))


def _shoot_internal(phi: np.ndarray, tx: np.ndarray, surface_y: float, target: CircularTarget,
                    v_out: float, v_in: float) -> tuple[np.ndarray, np.ndarray]:
    """Trace rays leaving tx at angles phi from straight down (positive
    towards +x): enter, reflect once off the far wall, leave. Returns
    (landing x on the surface, travel time), NaN for a ray that cannot."""
    phi = np.atleast_1d(np.asarray(phi, dtype=float))
    c = np.array([target.centre_x, target.centre_y])
    r = target.radius
    d = np.stack([np.sin(phi), -np.cos(phi)], axis=1)
    f = tx - c
    b = d @ f
    disc = b * b - (float(f @ f) - r * r)
    with np.errstate(invalid="ignore"):
        s1 = -b - np.sqrt(disc)
    s1[(disc <= 0.0) | (s1 <= 0.0)] = np.nan
    p1 = tx + s1[:, None] * d
    t1 = _refract(d, (p1 - c) / r, v_in / v_out)
    p2 = _far_hit(p1, t1, c)
    n2 = (p2 - c) / r
    d2 = t1 - 2.0 * np.sum(t1 * n2, axis=1, keepdims=True) * n2
    p3 = _far_hit(p2, d2, c)
    d3 = _refract(d2, -(p3 - c) / r, v_out / v_in)
    with np.errstate(invalid="ignore", divide="ignore"):
        s4 = np.where(d3[:, 1] > 0.0, (surface_y - p3[:, 1]) / d3[:, 1], np.nan)
    land = p3[:, 0] + s4 * d3[:, 0]
    time = (s1 + s4) / v_out + (np.linalg.norm(p2 - p1, axis=1) + np.linalg.norm(p3 - p2, axis=1)) / v_in
    return land, time


def internal_reflection_time(
    tx: tuple[float, float], rx: tuple[float, float], target: CircularTarget,
    v_out: float, v_in: float,
) -> float | None:
    """Earliest tx -> refract in -> far-wall reflection -> refract out -> rx
    path, by shooting. None when no such ray reaches rx (total internal
    reflection, or the receiver lies outside every exit ray)."""
    tx_a = np.asarray(tx, dtype=float)
    to_c = np.array([target.centre_x, target.centre_y]) - tx_a
    centre_phi = math.atan2(to_c[0], -to_c[1])
    half_width = math.asin(min(1.0, target.radius / float(np.hypot(*to_c))))
    phis = np.linspace(centre_phi - half_width, centre_phi + half_width, _SHOOT_SAMPLES)[1:-1]

    def miss(phi: float) -> float:
        return float(_shoot_internal(phi, tx_a, tx[1], target, v_out, v_in)[0][0]) - rx[0]

    values = _shoot_internal(phis, tx_a, tx[1], target, v_out, v_in)[0] - rx[0]
    a, b = values[:-1], values[1:]
    with np.errstate(invalid="ignore"):
        brackets = np.flatnonzero((a == 0.0) | (a * b < 0.0))
    times = []
    for i in brackets:
        root = phis[i] if values[i] == 0.0 else brentq(miss, phis[i], phis[i + 1], xtol=1e-14)
        times.append(float(_shoot_internal(root, tx_a, tx[1], target, v_out, v_in)[1][0]))
    return min(times) if times else None


def predicted_internal_times(s: Scenario2D, target: CircularTarget) -> np.ndarray | None:
    """Predicted internal-reflection peak time per trace (NaN where no ray
    connects), wavelet delay included; None for an opaque target."""
    v_in = target_velocity(s, target)
    if v_in is None:
        return None
    delay = ricker_peak_delay(s.centre_frequency)
    out = []
    for i in range(s.n_traces):
        t = internal_reflection_time((s.tx_x(i), s.surface_y), (s.rx_x(i), s.surface_y),
                                     target, s.soil.velocity, v_in)
        out.append(math.nan if t is None else t + delay)
    return np.asarray(out)


def _event(model: str, times: np.ndarray) -> dict:
    finite = np.where(np.isfinite(times), times, np.inf)
    apex = int(np.argmin(finite))
    return {
        "model": model,
        # JSON has no NaN: a trace no ray reaches is null.
        "two_way_time_s": [float(t) if math.isfinite(t) else None for t in times],
        "apex_trace": apex,
        "apex_time_s": float(times[apex]),
    }


def build_truth_manifest(s: Scenario2D) -> dict:
    validate(s)
    targets = []
    for t in s.targets:
        times = predicted_two_way_times(s, t)
        apex = int(np.argmin(times))
        events = {"top": _event("straight_ray_single_medium_specular", times)}
        internal = predicted_internal_times(s, t)
        if internal is not None and np.isfinite(internal).any():
            events["internal"] = _event("refracted_ray_single_internal_reflection", internal)
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
            # The top event, kept in its v1 shape for every existing reader.
            "predicted": {
                "model": "straight_ray_single_medium_specular",
                "two_way_time_s": times.tolist(),
                "apex_trace": apex,
                "apex_time_s": float(times[apex]),
            },
            "predicted_events": events,
        })
    return {
        "scenario_id": s.scenario_id,
        "scenario_fingerprint": s.fingerprint(),
        "truth_kind": "simulated_exact_by_construction",
        "truth_model_version": TRUTH_MODEL_VERSION,
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
            "target_materials": {
                m.name: {"relative_permittivity": m.relative_permittivity,
                         "conductivity_s_per_m": m.conductivity}
                for m in s.materials
            },
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
        **_layer_entry(s),
    }


def _layer_entry(s: Scenario2D) -> dict:
    """Only scenes with a layer get this key, so existing manifests are
    unchanged. Two-way time of the specular reflection off the flat
    interface for each trace's tx/rx pair (one medium above it)."""
    if s.layer is None:
        return {}
    h = s.surface_y - s.layer.interface_y
    v = s.soil.velocity
    times = [2 * math.hypot(h, s.antenna_offset / 2) / v + ricker_peak_delay(s.centre_frequency)
             for _ in range(s.n_traces)]
    return {"layer": {
        "interface_depth_m": h,
        "material": {"name": s.layer.material.name,
                     "relative_permittivity": s.layer.material.relative_permittivity,
                     "conductivity_s_per_m": s.layer.material.conductivity},
        "predicted_two_way_time_s": times,
        "model": "straight_ray_single_medium_specular_flat_interface",
    }}
