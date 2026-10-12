"""
Build (or extend) a simulated corpus from the seeded generator.

Runs inside the docker/gprmax image:

    docker run --rm -v "$PWD:/app" subterra-gprmax:4.0.0 \\
        python -m simulation.build_corpus --seed 0 --count 20

Writes artifacts/simulation/corpus_s<seed>/<scenario_id>/ per scene (see
run_gprmax) and corpus_s<seed>/index.json summarising every scene built so
far. Resumable: a scene whose manifest already carries the same scene
fingerprint is skipped, so a corpus can grow across sessions (or across free
Kaggle/Colab quotas) without recomputing anything. A scene whose fingerprint
changed -- i.e. the generator changed -- is rebuilt, never silently kept;
one scored under an older analysis version is rescored from its stored
B-scan, with the old verdict archived.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from simulation import generator
from simulation.analysis import ANALYSIS_VERSION
from simulation.generator import SPLIT_VERSION, generate, geometry_group, split_of
from simulation.run_gprmax import DEFAULT_OUT, rescore, run_scenario
from simulation.truth import TRUTH_MODEL_VERSION

# Thresholds used only to REPORT soil balance; the generator draws eps_r
# uniformly and never sees these.
SOIL_CLASSES = (("dry", 3.0, 8.0), ("moist", 8.0, 15.0), ("wet", 15.0, 25.0))


def soil_class(eps: float) -> str:
    return next(name for name, lo, hi in SOIL_CLASSES if lo <= eps <= hi)


def _generator_settings() -> dict:
    names = [n for n in dir(generator) if n.isupper() and not n.startswith("_")]
    return {n: getattr(generator, n) for n in sorted(names)
            if isinstance(getattr(generator, n), (int, float, str, tuple, dict))}


def _scene_entry(s, manifest: dict, seed: int, index: int) -> dict:
    """Everything needed to audit one scene without opening its folder."""
    materials = {m.name: m for m in s.materials}
    return {
        "seed": seed,
        "index": index,
        "fingerprint": s.fingerprint(),
        "geometry_group": geometry_group(s),
        "split": split_of(s),
        "centre_frequency_hz": s.centre_frequency,
        "soil_relative_permittivity": s.soil.relative_permittivity,
        "soil_conductivity_s_per_m": s.soil.conductivity,
        "soil_class": soil_class(s.soil.relative_permittivity),
        "cell_m": s.cell,
        "n_traces": s.n_traces,
        "time_window_s": s.time_window,
        "n_targets": len(s.targets),
        "labels": [t.label for t in s.targets],
        "targets": [{
            "target_id": t.target_id, "label": t.label, "material": t.material,
            "material_relative_permittivity": (materials[t.material].relative_permittivity
                                               if t.material in materials else None),
            "centre_x_m": t.centre_x, "centre_y_m": t.centre_y, "radius_m": t.radius,
            "depth_to_top_m": s.surface_y - (t.centre_y + t.radius),
            "depth_to_centre_wavelengths": (s.surface_y - t.centre_y) / (s.soil.velocity / s.centre_frequency),
        } for t in s.targets],
        "validation_status": manifest["validation_status"],
        "validation_pass": manifest["validation_pass"],
        "analysis_version": manifest["analysis_version"],
        "truth_model_version": manifest.get("truth_model_version", 1),
        "solver": manifest["solver"],
        "wall_seconds": manifest["runtime"]["wall_seconds"],
        "files_sha256": manifest["files"],
    }


def _existing_manifest(out: Path, fingerprint: str) -> dict | None:
    path = out / "manifest.json"
    if not path.exists():
        return None
    manifest = json.loads(path.read_text())
    return manifest if manifest.get("scenario_fingerprint") == fingerprint else None


def build(seed: int, count: int, start: int = 0, out_root: Path = DEFAULT_OUT) -> dict:
    corpus = out_root / f"corpus_s{seed}"
    corpus.mkdir(parents=True, exist_ok=True)
    index_path = corpus / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"scenes": {}}
    index.update({
        "seed": seed,
        "split_version": SPLIT_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "truth_model_version": TRUTH_MODEL_VERSION,
        "generator_settings": _generator_settings(),
        "simulated": True,
    })

    for i, s in enumerate(generate(seed, count, start), start=start):
        manifest = _existing_manifest(corpus / s.scenario_id, s.fingerprint())
        if manifest is None:
            manifest = run_scenario(s, corpus)
        elif (manifest.get("analysis_version", 1) != ANALYSIS_VERSION
              or manifest.get("truth_model_version", 1) != TRUTH_MODEL_VERSION):
            manifest = rescore(corpus / s.scenario_id)
        index["scenes"][s.scenario_id] = _scene_entry(s, manifest, seed, i)
        index_path.write_text(json.dumps(index, indent=2, sort_keys=True))
        entry = index["scenes"][s.scenario_id]
        print(json.dumps({"scene": s.scenario_id, **{k: entry[k] for k in (
            "split", "centre_frequency_hz", "labels", "validation_status", "validation_pass")}}),
            flush=True)
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a simulated GPR corpus.")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    build(args.seed, args.count, args.start, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
