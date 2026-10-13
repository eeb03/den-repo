"""
Plan-View Linearity V1 primitives (docs/pvl-v1-l1-protocol.md) on synthetic
candidate sets only: linking, descriptors, the three-way label and the
in-line width. No BAM, 4TU or corpus data is read.
"""
import inspect
import math

import numpy as np

from scripts.pvl_v1 import apply, describe, inline_width_m, label, link

CFG = {"G": 1, "dx": 0.25, "dt": 0.5, "L": 3, "W": 2}
LAM = 86.0          # mm, concrete at 1.5 GHz
T = 1 / 1.5         # ns


def _c(line, x, t=4.0, W=0.5, z=10.0):
    return {"line": line, "y_mm": 5.0 * line, "x_mm": x, "t_ns": t, "abs_z": z, "lam_mm": LAM, "W": W}


def test_a_crossing_line_is_linear_even_when_oblique():
    cands = [_c(j, 250 + 0.5 * 5.0 * j) for j in range(0, 120)]          # 26.6 deg from the normal
    tracks = link(cands, CFG, T)
    assert len(tracks) == 1
    d = describe(tracks[0])
    assert d["n_lines"] == 120 and label(d, CFG) == "linear"
    assert math.isclose(d["L"], math.hypot(595, 297.5) / LAM, rel_tol=1e-9)


def test_wide_inline_response_is_planar_however_long():
    tracks = link([_c(j, 250, W=5.0) for j in range(0, 120)], CFG, T)
    assert label(describe(tracks[0]), CFG) == "planar"


def test_short_response_is_compact():
    tracks = link([_c(j, 750) for j in range(60, 64)], CFG, T)        # 15 mm < 3 lambda
    assert label(describe(tracks[0]), CFG) == "compact"


def test_time_and_lateral_tolerances_split_tracks():
    a = [_c(j, 250, t=4.0) for j in range(0, 20)]
    b = [_c(j, 250, t=6.0) for j in range(0, 20)]                       # 2 ns later: a different event
    assert len(link(a + b, CFG, T)) == 2
    far = [_c(j, 250 if j % 2 else 900) for j in range(0, 20)]
    assert len(link(far, CFG, T)) >= 2


def test_gaps_beyond_G_are_not_bridged():
    cands = [_c(j, 250) for j in (0, 1, 2, 10, 11, 12)]
    assert len(link(cands, CFG, T)) == 2
    assert len(link(cands, {**CFG, "G": 8}, T)) == 1


def test_inline_width_half_maximum():
    env = np.zeros((101, 50))
    env[:, 25] = np.exp(-0.5 * ((np.arange(101) - 50) / 4.0) ** 2)
    w = inline_width_m(env, 50, 25, 0, 0.005)
    assert math.isclose(w, 0.005 * 8, abs_tol=0.0051)               # FWHM of sigma 4 = 9.4 traces -> 8 steps


def test_linking_and_labelling_read_no_truth():
    for fn in (link, describe, label, apply):
        src = inspect.getsource(fn)
        assert "truth" not in src and "objects(" not in src and "calibration(" not in src
