"""
Generating a candidate set for a held dataset, with its provenance.

This is the seam between the detector (`interpretation.anomaly_candidates`,
unchanged) and the stored, inspectable candidate set the API serves. It decides
one thing the detector deliberately does not: whether candidate generation is
possible for this dataset at all, and if not, exactly what is missing.

WHY BLOCKED IS A REAL ANSWER HERE. The detector raises if a dataset has not been
through trace-local anomaly preprocessing, because reading raw amplitude as if
it were a z-score would misinterpret physical units as statistical evidence.
That is the right refusal, but an exception is not a useful answer to a user.
This module turns it into a BLOCKED state that names the missing step -- the
same shape every other assessment in the platform uses, and for the same
reason: a blocked state nobody can act on is a dead end.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from database.candidates_store import StoredCandidateSet, load_candidates, save_candidates
from database.records_store import load_records
from interpretation.anomaly_candidates import find_anomaly_candidates_all_lines
from interpretation.candidate_intelligence import (
    CandidateGeneration, CandidateIntelligence, GenerationParameters,
    assess_staleness, blocked, build_intelligence, inspectable, input_fingerprint, utcnow,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def _newest_declaration_at(db: Session, dataset_id: str):
    """
    When this dataset's spatial reference last changed.

    Folded into the input fingerprint so that declaring a CRS, datum, tie or
    velocity makes an existing candidate set stale -- exactly as Stage 8 made
    fusion samples stale, and for the same reason: the data now means something
    different from what it meant when the candidates were computed.
    """
    from database.models import SpatialDeclaration

    rows = (db.query(SpatialDeclaration)
              .filter(SpatialDeclaration.dataset_id == dataset_id)
              .all())
    stamps = [r.created_at for r in rows if r.created_at]
    return max(stamps) if stamps else None


def _anomaly_ready(records) -> bool:
    """Trace-local anomaly preprocessing marks every record it touches."""
    return bool(records) and all(
        r.metadata.get("anomaly_reliable") is not None for r in records
    )


def _trace_addressable(records) -> bool:
    """
    Whether these records carry the trace/depth addressing the rule needs.

    `anomaly_reliable` ALONE IS NOT ENOUGH, and this is not hypothetical: the
    Lazaresti depth slice carries it from the (lat, lon) grid anomaly mode,
    which computes a genuine z-score over a different geometry entirely. Its
    records have no `trace_index`, so the connected-component rule -- which
    works on a (depth x trace) grid -- has nothing to build a grid from.
    Checking only the reliability flag let that dataset through to a ValueError
    deep in the grid builder, which reaches the user as a 500 rather than as an
    answer. The two preprocessing modes are different capabilities and the
    difference has to be visible here.
    """
    return bool(records) and all(
        r.metadata.get("trace_index") is not None and r.depth is not None
        for r in records
    )


def current_fingerprint(dataset_id: str, records) -> str:
    # `source_file` and `trace_index` live in `metadata`, not as columns:
    # trace_index is only unique within one file, so the pipeline groups on both.
    return input_fingerprint(
        dataset_id=dataset_id,
        source_files=sorted({f for f in (r.metadata.get("source_file") for r in records) if f}),
        n_records=len(records),
        preprocessing_mode="gpr_local_anomaly",
    )


def _count_traces(records) -> Optional[int]:
    """
    Distinct traces examined, for the candidate-burden figure.

    None rather than 0 when the records carry no trace index: absence is not
    zero, and a burden of 0.0 would claim there is nothing to inspect.
    """
    traces = {(r.metadata.get("source_file"), r.metadata.get("trace_index"))
              for r in records if r.metadata.get("trace_index") is not None}
    return len(traces) or None


def generate(db: Session, dataset_id: str,
             parameters: Optional[GenerationParameters] = None) -> CandidateIntelligence:
    """
    Run candidate generation and store the result with its provenance.

    Nothing is invented and nothing is filtered on a claim the data cannot
    support: `min_trace_span` is applied here because it is a property of the
    candidate's own measured trace range, and it is recorded in the parameters
    so a set produced under it can never be mistaken for the baseline.
    """
    parameters = parameters or GenerationParameters()
    records = load_records(dataset_id, use_cache=False)

    if not records:
        return blocked(dataset_id, "this dataset holds no records",
                       ["an ingested dataset with records to analyse"])
    if not _anomaly_ready(records):
        return blocked(
            dataset_id,
            "trace-local anomaly preprocessing has not been run on this dataset",
            ["reprocessing with preprocessing_mode='gpr_local_anomaly', which "
             "computes the local-anomaly z-score the candidate rule reads"],
        )
    if not _trace_addressable(records):
        return blocked(
            dataset_id,
            "this dataset carries an anomaly score computed over a different "
            "geometry: its records have no trace index, so there is no "
            "(depth x trace) grid for the candidate rule to group",
            ["reprocessing with preprocessing_mode='gpr_local_anomaly'. This "
             "dataset appears to hold the (lat, lon) grid anomaly score "
             "instead, which is a real measurement of something else"],
        )

    by_file = find_anomaly_candidates_all_lines(
        records, threshold=parameters.threshold, min_cells=parameters.min_cells)

    kept = []
    for candidates in by_file.values():
        for c in candidates:
            lo, hi = c.evidence.trace_range
            if (hi - lo + 1) >= parameters.min_trace_span:
                kept.append(inspectable(c))

    generation = CandidateGeneration(
        generated_at=utcnow(),
        dataset_id=dataset_id,
        parameters=parameters,
        input_fingerprint=current_fingerprint(dataset_id, records),
        declared_reference_at=_newest_declaration_at(db, dataset_id),
        n_source_files=len(by_file),
        n_records=len(records),
    )
    n_traces = _count_traces(records)
    save_candidates(StoredCandidateSet(
        dataset_id=dataset_id, generation=generation,
        candidates=kept, n_traces=n_traces))

    logger.info("candidate generation for %s produced %d candidates over %d lines",
                dataset_id, len(kept), len(by_file))
    return build_intelligence(
        dataset_id, kept, generation=generation, status="available",
        status_reason=f"generated from {len(by_file)} survey line(s)",
        n_traces=n_traces)


def current(db: Session, dataset_id: str) -> CandidateIntelligence:
    """
    The stored candidate set, with staleness assessed against the dataset now.

    A stale set is still returned rather than hidden: the candidates are what
    the method genuinely produced, and concealing them would replace a visible
    problem with an invisible one. `staleness.reasons` says why they may no
    longer apply, and nothing is recomputed on the caller's behalf.
    """
    stored = load_candidates(dataset_id)
    if stored is None:
        return blocked(
            dataset_id, "candidate generation has not been run for this dataset",
            ["a candidate generation run"])

    records = load_records(dataset_id, use_cache=False)
    staleness = assess_staleness(
        stored.generation,
        current_fingerprint=current_fingerprint(dataset_id, records) if records else None,
        newest_declaration_at=_newest_declaration_at(db, dataset_id),
        check_declarations=True,
        current_parameters=stored.generation.parameters,
    )
    return build_intelligence(
        dataset_id, stored.candidates, generation=stored.generation,
        staleness=staleness,
        status="limited" if staleness.is_stale else "available",
        status_reason=("this candidate set no longer matches the dataset"
                       if staleness.is_stale
                       else f"generated from {stored.generation.n_source_files} survey line(s)"),
        n_traces=stored.n_traces)
