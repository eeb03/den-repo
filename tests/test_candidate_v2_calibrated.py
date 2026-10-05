"""
Calibrated Candidate V2 is an experiment beside production.

Guards:
  * truth-blind, and no production path imports it;
  * it never invents a calibration: without one it reports no depth and says so;
  * a supplied calibration must be complete and physical;
  * with the calibrated velocity a diffraction hyperbola is explained by the
    calibrated curve better than by wrong velocities, and a wrong calibration
    lowers that evidence;
  * a flat-topped (void-like) reflector is not forced into a point model;
  * components are bounded and the final score is the declared combination;
  * deterministic; the held-out guard refuses Rot90 before a committed freeze.
"""
import ast
from pathlib import Path

import numpy as np
import pytest

from benchmark import candidate_v2_calibrated as vc
from benchmark import gates

TRUTH_MODULES = ("benchmark.targets", "benchmark.target_scoring", "benchmark.ground_truth",
                 "benchmark.bam_truth", "benchmark.association", "benchmark.scoring",
                 "benchmark.fourtu_truth", "benchmark.tu1208_truth", "benchmark.definition")
MODULE = "benchmark/candidate_v2_calibrated.py"


def _imports(path):
    out = set()
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_truth_blind():
    assert not _imports(MODULE) & set(TRUTH_MODULES)
    src = Path(MODULE).read_text()
    for marker in (".targets.json", "manifests/", "specimen_ground_truth", "load_gt"):
        assert marker not in src


@pytest.mark.parametrize("root", ["api", "jobs", "interpretation", "preprocessing", "ingestion"])
def test_no_production_path_imports_it(root):
    for path in Path(root).rglob("*.py"):
        assert "benchmark.candidate_v2_calibrated" not in _imports(path), path


def test_capability_is_experimental():
    assert gates.CAPABILITY_STATUS["candidate_generation_v2_calibrated"] == gates.EXPERIMENTAL


# ------------------------------------------------------------- synthetic physics
DX, DT, NX, NT, NL = 5.0, 0.03, 161, 400, 9
X = np.arange(NX) * DX
Y = np.arange(NL) * 5.0
T = np.arange(NT) * DT
T0, V = 1.0, 0.12
CAL = {"t0_ns": T0, "velocity_m_per_ns": V, "pick_convention": "peak", "pick_precision_ns": 0.1}


def _ricker(t, f=1.5):
    a = (np.pi * f * t) ** 2
    return (1 - 2 * a) * np.exp(-a)


def _bscan(kind, rng, x0=400.0, t_apex=5.0, half_width=0.0):
    b = 0.02 * rng.standard_normal((NX, NT))
    b += _ricker(T[None, :] - T0) * 2.0                      # direct wave, laterally flat
    for i, x in enumerate(X):
        lat = max(abs(x - x0) - half_width, 0.0) / 1000.0
        tt = T0 + np.sqrt((t_apex - T0) ** 2 + (2 * lat / V) ** 2)
        b[i] += _ricker(T - tt)
    return b


def _volume(kind="hyperbola", seed=0, **kw):
    rng = np.random.default_rng(seed)
    return np.stack([_bscan(kind, rng, **kw) for _ in range(NL)], axis=1)


def _best_near(props, x0=400.0, t0=5.0):
    near = [p for p in props if abs(p["x"] - x0) <= 30 and abs(p["t_ns"] - t0) <= 0.4]
    return max(near, key=lambda p: p["z_row"]) if near else None


def test_without_calibration_no_depth_is_invented():
    res = vc.propose(_volume(), X, Y, T, vc.V2CalParams(), calibration=None)
    assert res["scan"]["physics_basis"] == "uncalibrated"
    assert res["proposals"]
    for p in res["proposals"]:
        assert p["depth_m"] is None
        assert p["physics_basis"].startswith("uncalibrated")


def test_use_calibration_false_ignores_a_supplied_calibration():
    res = vc.propose(_volume(), X, Y, T, vc.V2CalParams(use_calibration=False), calibration=CAL)
    assert res["scan"]["calibration_used"] is None
    assert all(p["depth_m"] is None for p in res["proposals"])


