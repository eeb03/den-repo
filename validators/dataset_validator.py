"""
Validates a converted dataset (a list of SubterraRecords) and produces
a DatasetQualityReport: integrity, coordinate validity, missing-data,
and an overall quality score.
"""
import math
from pathlib import Path

from schemas.subterra_record import SubterraRecord, DatasetQualityReport
from utils.checksum import sha256_of_file
from utils.logger import get_logger

logger = get_logger(__name__)


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

    missing_coords = 0
    missing_timestamps = 0
    missing_depth = 0
    invalid_signal = 0
    out_of_bounds = 0

    for r in records:
        if r.latitude == 0.0 and r.longitude == 0.0:
            missing_coords += 1
        if not (-90 <= r.latitude <= 90 and -180 <= r.longitude <= 180):
            out_of_bounds += 1
        if r.timestamp is None:
            missing_timestamps += 1
        if r.depth is None:
            missing_depth += 1
        if any(math.isnan(x) or math.isinf(x) for x in r.signal):
            invalid_signal += 1

    if out_of_bounds:
        issues.append(f"{out_of_bounds} record(s) have out-of-bounds coordinates.")
    if missing_coords:
        issues.append(f"{missing_coords} record(s) have null-island (0,0) coordinates — likely missing data.")
    if invalid_signal:
        issues.append(f"{invalid_signal} record(s) contain NaN/Inf signal values.")

    coordinate_bounds_valid = out_of_bounds == 0

    # Weighted quality score: coordinate integrity matters most, then signal
    # integrity, then completeness of optional fields (timestamp/depth).
    coord_score = 1.0 - (missing_coords + out_of_bounds) / n
    signal_score = 1.0 - invalid_signal / n
    completeness_score = 1.0 - ((missing_timestamps + missing_depth) / (2 * n))

    quality_score = round(
        max(0.0, 0.5 * coord_score + 0.3 * signal_score + 0.2 * completeness_score), 4
    )

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
