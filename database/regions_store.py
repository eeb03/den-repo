"""
Storage for region sets and their append-only reviews.

    {processed}/{dataset_id}.volumes/{volume_id}/regions/{set_id}.json   RegionSet (masks bit-packed inline)
    {processed}/{dataset_id}.volumes/{volume_id}/regions/reviews.jsonl   RegionReview events, append-only

No voxel is ever a row: a region is metadata plus a bit-packed mask over its
own bounding box.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from database.volumes_store import volume_dir
from schemas.region import RegionReview, RegionSet

_ID = re.compile(r"[A-Za-z0-9_-]+")


def _dir(dataset_id: str, volume_id: str) -> Path:
    return volume_dir(dataset_id, volume_id) / "regions"


def save_region_set(rs: RegionSet) -> Path:
    d = _dir(rs.dataset_id, rs.volume_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{rs.id}.json"
    p.write_text(rs.model_dump_json())
    return p


def load_region_set(dataset_id: str, volume_id: str, set_id: str) -> RegionSet | None:
    if not _ID.fullmatch(set_id):
        return None
    try:
        p = _dir(dataset_id, volume_id) / f"{set_id}.json"
    except ValueError:
        return None
    return RegionSet.model_validate_json(p.read_text()) if p.exists() else None


def list_region_sets(dataset_id: str, volume_id: str) -> list[RegionSet]:
    try:
        d = _dir(dataset_id, volume_id)
    except ValueError:
        return []
    if not d.exists():
        return []
    out = [RegionSet.model_validate_json(p.read_text()) for p in d.glob("*.json")]
    return sorted(out, key=lambda r: r.created_at, reverse=True)


def append_review(review: RegionReview) -> RegionReview:
    d = _dir(review.dataset_id, review.volume_id)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "reviews.jsonl", "a", encoding="utf-8") as f:
        f.write(review.model_dump_json() + "\n")
    return review


def load_reviews(dataset_id: str, volume_id: str) -> list[RegionReview]:
    try:
        p = _dir(dataset_id, volume_id) / "reviews.jsonl"
    except ValueError:
        return []
    if not p.exists():
        return []
    return [RegionReview.model_validate_json(line) for line in p.read_text().splitlines() if line.strip()]


def review_history(dataset_id: str, volume_id: str, region_id: str) -> list[RegionReview]:
    return [r for r in load_reviews(dataset_id, volume_id) if r.region_id == region_id]
