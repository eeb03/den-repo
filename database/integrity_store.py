"""
IntegritySignature storage, mirroring `reviews_store.py`/`labels_store.py`:
one JSON document per dataset, same seam as records/frames/labels/reviews.

A dataset that has never been signed simply has no file -- `load_integrity`
returns None, never a fabricated "unsigned" signature object.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from configs.settings import settings
from security.dataset_integrity import IntegritySignature


def _path_for(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.integrity.json"


def save_integrity(signature: IntegritySignature) -> Path:
    path = _path_for(signature.dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(signature.to_dict(), f, indent=2)
    return path


def load_integrity(dataset_id: str) -> Optional[IntegritySignature]:
    path = _path_for(dataset_id)
    if not path.exists():
        return None
    with open(path) as f:
        return IntegritySignature.from_dict(json.load(f))


def delete_integrity(dataset_id: str) -> bool:
    """Used when a dataset is deleted."""
    path = _path_for(dataset_id)
    if path.exists():
        path.unlink()
        return True
    return False
