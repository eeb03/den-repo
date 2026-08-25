"""
Human-in-the-Loop Anomaly Verification V1 API.

A thin surface, mirroring `api/routes/candidates.py` and `api/routes/labels.py`:
the route layer adds no semantics of its own. What a review may and may not
claim is enforced on `schemas.review.CandidateReview` and
`training.review_corpus`, so it holds equally for the API, a script, and a
future importer.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, require_dataset_access, require_owned_dataset
from database.candidates_store import load_candidates
from database.frames_store import load_frames, synthesize_frames_from_records
from database.models import User
from database.records_store import load_records
from database.reviews_store import get_review, load_reviews, upsert_review
from database.session import get_db
from schemas.review import (
    OPERATOR_LABEL_VOCABULARY, AnnotationGeometry, CandidateReview, DetectorSnapshot,
    ReviewStatus, make_review_id,
)
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/vocabulary")
def vocabulary():
    """Served, not assumed -- a client renders exactly what these words mean."""
    return {
        "review_status": {
            "unreviewed": "no human judgement has been recorded",
            "confirmed": "the reviewer believes the radar evidence represents a genuine "
                         "anomaly/structure -- this establishes NO identity",
            "rejected": "the reviewer believes the candidate is clutter/noise/not meaningful -- "
                        "this does NOT become a verified-empty ground truth",
            "uncertain": "the evidence is insufficient to say either way",
        },
        "operator_label_vocabulary": list(OPERATOR_LABEL_VOCABULARY),
        "operator_label_note": (
            "optional and human-supplied; a review may be CONFIRMED with no operator_label "
            "at all -- 'this is real but I cannot identify it' is a first-class, valid state"
        ),
        "evidence_grade": "every review produced here is C_OPERATOR_REVIEWED -- a knowledgeable "
                          "reviewer's judgement, useful for training research, never independent "
                          "ground truth (see schemas.segmentation.EvidenceGrade)",
        "ground_truth_status": "always not_independently_validated: a human saying 'this looks "
                               "like a pipe' never becomes 'Subterra detected a pipe'",
    }


class ReviewWriteRequest(BaseModel):
    review_status: ReviewStatus
    operator_label: Optional[str] = None
    annotation_geometry: Optional[AnnotationGeometry] = None
    notes: Optional[str] = None


class MissedEventRequest(BaseModel):
    source_file: str = Field(..., min_length=1)
    trace_range: tuple[int, int]
    review_status: ReviewStatus = ReviewStatus.CONFIRMED
    operator_label: Optional[str] = None
    annotation_geometry: Optional[AnnotationGeometry] = None
    notes: Optional[str] = None


def _detector_snapshot_for(dataset_id: str, candidate_id: str) -> tuple[Optional[DetectorSnapshot], str, tuple[int, int]]:
    """The candidate's OWN current output, frozen into a snapshot -- never touched by later regenerations (Section 9)."""
    stored = load_candidates(dataset_id)
    if stored is not None:
        for c in stored.candidates:
            if c.candidate.id == candidate_id:
                snapshot = DetectorSnapshot(
                    candidate_score=c.candidate_score,
                    candidate_class=c.candidate.interpretation.anomaly_class,
                    detector_method=stored.generation.method if stored.generation else None,
                    detector_version=stored.generation.method_version if stored.generation else None,
                    localisation=c.localisation.value, depth_certainty=c.depth.value,
                )
                return snapshot, c.candidate.evidence.source_file, tuple(c.candidate.evidence.trace_range)
    raise HTTPException(status_code=404, detail="no such candidate in this dataset")


@router.get("/{dataset_id}")
def dataset_reviews(dataset_id: str, _dataset=Depends(require_dataset_access)):
    """Every review for a dataset, plus Section 13's progress summary."""
    review_set = load_reviews(dataset_id)
    return {
        "dataset_id": dataset_id,
        "reviews": [r.model_dump(mode="json") for r in review_set.reviews],
        "summary": review_set.summary(),
    }


@router.get("/{dataset_id}/summary")
def dataset_review_summary(dataset_id: str, _dataset=Depends(require_dataset_access)):
    """Section 13's dataset-level progress display alone, for a lighter-weight poll than the full list."""
    return {"dataset_id": dataset_id, "summary": load_reviews(dataset_id).summary()}


@router.get("/{dataset_id}/candidate/{candidate_id}")
def get_candidate_review(dataset_id: str, candidate_id: str,
                         _dataset=Depends(require_dataset_access)):
    review = load_reviews(dataset_id).for_candidate(candidate_id)
    if review is None:
        raise HTTPException(status_code=404, detail="this candidate has not been reviewed yet")
    return review.model_dump(mode="json")


