"""
Leakage audit for a simulated corpus's train/val/test split.

Three checks, each a count that should be zero (the first two) or small and
reported (the third):

1. duplicate scenes -- two entries with one fingerprint;
2. split-straddling groups -- one geometry group (one random draw, see
   generator.geometry_group) in more than one split;
3. near-duplicate geometry across splits -- two DIFFERENT draws whose
   targets are nearly the same once lengths are measured in wavelengths
   (the generator scales geometry by the wavelength, so a scene at 250 MHz
   and one at 2.6 GHz can be the same picture at different sizes). Pairs
   are flagged when they have the same labels and every matched target
   agrees within NEAR_TOLERANCE. Empty scenes are excluded: every empty
   scene is the same "geometry", and their differences (soil, frequency)
   are exactly what a negative should vary.

Flagged pairs are REPORTED, not silently moved: moving scenes after seeing
results would be choosing the split.
"""
from __future__ import annotations

import itertools
from collections import defaultdict

from simulation.generator import geometry_group, split_of
from simulation.scenario import Scenario2D

#: Per-target agreement, in centre wavelengths (and eps_r for the soil).
NEAR_TOLERANCE = {"depth": 0.1, "x": 0.25, "radius": 0.05, "soil_eps": 2.0}


def _descriptor(s: Scenario2D) -> tuple:
    lam = s.soil.velocity / s.centre_frequency
    mid = s.tx_start_x + s.antenna_offset / 2 + (s.n_traces - 1) * s.step / 2
    return tuple(sorted(
        (t.label, (s.surface_y - t.centre_y) / lam, (t.centre_x - mid) / lam, t.radius / lam)
        for t in s.targets
    ))


def _near(a: Scenario2D, b: Scenario2D) -> bool:
    da, db = _descriptor(a), _descriptor(b)
    if [t[0] for t in da] != [t[0] for t in db]:
        return False
    if abs(a.soil.relative_permittivity - b.soil.relative_permittivity) > NEAR_TOLERANCE["soil_eps"]:
        return False
    return all(abs(p[1] - q[1]) <= NEAR_TOLERANCE["depth"] and abs(p[2] - q[2]) <= NEAR_TOLERANCE["x"]
               and abs(p[3] - q[3]) <= NEAR_TOLERANCE["radius"] for p, q in zip(da, db))


def audit(scenes: list[Scenario2D]) -> dict:
    fingerprints = defaultdict(list)
    group_splits = defaultdict(set)
    for s in scenes:
        fingerprints[s.fingerprint()].append(s.scenario_id)
        group_splits[geometry_group(s)].add(split_of(s))

    with_targets = [s for s in scenes if s.targets]
    near = [
        {"a": a.scenario_id, "b": b.scenario_id, "splits": sorted({split_of(a), split_of(b)})}
        for a, b in itertools.combinations(with_targets, 2)
        if split_of(a) != split_of(b) and _near(a, b)
    ]
    return {
        "scenes": len(scenes),
        "duplicate_fingerprints": [ids for ids in fingerprints.values() if len(ids) > 1],
        "groups_straddling_splits": sorted(g for g, sp in group_splits.items() if len(sp) > 1),
        "near_duplicate_pairs_across_splits": near,
        "near_tolerance": NEAR_TOLERANCE,
        "empty_scenes_excluded_from_near_check": len(scenes) - len(with_targets),
    }
