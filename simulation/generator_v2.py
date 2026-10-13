"""
Hard-case scene families for the fresh V2 evaluation corpus
(docs/hyperbola-v2-experiment.md §4). Seeded, deterministic, and written
before any scene of it was simulated.

The physics, cell rule, wavelength scaling, grid snapping, label radii and
loss cap are generator.py's, imported unchanged; only WHERE targets go (and,
for two families, the soil and depth range) differs per family:

    standard        generator.generate_scene(seed, i) itself (independent draws)
    weak_contrast   1-2 rocks, |eps_rock - eps_soil| in [0.5, 2.5]
    deep            1-2 targets, centre 3.5-5.5 lambda; soil 7 lambda deep
    close_pair      2 targets at similar depth (centres within 0.25 lambda),
                    surface-to-surface gap 0.2-1.0 lambda
    overlap         2 targets, lateral separation 0.5-2.0 lambda, depth
                    difference 1.0-2.5 lambda (crossing hyperbolas)
    wet_conductive  soil eps_r 15-25, loss tangent 0.05-0.10 (sigma set from
                    it, NOT capped at generator.MAX_CONDUCTIVITY, which would
                    leave GHz soils nearly lossless; amendment 1 of the
                    pre-registration); 1-3 targets
    empty_clutter   no scored targets; 3-8 clutter stones (CLUTTER_PREFIX ids)
                    and, in half the scenes, a horizontal layer below them

SPLIT: dev 30% / eval 70% by sha256("{family}:{seed}:{index}"), the draw,
fixed before the corpus exists.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np

from simulation import generator as g
from simulation.scenario import (
    CLUTTER_PREFIX, CircularTarget, Layer, Scenario2D, Soil, validate,
)

FAMILIES = ("standard", "weak_contrast", "deep", "close_pair", "overlap", "wet_conductive", "empty_clutter")
FAMILY_CODE = {f: i for i, f in enumerate(FAMILIES)}
SCENES_PER_FAMILY = 40
V2_SPLITS = (("dev", 30), ("eval", 70))

WEAK_CONTRAST = (0.5, 2.5)
DEEP_CENTRE_WAVELENGTHS = (3.5, 5.5)
DEEP_SOIL_WAVELENGTHS = 7.0
CLOSE_DEPTH_SPREAD = 0.25
CLOSE_GAP_WAVELENGTHS = (0.2, 1.0)
OVERLAP_LATERAL = (0.5, 2.0)
OVERLAP_DEPTH_DIFF = (1.0, 2.5)
WET_PERMITTIVITY = (15.0, 25.0)
WET_LOSS_TANGENT = (0.05, 0.10)
EPS0 = 8.8541878128e-12
CLUTTER_STONES = (3, 8)
CLUTTER_RADIUS = (0.03, 0.08)
CLUTTER_CONTRAST = (1.0, 4.0)
LAYER_DEPTH = (1.5, 4.0)
LAYER_CONTRAST = (2.0, 6.0)
MIN_GAP_CELLS = 2


def v2_split(family: str, seed: int, index: int) -> str:
    bucket = int(hashlib.sha256(f"{family}:{seed}:{index}".encode()).hexdigest(), 16) % 100
    edge = 0
    for name, percent in V2_SPLITS:
        edge += percent
        if bucket < edge:
            return name
    raise AssertionError


def scene_id(family: str, seed: int, index: int) -> str:
    return f"gen_s{seed}_{index:05d}" if family == "standard" else f"v2_s{seed}_{family}_{index:05d}"


class _Frame:
    """generator.generate_scene's frame, with the soil and depth overridable."""

    def __init__(self, rng, eps_range=g.PERMITTIVITY_RANGE, loss_tangent=None,
                 soil_depth_wl=g.SOIL_DEPTH_WAVELENGTHS):
        self.frequency = float(rng.choice(g.FREQUENCIES_HZ))
        self.eps = round(float(rng.uniform(*eps_range)), 2)
        if loss_tangent is None:
            cap = g.max_conductivity(self.eps, self.frequency)
            self.sigma = round(float(rng.uniform(0.0, cap)), 5)
        else:
            tan_d = float(rng.uniform(*loss_tangent))
            self.sigma = round(tan_d * 2 * math.pi * self.frequency * EPS0 * self.eps, 5)
        self.soil = Soil(name="soil", relative_permittivity=self.eps, conductivity=self.sigma)
        v = self.soil.velocity
        self.cell = g.choose_cell(v, self.frequency)
        self.lam = v / self.frequency
        self.nx = self.n(g.DOMAIN_WIDTH_WAVELENGTHS * self.lam)
        self.soil_cells = g.PML_CELLS + self.n(soil_depth_wl * self.lam)
        self.ny = self.soil_cells + g.PML_CELLS + g.AIR_CELLS_ABOVE_PML
        self.offset = self.n(g.ANTENNA_OFFSET_WAVELENGTHS * self.lam)
        self.step = self.n(g.TRACE_STEP_WAVELENGTHS * self.lam)
        self.tx0 = g.PML_CELLS + g.SCAN_EDGE_CELLS
        last_rx = self.nx - g.PML_CELLS - g.SCAN_EDGE_CELLS
        self.n_traces = (last_rx - self.offset - self.tx0) // self.step + 1
        chi = math.sqrt(2.0) / self.frequency
        self.time_window = 2 * soil_depth_wl * self.lam / v + 2 * chi
        self.mid_lo = self.tx0 + self.offset / 2 + self.n(self.lam)
        self.mid_hi = self.tx0 + (self.n_traces - 1) * self.step + self.offset / 2 - self.n(self.lam)
        self.max_depth_cells = self.soil_cells - g.PML_CELLS   # centre - r must stay above the PML

    def n(self, metres: float) -> int:
        return max(1, round(metres / self.cell))

    def radius(self, rng, label: str) -> int:
        lo, hi = g.RADIUS_WAVELENGTHS[label]
        return max(g.MIN_RADIUS_CELLS, self.n(float(rng.uniform(lo, hi)) * self.lam))


