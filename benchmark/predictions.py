"""
The prediction artifact: what a detector produced, written before any truth
is read.

    detect(dataset) -> PredictionArtifact -> JSON on disk
    score(PredictionArtifact, TargetManifest, MatchRule)   (benchmark.target_scoring)

BLIND BY CONSTRUCTION. This module imports no truth module and no manifest,
and an artifact has no field that could hold a label: `from_dict` refuses
truth-shaped keys by name. `tests/test_blind_benchmark.py` checks the imports
of every module on the detection path, and runs a detection with manifest
reads made to fail.

RADAR QUANTITIES LIVE HERE, AND ONLY HERE. Two-way time, the time-axis
origin, time-zero status, velocity and any radar-derived depth are recorded
with their provenance, so the scorer can decide whether a depth comparison is
supported. A radar depth is never copied into truth.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = "subterra.predictions.v1"

#: Keys that would mean truth had leaked into an artifact.
_TRUTH_KEYS = frozenset({"target_id", "targets", "label", "labels", "ground_truth", "truth",
                         "matched", "is_true_positive", "true_positive", "target"})


class PredictionArtifactError(ValueError):
    """A malformed artifact, or one carrying something a prediction cannot."""


@dataclass(frozen=True)
class AcquisitionLine:
    """One survey line's geometry in the artifact's frame. For a 2-D frame it
    is a segment; for a survey_line frame the line IS the frame (start/end are
    1-D distances)."""
    line_id: str
    start: tuple
    end: tuple

    @property
    def length(self) -> float:
        return sum((b - a) ** 2 for a, b in zip(self.start, self.end)) ** 0.5


@dataclass(frozen=True)
class Prediction:
    prediction_id: str
    line_id: str
    position: tuple
    peak_two_way_time_ns: Optional[float] = None
    #: Only with the velocity/time-zero it was derived under (see TimingProvenance).
    radar_depth: Optional[float] = None
    score: Optional[float] = None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TimingProvenance:
    """How any radar time/depth in this artifact was constructed."""
    axis: str = "two_way_time_ns"
    time_axis_origin: str = "instrument time-zero"
    #: not_applied | declared | measured | derived
    time_zero_status: str = "not_applied"
    time_zero_correction_ns: Optional[float] = None
    velocity_m_per_ns: Optional[float] = None
    #: none | converter_default | declared | measured
    velocity_source: str = "none"
    #: The physical surface a radar depth is referenced to, if DECLARED.
    depth_reference_surface: Optional[str] = None
    depth_units: Optional[str] = None


@dataclass(frozen=True)
class PredictionArtifact:
    dataset_id: str
    acquisition_id: str
    frame_id: str
    frame_units: str
    detector: dict
    preprocessing: dict
    input_sha256: str
    timing: TimingProvenance
    lines: tuple
    predictions: tuple
    frame_crs: Optional[str] = None
    antenna_frequency_mhz: Optional[float] = None
    antenna_frequency_source: str = "unknown"
    code_version: str = "unknown"
    created_utc: str = ""
    notes: tuple = ()
    schema: str = SCHEMA

    def __post_init__(self):
        ids = [p.prediction_id for p in self.predictions]
        if len(ids) != len(set(ids)):
            raise PredictionArtifactError("prediction_id values must be unique")
        line_ids = {ln.line_id for ln in self.lines}
        orphan = sorted({p.line_id for p in self.predictions} - line_ids)
        if orphan:
            raise PredictionArtifactError(f"predictions on undeclared line(s) {orphan[:5]}")

    # --- serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["lines"] = [asdict(ln) for ln in self.lines]
        d["predictions"] = [asdict(p) for p in self.predictions]
        return d

    def write(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1))
        return path

    @classmethod
    def from_dict(cls, d: dict) -> "PredictionArtifact":
        _refuse_truth(d, "artifact")
        if d.get("schema") != SCHEMA:
            raise PredictionArtifactError(f"schema {d.get('schema')!r}; expected {SCHEMA!r}")
        for p in d.get("predictions", []):
            _refuse_truth(p, f"prediction {p.get('prediction_id')}")
            _refuse_truth(p.get("detail") or {}, f"prediction {p.get('prediction_id')} detail")
        return cls(
            **{k: v for k, v in d.items()
               if k not in ("timing", "lines", "predictions", "notes")},
            timing=TimingProvenance(**d["timing"]),
            lines=tuple(AcquisitionLine(line_id=ln["line_id"], start=tuple(ln["start"]),
                                        end=tuple(ln["end"])) for ln in d["lines"]),
            predictions=tuple(Prediction(**{**p, "position": tuple(p["position"])})
                              for p in d["predictions"]),
            notes=tuple(d.get("notes") or ()),
        )

    @classmethod
    def read(cls, path) -> "PredictionArtifact":
        return cls.from_dict(json.loads(Path(path).read_text()))


def _refuse_truth(d: dict, where: str) -> None:
    leaked = sorted(set(d) & _TRUTH_KEYS)
    if leaked:
        raise PredictionArtifactError(
            f"{where} carries truth-shaped field(s) {leaked}; a prediction artifact is "
            f"written before truth is read and may not contain any")


def code_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True, cwd=Path(__file__).resolve().parent).stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# BAM: DetectionRun -> PredictionArtifact
# ---------------------------------------------------------------------------

def frequency_from_scan_id(scan_id: str) -> Optional[float]:
    """'..._1_5_GHz_Rot00' -> 1500.0. From the scan identifier only."""
    m = re.search(r"(\d+)_(\d+)_GHz", scan_id)
    return float(f"{m.group(1)}.{m.group(2)}") * 1000.0 if m else None


def bam_artifact(scan, run, frame_id: str, line_indices) -> PredictionArtifact:
    """
    A BAM detection run as a prediction artifact in the specimen frame.

    `line_indices` are the lines the run processed: a line with no detection
    is still an opportunity to find a target, so it must be listed.

    Positions are the grid's own X/Y values at the detection's PEAK trace and
    its line -- the same peak the legacy scorer matched by. The grid comes
    from the data archive (X-values.npy / Y-values.npy), not from any truth.
    """
    grid = scan.grid
    x0, x1 = float(grid.x[0]), float(grid.x[-1])
    line_indices = sorted(int(i) for i in line_indices)
    if len(line_indices) != run.lines_processed:
        raise PredictionArtifactError(
            f"{len(line_indices)} line indices given for a run that processed "
            f"{run.lines_processed}; every processed line is an opportunity and must be listed")
    lines = tuple(AcquisitionLine(line_id=f"L{i}", start=(x0, float(grid.y[i])),
                                  end=(x1, float(grid.y[i]))) for i in line_indices)
    preds = tuple(
        Prediction(
            prediction_id=d.detection_id, line_id=f"L{d.line_index}",
            position=(float(grid.x[d.peak_trace]), float(grid.y[d.line_index])),
            peak_two_way_time_ns=float(grid.z[d.peak_sample]),
            score=abs(float(d.peak_z)),
            detail={"peak_trace": d.peak_trace, "peak_sample": d.peak_sample,
                    "trace_span": [min(d.trace_indices), max(d.trace_indices)],
                    "n_cells": d.n_cells, "peak_z": d.peak_z},
        )
        for d in sorted(run.detections, key=lambda d: d.detection_id))
    freq = frequency_from_scan_id(scan.scan_id)
    conflict = scan.dzt_header.get("header_filename_conflict")
    sha = scan.provenance.get("archive_sha256") or hashlib.sha256(
        scan.archive.encode()).hexdigest()
    return PredictionArtifact(
        dataset_id=f"bam-concrete-gpr:{scan.specimen_id}",
        acquisition_id=scan.scan_id,
        frame_id=frame_id,
        frame_units=grid.units_xy,
        detector={"name": "benchmark.detection.detect_scan", "definition": run.detector,
                  "threshold": run.threshold, "min_cells": run.min_cells,
                  "parameters_changed": run.parameters_changed},
        preprocessing=dict(run.provenance),
        input_sha256=f"{sha}:{scan.volume_member}",
        timing=TimingProvenance(
            time_axis_origin="the archive's Z-values (ns); instrument time-zero not established",
            time_zero_status="not_applied", velocity_source="none"),
        lines=lines,
        predictions=preds,
        antenna_frequency_mhz=freq,
        antenna_frequency_source=(
            "scan identifier (filename)" + (f"; {conflict}" if conflict else "")),
        code_version=code_version(),
        created_utc=datetime.now(timezone.utc).isoformat(),
        notes=(f"lines processed: {run.lines_processed}",),
    )
