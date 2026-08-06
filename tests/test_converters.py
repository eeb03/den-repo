import csv
from pathlib import Path

import pytest

from converters.csv_converter import CSVConverter
from converters.registry import get_converter
from schemas.subterra_record import SensorType


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "mag_survey.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["lat", "lon", "elevation", "reading", "timestamp"])
        writer.writerow([40.001, -105.001, 1600.0, 123.4, "2024-01-01T00:00:00"])
        writer.writerow([40.002, -105.002, 1601.0, 125.1, "2024-01-01T00:01:00"])
        writer.writerow(["bad", -105.003, 1602.0, 127.0, "2024-01-01T00:02:00"])  # malformed lat
    return path


def test_csv_converter_parses_valid_rows(sample_csv):
    converter = CSVConverter()
    records = converter.convert(sample_csv, dataset_id="ds1", sensor_type=SensorType.MAGNETOMETER)
    assert len(records) == 2  # malformed row skipped
    assert records[0].latitude == 40.001
    assert records[0].longitude == -105.001
    assert records[0].signal == [123.4]
    assert records[0].elevation == 1600.0
    assert records[0].timestamp is not None


def test_csv_converter_missing_coords_raises(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("foo,bar\n1,2\n")
    converter = CSVConverter()
    with pytest.raises(ValueError):
        converter.convert(path, dataset_id="ds1", sensor_type=SensorType.GRAVITY)


def test_registry_dispatches_by_extension(sample_csv):
    converter = get_converter(sample_csv)
    assert converter.format_name == "csv"


def test_registry_raises_on_unknown_extension(tmp_path):
    path = tmp_path / "file.unknownext"
    path.write_text("data")
    with pytest.raises(ValueError):
        get_converter(path)
