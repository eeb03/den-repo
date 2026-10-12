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

from simulation.analysis import ANALYSIS_VERSION
from simulation.generator import generate, split_of
from simulation.run_gprmax import DEFAULT_OUT, rescore, run_scenario


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
    index = json.loads(index_path.read_text()) if index_path.exists() else {"seed": seed, "scenes": {}}

    for s in generate(seed, count, start):
        manifest = _existing_manifest(corpus / s.scenario_id, s.fingerprint())
        if manifest is None:
            manifest = run_scenario(s, corpus)
        elif manifest.get("analysis_version", 1) != ANALYSIS_VERSION:
            manifest = rescore(corpus / s.scenario_id)
        index["scenes"][s.scenario_id] = {
            "fingerprint": s.fingerprint(),
            "split": split_of(s),
            "centre_frequency_hz": s.centre_frequency,
            "soil_relative_permittivity": s.soil.relative_permittivity,
            "n_targets": len(s.targets),
            "labels": [t.label for t in s.targets],
            "validation_status": manifest["validation_status"],
            "validation_pass": manifest["validation_pass"],
            "wall_seconds": manifest["runtime"]["wall_seconds"],
        }
        index_path.write_text(json.dumps(index, indent=2, sort_keys=True))
        print(json.dumps({"scene": s.scenario_id, **index["scenes"][s.scenario_id]}), flush=True)
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
