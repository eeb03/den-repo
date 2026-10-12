"""
Seeded random scenario generator for a simulated GPR corpus (roadmap M1a).

Every choice below was fixed BEFORE the first generated scene was run, and is
stated with its reason so a later change is visibly a change:

* WAVELENGTH-SCALED GEOMETRY. Domain, depths, radii, antenna offset and trace
  step are all multiples of the centre wavelength in the soil (lambda_c).
  Every frequency/soil combination then costs about the same number of
  cells, and no scene is a short scan that its own hyperbola spans end to
  end (the failure the reference scene exposed; see analysis.py).
* GRID-SNAPPED COORDINATES. Every position and radius is an integer number of
  cells, so the truth written down is exactly the geometry the solver
  builds, never a value it silently rounded.
* RESOLUTION BY CONSTRUCTION. The cell is the largest whole multiple of
  0.1 mm giving >= 12 cells per wavelength at 2.9 x the centre frequency (gprMax reported
  its limiting frequency as 2.88 f for the Ricker reference). gprMax still
  makes its own check and refuses an under-resolved model; this only aims to
  never trigger it.
* BOUNDED LOSS. Soil conductivity is capped so the loss tangent stays <= 0.1,
  which keeps truth.py's low-loss velocity c/sqrt(eps_r) within ~0.15%.
* NEGATIVES ARE FIRST-CLASS. A fifth of scenes are attested-empty: the 4TU
  benchmark could not separate a detector from chance with 6 negatives.
* SPLIT BY HASH OF THE DRAW. train/val/test is decided by hashing the
  scene's geometry group, so it is stable, independent of corpus size, and
  cannot be chosen after results. The group is the random draw
  (seed, index), not the full fingerprint: any later variant of the same
  draw -- another antenna, a 3D acquisition of the same objects -- shares
  its split, so correlated scenes cannot straddle train and test. (Split v1
  hashed the fingerprint; changed before any model used a split.)
"""
from __future__ import annotations

import hashlib
import math
import re

import numpy as np

from simulation.scenario import (
    C0, PML_CELLS, CircularTarget, Scenario2D, ScenarioError, Soil, validate,
)

EPS0 = 8.8541878128e-12

FREQUENCIES_HZ = (2.5e8, 5e8, 1e9, 1.5e9, 2.6e9)  # common commercial antennas
PERMITTIVITY_RANGE = (3.0, 25.0)                  # dry sand .. wet clay
MAX_CONDUCTIVITY = 0.01                           # S/m
MAX_LOSS_TANGENT = 0.1
# Cells are whole multiples of this. A coarse "round" list (1, 2, 2.5 mm ...)
# over-resolved some scenes ~2x, which in 2D costs ~8x (cells x time steps).
CELL_QUANTUM_M = 1e-4
CELLS_PER_LIMIT_WAVELENGTH = 12
LIMIT_FREQUENCY_FACTOR = 2.9

DOMAIN_WIDTH_WAVELENGTHS = 8.0
SOIL_DEPTH_WAVELENGTHS = 5.0
AIR_CELLS_ABOVE_PML = 10
SCAN_EDGE_CELLS = 5            # clearance between the scan and the PML
TRACE_STEP_WAVELENGTHS = 1 / 12  # < lambda_limit / 4 spatial-aliasing bound
ANTENNA_OFFSET_WAVELENGTHS = 0.5

SCENE_MIX = (("empty", 0.2), ("single", 0.5), ("multi", 0.3))
LABELS = ("pipe", "cable", "void", "rock")
# (min, max) radius in lambda_c; each is floored at MIN_RADIUS_CELLS.
RADIUS_WAVELENGTHS = {
    "pipe": (0.10, 0.40),
    "cable": (0.03, 0.08),
    "void": (0.15, 0.50),
    "rock": (0.15, 0.50),
}
MIN_RADIUS_CELLS = 2
TARGET_DEPTH_WAVELENGTHS = (0.5, 4.0)  # top of target .. centre, below surface
TARGET_GAP_WAVELENGTHS = 0.5           # minimum surface-to-surface spacing
ROCK_PERMITTIVITY_RANGE = (4.0, 12.0)
ROCK_MIN_CONTRAST = 3.0                # |eps_rock - eps_soil|, else invisible
ROCK_CONDUCTIVITY = 0.001

SPLITS = (("train", 70), ("val", 15), ("test", 15))  # percent

LABEL_MATERIAL = {"pipe": "pec", "cable": "pec", "void": "free_space"}


def choose_cell(velocity: float, frequency: float) -> float:
    target = velocity / (LIMIT_FREQUENCY_FACTOR * frequency) / CELLS_PER_LIMIT_WAVELENGTH
    quanta = math.floor(target / CELL_QUANTUM_M + 1e-9)
    if quanta < 1:
        raise ScenarioError(f"required cell {target:.3g} m is finer than {CELL_QUANTUM_M} m")
    return round(quanta * CELL_QUANTUM_M, 10)


def max_conductivity(permittivity: float, frequency: float) -> float:
    """Largest sigma with loss tangent sigma / (omega eps0 eps_r) <= the cap."""
    return min(MAX_CONDUCTIVITY, MAX_LOSS_TANGENT * 2 * math.pi * frequency * EPS0 * permittivity)


SPLIT_VERSION = 2
_DRAW_ID = re.compile(r"gen_s(\d+)_(\d+)")