@pytest.mark.parametrize("bad", [{"t0_ns": 1.0, "pick_convention": "peak"},
                                 {**CAL, "velocity_m_per_ns": 0.5}])
def test_an_incomplete_or_unphysical_calibration_is_refused(bad):
    with pytest.raises(ValueError):
        vc.propose(_volume(), X, Y, T, vc.V2CalParams(), calibration=bad)


def test_calibrated_hyperbola_is_explained_by_the_calibrated_velocity():
    res = vc.propose(_volume(), X, Y, T, vc.V2CalParams(), calibration=CAL)
    p = _best_near(res["proposals"])
    assert p is not None
    assert p["physics_basis"] == "calibrated_from_known_geometry"
    assert p["depth_m"] == pytest.approx(V * (p["t_ns"] - T0) / 2)
    assert p["shape"]["velocity_consistency"] > 0.3
    assert p["shape_consistency"] > 0.4


def test_a_wrong_calibration_lowers_the_shape_evidence():
    right = _best_near(vc.propose(_volume(), X, Y, T, vc.V2CalParams(), calibration=CAL)["proposals"])
    wrong = _best_near(vc.propose(_volume(), X, Y, T, vc.V2CalParams(),
                                  calibration={**CAL, "velocity_m_per_ns": 0.24})["proposals"])
    assert wrong["shape_consistency"] < right["shape_consistency"]


def test_a_flat_topped_reflector_is_not_forced_into_a_point_model():
    res = vc.propose(_volume(half_width=60.0), X, Y, T, vc.V2CalParams(), calibration=CAL)
    p = _best_near(res["proposals"])
    assert p is not None
    assert p["shape"]["half_width_mm"] > 0
    assert p["shape_consistency"] > 0.3


def test_components_bounded_and_score_is_declared_combination():
    params = vc.V2CalParams()
    res = vc.propose(_volume(), X, Y, T, params, calibration=CAL)
    dets = vc.select(res, params)
    assert dets
    for d in dets:
        for c in vc.EVIDENCE + vc.PENALTIES:
            assert 0.0 <= d[c] <= 1.0, (c, d[c])
        expect = np.mean([d[k] for k in vc.EVIDENCE]) - vc.PENALTY_WEIGHT * sum(d[k] for k in vc.PENALTIES)
        assert d["final_score"] == pytest.approx(expect)


def test_term_ablation_drops_only_that_term():
    p = vc.V2CalParams().without("shape_consistency")
    assert p.dropped_terms == frozenset({"shape_consistency"})
    with pytest.raises(ValueError):
        vc.V2CalParams().without("magic")


def test_deterministic():
    vol = _volume(seed=3)
    assert vc.detect(vol, X, Y, T, calibration=CAL) == vc.detect(vol, X, Y, T, calibration=CAL)


def test_nms_keeps_one_detection_per_window_per_line():
    params = vc.V2CalParams()
    res = vc.propose(_volume(), X, Y, T, params, calibration=CAL)
    dets = vc.select(res, params)
    rad = vc.NMS_T_PERIODS * res["scan"]["period_ns"]
    for j in range(NL):
        line = [d for d in dets if d["line"] == j]
        for a in line:
            for b in line:
                if a is not b:
                    assert abs(a["x"] - b["x"]) > vc.NMS_X_MM or abs(a["t_ns"] - b["t_ns"]) > rad


# ------------------------------------------------------------- held-out guard
def test_rot90_cannot_be_opened_as_development(monkeypatch):
    from scripts import bam_v2cal_harness as h
    with pytest.raises(h.HeldOutLocked):
        h.CalScan("Pk266", "1_5_GHz_Rot90")


def test_heldout_needs_a_committed_frozen_config(monkeypatch, tmp_path):
    from scripts import bam_v2cal_harness as h
    monkeypatch.setattr(h, "FROZEN_CONFIG", tmp_path / "missing.json")
    with pytest.raises(h.HeldOutLocked):
        h.frozen_commit()
    f = tmp_path / "frozen.json"
    f.write_text("{}")
    monkeypatch.setattr(h, "FROZEN_CONFIG", f)
    with pytest.raises(h.HeldOutLocked):          # exists but not committed
        h.frozen_commit()
