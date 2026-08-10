"""
Validates a converted dataset (a list of SubterraRecords) and produces
a DatasetQualityReport: integrity, coordinate validity, missing-data,
and an overall quality score.

THE SCORE HAS DIMENSIONS, and they are now returned rather than collapsed.
`quality_score` has always been a weighted sum of three sub-scores computed
here, but only the sum survived the function -- so a 0.83 that is entirely a
coordinate problem and a 0.83 that is entirely a signal problem rendered
identically, and a reader had no way to tell which dataset they were looking
at. `quality_dimensions` exposes the three, and `validate_dataset` now computes
its score FROM that function rather than alongside it, so the two cannot drift.
The score itself is unchanged, to the last decimal place.
"""
import math
from pathlib import Path

from schemas.dataset_report import QualityDimension
from schemas.spatial import PositionKind
from schemas.subterra_record import SubterraRecord, DatasetQualityReport
from utils.checksum import sha256_of_file
from utils.logger import get_logger

logger = get_logger(__name__)

#: The weighting that has always been applied: coordinate integrity matters
#: most, then signal integrity, then completeness of optional fields.
DIMENSION_WEIGHTS = {
    "coordinate_integrity": 0.5,
    "signal_integrity": 0.3,
    "field_completeness": 0.2,
}


def _counts(records: list[SubterraRecord]) -> dict[str, int]:
    """Every defect counted once, in one pass, for both callers below."""
    out = dict(missing_coordinates=0, no_position=0, missing_timestamps=0,
               missing_depth=0, invalid_signal=0, out_of_bounds=0)
    for r in records:
        # A record without geographic coordinates is only a DEFECT when it
        # claims to have them. A projected, odometry, or deliberately
        # unpositioned sample is complete as it stands, and used to be
        # penalised for carrying the (0, 0) placeholder it was forced to
        # invent.
        if r.position.kind == PositionKind.GEOGRAPHIC:
            if r.latitude is None or r.longitude is None:
                out["missing_coordinates"] += 1
            elif not (-90 <= r.latitude <= 90 and -180 <= r.longitude <= 180):
                out["out_of_bounds"] += 1
        elif r.position.kind == PositionKind.NONE:
            out["no_position"] += 1
        if r.timestamp is None:
            out["missing_timestamps"] += 1
        if r.depth is None:
            out["missing_depth"] += 1
        if any(math.isnan(x) or math.isinf(x) for x in r.signal):
            out["invalid_signal"] += 1
    return out


def quality_dimensions(records: list[SubterraRecord]) -> list[QualityDimension]:
    """
    The scored components of dataset quality, each with the counts behind it.

    Returns an empty list for an empty dataset: there is nothing to measure,
    and a dimension of 0.0 would claim a measurement of perfectly bad quality
    rather than the absence of one.
    """
    n = len(records)
    if n == 0:
        return []
    c = _counts(records)
    return [
        QualityDimension(
            name="coordinate_integrity",
            value=1.0 - (c["missing_coordinates"] + c["out_of_bounds"]) / n,
            weight=DIMENSION_WEIGHTS["coordinate_integrity"],
            basis=("records that declare a geographic position and carry valid, "
                   "in-bounds coordinates"),
            counts={"missing_coordinates": c["missing_coordinates"],
                    "out_of_bounds": c["out_of_bounds"],
                    "no_position_declared": c["no_position"], "records": n},
        ),
        QualityDimension(
            name="signal_integrity",
            value=1.0 - c["invalid_signal"] / n,
            weight=DIMENSION_WEIGHTS["signal_integrity"],
            basis="records whose sample values contain no NaN or Inf",
            counts={"invalid_signal": c["invalid_signal"], "records": n},
        ),
        QualityDimension(
            name="field_completeness",
            value=1.0 - ((c["missing_timestamps"] + c["missing_depth"]) / (2 * n)),
            weight=DIMENSION_WEIGHTS["field_completeness"],
            basis="presence of the optional timestamp and depth fields",
            counts={"missing_timestamps": c["missing_timestamps"],
                    "missing_depth": c["missing_depth"], "records": n},
        ),
    ]


def score_from_dimensions(dimensions: list[QualityDimension]) -> float:
    """
    The overall score, and the ONLY place it is computed.

    Unweighted dimensions contribute nothing by construction, so the report can
    add reported-only measures without moving a score other things depend on.
    """
    if not dimensions:
        return 0.0
    total = sum(d.weight * (d.value or 0.0) for d in dimensions)
    return round(max(0.0, total), 4)


def validate_dataset(
    records: list[SubterraRecord],
    dataset_id: str,
    source_file: str | Path | None = None,
) -> DatasetQualityReport:
    issues: list[str] = []
    n = len(records)

    if n == 0:
        return DatasetQualityReport(
            dataset_id=dataset_id,
            checksum=sha256_of_file(source_file) if source_file else "",
            record_count=0,
            quality_score=0.0,
            issues=["Dataset produced zero records after conversion."],
        )

    counted = _counts(records)
    missing_coords = counted["missing_coordinates"]
    no_position = counted["no_position"]
    missing_timestamps = counted["missing_timestamps"]
    missing_depth = counted["missing_depth"]
    invalid_signal = counted["invalid_signal"]
    out_of_bounds = counted["out_of_bounds"]

    if out_of_bounds:
        issues.append(f"{out_of_bounds} record(s) have out-of-bounds coordinates.")
    if missing_coords:
        issues.append(
            f"{missing_coords} record(s) declare a geographic position but carry no coordinates."
        )
    if no_position == n:
        issues.append(
            "No record carries a horizontal position. This is legitimate for formats that "
            "provide none (e.g. IDS .dt), but such a dataset cannot be georeferenced or fused."
        )
    if invalid_signal:
        issues.append(f"{invalid_signal} record(s) contain NaN/Inf signal values.")

    coordinate_bounds_valid = out_of_bounds == 0

    # Computed from the dimensions rather than beside them, so the number the
    # report shows and the number stored on the dataset row are the same
    # arithmetic and cannot diverge.
    quality_score = score_from_dimensions(quality_dimensions(records))

    report = DatasetQualityReport(
        dataset_id=dataset_id,
        checksum=sha256_of_file(source_file) if source_file else "",
        record_count=n,
        missing_coordinates=missing_coords,
        missing_timestamps=missing_timestamps,
        missing_depth=missing_depth,
        invalid_signal_count=invalid_signal,
        coordinate_bounds_valid=coordinate_bounds_valid,
        quality_score=quality_score,
        issues=issues,
    )

    logger.info(f"Validated dataset {dataset_id}: score={quality_score}, issues={len(issues)}")
    return report
