"""
Write the KEC testbed targets into the Yesan manifest.

The targets are not hand-edited in the JSON: they are generated from Subterra's
transcription of the KEC report (evidence/yesan/kec_testbed_targets.csv) by
`evidence.yesan_kec.manifest_targets`, so the CSV stays the single source and a
test can check that the manifest has not drifted from it.

Usage:  venv/bin/python scripts/build_yesan_manifest_targets.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.targets import MANIFEST_DIR, load_manifest_dict  # noqa: E402
from evidence.yesan_kec import manifest_targets  # noqa: E402

PATH = MANIFEST_DIR / "yesan-fullscale.targets.json"


def main():
    d = json.loads(PATH.read_text())
    d["targets"] = manifest_targets()
    load_manifest_dict(d)  # refuse to write a manifest the loader would reject
    PATH.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(d['targets'])} targets to {PATH}")


if __name__ == "__main__":
    main()
