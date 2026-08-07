"""
SubsurfaceObject and AssociationRecord storage.

Same seam as frames/labels: one JSON document per dataset alongside the
record JSONL. Both are small -- associations scale with candidates, not with
samples -- and both upsert by id, so re-running association over a dataset
replaces its own records rather than accumulating near-duplicates.

Objects and associations are stored SEPARATELY on purpose. An association is
evidence and survives on its own; an object is a resolution of associations
and can be rebuilt, discarded or re-cut at a different score threshold
without touching the evidence it came from.
"""
from __future__ import annotations

import json
from pathlib import Path

from configs.settings import settings
from schemas.associations import AssociationRecord, AssociationSet
from schemas.objects import SubsurfaceObject


def _assoc_path(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.associations.json"


def _object_path(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.objects.json"


def load_associations(dataset_id: str) -> AssociationSet:
    p = _assoc_path(dataset_id)
    if not p.exists():
        return AssociationSet(dataset_id=dataset_id)
    with open(p) as f:
        return AssociationSet.model_validate(json.load(f))


def save_associations(s: AssociationSet) -> Path:
    p = _assoc_path(s.dataset_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(s.model_dump(mode="json"), f, indent=2)
    return p


def upsert_associations(dataset_id: str,
                        records: list[AssociationRecord]) -> AssociationSet:
    existing = load_associations(dataset_id)
    by_id = {a.id: a for a in existing.associations}
    for r in records:
        if r.dataset_id != dataset_id:
            raise ValueError(
                f"association {r.id} belongs to dataset {r.dataset_id!r}, not "
                f"{dataset_id!r}")
        by_id[r.id] = r
    out = AssociationSet(dataset_id=dataset_id, associations=list(by_id.values()))
    save_associations(out)
    return out


def load_objects(dataset_id: str) -> list[SubsurfaceObject]:
    p = _object_path(dataset_id)
    if not p.exists():
        return []
    with open(p) as f:
        return [SubsurfaceObject.model_validate(d) for d in json.load(f)]


def save_objects(dataset_id: str, objects: list[SubsurfaceObject]) -> Path:
    p = _object_path(dataset_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump([o.model_dump(mode="json") for o in objects], f, indent=2)
    return p


def replace_objects(dataset_id: str,
                    objects: list[SubsurfaceObject]) -> list[SubsurfaceObject]:
    """
    Objects are a RESOLUTION, so re-resolving replaces the whole set rather
    than merging. Merging two resolutions computed under different thresholds
    would produce a set that no single threshold could have produced.
    """
    for o in objects:
        if o.dataset_id != dataset_id:
            raise ValueError(
                f"object {o.id} belongs to dataset {o.dataset_id!r}, not {dataset_id!r}")
    save_objects(dataset_id, objects)
    return objects