def _rock(rng, frame: _Frame, k: int, contrast=None, prefix="rock_T") -> Soil | None:
    if contrast is None:
        eps = g._rock_permittivity(rng, frame.eps)
        if eps is None:
            return None
    else:
        sign = 1.0 if rng.random() < 0.5 else -1.0
        eps = round(max(1.0, frame.eps + sign * float(rng.uniform(*contrast))), 2)
    return Soil(name=f"{prefix}{k}", relative_permittivity=eps, conductivity=g.ROCK_CONDUCTIVITY)


def _target(rng, frame: _Frame, k: int, label: str | None = None, contrast=None):
    """(label, material name, extra material or None, radius cells), or None."""
    label = label or str(rng.choice(g.LABELS))
    material, rock = g.LABEL_MATERIAL.get(label), None
    if label == "rock":
        rock = _rock(rng, frame, k, contrast)
        if rock is None:
            return None
        material = rock.name
    return label, material, rock, frame.radius(rng, label)


def _fits(frame: _Frame, cx: int, cy: int, r: int, placed: list[tuple[int, int, int]], gap: int) -> bool:
    if not (frame.mid_lo <= cx <= frame.mid_hi):
        return False
    if cy - r <= g.PML_CELLS + 1 or cy + r >= frame.soil_cells:
        return False
    return all(math.hypot(cx - x, cy - y) >= r + rr + gap for x, y, rr in placed)


def _depth_to_cy(frame: _Frame, depth_cells: int) -> int:
    return frame.soil_cells - depth_cells


