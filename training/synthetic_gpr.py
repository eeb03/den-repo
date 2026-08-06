"""
Phase-0 synthetic GPR training data generator.

IMPORTANT — read before using this for anything beyond pipeline testing:
this is SIMPLIFIED, first-order physics (hyperbola travel-time kinematics
+ hand-crafted reflector shape heuristics), not a full electromagnetic
simulation. It is verified to be internally consistent (a "pipe" really
does produce a hyperbola with the geometry real hyperbolas have; a
"foundation" really does produce a flat reflector; etc.) but it has NOT
been validated against real field data or real gprMax/FDTD simulation
output. Treat models trained only on this as a pipeline/architecture
proof-of-concept, not a field-ready detector.

For real synthetic training data at scale, the legitimate path is
gprMax (github.com/gprMax/gprMax) — an open-source FDTD electromagnetic
solver — which this module is deliberately structured to be replaceable
by: same class taxonomy, same feature-vector interface.

Classes match schemas.subterra_record.GroundTruthLabel:
PIPE, CABLE, ROCK, VOID, CONCRETE (foundation), UNKNOWN_ANOMALY (background).
"""
from __future__ import annotations

import numpy as np

CLASSES = ["pipe", "cable", "rock", "void", "concrete", "unknown"]

# Maps our simplified class names to the real GroundTruthLabel enum values,
# so classifier output can be attached directly to a SubterraRecord.
CLASS_TO_GROUND_TRUTH_LABEL = {
    "pipe": "pipe",
    "cable": "cable",
    "rock": "rock",
    "void": "void",
    "concrete": "concrete",
    "unknown": "unknown_anomaly",
}


def _hyperbola_patch(
    n_traces: int, n_samples: int, apex_time: float, curvature: float,
    amplitude: float, polarity: float, width: float, rng: np.random.Generator,
) -> np.ndarray:
    """A point-source reflector: hyperbolic travel-time curve, Gaussian pulse shape at each trace."""
    patch = np.zeros((n_traces, n_samples))
    x = np.arange(n_traces) - n_traces / 2
    peak_times = apex_time + curvature * x**2
    t = np.arange(n_samples)
    for i in range(n_traces):
        pt = peak_times[i]
        if 0 <= pt < n_samples:
            patch[i] = polarity * amplitude * np.exp(-((t - pt) ** 2) / (2 * width**2))
    return patch


def _planar_patch(
    n_traces: int, n_samples: int, reflector_time: float,
    amplitude: float, polarity: float, width: float, rng: np.random.Generator,
) -> np.ndarray:
    """A large flat reflector: constant travel time across all traces (foundation/slab)."""
    patch = np.zeros((n_traces, n_samples))
    t = np.arange(n_samples)
    jitter = rng.normal(0, 0.3, n_traces)  # slight real-world unevenness
    for i in range(n_traces):
        pt = reflector_time + jitter[i]
        patch[i] = polarity * amplitude * np.exp(-((t - pt) ** 2) / (2 * width**2))
    return patch


def _diffuse_patch(
    n_traces: int, n_samples: int, mean_time: float, spread: float,
    amplitude: float, n_scatterers: int, width: float, rng: np.random.Generator,
) -> np.ndarray:
    """Heterogeneous scattering: several weak, incoherent small reflectors (rock)."""
    patch = np.zeros((n_traces, n_samples))
    t = np.arange(n_samples)
    for _ in range(n_scatterers):
        center_trace = rng.integers(0, n_traces)
        center_time = mean_time + rng.normal(0, spread)
        amp = amplitude * rng.uniform(0.3, 1.0) * rng.choice([-1, 1])
        span = rng.integers(2, 6)
        for i in range(max(0, center_trace - span), min(n_traces, center_trace + span)):
            patch[i] += amp * np.exp(-((t - center_time) ** 2) / (2 * width**2))
    return patch


def _noise_only_patch(n_traces: int, n_samples: int, noise_level: float, rng: np.random.Generator) -> np.ndarray:
    """No coherent target -- just background clutter/noise (matches what we actually saw in the real Lazaresti 0-0.5m slice)."""
    return rng.normal(0, noise_level, (n_traces, n_samples))


