"""
Topographic/air-gap correction: productionizes the exact methodology
validated by `scripts/four_tu_topographic_correction_audit.py` -- real
evidence found real 4TU lines where the antenna's height above the actual
ground varies enough along the line to matter, once compared against a
matched DEM's own ground elevation. That was a research audit only,
writing a JSON artifact and touching no live dataset. This module is the
reusable, tested capability the audit's own docstring named as the next
step ("currently a research-audit finding only, not implemented as a
correction and not wired into any live dataset") -- still not wired to a
live API endpoint (a real design question of its own: how a live caller
supplies a matched DEM), but no longer a one-off script.

THE ARITHMETIC, UNCHANGED FROM THE AUDIT. `height_above_ground = antenna_
elevation - dem_ground_elevation` per trace; `deviation = height_above_
ground - median(height_above_ground)` (a RELATIVE quantity -- see the
schema module's docstring for why an unknown, possibly differing vertical
datum between the antenna and DEM elevation sources cancels out of this
differencing rather than needing to be known); `correction_ns = 2 *
deviation_m / C_M_PER_NS` (air/vacuum speed of light, NOT the ground
velocity -- this deviation is an AIR path, not a subsurface one). A
correction is only reported as `DERIVED` (applicable) when the largest
`|correction_ns|` across the line EXCEEDS the line's own sample interval;
below that, the acquisition's own temporal resolution cannot distinguish
the correction from no correction at all, and this module reports
`NOT_MATERIAL` rather than fabricate a precision the data does not support.

WHERE THE TWO ELEVATIONS COME FROM FOR A REAL, STORED DATASET.
`preprocessing.dem_alignment.align_records_with_dem` overwrites
`record.elevation` with the DEM's ground elevation, but (since the fix
alongside this module) first preserves whatever elevation the record
already carried -- e.g. an antenna's own GNSS reading -- into
`record.metadata["pre_dem_elevation_m"]`. `resolve_topographic_correction_
for_records` reads exactly those two fields, so it is only ever meaningful
for records that have ALREADY been through DEM alignment; a dataset that
has not, or whose sensor never carried its own elevation to begin with,
correctly reports `UNAVAILABLE`.

WHAT THIS MODULE NEVER DOES. It never overwrites a frame's own time-zero
correction (`corrected_time_ns`, from `preprocessing.time_zero`) --
`apply_topographic_correction` ADDS `topographic_corrected_time_ns` as a
further refinement on top of it, never in place of it. It never asserts an
absolute height-above-ground value, only a differential. It never applies
a per-trace correction that was not classified `DERIVED`.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Optional

from ingestion.four_tu_velocity import C_M_PER_NS
from preprocessing.trace_processing import _reconstruct_traces_by_index
from schemas.subterra_record import SubterraRecord
from schemas.topographic_correction import (
    TopographicCorrectionMethod, TopographicCorrectionResult, TopographicCorrectionStatus,
)

#: Fewer valid (antenna + ground) trace pairs than this cannot support a
#: defensible median/deviation computation -- mirrors the audit script's
#: own `len(points) < 3` guard.
MIN_VALID_TRACES = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def dem_antenna_differential_correction(
    antenna_elevation_m: dict[int, float],
    ground_elevation_m: dict[int, float],
    sample_interval_ns: float,
) -> TopographicCorrectionResult:
    """
    `antenna_elevation_m`/`ground_elevation_m`: trace_index -> elevation
    (m), from any two sources -- only the DIFFERENCE from each trace's own
    line-median height-above-ground is ever used (see module docstring),
    so an unknown constant vertical-datum offset between the two sources
    never needs to be known, let alone equal.
    """
    shared = sorted(set(antenna_elevation_m) & set(ground_elevation_m))
    if len(shared) < MIN_VALID_TRACES:
        return TopographicCorrectionResult(
            status=TopographicCorrectionStatus.UNAVAILABLE,
            method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
            basis=(f"only {len(shared)} trace(s) carry both an antenna elevation and a DEM "
                  f"ground elevation; at least {MIN_VALID_TRACES} are needed for a "
                  f"defensible median/deviation computation"),
            n_traces_evaluated=len(shared), generated_utc=_now(),
        )

    height_above_ground = {ti: antenna_elevation_m[ti] - ground_elevation_m[ti] for ti in shared}
    hag_values = list(height_above_ground.values())
    median_hag = statistics.median(hag_values)
    deviation = {ti: v - median_hag for ti, v in height_above_ground.items()}
    corrections_ns = {ti: 2 * dev / C_M_PER_NS for ti, dev in deviation.items()}
    max_abs = max(abs(v) for v in corrections_ns.values())
    hag_range = max(hag_values) - min(hag_values)
    hag_std = statistics.pstdev(hag_values)

    common_kwargs = dict(
        method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
        max_abs_correction_ns=max_abs, sample_interval_ns=sample_interval_ns,
        n_traces_evaluated=len(shared), n_traces_valid=len(shared),
        height_above_ground_range_m=hag_range, height_above_ground_std_m=hag_std,
        generated_utc=_now(),
    )

    if sample_interval_ns <= 0 or max_abs <= sample_interval_ns:
        return TopographicCorrectionResult(
            status=TopographicCorrectionStatus.NOT_MATERIAL,
            basis=(f"max |correction| {max_abs:.4f} ns does not exceed this line's own sample "
                  f"interval ({sample_interval_ns:.4f} ns) -- not resolvable against the "
                  f"acquisition's own temporal resolution, so no per-trace correction is "
                  f"reported"),
            **common_kwargs,
        )

    return TopographicCorrectionResult(
        status=TopographicCorrectionStatus.DERIVED,
        per_trace_correction_ns=corrections_ns,
        basis=(f"max |correction| {max_abs:.4f} ns exceeds this line's own sample interval "
              f"({sample_interval_ns:.4f} ns): the antenna's height above the real ground "
              f"(from a matched DEM) varies enough along this line to be resolvable, computed "
              f"as a differential from the line's own median height-above-ground so an "
              f"unknown constant vertical-datum offset between the antenna and DEM elevation "
              f"sources cancels out"),
        **common_kwargs,
    )


def resolve_topographic_correction_for_records(
    records: list[SubterraRecord], sample_interval_ns: float,
    trace_index_field: str = "trace_index",
) -> TopographicCorrectionResult:
    """
    Reads antenna elevation from `metadata["pre_dem_elevation_m"]` and
    ground elevation from `record.elevation` -- see module docstring for
    why these are the two fields, and why this is only meaningful for
    already-DEM-aligned records.
    """
    antenna: dict[int, float] = {}
    ground: dict[int, float] = {}
    for r in records:
        ti = r.metadata.get(trace_index_field)
        pre = r.metadata.get("pre_dem_elevation_m")
        if ti is None or pre is None or r.elevation is None:
            continue
        antenna.setdefault(ti, pre)
        ground.setdefault(ti, r.elevation)

    if not antenna:
        return TopographicCorrectionResult(
            status=TopographicCorrectionStatus.UNAVAILABLE,
            method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
            basis=("no record carries both a pre-DEM-alignment elevation "
                  "(metadata['pre_dem_elevation_m']) and a DEM ground elevation "
                  "(record.elevation) -- this dataset has not been DEM-aligned via "
                  "preprocessing.dem_alignment.align_records_with_dem, or its sensor never "
                  "recorded its own elevation to begin with"),
            generated_utc=_now(),
        )
    return dem_antenna_differential_correction(antenna, ground, sample_interval_ns)


def apply_topographic_correction(
    records: list[SubterraRecord], result: TopographicCorrectionResult,
    trace_index_field: str = "trace_index", time_field: str = "corrected_time_ns",
) -> list[SubterraRecord]:
    """
    Adds `topographic_corrected_time_ns` ON TOP OF the existing corrected
    time axis (`corrected_time_ns`, from `preprocessing.time_zero`) --
    this is a further REFINEMENT of that correction, never a replacement:
    `corrected_time_ns` itself is never touched. Every record gets the
    `topographic_correction_*` stamp in `processing_applied` regardless of
    status (mirrors `apply_time_zero_correction`'s own "always stamp the
    honest status" behaviour); only a record whose trace has an actual
    per-trace correction (`status == DERIVED` and its own trace_index
    present) gets a non-None `topographic_corrected_time_ns`.
    """
    stamp = result.as_processing_applied()
    corrections = (
        result.per_trace_correction_ns
        if result.status == TopographicCorrectionStatus.DERIVED and result.per_trace_correction_ns
        else {}
    )
    for r in records:
        existing = r.metadata.get("processing_applied") or {}
        r.metadata["processing_applied"] = {**existing, **stamp}
        base = r.metadata.get(time_field)
        ti = r.metadata.get(trace_index_field)
        correction = corrections.get(ti) if ti is not None else None
        if base is not None and correction is not None:
            r.metadata["topographic_corrected_time_ns"] = base - correction
        else:
            r.metadata["topographic_corrected_time_ns"] = None
    return records


# ---------------------------------------------------------------------------
# production wiring: per frame, sample interval derived, then applied
# ---------------------------------------------------------------------------

def _sample_interval_for_frame_records(records: list[SubterraRecord]) -> Optional[float]:
    """
    Same derivation `preprocessing.time_zero.resolve_time_zero_for_frame`
    already uses: the median spacing between the first two samples of each
    reconstructed whole trace. Returns None if `records` are not in the
    per-sample-per-record shape `_reconstruct_traces_by_index` expects.
    """
    by_trace = _reconstruct_traces_by_index(records)
    if by_trace is None:
        return None
    intervals = []
    for recs in by_trace.values():
        times = [r.metadata.get("two_way_time_ns") for r in recs[:2]]
        if len(times) == 2 and all(t is not None for t in times):
            intervals.append(times[1] - times[0])
    return statistics.median(intervals) if intervals else None


def apply_topographic_correction_for_dataset(
    records: list[SubterraRecord], frames: list,
) -> tuple[list[SubterraRecord], dict[str, TopographicCorrectionResult]]:
    """
    Runs `resolve_topographic_correction_for_records` and applies the
    result, PER FRAME -- mirrors `preprocessing.time_zero.
    apply_time_zero_for_dataset`'s own per-frame scoping and for the same
    reason: each frame is a separate acquisition line, and the median
    height-above-ground this correction differences against is only
    meaningful within one line, never pooled across several.

    Records with no `frame_id`, or whose `frame_id` matches no frame in
    `frames`, are left completely untouched -- same as
    `apply_time_zero_for_dataset`.
    """
    frames_by_frame_id = {f.frame_id: f for f in frames}
    by_frame: dict[Optional[str], list[SubterraRecord]] = {}
    for r in records:
        by_frame.setdefault(r.frame_id, []).append(r)

    results: dict[str, TopographicCorrectionResult] = {}
    for frame_id, frame_records in by_frame.items():
        if frame_id is None or frame_id not in frames_by_frame_id:
            continue

        sample_interval_ns = _sample_interval_for_frame_records(frame_records)
        if not sample_interval_ns or sample_interval_ns <= 0:
            result = TopographicCorrectionResult(
                status=TopographicCorrectionStatus.UNAVAILABLE,
                method=TopographicCorrectionMethod.DEM_ANTENNA_DIFFERENTIAL,
                basis="no usable sample interval could be established from these records' own "
                     "two_way_time_ns spacing",
            )
        else:
            result = resolve_topographic_correction_for_records(frame_records, sample_interval_ns)

        if result.resolved:
            result = result.model_copy(update={"applied": True})
        apply_topographic_correction(frame_records, result)
        results[frame_id] = result

    return records, results
