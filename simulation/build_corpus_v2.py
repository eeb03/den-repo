"""
Build (or resume) the fresh V2 evaluation corpus (docs/hyperbola-v2-experiment.md §4):

    docker run --rm -v "$PWD:/app" -w /app subterra-gprmax:4.0.0 \\
        python -m simulation.build_corpus_v2 --seed 1

Writes artifacts/simulation/corpus_s<seed>_v2/<scenario_id>/ and index.json, in the
same per-scene format as build_corpus (so simulation.interface.load_line reads
it), with each entry carrying its family and its V2 split (dev / eval).
Resumable by scene fingerprint, like build_corpus.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from simulation import generator_v2
from simulation.analysis import ANALYSIS_VERSION
from simulation.build_corpus import _existing_manifest, _scene_entry
from simulation.generator_v2 import FAMILIES, SCENES_PER_FAMILY, generate_scene_v2, plan, v2_split
from simulation.run_gprmax import DEFAULT_OUT, rescore, run_scenario
from simulation.scenario import CLUTTER_PREFIX
from simulation.truth import TRUTH_MODEL_VERSION


def _settings() -> dict:
    return {n: getattr(generator_v2, n) for n in sorted(dir(generator_v2))
            if n.isupper() and isinstance(getattr(generator_v2, n), (int, float, str, tuple, dict))}


def build(seed: int, per_family: int = SCENES_PER_FAMILY, out_root: Path = DEFAULT_OUT,
          families: tuple[str, ...] = FAMILIES) -> dict:
    corpus = out_root / f"corpus_s{seed}_v2"
    corpus.mkdir(parents=True, exist_ok=True)
    index_path = corpus / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"scenes": {}}
    index.update({"seed": seed, "corpus": "v2", "split_scheme": "v2: sha256(family:seed:index), dev 30 / eval 70",
                  "analysis_version": ANALYSIS_VERSION, "truth_model_version": TRUTH_MODEL_VERSION,
                  "generator_v2_settings": _settings(), "simulated": True})
    for family, i in plan(seed, per_family):
        if family not in families:
            continue
        s = generate_scene_v2(family, seed, i)
        manifest = _existing_manifest(corpus / s.scenario_id, s.fingerprint())
        if manifest is None:
            manifest = run_scenario(s, corpus)
        elif (manifest.get("analysis_version", 1) != ANALYSIS_VERSION
              or manifest.get("truth_model_version", 1) != TRUTH_MODEL_VERSION):
            manifest = rescore(corpus / s.scenario_id)
        entry = _scene_entry(s, manifest, seed, i)
        entry.update({
            "family": family,
            "split": v2_split(family, seed, i),
            "geometry_group": f"{family}:{seed}:{i}",
            "n_scored_targets": sum(not t.target_id.startswith(CLUTTER_PREFIX) for t in s.targets),
            "n_clutter": sum(t.target_id.startswith(CLUTTER_PREFIX) for t in s.targets),
            "layer": None if s.layer is None else {"interface_depth_m": s.surface_y - s.layer.interface_y,
                                                    "relative_permittivity": s.layer.material.relative_permittivity},
        })
        index["scenes"][s.scenario_id] = entry
        index_path.write_text(json.dumps(index, indent=2, sort_keys=True))
        # Deliberately prints no result beyond the build status: the eval split
        # is not looked at before the freeze.
        print(json.dumps({"scene": s.scenario_id, "family": family, "split": entry["split"],
                          "wall_seconds": entry["wall_seconds"]}), flush=True)
    return index


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the V2 hard-case corpus.")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--per-family", type=int, default=SCENES_PER_FAMILY)
    p.add_argument("--families", default=",".join(FAMILIES))
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    build(args.seed, args.per_family, args.out, tuple(args.families.split(",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
