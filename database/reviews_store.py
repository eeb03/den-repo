"""
CandidateReview storage, mirroring `labels_store.py` and `candidates_store.py`:
one JSON document per dataset, same seam as records/frames/labels/candidates.

UPSERT BY DETERMINISTIC IDENTITY, HISTORY PRESERVED. `CandidateReview.id` is
derived from (dataset, candidate_id or "missed_event", source_file,
trace_range), so re-reviewing the same candidate UPDATES its one record
rather than accumulating duplicates -- but the PRIOR state is appended to
`history` first (Section 10: "if someone changes UNCERTAIN -> CONFIRMED, do
not silently erase the prior state"), never dropped.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from configs.settings import settings
from schemas.review import CandidateReview, ReviewRevision, ReviewSet


def _path_for(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.reviews.json"


def load_reviews(dataset_id: str) -> ReviewSet:
    """Returns an empty set for a dataset with no reviews yet."""
    path = _path_for(dataset_id)
    if not path.exists():
        return ReviewSet(dataset_id=dataset_id)
    with open(path) as f:
        return ReviewSet.model_validate(json.load(f))


def _save(review_set: ReviewSet) -> Path:
    path = _path_for(review_set.dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(review_set.model_dump(mode="json"), f, indent=2)
    return path


def upsert_review(dataset_id: str, review: CandidateReview) -> CandidateReview:
    """
    Creates a new review, or updates the existing one for the same
    candidate/geometry -- appending the PRIOR state to `history` first, so
    the sequence of judgements survives a later change of mind (Section 10).
    Detector-snapshot fields are carried forward from the existing record
    once frozen, never replaced by a later write (Section 9): a caller
    updating only `review_status`/`operator_label`/`notes` cannot
    accidentally overwrite the detector output a candidate carried when
    first reviewed.
    """
    review_set = load_reviews(dataset_id)
    existing = next((r for r in review_set.reviews if r.id == review.id), None)
    if existing is not None:
        review.history = existing.history + [ReviewRevision(
            reviewer_id=existing.reviewer_id, review_status=existing.review_status,
            operator_label=existing.operator_label, notes=existing.notes,
            timestamp=existing.updated_utc,
        )]
        review.created_utc = existing.created_utc
        if review.detector_snapshot is None:
            review.detector_snapshot = existing.detector_snapshot
        review_set.reviews = [r for r in review_set.reviews if r.id != review.id]
    review_set.reviews.append(review)
    _save(review_set)
    return review


def get_review(dataset_id: str, review_id: str) -> Optional[CandidateReview]:
    review_set = load_reviews(dataset_id)
    return next((r for r in review_set.reviews if r.id == review_id), None)


def get_review_for_candidate(dataset_id: str, candidate_id: str) -> Optional[CandidateReview]:
    return load_reviews(dataset_id).for_candidate(candidate_id)


def delete_reviews(dataset_id: str) -> bool:
    """Removes the stored set. Used when a dataset is deleted."""
    path = _path_for(dataset_id)
    if path.exists():
        path.unlink()
        return True
    return False