def geometry_group(s: Scenario2D) -> str:
    """The draw a scene came from; every variant of one draw shares it. A
    scene not made by this generator is its own group."""
    m = _DRAW_ID.match(s.scenario_id)
    return f"draw_s{int(m.group(1))}_{int(m.group(2))}" if m else f"scene_{s.fingerprint()}"


def split_of(s: Scenario2D) -> str:
    bucket = int(hashlib.sha256(geometry_group(s).encode()).hexdigest(), 16) % 100
    edge = 0
    for name, percent in SPLITS:
        edge += percent
        if bucket < edge:
            return name
    raise AssertionError("SPLITS must sum to 100")


def _choose(rng: np.random.Generator, weighted) -> str:
    names, weights = zip(*weighted)
    return str(rng.choice(names, p=np.asarray(weights) / sum(weights)))


def _rock_permittivity(rng: np.random.Generator, soil_eps: float) -> float | None:
    for _ in range(100):
        eps = round(float(rng.uniform(*ROCK_PERMITTIVITY_RANGE)), 2)
        if abs(eps - soil_eps) >= ROCK_MIN_CONTRAST:
            return eps
    return None


def generate_scene(seed: int, index: int) -> Scenario2D:
    """Scene `index` of corpus `seed`. Independent of how many are generated."""
    rng = np.random.default_rng([seed, index])

    frequency = float(rng.choice(FREQUENCIES_HZ))
    eps = round(float(rng.uniform(*PERMITTIVITY_RANGE)), 2)
    sigma = round(float(rng.uniform(0.0, max_conductivity(eps, frequency))), 5)
    soil = Soil(name="soil", relative_permittivity=eps, conductivity=sigma)
    v = soil.velocity
    cell = choose_cell(v, frequency)
    lam = v / frequency                      # lambda_c, metres
    n = lambda metres: max(1, round(metres / cell))  # metres -> whole cells

    nx = n(DOMAIN_WIDTH_WAVELENGTHS * lam)
    soil_cells = PML_CELLS + n(SOIL_DEPTH_WAVELENGTHS * lam)
    ny = soil_cells + PML_CELLS + AIR_CELLS_ABOVE_PML
    offset = n(ANTENNA_OFFSET_WAVELENGTHS * lam)
    step = n(TRACE_STEP_WAVELENGTHS * lam)
    tx0 = PML_CELLS + SCAN_EDGE_CELLS
    last_rx = nx - PML_CELLS - SCAN_EDGE_CELLS
    n_traces = (last_rx - offset - tx0) // step + 1

    chi = math.sqrt(2.0) / frequency
    time_window = 2 * SOIL_DEPTH_WAVELENGTHS * lam / v + 2 * chi

    kind = _choose(rng, SCENE_MIX)
    wanted = {"empty": 0, "single": 1, "multi": int(rng.integers(2, 4))}[kind]

    # Target centres stay a wavelength inside the scan's midpoint coverage.
    mid_lo = tx0 + offset / 2 + n(lam)
    mid_hi = tx0 + (n_traces - 1) * step + offset / 2 - n(lam)
    targets: list[CircularTarget] = []
    materials: list[Soil] = []
    attempts = 0
    while len(targets) < wanted and attempts < 200:
        attempts += 1
        label = str(rng.choice(LABELS))
        material = LABEL_MATERIAL.get(label)
        rock = None
        if label == "rock":
            rock_eps = _rock_permittivity(rng, eps)
            if rock_eps is None:
                continue
            rock = Soil(name=f"rock_T{len(targets) + 1}", relative_permittivity=rock_eps,
                        conductivity=ROCK_CONDUCTIVITY)
            material = rock.name
        r_lo, r_hi = RADIUS_WAVELENGTHS[label]
        r = max(MIN_RADIUS_CELLS, n(float(rng.uniform(r_lo, r_hi)) * lam))
        d_lo = n(TARGET_DEPTH_WAVELENGTHS[0] * lam) + r
        d_hi = n(TARGET_DEPTH_WAVELENGTHS[1] * lam)
        if d_hi <= d_lo or mid_hi <= mid_lo:
            continue
        cy = soil_cells - int(rng.integers(d_lo, d_hi + 1))
        cx = int(rng.integers(math.ceil(mid_lo), math.floor(mid_hi) + 1))
        gap = n(TARGET_GAP_WAVELENGTHS * lam)
        if any(math.hypot(cx - t.centre_x / cell, cy - t.centre_y / cell) < r + t.radius / cell + gap
               for t in targets):
            continue
        targets.append(CircularTarget(
            target_id=f"T{len(targets) + 1}", label=label,
            centre_x=cx * cell, centre_y=cy * cell, radius=r * cell, material=material,
        ))
        if rock is not None:
            materials.append(rock)

    s = Scenario2D(
        scenario_id=f"gen_s{seed}_{index:05d}",
        title=f"Generated scene {index} of corpus seed {seed} ({kind}, {len(targets)} targets)",
        domain_x=nx * cell,
        domain_y=ny * cell,
        cell=cell,
        time_window=time_window,
        surface_y=soil_cells * cell,
        soil=soil,
        centre_frequency=frequency,
        tx_start_x=tx0 * cell,
        antenna_offset=offset * cell,
        step=step * cell,
        n_traces=int(n_traces),
        targets=tuple(targets),
        materials=tuple(materials),
    )
    validate(s)
    return s


def generate(seed: int, count: int, start: int = 0) -> list[Scenario2D]:
    return [generate_scene(seed, i) for i in range(start, start + count)]
