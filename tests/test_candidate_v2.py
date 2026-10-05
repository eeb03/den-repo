"""
Candidate V2 is an experiment beside production, not a replacement.

Guards:
  * it is truth-blind (no truth module, no manifest name), like the detection path;
  * no production path imports it, and the production detector is unchanged;
  * it is deterministic;
  * its physics behaves on synthetic B-scans: a diffraction hyperbola scores a
    high shape score, a flat reflector and an isolated spike do not;
  * every component score is in [0, 1] and the final score is the declared
    fixed-weight combination;
  * its capability status is EXPERIMENTAL, never VALIDATED.
"""
import ast
from pathlib import Path

import numpy as np
import pytest

from benchmark import candidate_v2 as v2
from benchmark import gates

TRUTH_MODULES = ("benchmark.targets", "benchmark.target_scoring", "benchmark.ground_truth",
                 "benchmark.bam_truth", "benchmark.association", "benchmark.scoring",
                 "benchmark.fourtu_truth", "benchmark.tu1208_truth", "benchmark.definition")
COMPONENTS = ("signal_strength", "background_contrast", "shape_score", "persistence_score",
              "noise_penalty", "direct_wave_penalty")


def _imports(path):
    out = set()
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_v2_is_truth_blind():
    assert not _imports("benchmark/candidate_v2.py") & set(TRUTH_MODULES)
    src = Path("benchmark/candidate_v2.py").read_text()
    for marker in (".targets.json", "manifests/", "specimen_ground_truth"):
        assert marker not in src


@pytest.mark.parametrize("root", ["api", "jobs", "interpretation", "preprocessing", "ingestion"])
def test_no_production_path_imports_v2(root):
    for path in Path(root).rglob("*.py"):
        assert "benchmark.candidate_v2" not in _imports(path), path


def test_the_production_detector_does_not_use_v2():
    for path in ("benchmark/detection.py", "benchmark/blind_detection.py"):
        assert "benchmark.candidate_v2" not in _imports(path)


def test_v2_capability_is_experimental_not_validated():
    assert gates.CAPABILITY_STATUS["candidate_generation_v2"] == gates.EXPERIMENTAL
    assert gates.CAPABILITY_STATUS["candidate_generation"] == gates.FAILED


# ------------------------------------------------------------- synthetic physics
DX, DT, NX, NT = 5.0, 0.03, 161, 400
X = np.arange(NX) * DX
T = np.arange(NT) * DT


def _ricker(t, f=1.5):
    a = (np.pi * f * t) ** 2
    return (1 - 2 * a) * np.exp(-a)


def _bscan(kind, rng, x0=400.0, t_apex=5.0, v=0.12, t_s=1.0, amp=1.0):
    b = 0.02 * rng.standard_normal((NX, NT))
    b += _ricker(T[None, :] - t_s) * 2.0                     # direct wave, laterally flat
    for i, x in enumerate(X):
        if kind == "hyperbola":
            tt = t_s + np.sqrt((t_apex - t_s) ** 2 + (2 * abs(x - x0) / 1000 / v) ** 2)
            b[i] += amp * _ricker(T - tt)
        elif kind == "flat_segment" and abs(x - x0) <= 150:
            b[i] += amp * _ricker(T - t_apex)
    if kind == "spike":
        b[int(x0 / DX), int(t_apex / DT)] += 3.0
    return b


def _volume(kind, n_lines=9, seed=0):
    rng = np.random.default_rng(seed)
    return np.stack([_bscan(kind, rng) for _ in range(n_lines)], axis=1)


def _best_near(props, x0=400.0, t0=5.0):
    near = [p for p in props if abs(p["x"] - x0) <= 30 and abs(p["t_ns"] - t0) <= 0.4]
    return max(near, key=lambda p: p["z_env"]) if near else None


def test_a_diffraction_hyperbola_is_proposed_with_a_high_shape_score():
    props = v2.propose(_volume("hyperbola"), X, np.arange(9) * 5.0, T)
    p = _best_near(props)
    assert p is not None
    assert p["shape_score"] > 0.4
    assert p["shape"]["curvature"] > 0.3
    assert p["persistence_score"] == 1.0


def test_a_flat_reflector_segment_fails_the_curvature_test():
    props = v2.propose(_volume("flat_segment"), X, np.arange(9) * 5.0, T)
    p = _best_near(props)
    assert p is not None
    assert p["shape"]["curvature"] < 0.2
    assert p["shape_score"] < 0.3


def test_an_isolated_spike_fails_the_lateral_persistence_filter():
    props = v2.propose(_volume("spike"), X, np.arange(9) * 5.0, T)
    p = _best_near(props)
    assert p is not None
    assert not v2.passes(p, v2.V2Params())["F_lateral"]


def test_components_are_bounded_and_final_score_is_the_declared_combination():
    props = v2.propose(_volume("hyperbola"), X, np.arange(9) * 5.0, T)
    assert props
    for p in props:
        for c in COMPONENTS:
            assert 0.0 <= p[c] <= 1.0, (c, p[c])
        assert p["final_score"] == pytest.approx(sum(w * p[k] for k, w in v2.WEIGHTS.items()))


def test_v2_is_deterministic():
    vol = _volume("hyperbola", seed=3)
    a = v2.detect(vol, X, np.arange(9) * 5.0, T)
    b = v2.detect(vol, X, np.arange(9) * 5.0, T)
    assert a == b


def test_ablation_switches_only_the_named_filter():
    p = v2.V2Params().without("F_shape")
    assert p.disabled == frozenset({"F_shape"})
    with pytest.raises(ValueError):
        v2.V2Params().without("F_magic")


def test_nms_keeps_one_detection_per_window_per_line():
    props = v2.propose(_volume("hyperbola"), X, np.arange(9) * 5.0, T)
    dets = v2.select(props, v2.V2Params().without(*v2.FILTERS))
    for j in range(9):
        line = [d for d in dets if d["line"] == j]
        for a in line:
            for b in line:
                if a is not b:
                    assert (abs(a["x"] - b["x"]) > v2.FINAL_NMS_X_MM / 2
                            or abs(a["t_ns"] - b["t_ns"]) > v2.FINAL_NMS_T_NS / 2)
