"""
Front-end Phase 2 primitives (docs/frontend-phase2-bc-protocol.md) on synthetic
arrays only: arm B's preprocessing and arm C's hysteresis growth. No BAM data.
"""
import numpy as np

from scripts.frontend_phase2 import _sign_p, grow, preprocess_b


def test_preprocess_b_mutes_early_time_and_removes_flat_events():
    n_tr, n_s = 201, 300
    t = np.arange(n_s) * 0.05e-9
    tr = np.zeros((n_tr, n_s))
    tr[:, 100] = 5.0                       # flat reflector across the whole line
    tr[100, 200] = 3.0                     # compact event on one trace
    tr[:, 10] = 9.0                        # early (direct-wave) energy
    out = preprocess_b(tr, t, 0.0, 1e-9, 2.0, 41)
    assert np.allclose(out[:, 10], 0.0)                     # muted: 0.5 ns < t0 + 2T - 0.5T
    assert np.abs(out[:, 100]).max() < 1e-9                 # flat event removed by the lateral median
    assert out[100, 200] == 3.0                             # compact event kept, after the mute


def _res(z_lines, z_star=10.0, v=1.0e8):
    lines = []
    for z in z_lines:
        lines.append({"z": z.astype(np.float32), "v_hat": np.full(z.shape, v, np.float32), "z_star": z_star,
                      "kept": [], "cpu_s": 0.0})
    return {"scan": "1_5_GHz_Rot00", "lines": lines, "x_mm": np.arange(z_lines[0].shape[1]) * 5.0,
            "t0_canon_ns": 0.0, "dt_canon_ns": 0.033}


def test_growth_follows_a_consistent_ridge_above_alpha_z_star():
    n = 9
    zs = [np.zeros((60, 40)) for _ in range(n)]
    for z in zs:
        z[30, 20] = 6.0                      # 0.6 z* on every line
    res = _res(zs)
    res["lines"][4]["kept"] = [{"sample": 30, "trace": 20, "z": 12.0, "v": 1.0e8}]
    zs_seed = res["lines"][4]["z"]
    zs_seed[30, 20] = 12.0
    out, multi = grow(res, {"G": 1, "dx": 0.25, "dt": 0.25}, 0.5)
    assert multi == 1 and all(len(o) == 1 for o in out)
    out, multi = grow(res, {"G": 1, "dx": 0.25, "dt": 0.25}, 0.7)   # 6 < 0.7 * 10
    assert multi == 0 and sum(len(o) for o in out) == 1


def test_growth_does_not_jump_beyond_G():
    zs = [np.zeros((60, 40)) for _ in range(7)]
    for j in (0, 1, 2, 5):
        zs[j][30, 20] = 9.0
    res = _res(zs)
    res["lines"][0]["kept"] = [{"sample": 30, "trace": 20, "z": 12.0, "v": 1.0e8}]
    out, _ = grow(res, {"G": 1, "dx": 0.25, "dt": 0.25}, 0.5)
    assert [len(o) for o in out] == [1, 1, 1, 0, 0, 0, 0]
    out, _ = grow(res, {"G": 3, "dx": 0.25, "dt": 0.25}, 0.5)
    assert [len(o) for o in out] == [1, 1, 1, 0, 0, 1, 0]          # line 5 is 3 lines from line 2


def test_sign_test():
    assert _sign_p(3, 3) == 1 / 8 and _sign_p(0, 3) == 1.0
