"""
Candidate-set storage, mirroring labels_store and frames_store.

WHY STORE CANDIDATES AT ALL. `anomaly_candidates` was written to compute on
demand and persist nothing, and its docstring gives the reason: a cached result
can stop matching how the data was actually processed. That reasoning is sound
and this module does not overturn it -- it satisfies it. What is stored here is
not a bare list of candidates but a candidate SET carrying the generation record
that says which method, version, parameters and inputs produced it. A stored set
whose fingerprint no longer matches the dataset is reported stale rather than
served as current, which is the property the on-demand design was protecting.

Candidate generation over a real corpus is minutes of work, not milliseconds, so
recomputing it inside every report request was never an option; the choice was
between storing it with provenance and not offering it at all.

ONE DOCUMENT PER DATASET, REPLACED WHOLE. A candidate set is a single coherent
result of one generation run: half of an old set beside half of a new one would
describe no run that ever happened. Regenerating therefore REPLACES, and the
review statuses of candidates that survive by id are carried across so a
reviewer's work is not silently discarded.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from configs.settings import settings
from interpretation.candidate_intelligence import (
    CandidateGeneration, CandidateStatus, InspectableCandidate,
)


class StoredCandidateSet(BaseModel):
    dataset_id: str
    generation: CandidateGeneration
    candidates: list[InspectableCandidate] = Field(default_factory=list)
    #: Traces examined, so candidate burden can be reported without reopening
    #: the records. None when the generator could not count them.
    n_traces: Optional[int] = None


def _path_for(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.candidates.json"


def load_candidates(dataset_id: str) -> Optional[StoredCandidateSet]:
    """None for a dataset whose candidates have never been generated."""
    path = _path_for(dataset_id)
    if not path.exists():
        return None
    with open(path) as f:
        return StoredCandidateSet.model_validate(json.load(f))


def save_candidates(candidate_set: StoredCandidateSet) -> Path:
    """
    Replaces the dataset's candidate set, preserving review decisions by id.

    A candidate id encodes its dataset, source file, cluster and parameters, so
    an id that survives a regeneration genuinely refers to the same region found
    the same way. An id that does not survive had its region, its rule or its
    parameters change, and carrying a review decision across that would be
    attributing a judgement to something the reviewer never saw.
    """
    previous = load_candidates(candidate_set.dataset_id)
    if previous:
        kept = {
            c.candidate.id: c.status for c in previous.candidates
            if c.status != CandidateStatus.PROPOSED
        }
        for candidate in candidate_set.candidates:
            if candidate.candidate.id in kept:
                candidate.status = kept[candidate.candidate.id]

    path = _path_for(candidate_set.dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(candidate_set.model_dump(mode="json"), f, indent=2)
    return path


def set_status(dataset_id: str, candidate_id: str,
               status: CandidateStatus) -> Optional[InspectableCandidate]:
    """
    Record a reviewer's decision about one candidate.

    Accepting a candidate means a reviewer decided it is worth retaining. It
    does not promote it to a detection, an object or ground truth, and nothing
    in this module lets it: `status` is the only field a review can touch.
    """
    stored = load_candidates(dataset_id)
    if stored is None:
        return None
    for candidate in stored.candidates:
        if candidate.candidate.id == candidate_id:
            candidate.status = status
            path = _path_for(dataset_id)
            with open(path, "w") as f:
                json.dump(stored.model_dump(mode="json"), f, indent=2)
            return candidate
    return None


def delete_candidates(dataset_id: str) -> bool:
    """Removes the stored set. Used when a dataset is deleted."""
    path = _path_for(dataset_id)
    if path.exists():
        path.unlink()
        return True
    return False