@router.post("/{dataset_id}/candidate/{candidate_id}")
def review_candidate(dataset_id: str, candidate_id: str, body: ReviewWriteRequest,
                     user: User = Depends(get_current_user),
                     _dataset=Depends(require_owned_dataset)):
    """
    Records a reviewer's judgement about an EXISTING detector candidate.

    The candidate's own output is looked up and frozen into `detector_snapshot`
    on first review; `upsert_review` never lets a later write replace it
    (Section 9 -- detector output is immutable once a review exists for it).
    """
    snapshot, source_file, trace_range = _detector_snapshot_for(dataset_id, candidate_id)
    review = CandidateReview(
        id=make_review_id(dataset_id, candidate_id, source_file, trace_range),
        dataset_id=dataset_id, candidate_id=candidate_id, source_file=source_file,
        trace_range=trace_range, reviewer_id=user.id, review_status=body.review_status,
        operator_label=body.operator_label, annotation_geometry=body.annotation_geometry,
        notes=body.notes, detector_snapshot=snapshot,
    )
    saved = upsert_review(dataset_id, review)
    logger.info("review: candidate %s in %s marked %s by %s",
               candidate_id, dataset_id, body.review_status.value, user.id)
    return {
        **saved.model_dump(mode="json"),
        "note": "a review records a human judgement about real evidence. It does not make "
                "this candidate a detection, an object, or independently validated ground truth.",
    }


@router.post("/{dataset_id}/missed_event")
def create_missed_event(dataset_id: str, body: MissedEventRequest,
                        user: User = Depends(get_current_user),
                        _dataset=Depends(require_owned_dataset)):
    """
    Section 12: a candidate-INDEPENDENT annotation for a real event the
    detector never proposed. No `detector_snapshot` exists here by
    construction -- there is no candidate output to freeze.
    """
    if body.trace_range[0] > body.trace_range[1]:
        raise HTTPException(status_code=422, detail=f"trace_range {body.trace_range} is inverted")
    review = CandidateReview(
        id=make_review_id(dataset_id, None, body.source_file, body.trace_range),
        dataset_id=dataset_id, candidate_id=None, source_file=body.source_file,
        trace_range=body.trace_range, reviewer_id=user.id, review_status=body.review_status,
        operator_label=body.operator_label, annotation_geometry=body.annotation_geometry,
        notes=body.notes, detector_snapshot=None,
    )
    saved = upsert_review(dataset_id, review)
    logger.info("review: missed-event annotation created in %s by %s", dataset_id, user.id)
    return {
        **saved.model_dump(mode="json"),
        "note": "a missed-event annotation records that a human found real evidence the "
                "detector did not propose. It is not a detection and not ground truth.",
    }


@router.get("/{dataset_id}/corpus_export")
def export_corpus(dataset_id: str, db: Session = Depends(get_db),
                  _dataset=Depends(require_dataset_access)):
    """
    Section 15/20: converts every corpus-eligible review into the EXISTING
    Real GPR Annotation Corpus format and runs the existing QA/manifest
    logic against it -- reuses `training.segmentation.validate_corpus`/
    `build_corpus_manifest` verbatim, never a second implementation.
    """
    from preprocessing.spatial_grid import build_trace_depth_grid_for_records
    from schemas.dataset_report import frame_modalities
    from training.review_corpus import review_to_training_example
    from training.segmentation import build_corpus_manifest, validate_corpus

    review_set = load_reviews(dataset_id)
    eligible = [r for r in review_set.reviews if r.eligible_for_corpus]
    if not eligible:
        return {
            "dataset_id": dataset_id, "examples": [], "manifest": None,
            "note": "no corpus-eligible reviews exist yet (UNREVIEWED reviews are excluded)",
        }

    records = load_records(dataset_id)
    if not records:
        raise HTTPException(status_code=404, detail="No stored records found for this dataset")
    all_frames = load_frames(dataset_id) or synthesize_frames_from_records(records)
    composition = frame_modalities(all_frames)
    if composition and "gpr" not in composition:
        raise HTTPException(
            status_code=400,
            detail=f"this dataset's recorded modality composition is {', '.join(composition)}; "
                   f"corpus export needs real multi-sample GPR trace data, which does not apply here")

    examples, errors = [], []
    for review in eligible:
        try:
            grid_result = build_trace_depth_grid_for_records(
                records, source_file=review.source_file, field="pre_anomaly_signal")
        except ValueError as e:
            errors.append({"review_id": review.id, "error": str(e)[:200]})
            continue

        trace_ids = grid_result["trace_indices"]
        try:
            t0 = trace_ids.index(review.trace_range[0])
            t1 = trace_ids.index(review.trace_range[1])
        except ValueError:
            errors.append({"review_id": review.id,
                           "error": f"trace_range {review.trace_range} not found in this line's current grid"})
            continue

        window = [row[t0:t1 + 1] for row in grid_result["grid"]]
        example = review_to_training_example(
            review, signal=window, window_trace_range=(t0, t1),
            window_sample_range=(0, len(window) - 1 if window else 0),
            preprocessing_version="live-pre-anomaly-signal-v1",
        )
        if example is not None:
            examples.append(example)

    issues = validate_corpus(examples)
    manifest = build_corpus_manifest(examples, version=f"human-review-{dataset_id}-v1") if examples else None
    return {
        "dataset_id": dataset_id,
        "n_eligible_reviews": len(eligible),
        "n_examples_exported": len(examples),
        "errors": errors,
        "qa_issues": [{"index": i.example_index, "check": i.check, "detail": i.detail} for i in issues],
        "manifest": manifest,
        "examples": [e.model_dump(mode="json") for e in examples],
    }
