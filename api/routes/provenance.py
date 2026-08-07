"""
Provenance as a first-class API surface.

Every rendered object should be able to say where each of its numbers came
from. These endpoints answer that for the three things a viewer draws: a
survey frame, a record, and an anomaly candidate.

Nothing here computes provenance -- `schemas.provenance` projects it from
fields the frame and record already carry, so these routes cannot disagree
with the data.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database.frames_store import load_frames, synthesize_frames_from_records
from database.records_store import load_records
from schemas.provenance import (
    CLASS_STRENGTH, ProvenanceClass, candidate_provenance, frame_provenance,
    record_provenance, summarise,
)
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/vocabulary")
def vocabulary():
    """
    The classes a viewer must be able to render, strongest evidence first.

    Exposed so a client never hard-codes the list: adding a class here makes
    it renderable without a client release.
    """
    return {
        "classes": [
            {"value": c.value, "strength": CLASS_STRENGTH[c],
             "meaning": _MEANING[c]}
            for c in sorted(ProvenanceClass, key=lambda x: -CLASS_STRENGTH[x])
        ],
        "note": ("An object should be badged with its WEAKEST class. It is only as "
                 "trustworthy as its least-supported component, and 'unavailable' is "
                 "a state to render, not a value to substitute."),
    }


_MEANING = {
    ProvenanceClass.MEASURED: "an instrument recorded it",
    ProvenanceClass.DECLARED_BY_SOURCE: "the file states it about itself",
    ProvenanceClass.SUPPLIED_BY_CALLER: "asserted at ingest, for this dataset only",
    ProvenanceClass.DERIVED: "computed from other quantities by a stated rule",
    ProvenanceClass.INFERRED: "deduced from the data's own values, with a justification",
    ProvenanceClass.ASSUMED: "taken as true without evidence, and labelled as such",
    ProvenanceClass.UNAVAILABLE: "genuinely absent -- not zero, not defaulted",
}


def _frames_for(dataset_id: str):
    frames = load_frames(dataset_id)
    if frames:
        return frames
    records = load_records(dataset_id)
    if not records:
        raise HTTPException(404, f"dataset {dataset_id!r} has no records")
    # Datasets ingested before frames existed still get an honest answer.
    return synthesize_frames_from_records(records)


@router.get("/{dataset_id}/frames")
def dataset_frame_provenance(dataset_id: str,
                             frame_id: Optional[str] = Query(None)):
    """Provenance for every survey frame in a dataset, or one named frame."""
    frames = _frames_for(dataset_id)
    if frame_id:
        frames = [f for f in frames if f.frame_id == frame_id]
        if not frames:
            raise HTTPException(404, f"no frame {frame_id!r} in dataset {dataset_id!r}")
    out = []
    for f in frames:
        entries = frame_provenance(f)
        out.append({
            "frame_id": f.frame_id,
            "source_file": f.source_file,
            "modality": f.modality.value if hasattr(f.modality, "value") else f.modality,
            "source_format": f.source_format,
            "provenance": [e.model_dump() for e in entries],
            "summary": summarise(entries),
        })
    return {"dataset_id": dataset_id, "frame_count": len(out), "frames": out}


@router.get("/{dataset_id}/records")
def dataset_record_provenance(dataset_id: str,
                              limit: int = Query(5, ge=1, le=200),
                              source_file: Optional[str] = Query(None)):
    """
    Provenance for a sample of records.

    Capped deliberately: provenance is constant across a frame's records by
    construction, so a handful is representative and a caller asking for
    millions is asking the wrong question.
    """
    records = load_records(dataset_id)
    if not records:
        raise HTTPException(404, f"dataset {dataset_id!r} has no records")
    if source_file:
        records = [r for r in records
                   if (r.metadata or {}).get("source_file") == source_file]
        if not records:
            raise HTTPException(404, f"no records from source_file {source_file!r}")
    by_id = {f.frame_id: f for f in _frames_for(dataset_id)}
    out = []
    for r in records[:limit]:
        entries = record_provenance(r, by_id.get(r.frame_id))
        out.append({
            "frame_id": r.frame_id,
            "source_file": (r.metadata or {}).get("source_file"),
            "trace_index": (r.metadata or {}).get("trace_index"),
            "sample_index": (r.metadata or {}).get("sample_index"),
            "provenance": [e.model_dump() for e in entries],
            "summary": summarise(entries),
        })
    return {"dataset_id": dataset_id, "sampled": len(out),
            "total_records": len(records), "records": out}


@router.post("/candidates")
def candidates_provenance(candidates: list[dict]):
    """
    Provenance for anomaly candidates supplied by the caller.

    Takes candidates rather than re-detecting them, so a viewer can ask about
    exactly what it is drawing. Detection stays where it belongs.
    """
    from interpretation.anomaly_candidates import AnomalyCandidate
    out = []
    for raw in candidates:
        try:
            c = AnomalyCandidate.model_validate(raw)
        except Exception as e:
            out.append({"id": raw.get("id"), "error": f"not an AnomalyCandidate: {e}"})
            continue
        entries = candidate_provenance(c)
        out.append({
            "id": c.id, "dataset_id": c.dataset_id,
            "source_file": c.evidence.source_file,
            "provenance": [e.model_dump() for e in entries],
            "summary": summarise(entries),
        })
    return {"count": len(out), "candidates": out}