def _place_free(rng, frame, count, depth_wl, contrast=None, labels=None):
    """generator.py's placement rule: uniform centre depth and x, gap rule."""
    out, attempts = [], 0
    gap = frame.n(g.TARGET_GAP_WAVELENGTHS * frame.lam)
    while len(out) < count and attempts < 400:
        attempts += 1
        t = _target(rng, frame, len(out) + 1, labels and str(rng.choice(labels)), contrast)
        if t is None:
            continue
        label, material, rock, r = t
        d_lo = max(frame.n(depth_wl[0] * frame.lam), frame.n(0.5 * frame.lam) + r)
        d_hi = frame.n(depth_wl[1] * frame.lam)
        if d_hi <= d_lo:
            continue
        cy = _depth_to_cy(frame, int(rng.integers(d_lo, d_hi + 1)))
        cx = int(rng.integers(math.ceil(frame.mid_lo), math.floor(frame.mid_hi) + 1))
        if not _fits(frame, cx, cy, r, [(x, y, rr) for x, y, rr, *_ in out], gap):
            continue
        out.append((cx, cy, r, label, material, rock))
    return out


def _place_pair(rng, frame, kind):
    gap_min = MIN_GAP_CELLS
    for _ in range(400):
        a, b = _target(rng, frame, 1), _target(rng, frame, 2)
        if a is None or b is None:
            continue
        ra, rb = a[3], b[3]
        if kind == "close_pair":
            d1 = int(rng.integers(frame.n(1.0 * frame.lam) + ra, frame.n(3.5 * frame.lam) + 1))
            d2 = d1 + int(rng.integers(-frame.n(CLOSE_DEPTH_SPREAD * frame.lam),
                                       frame.n(CLOSE_DEPTH_SPREAD * frame.lam) + 1))
            sep = ra + rb + frame.n(float(rng.uniform(*CLOSE_GAP_WAVELENGTHS)) * frame.lam)
            dx = int(round(math.sqrt(max(sep ** 2 - (d2 - d1) ** 2, 0))))
        else:
            d1 = int(rng.integers(frame.n(0.75 * frame.lam) + ra, frame.n(2.5 * frame.lam) + 1))
            d2 = d1 + frame.n(float(rng.uniform(*OVERLAP_DEPTH_DIFF)) * frame.lam)
            dx = frame.n(float(rng.uniform(*OVERLAP_LATERAL)) * frame.lam)
        if rng.random() < 0.5:
            dx = -dx
        lo = math.ceil(frame.mid_lo) + max(0, -dx)
        hi = math.floor(frame.mid_hi) - max(0, dx)
        if hi < lo:
            continue
        cx1 = int(rng.integers(lo, hi + 1))
        cy1, cy2 = _depth_to_cy(frame, d1), _depth_to_cy(frame, d2)
        if not _fits(frame, cx1, cy1, ra, [], 0):
            continue
        if not _fits(frame, cx1 + dx, cy2, rb, [(cx1, cy1, ra)], gap_min):
            continue
        return [(cx1, cy1, ra, *a[:3]), (cx1 + dx, cy2, rb, *b[:3])]
    return []


def _clutter(rng, frame, layer_cy):
    stones, out = int(rng.integers(CLUTTER_STONES[0], CLUTTER_STONES[1] + 1)), []
    lo_x, hi_x = math.ceil(frame.mid_lo - frame.n(frame.lam)), math.floor(frame.mid_hi + frame.n(frame.lam))
    for _ in range(400):
        if len(out) >= stones:
            break
        k = len(out) + 1
        r = max(g.MIN_RADIUS_CELLS, frame.n(float(rng.uniform(*CLUTTER_RADIUS)) * frame.lam))
        rock = _rock(rng, frame, k, CLUTTER_CONTRAST, prefix="rock_clutter_")
        d_lo = frame.n(0.3 * frame.lam) + r
        d_hi = frame.n(4.0 * frame.lam)
        cy = _depth_to_cy(frame, int(rng.integers(d_lo, d_hi + 1)))
        cx = int(rng.integers(lo_x, hi_x + 1))
        if layer_cy is not None and cy - r <= layer_cy + MIN_GAP_CELLS:
            continue
        if cy - r <= g.PML_CELLS + 1 or any(math.hypot(cx - x, cy - y) < r + rr + MIN_GAP_CELLS
                                            for x, y, rr, *_ in out):
            continue
        out.append((cx, cy, r, "rock", rock.name, rock))
    return out


