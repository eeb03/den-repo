"""
Runs Subterra's EXISTING detector over a benchmark scan.

No new model, and no new detection maths. This is the thinnest adapter that
lets the benchmark's array-shaped data reach the same pipeline the 4TU corpus
went through:

    background_removal -> dewow -> apply_gain -> ring z-score
        (preprocessing.spatial_grid.anomaly_grid_from_traces)
    -> |z| > threshold -> ndimage.label (4-connectivity) -> min_cells filter
        (the rule interpretation.anomaly_candidates.find_anomaly_candidates uses)

`find_anomaly_candidates` itself is record-based, and one scan of this
benchmark is 401 x 161 x 512 = 33 million cells, which is far past the memory
budget that forced the array path to exist in the first place. So the adapter
reuses the array path, whose equivalence to the record path is asserted by
`scripts/characterise_4tu.py --verify-arraywise`.

Thresholds are NOT tuned here. The detector's published defaults are used
as-is, and every result records which values produced it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from benchmark.bam_ingest import line_traces
from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS
from preprocessing.spatial_grid import anomaly_grid_from_traces


@dataclass(frozen=True)
class BenchmarkDetection:
    """
    One connected component on one line.

    `trace_indices` are grid nodes along X, which is what association needs.
    `peak_trace` is the node of the largest |z| cell -- reported because a
    component spans several nodes and a scoring rule has to say which one it
    is matched by.
    """
    scan_id: str
    line_index: int
    detection_id: str
    trace_indices: tuple[int, ...]
    sample_indices: tuple[int, ...]
    peak_trace: int
    peak_sample: int
    peak_z: float
    n_cells: int


@dataclass(frozen=True)
class DetectionRun:
    scan_id: str
    specimen_id: str
    detections: list[BenchmarkDetection]
    lines_processed: int
    threshold: float
    min_cells: int
    detector: str = ("preprocessing.spatial_grid.anomaly_grid_from_traces + "
                     "scipy.ndimage.label, matching "
                     "interpretation.anomaly_candidates.find_anomaly_candidates")
    parameters_changed: str = "none"
    provenance: dict = field(default_factory=dict)


def detect_line(traces: np.ndarray, scan_id: str, line_index: int,
                threshold: float = DEFAULT_ANOMALY_THRESHOLD,
                min_cells: int = DEFAULT_MIN_CELLS) -> list[BenchmarkDetection]:
    """Connected components on one B-scan's z-grid."""
    z = anomaly_grid_from_traces(traces)          # (n_samples, n_traces)
    mask = np.abs(np.nan_to_num(z, nan=0.0)) > threshold
    labeled, n = ndimage.label(mask)              # default 4-connectivity

    out = []
    for label_id in range(1, n + 1):
        cluster = labeled == label_id
        n_cells = int(cluster.sum())
        if n_cells < min_cells:
            continue
        samples, traces_idx = np.nonzero(cluster)
        vals = np.abs(np.nan_to_num(z, nan=0.0))[samples, traces_idx]
        peak = int(np.argmax(vals))
        out.append(BenchmarkDetection(
            scan_id=scan_id,
            line_index=line_index,
            detection_id=f"{scan_id}:L{line_index}:{label_id}",
            trace_indices=tuple(sorted(set(int(t) for t in traces_idx))),
            sample_indices=tuple(sorted(set(int(s) for s in samples))),
            peak_trace=int(traces_idx[peak]),
            peak_sample=int(samples[peak]),
            peak_z=float(z[samples[peak], traces_idx[peak]]),
            n_cells=n_cells,
        ))
    return out


def detect_scan(scan, volume: np.ndarray,
                threshold: float = DEFAULT_ANOMALY_THRESHOLD,
                min_cells: int = DEFAULT_MIN_CELLS,
                line_indices=None) -> DetectionRun:
    """
    Run the detector over every line of a scan (or a chosen subset).

    `line_indices` exists so a caller can score a documented subset without
    pretending it ran the whole scan; the count is always reported.
    """
    lines = range(volume.shape[1]) if line_indices is None else list(line_indices)
    detections = []
    for y in lines:
        detections.extend(detect_line(line_traces(volume, y), scan.scan_id, int(y),
                                      threshold=threshold, min_cells=min_cells))
    return DetectionRun(
        scan_id=scan.scan_id,
        specimen_id=scan.specimen_id,
        detections=detections,
        lines_processed=len(list(lines)),
        threshold=threshold,
        min_cells=min_cells,
        provenance={
            "amplitude_source": scan.volume_member.split("/")[-1],
            "preprocessing": "existing pipeline, unchanged",
            "thresholds": "detector defaults; not tuned for this benchmark",
            **scan.provenance,
        },
    )
