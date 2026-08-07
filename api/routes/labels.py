"""
Semantic label API.

A thin, stable surface over `schemas.labels` and `database.labels_store`, so a
viewer can draw labels without knowing how they are stored and without
re-deriving anything.

The route layer adds no semantics of its own: the validation that matters
(ground truth needs an attestation, confidence needs a basis, a label is never
`measured`) lives on the model, so it applies equally to the API, a script and
a future importer.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from database.labels_store import (
    delete_labels, load_labels, upsert_labels,
)
from schemas.labels import LabelKind, LabelTargetKind, SemanticLabel
from schemas.provenance import ProvenanceClass, summarise
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class LabelWriteRequest(BaseModel):
    labels: list[SemanticLabel] = Field(..., min_length=1)


@router.get("/vocabulary")
def vocabulary():
    """
    The label vocabulary a client must be able to render.

    Served rather than hard-coded, and it states the rules the model enforces
    so a client can explain a rejection without guessing.
    """
    return {
        "kinds": [
            {"value": LabelKind.DETECTOR_CANDIDATE.value,
             "meaning": "a detector's neutral geometric class, carried forward",
             "is_truth": False},
            {"value": LabelKind.HUMAN_INTERPRETATION.value,
             "meaning": "a human's reading of the data; an opinion, recorded as one",
             "is_truth": False},
            {"value": LabelKind.MODEL_PREDICTION.value,
             "meaning": "a model's output; requires the model name and version",
             "is_truth": False},
            {"value": LabelKind.GROUND_TRUTH.value,
             "meaning": ("established by an independent observation; REQUIRES an "
                         "attestation naming it"),
             "is_truth": True},
        ],
        "target_kinds": [k.value for k in LabelTargetKind],
        "rules": [
            "a label is an assertion by a labeller, never a property of the ground",
            "ground_truth requires an attestation; nothing else may carry one",
            "confidence requires a confidence_basis, and is not comparable between labellers",
            "a label is never `measured`: naming a thing is not measuring it",
            "disagreement between labellers is preserved, never resolved",
        ],
    }


def _summary(labels: list[SemanticLabel]) -> dict:
    kinds: dict[str, int] = {}
    stages: dict[str, int] = {}
    sources: dict[str, int] = {}
    for l in labels:
        kinds[l.kind.value] = kinds.get(l.kind.value, 0) + 1
        stages[l.processing_stage] = stages.get(l.processing_stage, 0) + 1
        key = f"{l.source.kind}:{l.source.name}"
        sources[key] = sources.get(key, 0) + 1
    return {
        "count": len(labels),
        "by_kind": kinds,
        "by_processing_stage": stages,
        "by_source": sources,
        "ground_truth_count": sum(1 for l in labels if l.is_ground_truth),
        "provenance": summarise([
            type("E", (), {"quantity": l.id, "provenance": l.provenance})()
            for l in labels
        ]) if labels else None,
    }


@router.get("/{dataset_id}")
def list_labels(
    dataset_id: str,
    kind: Optional[LabelKind] = Query(None),
    target_id: Optional[str] = Query(None),
    frame_id: Optional[str] = Query(None),
    source_name: Optional[str] = Query(None),
    processing_stage: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
):
    """
    Labels for a dataset, filtered on the axes a viewer actually filters on.

    `min_confidence` drops labels that HAVE a confidence below the threshold.
    A label with no confidence is kept: absence of a stated confidence is not
    low confidence, and silently hiding unscored labels would misrepresent
    what is known.
    """
    ls = load_labels(dataset_id)
    out = ls.labels
    if kind:
        out = [l for l in out if l.kind == kind]
    if target_id:
        out = [l for l in out if l.target.target_id == target_id]
    if frame_id:
        out = [l for l in out if l.target.frame_id == frame_id]
    if source_name:
        out = [l for l in out if l.source.name == source_name]
    if processing_stage:
        out = [l for l in out if l.processing_stage == processing_stage]
    if min_confidence is not None:
        out = [l for l in out
               if l.confidence is None or l.confidence >= min_confidence]
    return {
        "dataset_id": dataset_id,
        "labels": [l.model_dump(mode="json") for l in out],
        "summary": _summary(out),
        "filters_applied": {
            "kind": kind.value if kind else None, "target_id": target_id,
            "frame_id": frame_id, "source_name": source_name,
            "processing_stage": processing_stage, "min_confidence": min_confidence,
        },
        "note": ("labels with no stated confidence are retained by min_confidence: "
                 "an unscored label is not a low-confidence one"),
    }


@router.post("/{dataset_id}")
def write_labels(dataset_id: str, body: LabelWriteRequest):
    """
    Creates or replaces labels.

    Identity is derived from (dataset, target, labeller, value), so re-running
    a detector updates its own labels instead of accumulating duplicates,
    while a second labeller's disagreement is kept as a separate label.
    """
    try:
        out = upsert_labels(dataset_id, body.labels)
    except ValueError as e:
        raise HTTPException(400, str(e))
    logger.info(f"labels: wrote {len(body.labels)} label(s) to {dataset_id}")
    return {
        "dataset_id": dataset_id,
        "written": [l.id for l in body.labels],
        "total_after_write": len(out.labels),
        "summary": _summary(out.labels),
    }


@router.delete("/{dataset_id}")
def remove_labels(dataset_id: str, label_ids: list[str] = Query(...)):
    out, missing = delete_labels(dataset_id, label_ids)
    return {"dataset_id": dataset_id, "deleted": [i for i in label_ids if i not in missing],
            "not_found": missing, "total_after_delete": len(out.labels)}


@router.get("/{dataset_id}/disagreements")
def disagreements(dataset_id: str):
    """
    Targets carrying more than one distinct label value.

    Reported, never resolved -- a reviewer needs to see that two labellers
    disagree, and picking a winner here would be inventing an answer.
    """
    ls = load_labels(dataset_id)
    d = ls.disagreements()
    return {
        "dataset_id": dataset_id,
        "disagreeing_targets": len(d),
        "targets": {
            t: [{"id": l.id, "value": l.value, "kind": l.kind.value,
                 "source": f"{l.source.kind}:{l.source.name}",
                 "confidence": l.confidence, "confidence_basis": l.confidence_basis}
                for l in ls]
            for t, ls in d.items()
        },
        "note": "disagreement is preserved, not resolved",
    }


@router.post("/{dataset_id}/from_candidates")
def labels_from_candidates(dataset_id: str, candidates: list[dict],
                           detector_name: str = Query("find_anomaly_candidates"),
                           detector_version: str = Query(...),
                           processing_stage: str = Query("detection")):
    """
    Turns detector candidates into detector_candidate labels.

    Carries the candidate's OWN neutral geometric class across; it invents no
    semantics, assigns no confidence (the detector reports none that is
    comparable to anything), and produces nothing that could be mistaken for
    ground truth.
    """
    from interpretation.anomaly_candidates import AnomalyCandidate
    from schemas.labels import LabelSource, LabelTarget

    made, errors = [], []
    for raw in candidates:
        try:
            c = AnomalyCandidate.model_validate(raw)
        except Exception as e:
            errors.append({"id": raw.get("id"), "error": str(e)[:200]})
            continue
        made.append(SemanticLabel(
            kind=LabelKind.DETECTOR_CANDIDATE,
            target=LabelTarget(kind=LabelTargetKind.CANDIDATE, dataset_id=dataset_id,
                               target_id=c.id, source_file=c.evidence.source_file,
                               trace_range=tuple(c.evidence.trace_range)),
            source=LabelSource(kind="detector", name=detector_name,
                               version=detector_version),
            value=c.interpretation.anomaly_class,
            vocabulary="anomaly_geometry",
            provenance=ProvenanceClass.DERIVED,
            processing_stage=processing_stage,
            evidence_ref=c.id,
            notes=("the detector's own neutral shape class; not a physical-object "
                   "claim and not ground truth"),
        ))
    if made:
        upsert_labels(dataset_id, made)
    return {"dataset_id": dataset_id, "created": len(made),
            "errors": errors, "labels": [l.model_dump(mode="json") for l in made]}