def generate_scene_v2(family: str, seed: int, index: int) -> Scenario2D:
    if family == "standard":
        return g.generate_scene(seed, index)
    if family not in FAMILY_CODE:
        raise ValueError(family)
    rng = np.random.default_rng([seed, FAMILY_CODE[family], index])
    frame = _Frame(
        rng,
        eps_range=WET_PERMITTIVITY if family == "wet_conductive" else g.PERMITTIVITY_RANGE,
        loss_tangent=WET_LOSS_TANGENT if family == "wet_conductive" else None,
        soil_depth_wl=DEEP_SOIL_WAVELENGTHS if family == "deep" else g.SOIL_DEPTH_WAVELENGTHS,
    )
    layer = None
    if family == "weak_contrast":
        placed = _place_free(rng, frame, int(rng.integers(1, 3)), g.TARGET_DEPTH_WAVELENGTHS,
                             contrast=WEAK_CONTRAST, labels=("rock",))
    elif family == "deep":
        placed = _place_free(rng, frame, int(rng.integers(1, 3)), DEEP_CENTRE_WAVELENGTHS)
    elif family in ("close_pair", "overlap"):
        placed = _place_pair(rng, frame, family)
    elif family == "wet_conductive":
        placed = _place_free(rng, frame, int(rng.integers(1, 4)), g.TARGET_DEPTH_WAVELENGTHS)
    else:  # empty_clutter
        layer_cy = None
        if rng.random() < 0.5:
            layer_cy = _depth_to_cy(frame, frame.n(float(rng.uniform(*LAYER_DEPTH)) * frame.lam))
            sign = 1.0 if rng.random() < 0.5 else -1.0
            leps = round(min(30.0, max(2.0, frame.eps + sign * float(rng.uniform(*LAYER_CONTRAST)))), 2)
            lsig = round(float(rng.uniform(0.0, g.max_conductivity(leps, frame.frequency))), 5)
            layer = Layer(material=Soil(name="soil_layer", relative_permittivity=leps, conductivity=lsig),
                          interface_y=layer_cy * frame.cell)
        placed = _clutter(rng, frame, layer_cy)

    cell = frame.cell
    targets, materials = [], []
    for k, (cx, cy, r, label, material, rock) in enumerate(placed, start=1):
        tid = f"{CLUTTER_PREFIX}{k}" if family == "empty_clutter" else f"T{k}"
        if rock is not None and family != "empty_clutter":
            rock = Soil(name=f"rock_T{k}", relative_permittivity=rock.relative_permittivity,
                        conductivity=rock.conductivity)
            material = rock.name
        targets.append(CircularTarget(target_id=tid, label=label, centre_x=cx * cell, centre_y=cy * cell,
                                      radius=r * cell, material=material))
        if rock is not None:
            materials.append(rock)
    scored = 0 if family == "empty_clutter" else len(targets)
    s = Scenario2D(
        scenario_id=scene_id(family, seed, index),
        title=f"V2 {family} scene {index} of seed {seed} ({scored} scored targets, "
              f"{len(targets) - scored} clutter{', layer' if layer else ''})",
        domain_x=frame.nx * cell, domain_y=frame.ny * cell, cell=cell,
        time_window=frame.time_window, surface_y=frame.soil_cells * cell, soil=frame.soil,
        centre_frequency=frame.frequency, tx_start_x=frame.tx0 * cell,
        antenna_offset=frame.offset * cell, step=frame.step * cell, n_traces=int(frame.n_traces),
        targets=tuple(targets), materials=tuple(materials), layer=layer,
    )
    validate(s)
    return s


def plan(seed: int = 1, per_family: int = SCENES_PER_FAMILY) -> list[tuple[str, int]]:
    """Build order: interleaved across families, so a partial build is balanced."""
    return [(f, i) for i in range(per_family) for f in FAMILIES]
