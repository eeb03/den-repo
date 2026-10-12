"""
The seeded scenario generator (roadmap M1a). No solver needed: these pin the
generator's own pre-registered rules -- determinism, grid snapping,
resolution, bounded loss, scene mix and hash splits -- over many scenes.
"""
import math
from collections import Counter
from dataclasses import replace

import pytest

from simulation.generator import (
    CELLS_PER_LIMIT_WAVELENGTH, LIMIT_FREQUENCY_FACTOR, MAX_LOSS_TANGENT, MIN_RADIUS_CELLS,
    ROCK_MIN_CONTRAST, choose_cell, generate, generate_scene, geometry_group, split_of,
)
from simulation.scenario import Soil, ScenarioError, to_gprmax_input, validate
from simulation.truth import build_truth_manifest

EPS0 = 8.8541878128e-12
SCENES = generate(seed=7, count=300)


def _on_grid(value, cell):
    return abs(value / cell - round(value / cell)) < 1e-6


def test_same_seed_and_index_give_the_same_scene_regardless_of_batch():
    assert generate_scene(7, 42).fingerprint() == SCENES[42].fingerprint()
    assert generate(7, 5, start=40)[2].fingerprint() == SCENES[42].fingerprint()
    assert generate_scene(8, 42).fingerprint() != SCENES[42].fingerprint()


def test_every_scene_validates_and_renders():
    for s in SCENES:
        validate(s)
        assert to_gprmax_input(s).startswith("#title:")


def test_every_coordinate_is_snapped_to_the_grid():
    for s in SCENES:
        c = s.cell
        for v in (s.domain_x, s.domain_y, s.surface_y, s.tx_start_x, s.antenna_offset, s.step):
            assert _on_grid(v, c), (s.scenario_id, v)
        for t in s.targets:
            for v in (t.centre_x, t.centre_y, t.radius):
                assert _on_grid(v, c), (s.scenario_id, t.target_id, v)
            assert t.radius >= MIN_RADIUS_CELLS * c - 1e-12


def test_cell_meets_the_resolution_rule():
    for s in SCENES:
        limit_wavelength = s.soil.velocity / (LIMIT_FREQUENCY_FACTOR * s.centre_frequency)
        assert limit_wavelength / s.cell >= CELLS_PER_LIMIT_WAVELENGTH


def test_choose_cell_refuses_impossible_resolution():
    with pytest.raises(ScenarioError):
        choose_cell(velocity=1e5, frequency=1e9)


def test_soil_loss_is_bounded():
    for s in SCENES:
        omega = 2 * math.pi * s.centre_frequency
        tan_delta = s.soil.conductivity / (omega * EPS0 * s.soil.relative_permittivity)
        assert tan_delta <= MAX_LOSS_TANGENT + 1e-9


def test_rocks_contrast_with_their_soil_and_declare_their_material():
    rocks = [(s, t) for s in SCENES for t in s.targets if t.label == "rock"]
    assert rocks
    for s, t in rocks:
        m = {m.name: m for m in s.materials}[t.material]
        assert abs(m.relative_permittivity - s.soil.relative_permittivity) >= ROCK_MIN_CONTRAST
        assert f"#material: " in to_gprmax_input(s) and t.material in to_gprmax_input(s)


def test_scene_mix_includes_negatives_singles_and_multiples():
    counts = Counter(min(len(s.targets), 2) for s in SCENES)
    # 20/50/30 by design; generous bounds for 300 draws.
    assert 0.12 < counts[0] / len(SCENES) < 0.28
    assert 0.40 < counts[1] / len(SCENES) < 0.60
    assert 0.20 < counts[2] / len(SCENES) < 0.40
    assert {t.label for s in SCENES for t in s.targets} == {"pipe", "cable", "void", "rock"}


def test_scans_are_long_relative_to_their_targets():
    """The reference-scene lesson: no target's hyperbola apex may sit within a
    wavelength of either end of the scan."""
    for s in SCENES:
        for t in build_truth_manifest(s)["targets"]:
            apex = t["predicted"]["apex_trace"]
            assert 0 < apex < s.n_traces - 1


def test_splits_are_stable_and_roughly_70_15_15():
    counts = Counter(split_of(s) for s in SCENES)
    assert set(counts) == {"train", "val", "test"}
    assert 0.6 < counts["train"] / len(SCENES) < 0.8
    assert split_of(SCENES[3]) == split_of(generate_scene(7, 3))


def test_validate_rejects_unknown_materials_and_overlaps():
    s = next(s for s in SCENES if len(s.targets) >= 2)
    a, b = s.targets[:2]
    with pytest.raises(ScenarioError, match="unknown material"):
        validate(replace(s, targets=(replace(a, material="granite"),)))
    with pytest.raises(ScenarioError, match="overlap"):
        validate(replace(s, targets=(a, replace(b, centre_x=a.centre_x, centre_y=a.centre_y))))
    with pytest.raises(ScenarioError, match="shadow"):
        validate(replace(s, materials=(Soil("pec", 5.0, 0.0),)))


def test_variants_of_one_draw_share_a_split_so_they_cannot_leak():
    """A re-acquisition of the same objects (another antenna, a later 3D
    variant) is not an independent scene and must land in the same split."""
    s = SCENES[11]
    variant = replace(s, scenario_id=s.scenario_id + "_3d", centre_frequency=s.centre_frequency * 2)
    assert variant.fingerprint() != s.fingerprint()
    assert geometry_group(variant) == geometry_group(s) == "draw_s7_11"
    assert split_of(variant) == split_of(s)
    assert len({geometry_group(s) for s in SCENES}) == len(SCENES)


def test_leakage_audit_on_a_300_scene_design():
    from simulation.leakage import audit
    report = audit(SCENES)
    assert report["duplicate_fingerprints"] == []
    assert report["groups_straddling_splits"] == []
    assert report["empty_scenes_excluded_from_near_check"] == sum(not s.targets for s in SCENES)


def test_leakage_audit_flags_a_rescaled_copy_in_another_split():
    """The same picture at another frequency is the same geometry in
    wavelengths; planted under a different draw id it must be flagged."""
    from simulation.leakage import audit
    s = next(s for s in SCENES if len(s.targets) == 1)
    other_split = next(i for i in range(10_000)
                       if split_of(replace(s, scenario_id=f"gen_s99_{i:05d}")) != split_of(s))
    copy = replace(s, scenario_id=f"gen_s99_{other_split:05d}")
    pairs = audit([s, copy])["near_duplicate_pairs_across_splits"]
    assert [sorted((p["a"], p["b"])) for p in pairs] == [sorted((s.scenario_id, copy.scenario_id))]
