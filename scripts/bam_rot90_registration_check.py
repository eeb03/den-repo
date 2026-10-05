"""
Is the Rot90 volume on the same specimen grid as the Rot00 volume? A
TARGET-FREE registration check, run after the frozen configuration was
committed and before any held-out detection was scored.

    python -m scripts.bam_rot90_registration_check --out evidence/bam/results/rot90_registration_check.json

WHY. The previous Candidate V2 did not use Rot90 because "the grid mapping is
not established in this repository". Scoring Rot90 against the drawn target
positions assumes the Rot90 `.npy` volume uses the same (x, y) specimen grid as
Rot00. If it were mirrored, every target window would be in the wrong place.

WHAT IS COMPARED. For each specimen, a depth-integrated map of conditioned
energy (dewow, running-median background removal along x over 81 traces,
Hilbert envelope, summed over 2 ns .. end - 0.5 ns) from Rot00 and from Rot90,
correlated under the four discrete grid hypotheses: identity, x mirrored,
y mirrored, both. Nothing reads the target list or a detection result, and the
detector cannot change: its configuration is already frozen. The back-wall
orientation fit (`calibration` in the held-out report) is an independent
target-free check of the x axis.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import hilbert

from benchmark.bam_ingest import load_scan, load_volume
from scripts.bam_v2cal_harness import frozen_commit

SPECIMENS = ("Pk266", "Pk401", "Pk050")
ANTENNAS = ("1_5_GHz", "2_6_GHz")


def energy_map(vol, dt):
    n_x, n_l, n_t = vol.shape
    i0, i1 = int(2.0 / dt), n_t - int(0.5 / dt)
    out = np.zeros((n_x, n_l))
    for j in range(n_l):
        x = vol[:, j, :].astype(float)
        x = x - uniform_filter1d(x, size=max(3, int(round(2.0 / dt))), axis=1, mode="nearest")
        x = x - median_filter(x, size=(81, 1), mode="nearest")
        out[:, j] = np.abs(hilbert(x, axis=1))[:, i0:i1].sum(axis=1)
    return out


def corr(a, b):
    a = (a - a.mean()) / (a.std() + 1e-12)
    b = (b - b.mean()) / (b.std() + 1e-12)
    return float((a * b).mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    commit = frozen_commit()
    res = {"frozen_config_commit": commit, "method": __doc__, "results": {}}
    for spec in SPECIMENS:
        for ant in ANTENNAS:
            maps = {}
            for rot in ("Rot00", "Rot90"):
                s = load_scan(spec, f"{spec}_3D_Dataset_{ant}_{rot}")
                maps[rot] = energy_map(load_volume(s), float(s.grid.z[1] - s.grid.z[0]))
            a, b = maps["Rot00"], maps["Rot90"]
            hyp = {"identity": corr(a, b), "x_mirrored": corr(a, b[::-1, :]),
                   "y_mirrored": corr(a, b[:, ::-1]), "both_mirrored": corr(a, b[::-1, ::-1])}
            best = max(hyp, key=hyp.get)
            res["results"][f"{spec}_{ant}"] = {"correlation": {k: round(v, 4) for k, v in hyp.items()},
                                               "best": best}
            print(spec, ant, res["results"][f"{spec}_{ant}"], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
