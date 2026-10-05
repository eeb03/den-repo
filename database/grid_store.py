"""
Array storage for gridded acquisitions (`schemas.survey_grid`).

Layout, under the processed directory:
    {dataset_id}.grid/{safe frame id}.npy     float32 (n_trace, n_line, n_time)
    {dataset_id}.grid/{safe frame id}.json    GriddedAcquisition

The array is opened memory-mapped, so a 130 MB grid is never copied into
Python objects just to read one line.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from configs.settings import settings
from schemas.survey_grid import GriddedAcquisition


def _dir(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.grid"


def _safe(frame_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", frame_id)


def array_sha256(arr: np.ndarray) -> str:
    h = hashlib.sha256()
    a = np.ascontiguousarray(arr, dtype=np.float32)
    h.update(str(a.shape).encode())
    h.update(memoryview(a).cast("B"))
    return h.hexdigest()


def save_grid(geometry: GriddedAcquisition, array: np.ndarray) -> GriddedAcquisition:
    a = np.ascontiguousarray(array, dtype=np.float32)
    if a.shape != geometry.shape:
        raise ValueError(f"array shape {a.shape} does not match the declared grid {geometry.shape}")
    d = _dir(geometry.dataset_id)
    d.mkdir(parents=True, exist_ok=True)
    name = _safe(geometry.frame_id)
    np.save(d / f"{name}.npy", a)
    geometry = geometry.model_copy(update={"array_file": f"{name}.npy", "array_sha256": array_sha256(a)})
    (d / f"{name}.json").write_text(geometry.model_dump_json(indent=1))
    return geometry


def load_grids(dataset_id: str) -> list[GriddedAcquisition]:
    d = _dir(dataset_id)
    if not d.exists():
        return []
    return [GriddedAcquisition.model_validate_json(p.read_text()) for p in sorted(d.glob("*.json"))]


def load_grid(dataset_id: str, frame_id: str) -> GriddedAcquisition | None:
    p = _dir(dataset_id) / f"{_safe(frame_id)}.json"
    return GriddedAcquisition.model_validate_json(p.read_text()) if p.exists() else None


def open_array(geometry: GriddedAcquisition) -> np.ndarray:
    """Read-only memory map of the stored array."""
    return np.load(_dir(geometry.dataset_id) / geometry.array_file, mmap_mode="r")


def delete_grids(dataset_id: str) -> None:
    import shutil
    shutil.rmtree(_dir(dataset_id), ignore_errors=True)
