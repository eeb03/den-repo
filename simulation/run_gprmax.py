"""
Run a scenario through gprMax and write a self-describing simulation artifact.

Runs ONLY inside the docker/gprmax image (the platform image has no solver):

    docker run --rm -v "$PWD:/app" subterra-gprmax:4.0.0 \\
        python -m simulation.run_gprmax gprmax_reference_cylinder_bscan_2d

Writes to artifacts/simulation/<scenario_id>/:
    model.in         the exact gprMax input that was run
    bscan.npz        data (samples x traces, Ez), dt, time_offset, tx_x, rx_x,
                     and `background`: the same model with no targets
    truth.json       exact geometry + predicted travel times (truth.py)
    validation.json  measured vs predicted, pre-registered tolerances (analysis.py)
    manifest.json    provenance: solver version, scene fingerprint, checksums
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np

from simulation.analysis import assess_against_truth
from simulation.scenario import SCENARIOS, Scenario2D, to_gprmax_input
from simulation.truth import build_truth_manifest

DEFAULT_OUT = Path("artifacts/simulation")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trace_files(workdir: Path, stem: str, n: int) -> list[Path]:
    """The per-trace output files, ordered by trace number, all n of them."""
    found = []
    for p in workdir.iterdir():
        m = re.fullmatch(rf"{re.escape(stem)}(\d+)\.h5", p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort()
    numbers = [k for k, _ in found]
    if numbers != list(range(1, n + 1)):
        raise RuntimeError(f"expected trace files 1..{n} for {stem!r}, found {numbers}")
    return [p for _, p in found]


def simulate(s: Scenario2D) -> tuple[np.ndarray, float, float, str]:
    """Run the solver. Returns (bscan[samples, traces], dt, time_offset, input_text)."""
    import gprMax
    from gprMax.toolboxes.Utilities.outputfiles_merge import get_output_data

    input_text = to_gprmax_input(s)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        in_path = workdir / "model.in"
        in_path.write_text(input_text)
        gprMax.run(inputfile=str(in_path), n=s.n_traces, hide_progress_bars=True)

        columns, dts, offsets = [], set(), set()
        for f in _trace_files(workdir, "model", s.n_traces):
            data, dt, offset = get_output_data(str(f), 1, "Ez", return_time_offset=True)
            columns.append(np.asarray(data, dtype=np.float64).reshape(-1))
            dts.add(float(dt))
            offsets.add(float(offset))
    if len(dts) != 1 or len(offsets) != 1:
        raise RuntimeError(f"traces disagree on sampling: dt={dts} offset={offsets}")
    return np.stack(columns, axis=1), dts.pop(), offsets.pop(), input_text


def run(scenario_id: str, out_root: Path = DEFAULT_OUT) -> dict:
    s = SCENARIOS[scenario_id]
    out = out_root / s.scenario_id
    out.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    bscan, dt, time_offset, input_text = simulate(s)
    background, bg_dt, bg_offset, _ = simulate(replace(s, targets=()))
    elapsed = time.monotonic() - started
    if (bg_dt, bg_offset, background.shape) != (dt, time_offset, bscan.shape):
        raise RuntimeError("target-free twin does not share the B-scan's sampling")

    truth = build_truth_manifest(s)
    # Both methods, always: see simulation.analysis on why the first one's
    # failure on the reference scene is kept rather than replaced.
    by_method = {
        "mean_trace": assess_against_truth(bscan, dt, time_offset, truth),
        "target_free_reference": assess_against_truth(bscan, dt, time_offset, truth, background),
    }
    validation = {
        "methods": by_method,
        "preregistration": {
            "mean_trace": "before the first solver run (2026-10-12)",
            "target_free_reference": (
                "after the reference scene's mean_trace failure; post hoc for "
                "gprmax_reference_cylinder_bscan_2d, pre-registered for later scenes"
            ),
        },
        "pass": by_method["target_free_reference"]["pass"],
        "pass_basis": "target_free_reference",
    }

    (out / "model.in").write_text(input_text)
    np.savez_compressed(
        out / "bscan.npz",
        data=bscan.astype(np.float32),
        dt=dt,
        time_offset=time_offset,
        tx_x=np.asarray(truth["antennas"]["tx_x_m"]),
        rx_x=np.asarray(truth["antennas"]["rx_x_m"]),
        background=background.astype(np.float32),
    )
    (out / "truth.json").write_text(json.dumps(truth, indent=2))
    (out / "validation.json").write_text(json.dumps(validation, indent=2))

    manifest = {
        "scenario_id": s.scenario_id,
        "scenario_fingerprint": s.fingerprint(),
        "scenario": s.to_dict(),
        "simulated": True,
        "solver": {"name": "gprMax", "version": version("gprMax"), "field_component": "Ez"},
        "runtime": {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "wall_seconds": round(elapsed, 2),
        },
        "bscan_shape_samples_traces": list(bscan.shape),
        "dt_s": dt,
        "time_offset_s": time_offset,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": {
            name: _sha256(out / name)
            for name in ("model.in", "bscan.npz", "truth.json", "validation.json")
        },
        "validation_pass": validation["pass"],
        "validation_pass_by_method": {k: v["pass"] for k, v in by_method.items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("scenario_id", choices=sorted(SCENARIOS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    manifest = run(args.scenario_id, args.out)
    print(json.dumps({k: manifest[k] for k in
                      ("scenario_id", "bscan_shape_samples_traces", "dt_s", "validation_pass")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
