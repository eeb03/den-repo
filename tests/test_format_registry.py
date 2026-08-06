"""
The converter registry as the single source of truth for readable formats,
and the explicit boundary for formats we recognise but cannot read.

Before this, `ingestion/downloader.py` kept its own hand-maintained copy of
the extension set. Two lists that must agree but are edited separately will
eventually disagree; `test_downloader_derives_from_registry` makes that
impossible. And archive scanning dropped unreadable files silently, so a zip
full of proprietary GPR data was indistinguishable from an empty one.
"""
import zipfile

import pytest

from converters.registry import (
    KNOWN_UNSUPPORTED_FORMATS, classify_file, describe_unsupported,
    get_converter, is_supported, supported_extensions,
)
from ingestion.downloader import extract_zip_and_find_supported_files, scan_archive


# --- registry is the single source of truth ---

def test_supported_extensions_covers_every_registered_converter():
    exts = supported_extensions()
    for ext in (".csv", ".xyz", ".tsv", ".sgy", ".segy", ".las", ".laz", ".tif", ".tiff"):
        assert ext in exts, f"{ext} lost from the registry"


def test_supported_extensions_reflects_a_runtime_registration():
    """Computed live, not frozen at import -- register_converter must take effect."""
    from converters.base import BaseConverter
    from converters.registry import _CONVERTERS, register_converter

    class _Fake(BaseConverter):
        format_name = "fake"
        supported_extensions = (".fakeext",)

        def convert(self, path, dataset_id, sensor_type, **kwargs):
            return []

    assert ".fakeext" not in supported_extensions()
    register_converter(_Fake())
    try:
        assert ".fakeext" in supported_extensions()
        assert get_converter("x.fakeext").format_name == "fake"
    finally:
        _CONVERTERS.pop()
    assert ".fakeext" not in supported_extensions()


def test_downloader_derives_from_registry_rather_than_a_private_copy():
    import ingestion.downloader as dl
    assert not hasattr(dl, "SUPPORTED_EXTENSIONS"), (
        "downloader must not keep its own extension list; it duplicates the registry"
    )


# --- recognised-but-unreadable formats ---

def test_known_unsupported_formats_are_named_not_silently_skipped():
    assert describe_unsupported("survey.dt") == "IDS GeoRadar (proprietary GPR)"
    assert describe_unsupported("line.rd3").startswith("MALA")
    assert describe_unsupported("scan.dzt").startswith("GSSI")
    assert describe_unsupported("readme.txt") is None


def test_no_unsupported_format_is_also_claimed_as_supported():
    """A format cannot simultaneously be readable and listed as unreadable."""
    assert not (set(KNOWN_UNSUPPORTED_FORMATS) & supported_extensions())


@pytest.mark.parametrize("name,expected", [
    ("a.csv", "supported"),
    ("a.SGY", "supported"),
    ("a.dt", "recognized_unsupported"),
    ("a.dzt", "recognized_unsupported"),
    ("a.txt", "unknown"),
    ("noext", "unknown"),
])
def test_classify_file(name, expected):
    assert classify_file(name)[0] == expected


def test_get_converter_error_names_a_recognised_format(tmp_path):
    """The error should say 'IDS GeoRadar, no adapter yet', not 'unknown extension'."""
    with pytest.raises(ValueError, match="IDS GeoRadar"):
        get_converter("survey.dt")
    with pytest.raises(ValueError, match="No converter registered"):
        get_converter("survey.qqq")


def test_is_supported():
    assert is_supported("a.sgy") and not is_supported("a.dt")


# --- archive scanning ---

def _zip(tmp_path, names):
    path = tmp_path / "archive.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for n in names:
            zf.writestr(n, "lat,lon,signal\n41.0,15.0,1.0\n" if n.endswith(".csv") else "binary")
    return path


def test_scan_archive_separates_supported_from_recognised_unsupported(tmp_path):
    path = _zip(tmp_path, ["Site/line1.csv", "Site/line2.dt", "Site/line3.dt", "Site/readme.txt"])
    scan = scan_archive(path, extract_to=tmp_path / "out")
    assert [p.name for p in scan.supported] == ["line1.csv"]
    assert len(scan.recognized_unsupported) == 2
    assert scan.unsupported_summary() == {"IDS GeoRadar (proprietary GPR)": 2}


def test_scan_archive_of_only_proprietary_files_reports_them(tmp_path):
    """The case that used to look identical to an empty archive."""
    path = _zip(tmp_path, ["a.dt", "b.dt", "c.rd3"])
    scan = scan_archive(path, extract_to=tmp_path / "out")
    assert scan.supported == []
    assert scan.unsupported_summary() == {
        "IDS GeoRadar (proprietary GPR)": 2, "MALA RAMAC (proprietary GPR)": 1,
    }


def test_scan_archive_excludes_macos_appledouble_sidecars(tmp_path):
    path = _zip(tmp_path, ["Site/line1.csv", "__MACOSX/Site/._line1.csv", "Site/._line1.csv"])
    scan = scan_archive(path, extract_to=tmp_path / "out")
    assert [p.name for p in scan.supported] == ["line1.csv"]
    assert scan.recognized_unsupported == []


def test_legacy_extract_helper_still_returns_supported_files_only(tmp_path):
    """Backward compatibility: the old function keeps its exact contract."""
    path = _zip(tmp_path, ["a.csv", "b.dt"])
    found = extract_zip_and_find_supported_files(path, extract_to=tmp_path / "out")
    assert [p.name for p in found] == ["a.csv"]
