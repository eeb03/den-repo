"""
Candidate intelligence API.

A thin surface over `api.candidates` and `database.candidates_store`. The route
layer adds no semantics: what a candidate may and may not claim is enforced on
the models in `interpretation.candidate_intelligence`, so it holds equally for
the API, a script and the report.

EVERY RESPONSE CARRIES ITS OWN FRAMING. `definition`, `classification_status`
and `benchmark` travel in the payload rather than in documentation a client
might not read, because a candidate list served without them reads as a list of
findings. That is the single most important thing this API must not let happen.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api import candidates as candidate_service
from auth.dependencies import require_dataset_access, require_owned_dataset
from database.candidates_store import load_candidates, set_status
from database.records_store import load_records
from database.session import get_db
from interpretation.candidate_intelligence import (
    CANDIDATE_DEFINITION, CANDIDATE_SCORE_MEANING, CLASSIFICATION_BLOCKED_REASON,
    CLASSIFICATION_STATUS, BenchmarkContext, CandidateStatus, GenerationParameters,
)
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/vocabulary")
def vocabulary():
    """
    What the words in this API mean, served rather than assumed.

    A client that renders `candidate_score` as a percentage, or `accepted` as a
    confirmed object, is making a scientific error. This endpoint exists so it
    has no excuse to.
    """
    return {
        "candidate": CANDIDATE_DEFINITION,
        "candidate_score": CANDIDATE_SCORE_MEANING,
        "classification_status": CLASSIFICATION_STATUS,
        "classification_blocked_reason": CLASSIFICATION_BLOCKED_REASON,
        "localisation_certainty": {
            "spatially_registered": "geographic coordinates are available for the supporting traces",
            "frame_relative": "along-track distance is measured, but no geographic position exists",
            "trace_relative": "locatable only as traces within a named source file",
            "unknown": "no defensible location exists",
        },
        "depth_certainty": {
            "measured": "a directly measured depth axis",
            "derived": "converted from time using a declared velocity -- an assumption, not a measurement",
            "unavailable": "no physical depth exists for this candidate",
        },
        "review_status": {
            "proposed": "generated, not yet reviewed",
            "reviewed": "a reviewer has looked at it",
            "accepted": "a reviewer decided it is worth retaining -- NOT ground truth, "
                        "not a detection, and not an object",
            "rejected": "a reviewer decided it is not worth retaining",
        },
        "benchmark": BenchmarkContext().model_dump(mode="json"),
    }


@router.get("/{dataset_id}")
def get_candidates(dataset_id: str, db: Session = Depends(get_db),
                   _dataset=Depends(require_dataset_access)):
    """The stored candidate set for a dataset, with staleness assessed now."""
    return candidate_service.current(db, dataset_id).model_dump(mode="json")


@router.post("/{dataset_id}/generate")
def generate_candidates(dataset_id: str,
                        threshold: float = Query(None),
                        min_cells: int = Query(None),
                        min_trace_span: int = Query(None),
                        db: Session = Depends(get_db),
                        _dataset=Depends(require_owned_dataset)):
    """
    Run candidate generation and store the result.

    Generation is an explicit action, never a side effect of opening a report:
    it reads every record in the dataset, and a report request must not silently
    spend that. Parameters default to the provisional values the detector
    documents; whatever is used is recorded on the stored set.
    """
    supplied = {k: v for k, v in {
        "threshold": threshold, "min_cells": min_cells, "min_trace_span": min_trace_span,
    }.items() if v is not None}
    try:
        parameters = GenerationParameters(**supplied)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"invalid generation parameters: {e}")

    if parameters.min_trace_span < 1:
        raise HTTPException(status_code=422,
                            detail="min_trace_span must be at least 1 (1 reproduces the baseline)")
    return candidate_service.generate(db, dataset_id, parameters).model_dump(mode="json")


@router.get("/{dataset_id}/{candidate_id}")
def inspect_candidate(dataset_id: str, candidate_id: str,
                      _dataset=Depends(require_dataset_access)):
    """
    One candidate, with the evidence chain that addresses its measurements.

    The response deliberately repeats the framing fields. Inspecting a single
    candidate is exactly the moment a reader is most likely to forget that it
    is not a detection.
    """
    stored = load_candidates(dataset_id)
    if stored is None:
        # Same composition gate `current()` already applies to the list
        # endpoint (slice 4) -- an off-GPR dataset's absence is not "has not
        # been run", because no retry would produce a stored set. No db
        # session needed here: `_recorded_composition` is file-backed, same
        # as it already is in `current()`'s own no-session path.
        records = load_records(dataset_id)
        composition = candidate_service._recorded_composition(dataset_id, records)
        if composition and "gpr" not in composition:
            raise HTTPException(
                status_code=404,
                detail=candidate_service._off_gpr_blocked(dataset_id, composition).status_reason)
        raise HTTPException(status_code=404,
                            detail="candidate generation has not been run for this dataset")
    for candidate in stored.candidates:
        if candidate.candidate.id == candidate_id:
            return {
                **candidate.model_dump(mode="json"),
                "definition": CANDIDATE_DEFINITION,
                "generation": stored.generation.model_dump(mode="json"),
                "benchmark": BenchmarkContext().model_dump(mode="json"),
                "evidence_chain": {
                    "source_file": candidate.candidate.evidence.source_file,
                    "trace_range": list(candidate.candidate.evidence.trace_range),
                    "n_supporting_cells": candidate.candidate.evidence.n_supporting_cells,
                    "note": "these address the measurements the proposal rests on, so "
                            "the reasoning can be checked rather than trusted",
                },
            }
    raise HTTPException(status_code=404, detail="no such candidate in this dataset")


@router.post("/{dataset_id}/{candidate_id}/status")
def review_candidate(dataset_id: str, candidate_id: str,
                     status: CandidateStatus = Query(...),
                     _dataset=Depends(require_owned_dataset)):
    """
    Record a reviewer's decision.

    Acceptance means "worth retaining", and the response says so, because this
    is the one endpoint whose output could most easily be mistaken for a
    promotion from candidate to fact.
    """
    updated = set_status(dataset_id, candidate_id, status)
    if updated is None:
        raise HTTPException(status_code=404,
                            detail="no such candidate in this dataset")
    logger.info("candidate %s in %s marked %s", candidate_id, dataset_id, status.value)
    return {
        **updated.model_dump(mode="json"),
        "note": "a review decision records what a reviewer thought worth retaining. "
                "It does not make this candidate a detection, an object, or ground truth.",
    }
