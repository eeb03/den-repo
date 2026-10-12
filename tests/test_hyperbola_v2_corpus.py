"""
The fresh V2 corpus generator (docs/hyperbola-v2-experiment.md §4) and the
scenario/truth/twin extensions it needs. No solver is run.
"""
import math

import pytest

from simulation.generator import generate_scene
from simulation.generator_v2 import (
    CLOSE_DEPTH_SPREAD, CLOSE_GAP_WAVELENGTHS, DEEP_CENTRE_WAVELENGTHS, FAMILIES, OVERLAP_DEPTH_DIFF,
    OVERLAP_LATERAL, SCENES_PER_FAMILY, WEAK_CONTRAST, WET_PERMITTIVITY, generate_scene_v2, plan, v2_split,
)
from simulation.run_gprmax import _target_free_twin
from simulation.scenario import CLUTTER_PREFIX, REFERENCE_CYLINDER_2D, to_gprmax_input
from simulation.truth import build_truth_manifest

N = 12  # scenes per family checked here (the corpus has SCENES_PER_FAMILY)


def _lam(s):
    return s.soil.velocity / s.centre_frequency


def _depth_wl(s, t):
    return (s.surface_y - t.centre_y) / _lam(s)


def test_existing_fingerprints_are_unchanged_by_the_layer_field():
    # Values recorded in corpus_s0/index.json and the reference manifest, built
    # before Scenario2D had a layer.
    assert generate_scene(0, 0).fingerprint() == "bf1bff45b8074d09f574ee7edd7e0b6d7e193c124dd2dab829c2af54fa95b548"
    assert generate_scene(0, 13).fingerprint() == "12e8169b4cc1951b66fb426a7771bac2acbf3087356f7ea84f0a3a174cf3f472"
    assert REFERENCE_CYLINDER_2D.fingerprint() == "72db2328bb2107115e854d6cb807239344f956736208225470df986aa063f00e"
    assert "layer" not in generate_scene(0, 0).to_dict()
    assert "layer" not in build_truth_manifest(generate_scene(0, 1))


def test_generation_is_deterministic_and_the_plan_is_balanced():
    assert generate_scene_v2("deep", 1, 3).fingerprint() == generate_scene_v2("deep", 1, 3).fingerprint()
    assert generate_scene_v2("standard", 1, 5).fingerprint() == generate_scene(1, 5).fingerprint()
    p = plan()
    assert len(p) == len(FAMILIES) * SCENES_PER_FAMILY
    assert p[: len(FAMILIES)] == [(f, 0) for f in FAMILIES]


def test_split_is_by_draw_and_roughly_30_70():
    splits = [v2_split(f, 1, i) for f, i in plan()]
    assert set(splits) == {"dev", "eval"}
    assert 0.2 < splits.count("dev") / len(splits) < 0.4
    assert v2_split("overlap", 1, 7) == v2_split("overlap", 1, 7)


def test_independent_of_corpus_s0():
    ids0 = {generate_scene(0, i).fingerprint() for i in range(40)}
    assert not ids0 & {generate_scene_v2(f, 1, i).fingerprint() for f, i in plan(per_family=6)}


@pytest.mark.parametrize("i", range(N))
def test_family_constraints(i):
    s = generate_scene_v2("weak_contrast", 1, i)
    assert 1 <= len(s.targets) <= 2 and all(t.label == "rock" for t in s.targets)
    mats = {m.name: m for m in s.materials}
    for t in s.targets:
        d = abs(mats[t.material].relative_permittivity - s.soil.relative_permittivity)
        assert d <= WEAK_CONTRAST[1] + 1e-9 and (d >= WEAK_CONTRAST[0] - 1e-9 or mats[t.material].relative_permittivity == 1.0)

    s = generate_scene_v2("deep", 1, i)
    assert all(DEEP_CENTRE_WAVELENGTHS[0] - 0.05 <= _depth_wl(s, t) <= DEEP_CENTRE_WAVELENGTHS[1] + 0.05
               for t in s.targets)

    s = generate_scene_v2("close_pair", 1, i)
    a, b = s.targets
    lam = _lam(s)
    assert abs(_depth_wl(s, a) - _depth_wl(s, b)) <= CLOSE_DEPTH_SPREAD + 0.05
    gap = math.hypot(a.centre_x - b.centre_x, a.centre_y - b.centre_y) - a.radius - b.radius
    assert CLOSE_GAP_WAVELENGTHS[0] * lam - 2 * s.cell <= gap <= CLOSE_GAP_WAVELENGTHS[1] * lam + 2 * s.cell

    s = generate_scene_v2("overlap", 1, i)
    a, b = s.targets
    lam = _lam(s)
    assert OVERLAP_LATERAL[0] - 0.05 <= abs(a.centre_x - b.centre_x) / lam <= OVERLAP_LATERAL[1] + 0.05
    assert OVERLAP_DEPTH_DIFF[0] - 0.05 <= _depth_wl(s, b) - _depth_wl(s, a) <= OVERLAP_DEPTH_DIFF[1] + 0.05

    s = generate_scene_v2("wet_conductive", 1, i)
    assert WET_PERMITTIVITY[0] <= s.soil.relative_permittivity <= WET_PERMITTIVITY[1]
    tan_d = s.soil.conductivity / (2 * math.pi * s.centre_frequency * 8.8541878128e-12 * s.soil.relative_permittivity)
    assert 0.0499 <= tan_d <= 0.1001

    s = generate_scene_v2("empty_clutter", 1, i)
    assert 3 <= len(s.targets) <= 8 and all(t.target_id.startswith(CLUTTER_PREFIX) for t in s.targets)
    if s.layer is not None:
        assert all(t.centre_y - t.radius > s.layer.interface_y for t in s.targets)


def test_some_clutter_scenes_have_a_layer_and_it_is_rendered_and_in_truth():
    scenes = [generate_scene_v2("empty_clutter", 1, i) for i in range(N)]
    layered = [s for s in scenes if s.layer is not None]
    assert 0 < len(layered) < len(scenes)
    s = layered[0]
    text = to_gprmax_input(s)
    soil_box = text.index(f"inf {s.soil.name}\n")
    layer_box = text.index(f"inf {s.layer.material.name}\n")
    assert soil_box < layer_box < text.index("#cylinder")
    truth = build_truth_manifest(s)
    h = s.surface_y - s.layer.interface_y
    assert truth["layer"]["interface_depth_m"] == pytest.approx(h)
    assert len(truth["layer"]["predicted_two_way_time_s"]) == s.n_traces
    assert "layer" in s.to_dict()


def test_twin_keeps_clutter_and_removes_scored_targets():
    s = generate_scene_v2("empty_clutter", 1, 0)
    scored, twin = _target_free_twin(s)
    assert not scored and twin.targets == s.targets
    s = generate_scene_v2("overlap", 1, 0)
    scored, twin = _target_free_twin(s)
    assert scored and twin.targets == () and twin.materials == ()
    s = generate_scene(0, 13)
    scored, twin = _target_free_twin(s)
    assert scored and twin.targets == () and twin.materials == ()
