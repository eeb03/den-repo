"""
Storage for `schemas.volume.VolumeProduct`s.

    {processed}/{dataset_id}.volumes/{volume_id}/volume.json   metadata
    {processed}/{dataset_id}.volumes/{volume_id}/*.npy         fields, opened memory-mapped

Volumes are derived products: deleting one never touches the source grid.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np

from configs.settings import settings
from schemas.volume import VolumeProduct


def _root(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.volumes"


def volume_dir(dataset_id: str, volume_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", volume_id):
        raise ValueError("invalid volume id")
    return _root(dataset_id) / volume_id


def save_volume(product: VolumeProduct, arrays: dict[str, np.ndarray]) -> Path:
    d = volume_dir(product.dataset_id, product.id)
    d.mkdir(parents=True, exist_ok=True)
    for name, arr in arrays.items():
        np.save(d / name, arr)
    (d / "volume.json").write_text(product.model_dump_json(indent=1))
    return d


def load_volume(dataset_id: str, volume_id: str) -> VolumeProduct | None:
    try:
        p = volume_dir(dataset_id, volume_id) / "volume.json"
    except ValueError:
        return None
    return VolumeProduct.model_validate_json(p.read_text()) if p.exists() else None


def list_volumes(dataset_id: str) -> list[VolumeProduct]:
    r = _root(dataset_id)
    if not r.exists():
        return []
    out = [VolumeProduct.model_validate_json(p.read_text()) for p in r.glob("*/volume.json")]
    return sorted(out, key=lambda v: v.created_at, reverse=True)


def open_array(product: VolumeProduct, file: str) -> np.ndarray:
    return np.load(volume_dir(product.dataset_id, product.id) / file, mmap_mode="r")


def delete_volume(dataset_id: str, volume_id: str) -> bool:
    d = volume_dir(dataset_id, volume_id)
    if not d.exists():
        return False
    shutil.rmtree(d)
    return True
