import csv
from pathlib import Path

import pytest

from converters.registry import get_converter
from validators.dataset_validator import validate_dataset
from preprocessing.pipeline import run_pipeline
from schemas.subterra_record import SensorType


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "downloaded_survey.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["lat", "lon", "elevation", "reading", "timestamp"])
        for i in range(20):
            writer.writerow([40.0 + i * 0.0001, -105.0 - i * 0.0001, 1600.0, 100 + i, f"2024-01-01T00:{i:02d}:00"])
    return path


def test_full_pipeline_convert_validate_preprocess(sample_csv):
    """
    Mirrors what _run_ingest_pipeline does end to end, without the FastAPI/
    DB layer: convert -> validate -> preprocess. This is the same chain a
    downloaded Zenodo/OpenTopography file goes through via /ingest_from_url.
    """
    converter = get_converter(sample_csv)
    dataset_id = "test-dataset-1"
    records = converter.convert(sample_csv, dataset_id=dataset_id, sensor_type=SensorType.MAGNETOMETER)
    assert len(records) == 20

    report = validate_dataset(records, dataset_id=dataset_id, source_file=sample_csv)
    assert report.record_count == 20
    assert report.quality_score > 0.8

    processed = run_pipeline(records)
    assert len(processed) == 20
    # signal preprocessing shouldn't change record count or coordinates
    assert processed[0].latitude == records[0].latitude


def test_unsupported_extension_raises_before_pipeline(tmp_path):
    path = tmp_path / "raw_gssi_scan.lte"  # unsupported raw GPR format
    path.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError):
        get_converter(path)
