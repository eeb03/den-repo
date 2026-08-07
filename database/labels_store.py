"""
SemanticLabel storage, mirroring frames_store.

Labels are small and few relative to records -- one per detector candidate at
most, usually far fewer -- so one JSON document per dataset alongside the
record JSONL, same seam and same swap-later story as records and frames.

UPSERT BY IDENTITY, NOT APPEND. `SemanticLabel.id` is derived from
(dataset, target, labeller, value), so re-running a detector over a dataset
REPLACES its previous labels rather than accumulating near-duplicates. Two
labellers disagreeing about one target still produce two labels, because
their ids differ -- disagreement is preserved, duplication is not.
"""
from __future__ import annotations

import json
from pathlib import Path

from configs.settings import settings
from schemas.labels import LabelSet, SemanticLabel


def _path_for(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.labels.json"


def load_labels(dataset_id: str) -> LabelSet:
    """Returns an empty set for a dataset that has never been labelled."""
    path = _path_for(dataset_id)
    if not path.exists():
        return LabelSet(dataset_id=dataset_id)
    with open(path) as f:
        return LabelSet.model_validate(json.load(f))


def save_labels(label_set: LabelSet) -> Path:
    path = _path_for(label_set.dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(label_set.model_dump(mode="json"), f, indent=2)
    return path


def upsert_labels(dataset_id: str, labels: list[SemanticLabel]) -> LabelSet:
    """
    Adds or replaces labels by id, preserving everything else.

    Returns the whole set so a caller can see the result without a second read.
    """
    existing = load_labels(dataset_id)
    by_id = {l.id: l for l in existing.labels}
    for l in labels:
        if l.target.dataset_id != dataset_id:
            raise ValueError(
                f"label {l.id} targets dataset {l.target.dataset_id!r} but is being "
                f"written to {dataset_id!r}; a label belongs to the dataset it labels"
            )
        by_id[l.id] = l
    out = LabelSet(dataset_id=dataset_id, labels=list(by_id.values()))
    save_labels(out)
    return out


def delete_labels(dataset_id: str, label_ids: list[str]) -> tuple[LabelSet, list[str]]:
    """Removes labels by id. Returns the remaining set and the ids not found."""
    existing = load_labels(dataset_id)
    wanted = set(label_ids)
    kept = [l for l in existing.labels if l.id not in wanted]
    missing = sorted(wanted - {l.id for l in existing.labels})
    out = LabelSet(dataset_id=dataset_id, labels=kept)
    save_labels(out)
    return out, missing


def labels_for_datasets(dataset_ids) -> list[SemanticLabel]:
    out: list[SemanticLabel] = []
    for d in sorted(set(dataset_ids)):
        out.extend(load_labels(d).labels)
    return out
