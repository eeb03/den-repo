"""
How much noise a real instrument adds, measured on the platform's main real
dataset (4TU utility survey), so simulated lines can carry the same.

The solver's output is noise-free. A detector that normalises by its own
background spread (the ring z-score, the hyperbola stack) has no meaningful
false-alarm rate on noise-free data: either the spread is zero and nothing
is reliable, or it is float round-off and anything is. So the benchmark's
noisy condition adds white Gaussian noise at a level taken from real lines,
never chosen to make a result come out.

MEASUREMENT, per trace of a raw 4TU line:
* reference amplitude = max |a| in the first quarter of the window (the
  direct ground wave dominates there);
* incoherent noise = std of the difference between ADJACENT traces over the
  last 10% of the window, divided by sqrt(2). Differencing cancels anything
  laterally coherent (layers, slow clutter) that a plain late-time std would
  count as noise, so this is closer to receiver noise -- but residual
  incoherent scattering still counts, so it is an UPPER bound.
The ratio noise / reference is reported as its median over every trace of
the first N lines in sorted path order (deterministic).

    python -m simulation.noise_calibration --lines 50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from converters.segy_endian import BIG, LITTLE, LittleEndianSegyFile, detect_endianness

FOURTU_ROOT = Path("datasets/raw/4tu")


def read_traces(path: Path) -> np.ndarray:
    """(n_traces, n_samples), decoded as scripts/characterise_4tu.py and the
    converter decode it: 4TU files are little-endian, which segyio rejects."""
    order, _ = detect_endianness(path)
    if order == BIG:
        import segyio
        with segyio.open(str(path), "r", ignore_geometry=True) as f:
            return np.array([f.trace[i] for i in range(f.tracecount)], dtype=float)
    with LittleEndianSegyFile(path, order=LITTLE) as f:
        return np.array([f.trace[i] for i in range(f.tracecount)], dtype=float)


def line_ratios(path: Path) -> np.ndarray:
    data = read_traces(path)
    if data.shape[0] < 3:
        return np.array([])
    n = data.shape[1]
    ref = np.abs(data[:, : n // 4]).max(axis=1)
    late = data[:, int(0.9 * n):]
    noise = np.diff(late, axis=0).std(axis=1) / np.sqrt(2)
    ref = ref[1:]
    ok = ref > 0
    return noise[ok] / ref[ok]


def calibrate(n_lines: int, root: Path = FOURTU_ROOT) -> dict:
    paths = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".sgy", ".segy"})[:n_lines]
    ratios = np.concatenate([line_ratios(p) for p in paths])
    return {
        "dataset": "4TU GPR utility survey (raw)",
        "lines": len(paths),
        "traces": int(ratios.size),
        "method": "std of adjacent-trace difference over the last 10% of the window / sqrt(2), "
                  "over max |a| in the first quarter; median over traces (upper bound on receiver noise)",
        "noise_to_direct_wave_ratio_median": float(np.median(ratios)),
        "noise_to_direct_wave_ratio_p10": float(np.percentile(ratios, 10)),
        "noise_to_direct_wave_ratio_p90": float(np.percentile(ratios, 90)),
        "first_line": str(paths[0]) if paths else None,
        "last_line": str(paths[-1]) if paths else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines", type=int, default=50)
    args = parser.parse_args(argv)
    print(json.dumps(calibrate(args.lines), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
