"""
Source resolution: files, directories, archives, and the sidecars that
belong with them.

The gap this closes: sidecar discovery used to live hardcoded inside
/ingest_zip_from_url, so a .kmz survey track was found for zip ingests and
nowhere else. Handing the platform the same .sgy directly, or the extracted
folder, silently lost the positioning data sitting right next to it.
"""
import zipfile

import pytest

from ingestion.source_resolver import (
    ACQUISITION_SIDECAR_EXTENSIONS, ResolutionResult, readable_formats, resolve,
)

CSV_BODY = "lat,lon,signal\n41.0,15.0,1.0\n"


def _write(root, names):
    for n in names:
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CSV_BODY if n.endswith(".csv") else "binary")
    return root


def _zip(tmp_path, names, name="archive.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for n in names:
            zf.writestr(n, CSV_BODY if n.endswith(".csv") else "binary")
    return path


# --- plain files ---

def test_a_single_supported_file_resolves_to_one_source(tmp_path):
    _write(tmp_path, ["line.csv"])
    result = resolve(tmp_path / "line.csv")
    assert [s.primary.name for s in result.sources] == ["line.csv"]
    assert result.sources[0].kind == "file"


def test_a_single_unreadable_but_recognised_file_is_reported_not_dropped(tmp_path):
    _write(tmp_path, ["survey.sgd"])
    result = resolve(tmp_path / "survey.sgd")
    assert result.sources == []
    assert result.unsupported_summary() == {"Sensors & Software (proprietary GPR)": 1}


def test_an_unknown_file_yields_nothing_and_claims_nothing(tmp_path):
    _write(tmp_path, ["notes.txt"])
    result = resolve(tmp_path / "notes.txt")
    assert result.sources == [] and result.recognized_unsupported == []


def test_a_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve(tmp_path / "nope.csv")


# --- directories ---

def test_a_directory_resolves_every_readable_file_inside(tmp_path):
    _write(tmp_path, ["Site/a.csv", "Site/b.csv", "Site/readme.txt"])
    result = resolve(tmp_path / "Site")
    assert sorted(s.primary.name for s in result.sources) == ["a.csv", "b.csv"]


def test_directory_resolution_recurses(tmp_path):
    _write(tmp_path, ["Site/ground/a.csv", "Site/drone/b.csv"])
    result = resolve(tmp_path / "Site")
    assert len(result.sources) == 2


def test_directory_resolution_excludes_appledouble_sidecars(tmp_path):
    _write(tmp_path, ["Site/a.csv", "Site/._a.csv", "__MACOSX/Site/._a.csv"])
    result = resolve(tmp_path / "Site")
    assert [s.primary.name for s in result.sources] == ["a.csv"]


# --- archives ---

def test_an_archive_is_extracted_and_resolved(tmp_path):
    path = _zip(tmp_path, ["Site/a.csv", "Site/b.csv"])
    result = resolve(path, extract_to=tmp_path / "out")
    assert sorted(s.primary.name for s in result.sources) == ["a.csv", "b.csv"]
    assert all(s.kind == "archive_member" for s in result.sources)
    assert all(s.archive_path == path for s in result.sources)


def test_an_archive_of_only_proprietary_files_says_so(tmp_path):
    """Distinguishable from an archive holding nothing of interest."""
    path = _zip(tmp_path, ["a.dzx", "b.dzx", "c.sgd"])
    result = resolve(path, extract_to=tmp_path / "out")
    assert result.sources == []
    assert result.unsupported_summary() == {
        "GSSI XML sidecar (read with its .dzt)": 2,
        "Sensors & Software (proprietary GPR)": 1,
    }


def test_an_empty_archive_reports_nothing_rather_than_failing(tmp_path):
    path = _zip(tmp_path, ["readme.txt"])
    result = resolve(path, extract_to=tmp_path / "out")
    assert result.sources == [] and result.unsupported_summary() == {}


# --- sidecar attachment ---

def test_a_kmz_attaches_to_every_segy_in_the_archive(tmp_path):
    """One KMZ commonly holds the tracks for a whole directory of lines."""
    path = _zip(tmp_path, ["Site/l1.sgy", "Site/l2.sgy", "Site/ANF.kmz"])
    result = resolve(path, extract_to=tmp_path / "out")
    assert len(result.sources) == 2
    for s in result.sources:
        assert [p.name for p in s.sidecars_with_suffix(ACQUISITION_SIDECAR_EXTENSIONS)] == ["ANF.kmz"]


def test_a_kmz_does_not_attach_to_unrelated_formats(tmp_path):
    path = _zip(tmp_path, ["Site/a.csv", "Site/ANF.kmz"])
    result = resolve(path, extract_to=tmp_path / "out")
    assert result.sources[0].sidecars == []


def test_acquisition_sidecars_are_deduplicated_across_sources(tmp_path):
    path = _zip(tmp_path, ["Site/l1.sgy", "Site/l2.sgy", "Site/ANF.kmz"])
    result = resolve(path, extract_to=tmp_path / "out")
    assert [p.name for p in result.acquisition_sidecars] == ["ANF.kmz"]


def test_same_stem_sidecars_attach_only_to_their_own_primary(tmp_path):
    _write(tmp_path, ["Site/l1.sgy", "Site/l1.hdr", "Site/l2.sgy", "Site/l2.hdr"])
    result = resolve(tmp_path / "Site")
    by_stem = {s.stem: [p.name for p in s.sidecars] for s in result.sources}
    assert by_stem["l1"] == ["l1.hdr"]
    assert by_stem["l2"] == ["l2.hdr"]


def test_a_single_file_still_finds_the_sidecar_next_to_it(tmp_path):
    """
    The case that used to be lost entirely: handing over one .sgy directly
    rather than a zip meant its .kmz was never looked for.
    """
    _write(tmp_path, ["Site/l1.sgy", "Site/ANF.kmz"])
    result = resolve(tmp_path / "Site" / "l1.sgy")
    assert len(result.sources) == 1
    assert [p.name for p in result.sources[0].sidecars] == ["ANF.kmz"]


def test_resolving_one_file_does_not_pull_in_its_siblings_as_sources(tmp_path):
    _write(tmp_path, ["Site/a.csv", "Site/b.csv"])
    result = resolve(tmp_path / "Site" / "a.csv")
    assert [s.primary.name for s in result.sources] == ["a.csv"]


# --- helpers ---

def test_readable_formats_comes_from_the_registry():
    formats = readable_formats()
    assert ".sgy" in formats and ".csv" in formats
    assert ".dt" in formats          # IDS .dt is now readable
    assert ".dzt" in formats         # GSSI now is too
    assert ".sgd" not in formats     # Sensors & Software still is not


def test_unsupported_summary_of_an_empty_result_is_empty(tmp_path):
    assert ResolutionResult(root=tmp_path).unsupported_summary() == {}
