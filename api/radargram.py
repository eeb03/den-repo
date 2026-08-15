"""
Assembling the honest description of one survey line's radargram.

This adds no new representation of the trace grid and no second candidate
model. It answers three questions the existing `trace_grid` response left to the
caller's judgement, each of which is a scientific claim rather than a formatting
choice:

  * what the numbers ARE (amplitude, or a statistic computed from it)
  * what the vertical axis IS (instrument time, or a depth derived from a
    velocity that somebody either declared or did not)
  * which cells carry a trustworthy statistic

The third is why `reliability_grid` exists. `preprocess_trace_local_anomaly`
marks a cell unreliable when its ring had too few neighbours to estimate a
background from -- and an unreliable cell is not a cell where nothing was found.
Rendering it identically to a confident zero would erase the distinction the
preprocessing went to the trouble of recording.
"""
from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy.orm import Session

from schemas.radargram import (
    RadargramSemantics, describe_field, describe_horizontal_axis,
    describe_vertical_axis,
)


def anomaly_processed(records) -> bool:
    """
    Whether these records carry a local-anomaly statistic in `signal`.

    Any record marked is enough to change what the grid MEANS: the
    preprocessing writes the flag on every record it touches, so a partially
    marked line is already a line whose `signal` is not purely amplitude.
    """
    return any(r.metadata.get("anomaly_reliable") is not None for r in records)


def velocity_is_declared(db: Optional[Session], dataset_id: str) -> bool:
    """
    Did somebody assert a propagation velocity for this dataset?

    The converter applies a default so that a depth axis exists at all; that is
    not an assertion and must not be reported as one. Only a `depth_conversion`
    spatial declaration counts. Absent a database session the answer is False --
    the weaker claim is the safe direction for an unknown.
    """
    if db is None:
        return False
    try:
        from database.models import SpatialDeclaration

        return db.query(SpatialDeclaration).filter(
            SpatialDeclaration.dataset_id == dataset_id,
            SpatialDeclaration.kind == "depth_conversion",
            SpatialDeclaration.superseded_at.is_(None),
        ).first() is not None
    except Exception:  # noqa: BLE001 -- no declarations table is "not declared"
        return False


def reliability_grid(records, source_file: Optional[str],
                     trace_indices: Sequence[int],
                     depths: Sequence[float]) -> Optional[list[list[Optional[bool]]]]:
    """
    Per-cell reliability, in the same (depth x trace) shape as the value grid.

    None for a cell means the acquisition recorded no sample there, which is a
    third state distinct from reliable and unreliable. Returns None entirely
    when the dataset has not been through anomaly preprocessing -- there is no
    reliability to report, and an all-True grid would invent one.

    Built here from the records rather than by extending
    `build_trace_depth_grid_for_records`, which many callers share and which has
    no business growing a second output for one consumer.
    """
    if not anomaly_processed(records):
        return None

    row_of = {round(float(d), 9): i for i, d in enumerate(depths)}
    col_of = {int(t): i for i, t in enumerate(trace_indices)}
    grid: list[list[Optional[bool]]] = [
        [None] * len(trace_indices) for _ in range(len(depths))
    ]

    for record in records:
        meta = record.metadata
        if source_file is not None and meta.get("source_file") != source_file:
            continue
        reliable = meta.get("anomaly_reliable")
        if reliable is None or record.depth is None:
            continue
        column = col_of.get(meta.get("trace_index"))
        row = row_of.get(round(float(record.depth), 9))
        if column is not None and row is not None:
            grid[row][column] = bool(reliable)
    return grid


def semantics(records, survey_frame: Optional[dict], field: str,
              velocity_m_per_ns: Optional[float],
              declared: bool,
              trace_geographic: Optional[Sequence[bool]],
              trace_along_track: Optional[Sequence[Optional[float]]],
              reliability: Optional[list[list[Optional[bool]]]],
              n_cells: Optional[int] = None) -> RadargramSemantics:
    processed = anomaly_processed(records)
    unreliable = None
    if reliability is not None:
        unreliable = sum(1 for row in reliability for cell in row if cell is False)

    return RadargramSemantics(
        vertical=describe_vertical_axis(survey_frame, velocity_m_per_ns, declared),
        horizontal=describe_horizontal_axis(trace_geographic, trace_along_track),
        field=describe_field(field, processed),
        unreliable_cells=unreliable,
        total_cells=n_cells,
    )