def generate_patch(class_name: str, n_traces: int = 32, n_samples: int = 64, rng: np.random.Generator | None = None) -> np.ndarray:
    """Generates one labeled synthetic B-scan patch, with randomized realistic parameter ranges per class."""
    rng = rng or np.random.default_rng()
    noise_level = 0.15

    if class_name == "pipe":
        patch = _hyperbola_patch(
            n_traces, n_samples, apex_time=rng.uniform(15, 45), curvature=rng.uniform(0.08, 0.25),
            amplitude=rng.uniform(2.0, 4.0), polarity=1.0, width=rng.uniform(1.5, 3.0), rng=rng,
        )
    elif class_name == "cable":
        patch = _hyperbola_patch(
            n_traces, n_samples, apex_time=rng.uniform(15, 45), curvature=rng.uniform(0.10, 0.30),
            amplitude=rng.uniform(0.8, 1.8), polarity=1.0, width=rng.uniform(1.0, 2.0), rng=rng,
        )
    elif class_name == "void":
        # Air-filled cavity: strong reflection, opposite polarity vs. a metal
        # pipe -- a real, well-known qualitative GPR interpretation cue.
        patch = _hyperbola_patch(
            n_traces, n_samples, apex_time=rng.uniform(15, 45), curvature=rng.uniform(0.08, 0.25),
            amplitude=rng.uniform(2.5, 5.0), polarity=-1.0, width=rng.uniform(2.0, 3.5), rng=rng,
        )
    elif class_name == "concrete":
        patch = _planar_patch(
            n_traces, n_samples, reflector_time=rng.uniform(15, 45),
            amplitude=rng.uniform(2.0, 4.0), polarity=1.0, width=rng.uniform(2.0, 3.5), rng=rng,
        )
    elif class_name == "rock":
        patch = _diffuse_patch(
            n_traces, n_samples, mean_time=rng.uniform(15, 45), spread=rng.uniform(5, 12),
            amplitude=rng.uniform(1.0, 2.5), n_scatterers=rng.integers(4, 10), width=rng.uniform(1.5, 3.0), rng=rng,
        )
    elif class_name == "unknown":
        patch = np.zeros((n_traces, n_samples))
    else:
        raise ValueError(f"Unknown class '{class_name}'. Options: {CLASSES}")

    patch = patch + rng.normal(0, noise_level, (n_traces, n_samples))
    return patch


def extract_features(patch: np.ndarray) -> dict[str, float]:
    """
    Hand-crafted, interpretable features from a B-scan patch — deliberately
    NOT a black-box CNN, so the classifier's reasoning stays inspectable
    (matches "explain itself" rather than opaque confidence numbers):
    - peak_amplitude / energy: is there anything here at all
    - planarity: does the reflection stay at ~constant time across traces (flat)
    - curvature: does a parabola (hyperbola proxy) fit the reflection well
    - diffuseness: how much is left unexplained by either a flat or curved fit
    - polarity: sign of the reflection at its strongest point
    """
    n_traces, n_samples = patch.shape
    x = np.arange(n_traces) - n_traces / 2
    peak_times = np.argmax(np.abs(patch), axis=1).astype(float)
    peak_vals = np.array([patch[i, int(peak_times[i])] for i in range(n_traces)])

    peak_amplitude = float(np.max(np.abs(patch)))
    energy = float(np.mean(patch**2))

    resid_flat = peak_times - np.mean(peak_times)
    planarity = float(1.0 / (1.0 + np.var(resid_flat)))

    try:
        coeffs = np.polyfit(x, peak_times, deg=2)
        fit = np.polyval(coeffs, x)
        resid_curved = peak_times - fit
        curvature = float(1.0 / (1.0 + np.var(resid_curved)))
        quad_coeff = float(abs(coeffs[0]))
    except np.linalg.LinAlgError:
        curvature, quad_coeff = 0.0, 0.0

    diffuseness = float(1.0 - max(planarity, curvature))
    polarity = float(np.sign(np.mean(peak_vals[np.abs(peak_vals) > peak_amplitude * 0.3])) if peak_amplitude > 0 else 0.0)

    return {
        "peak_amplitude": peak_amplitude, "energy": energy, "planarity": planarity,
        "curvature": curvature, "quad_coeff": quad_coeff, "diffuseness": diffuseness, "polarity": polarity,
    }


FEATURE_NAMES = ["peak_amplitude", "energy", "planarity", "curvature", "quad_coeff", "diffuseness", "polarity"]


def generate_dataset(n_per_class: int = 200, seed: int = 42) -> tuple[np.ndarray, list[str]]:
    """Generates a labeled synthetic dataset as (feature_matrix, labels)."""
    rng = np.random.default_rng(seed)
    X, y = [], []
    for class_name in CLASSES:
        for _ in range(n_per_class):
            patch = generate_patch(class_name, rng=rng)
            feats = extract_features(patch)
            X.append([feats[name] for name in FEATURE_NAMES])
            y.append(class_name)
    return np.array(X), y
