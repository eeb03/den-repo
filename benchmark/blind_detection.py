"""
The blind half of a benchmark run: dataset in, prediction artifact out.

This module is the detection path and nothing else. It imports the dataset
reader, the unchanged detector and the artifact format -- never a truth
module, a manifest, or the scorer. `tests/test_blind_benchmark.py` imports it
in a fresh interpreter and checks that no truth module was loaded, and runs a
detection with manifest reads made to fail.

    python -m benchmark.blind_detection Pk266 1_5_GHz_Rot00 artifacts/bam/predictions.json
"""
from __future__ import annotations

import sys
from pathlib import Path

from benchmark.bam_ingest import DEFAULT_ROOT, load_scan, load_volume
from benchmark.detection import detect_scan
from benchmark.predictions import PredictionArtifact, bam_artifact


def bam_frame_id(specimen_id: str) -> str:
    """The specimen frame the BAM grid is expressed in. A naming convention of
    the ACQUISITION side; a truth manifest declares a frame with this id if its
    targets are expressed in the same frame, and the scorer checks equality."""
    return f"bam:{specimen_id}:specimen_mm"


def run_bam(specimen_id: str, scan_suffix: str, root: Path = DEFAULT_ROOT,
            line_indices=None) -> PredictionArtifact:
    """Run the UNCHANGED detector over a BAM scan, with its default parameters."""
    scan = load_scan(specimen_id, f"{specimen_id}_3D_Dataset_{scan_suffix}", root=root)
    volume = load_volume(scan, root=root)
    lines = list(range(volume.shape[1])) if line_indices is None else list(line_indices)
    run = detect_scan(scan, volume, line_indices=lines)
    del volume
    return bam_artifact(scan, run, bam_frame_id(specimen_id), lines)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    specimen, suffix, out = argv[0], argv[1], Path(argv[2])
    artifact = run_bam(specimen, suffix)
    artifact.write(out)
    print(f"{artifact.acquisition_id}: {len(artifact.predictions)} predictions on "
          f"{len(artifact.lines)} lines -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
