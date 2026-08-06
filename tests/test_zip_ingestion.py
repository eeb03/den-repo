import zipfile

import pytest

from ingestion.downloader import extract_zip_and_find_supported_files
# The readable-format set now comes from the converter registry, which is its
# single source of truth; downloader.py no longer keeps a private copy.
from converters.registry import supported_extensions as _supported_extensions

SUPPORTED_EXTENSIONS = _supported_extensions()
from converters.registry import get_converter
from converters.csv_converter import CSVConverter
from schemas.subterra_record import SensorType


@pytest.fixture
def sample_zip(tmp_path):
    zip_path = tmp_path / "site.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Site_1/line1.csv", "lat,lon,signal\n45.0,25.0,1.0\n45.001,25.001,2.0\n")
        zf.writestr("Site_1/line2.csv", "lat,lon,signal\n45.0,25.0,1.5\n45.002,25.002,3.0\n")
        zf.writestr("Site_1/readme.txt", "not a supported format")
        zf.writestr("Site_1/subdir/notes.md", "also not supported")
    return zip_path


def test_extract_zip_finds_only_supported_files(sample_zip, tmp_path):
    found = extract_zip_and_find_supported_files(sample_zip, extract_to=tmp_path / "extracted")
    assert len(found) == 2
    assert all(f.suffix == ".csv" for f in found)


def test_extract_zip_with_no_supported_files_returns_empty(tmp_path):
    zip_path = tmp_path / "empty_useful.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        # .dzt (GSSI) stands in for a proprietary format with no adapter.
        # .dt is no longer an example: an IDS .dt reader now exists
        # (converters/ids_dt_converter.py).
        zf.writestr("data.dzt", b"proprietary format content")
        zf.writestr("readme.txt", "nothing usable here")
    found = extract_zip_and_find_supported_files(zip_path, extract_to=tmp_path / "extracted2")
    assert found == []


def test_extract_zip_skips_macos_appledouble_sidecar_files(tmp_path):
    """
    Regression test: real-world Mac-zipped archives contain ._filename
    sidecar files alongside every real file (Finder resource-fork
    metadata). These share the real file's extension but aren't valid
    data -- segyio correctly rejects them as corrupted when accidentally
    included. This confirms they're filtered out before conversion is
    ever attempted, exactly the bug hit on the real INGV/UNISA Site_1.zip
    (50/100 files were AppleDouble sidecars).
    """
    zip_path = tmp_path / "mac_zipped.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("line1.csv", "lat,lon,signal\n45.0,25.0,1.0\n")
        zf.writestr("._line1.csv", b"\x00\x05\x16\x07finder metadata garbage")
        zf.writestr("__MACOSX/._line1.csv", b"more finder metadata garbage")
    found = extract_zip_and_find_supported_files(zip_path, extract_to=tmp_path / "extracted_mac")
    assert len(found) == 1
    assert found[0].name == "line1.csv"


def test_extract_and_convert_all_files_in_zip(sample_zip, tmp_path):
    found = extract_zip_and_find_supported_files(sample_zip, extract_to=tmp_path / "extracted3")
    all_records = []
    for f in found:
        converter = get_converter(f)
        records = converter.convert(f, dataset_id="zip-test", sensor_type=SensorType.GPR)
        all_records.extend(records)
    assert len(all_records) == 4  # 2 records from each of 2 files
