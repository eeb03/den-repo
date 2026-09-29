"""
Detection cannot see target truth.

Three independent checks, because each alone has a hole:
  1. STATIC: no module on the detection path imports a truth module or names
     a manifest file (AST, so a comment cannot fail it and an import cannot
     hide from it).
  2. PROCESS: importing the detection entry point in a fresh interpreter
     loads no truth module (catches a transitive import the AST check of one
     file would miss).
  3. RUNTIME: a real detection run with every file read audited, refusing any
     read of a manifest or truth file (catches a path built at runtime).
And the artifact itself cannot carry a label.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.bam_ingest import DEFAULT_ROOT
from benchmark.predictions import PredictionArtifact, PredictionArtifactError

DETECTION_PATH = ("benchmark/blind_detection.py", "benchmark/detection.py",
                  "benchmark/predictions.py", "benchmark/bam_ingest.py")

TRUTH_MODULES = ("benchmark.targets", "benchmark.target_scoring", "benchmark.ground_truth",
                 "benchmark.bam_truth", "benchmark.association", "benchmark.scoring",
                 "benchmark.fourtu_truth", "benchmark.tu1208_truth", "benchmark.definition")

TRUTH_FILE_MARKERS = ("manifests", ".targets.json", "_targets.json")


def imports_of(path):
    tree = ast.parse(Path(path).read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def strings_of(path):
    return [n.value for n in ast.walk(ast.parse(Path(path).read_text()))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


@pytest.mark.parametrize("path", DETECTION_PATH)
def test_the_detection_path_imports_no_truth_module(path):
    leaked = {m for m in imports_of(path) if m in TRUTH_MODULES}
    assert not leaked, f"{path} imports {leaked}"


@pytest.mark.parametrize("path", DETECTION_PATH)
def test_the_detection_path_names_no_truth_file(path):
    code_strings = [s for s in strings_of(path) if "\n" not in s]   # not docstrings
    hits = [s for s in code_strings for m in TRUTH_FILE_MARKERS if m in s]
    assert not hits, f"{path} names {hits}"


def test_the_truth_side_imports_no_detector():
    for path in ("benchmark/targets.py",):
        mods = imports_of(path)
        assert not any(m.startswith(("interpretation", "preprocessing")) or
                       m in ("benchmark.detection", "benchmark.predictions",
                             "benchmark.blind_detection") for m in mods), mods


def test_a_fresh_detection_process_loads_no_truth_module():
    code = ("import sys, benchmark.blind_detection; "
            f"print(sorted(m for m in sys.modules if m in {TRUTH_MODULES!r}))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True).stdout.strip()
    assert out == "[]", out


@pytest.mark.skipif(not (DEFAULT_ROOT / "Pk266_Dataset.zip").exists(),
                    reason="BAM archive not present")
def test_a_real_detection_run_never_opens_a_truth_file():
    code = f"""
import sys
MARKERS = {TRUTH_FILE_MARKERS!r}
def hook(event, args):
    if event == "open" and isinstance(args[0], str) and any(m in args[0] for m in MARKERS):
        raise PermissionError("detection tried to read truth: " + args[0])
sys.addaudithook(hook)
from benchmark.blind_detection import run_bam
art = run_bam("Pk266", "1_5_GHz_Rot00", line_indices=[0, 80, 160])
bad = [m for m in sys.modules if m in {TRUTH_MODULES!r}]
assert not bad, bad
print(len(art.predictions), len(art.lines))
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().split()[-1] == "3"


def test_an_artifact_cannot_carry_a_label():
    base = {"schema": "subterra.predictions.v1", "dataset_id": "d", "acquisition_id": "a",
            "frame_id": "f", "frame_units": "m", "detector": {}, "preprocessing": {},
            "input_sha256": "x", "timing": {}, "lines": [{"line_id": "A", "start": [0.0],
                                                          "end": [1.0]}],
            "predictions": [{"prediction_id": "p", "line_id": "A", "position": [0.5]}]}
    assert PredictionArtifact.from_dict(base).predictions[0].prediction_id == "p"
    for where, key in (("artifact", "targets"), ("prediction", "target_id"),
                       ("prediction", "label"), ("detail", "ground_truth")):
        d = {**base, "predictions": [dict(base["predictions"][0])]}
        if where == "artifact":
            d[key] = []
        elif where == "prediction":
            d["predictions"][0][key] = "T1"
        else:
            d["predictions"][0]["detail"] = {key: True}
        with pytest.raises(PredictionArtifactError, match=key):
            PredictionArtifact.from_dict(d)


def test_an_artifact_has_no_field_that_could_hold_truth():
    fields = set(PredictionArtifact.__dataclass_fields__)
    assert not fields & {"targets", "labels", "ground_truth", "truth", "matches"}
