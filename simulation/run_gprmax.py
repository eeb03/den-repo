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

from simulation.analysis import ANALYSIS_VERSION, assess_against_truth
from simulation.scenario import SCENARIOS, CircularTarget, Scenario2D, Soil, to_gprmax_input
from simulation.truth import TRUTH_MODEL_VERSION, build_truth_manifest

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


def _validate(s: Scenario2D, bscan, dt, time_offset, truth, background) -> dict:
    if len(s.targets) != 1:
        # The blind global-max picker is defined for one target per scene.
        # Empty and multi-target scenes are still corpus members with exact
        # truth; they are simply outside what this check can score.
        return {
            "analysis_version": ANALYSIS_VERSION,
            "status": "not_applicable",
            "reason": f"{len(s.targets)} targets; the assessor scores single-target scenes only",
            "pass": None,
        }
    # Both methods, always: see simulation.analysis on why the first one's
    # failure on the reference scene is kept rather than replaced.
    by_method = {
        "mean_trace": assess_against_truth(bscan, dt, time_offset, truth),
        "target_free_reference": assess_against_truth(bscan, dt, time_offset, truth, background),
    }
    return {
        "analysis_version": ANALYSIS_VERSION,
        "status": "scored",
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


def run_scenario(s: Scenario2D, out_root: Path = DEFAULT_OUT) -> dict:
    out = out_root / s.scenario_id
    out.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    bscan, dt, time_offset, input_text = simulate(s)
    if s.targets:
        background, bg_dt, bg_offset, _ = simulate(replace(s, targets=(), materials=()))
        if (bg_dt, bg_offset, background.shape) != (dt, time_offset, bscan.shape):
            raise RuntimeError("target-free twin does not share the B-scan's sampling")
    else:
        background = bscan  # an empty scene is its own target-free twin
    elapsed = time.monotonic() - started

    truth = build_truth_manifest(s)
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
    # Validate only after the expensive solver output is safely on disk.
    validation = _validate(s, bscan, dt, time_offset, truth, background)
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
        "truth_model_version": TRUTH_MODEL_VERSION,
        **_validation_summary(validation),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _validation_summary(validation: dict) -> dict:
    return {
        "analysis_version": validation["analysis_version"],
        "validation_pass": validation["pass"],
        "validation_status": validation["status"],
        "validation_pass_by_method": {
            k: v["pass"] for k, v in validation.get("methods", {}).items()
        },
    }


def rescore(out: Path) -> dict:
    """Re-validate a stored artifact under the current analysis, no solver.

    The previous validation.json is archived under validation_history/, never
    overwritten: a superseded verdict is part of the record. Truth built by
    an older truth model is rebuilt from the scene (geometry cannot change:
    the fingerprint is checked first) and the old file kept in
    truth_history/."""
    manifest = json.loads((out / "manifest.json").read_text())
    previous = json.loads((out / "validation.json").read_text())
    s = Scenario2D(**{**manifest["scenario"],
                      "soil": Soil(**manifest["scenario"]["soil"]),
                      "targets": tuple(CircularTarget(**t) for t in manifest["scenario"]["targets"]),
                      "materials": tuple(Soil(**m) for m in manifest["scenario"].get("materials", ()))})
    if s.fingerprint() != manifest["scenario_fingerprint"]:
        raise RuntimeError(f"{out}: stored scene does not reproduce its fingerprint")
    history = out / "validation_history"
    history.mkdir(exist_ok=True)
    old_version = previous.get("analysis_version", 1)
    (history / f"validation_v{old_version}.json").write_text(json.dumps(previous, indent=2))

    d = np.load(out / "bscan.npz")
    truth = json.loads((out / "truth.json").read_text())
    old_truth_version = truth.get("truth_model_version", 1)
    if old_truth_version != TRUTH_MODEL_VERSION:
        truth_history = out / "truth_history"
        truth_history.mkdir(exist_ok=True)
        (truth_history / f"truth_v{old_truth_version}.json").write_text(json.dumps(truth, indent=2))
        truth = build_truth_manifest(s)
        (out / "truth.json").write_text(json.dumps(truth, indent=2))
        manifest["files"]["truth.json"] = _sha256(out / "truth.json")
        manifest.setdefault("superseded_truth", []).append({"truth_model_version": old_truth_version})
    manifest["truth_model_version"] = TRUTH_MODEL_VERSION
    validation = _validate(s, d["data"].astype(np.float64), float(d["dt"]), float(d["time_offset"]),
                           truth, d["background"].astype(np.float64))
    (out / "validation.json").write_text(json.dumps(validation, indent=2))
    manifest.update(_validation_summary(validation))
    manifest["files"]["validation.json"] = _sha256(out / "validation.json")
    manifest["rescored_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest.setdefault("superseded_validations", []).append(
        {"analysis_version": old_version, "pass": previous.get("pass")})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("scenario_id", choices=sorted(SCENARIOS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--rescore", action="store_true",
                        help="re-validate the stored artifact; do not run the solver")
    args = parser.parse_args(argv)
    if args.rescore:
        manifest = rescore(args.out / args.scenario_id)
    else:
        manifest = run_scenario(SCENARIOS[args.scenario_id], args.out)
    print(json.dumps({k: manifest[k] for k in
                      ("scenario_id", "bscan_shape_samples_traces", "dt_s", "validation_pass")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
