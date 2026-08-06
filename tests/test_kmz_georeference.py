import zipfile

import numpy as np
import pytest

from ingestion.kmz_georeference import (
    parse_kmz, resample_path_by_arc_length, find_matching_kmz_files, build_georeference_lookup,
    georeference_records_by_trace,
)
from schemas.subterra_record import SubterraRecord, SensorType


@pytest.fixture
def sample_kmz(tmp_path):
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<Placemark><name>C1T_7,5_0001</name><LineString><coordinates>15.01300,41.05300,0 15.01310,41.05305,0 15.01320,41.05310,0</coordinates></LineString></Placemark>
<Folder>
<Placemark><name>c2_7,5_0001 (2)</name><LineString><coordinates>15.01346,41.05357,0 15.01347,41.05356,0</coordinates></LineString></Placemark>
</Folder>
<Placemark><name>point_only</name></Placemark>
</Document>
</kml>"""
    kmz_path = tmp_path / "ANF_CARRELLO.kmz"
    with zipfile.ZipFile(kmz_path, "w") as zf:
        zf.writestr("doc.kml", kml_content)
    return kmz_path


def test_parse_kmz_finds_top_level_and_nested_placemarks(sample_kmz):
    parsed = parse_kmz(sample_kmz)
    assert "C1T_7,5_0001" in parsed
    assert "c2_7,5_0001 (2)" in parsed  # nested inside a Folder
    assert len(parsed["C1T_7,5_0001"]) == 3


def test_parse_kmz_skips_placemarks_without_linestring(sample_kmz):
    parsed = parse_kmz(sample_kmz)
    assert "point_only" not in parsed


def test_resample_path_preserves_endpoints():
    coords = [(0, 0), (1, 0), (1.2, 0), (5, 0), (10, 0)]
    result = resample_path_by_arc_length(coords, 6)
    assert np.allclose(result[0], [0, 0])
    assert np.allclose(result[-1], [10, 0])


def test_resample_path_produces_even_spacing_regardless_of_input_irregularity():
    coords = [(0, 0), (1, 0), (1.2, 0), (5, 0), (10, 0)]  # very uneven
    result = resample_path_by_arc_length(coords, 6)
    spacings = np.diff(result[:, 0])
    assert np.allclose(spacings, spacings[0], atol=1e-9)


def test_resample_path_matches_or_exceeds_original_point_count():
    coords = [(15.013 + i * 0.0001, 41.053) for i in range(22)]
    result = resample_path_by_arc_length(coords, 72)
    assert len(result) == 72


def test_find_matching_kmz_files_skips_appledouble(tmp_path):
    (tmp_path / "._ANF_CARRELLO.kmz").write_bytes(b"garbage")
    real = tmp_path / "ANF_CARRELLO.kmz"
    with zipfile.ZipFile(real, "w") as zf:
        zf.writestr("doc.kml", "<kml xmlns='http://www.opengis.net/kml/2.2'><Document></Document></kml>")
    found = find_matching_kmz_files(tmp_path)
    assert len(found) == 1
    assert found[0].name == "ANF_CARRELLO.kmz"


def test_build_georeference_lookup_merges_multiple_kmz_files(tmp_path):
    kml1 = """<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>line_a</name><LineString><coordinates>1,1,0 2,2,0</coordinates></LineString></Placemark>
</Document></kml>"""
    kml2 = """<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>line_b</name><LineString><coordinates>3,3,0 4,4,0</coordinates></LineString></Placemark>
</Document></kml>"""
    p1, p2 = tmp_path / "a.kmz", tmp_path / "b.kmz"
    with zipfile.ZipFile(p1, "w") as zf: zf.writestr("doc.kml", kml1)
    with zipfile.ZipFile(p2, "w") as zf: zf.writestr("doc.kml", kml2)

    lookup = build_georeference_lookup([p1, p2])
    assert "line_a" in lookup and "line_b" in lookup


def _sample_record(trace_index, depth, source_file="C1T_7,5_0001"):
    return SubterraRecord(
        dataset_id="kmz-trace-test", sensor_type=SensorType.GPR,
        latitude=0.0, longitude=0.0, depth=depth, signal=[1.0],
        metadata={"trace_index": trace_index, "source_file": source_file},
    )


def test_georeference_records_by_trace_shares_one_position_across_samples():
    """Mirrors SEGYConverter's one-record-per-(trace,depth)-sample shape: 3 traces x 4 depth samples."""
    records = [_sample_record(trace_index=t, depth=d * 0.1) for t in range(3) for d in range(4)]
    path = [(15.0, 41.0), (15.001, 41.001), (15.002, 41.002)]

    n_georeferenced = georeference_records_by_trace(records, path)

    assert n_georeferenced == 3
    by_trace = {}
    for r in records:
        by_trace.setdefault(r.metadata["trace_index"], set()).add((r.latitude, r.longitude))
    assert all(len(coords) == 1 for coords in by_trace.values())  # every sample of a trace shares one position
    assert all(r.metadata["georeferenced_from_kmz"] for r in records)


def test_georeference_records_by_trace_flags_direction_as_unverified():
    """C3: trace-order-to-KMZ-path-order direction is an assumption, not verified ground truth -- must be visible in metadata."""
    records = [_sample_record(trace_index=t, depth=0.0) for t in range(3)]
    georeference_records_by_trace(records, [(15.0, 41.0), (15.01, 41.01)])
    assert all(r.metadata["kmz_direction_verified"] is False for r in records)


def test_georeference_records_by_trace_endpoints_match_path_endpoints():
    records = [_sample_record(trace_index=t, depth=0.0) for t in range(5)]
    path = [(15.0, 41.0), (15.01, 41.01)]

    georeference_records_by_trace(records, path)

    first = next(r for r in records if r.metadata["trace_index"] == 0)
    last = next(r for r in records if r.metadata["trace_index"] == 4)
    assert abs(first.longitude - 15.0) < 1e-9 and abs(first.latitude - 41.0) < 1e-9
    assert abs(last.longitude - 15.01) < 1e-9 and abs(last.latitude - 41.01) < 1e-9


def test_georeference_records_by_trace_handles_missing_trace_index_as_one_trace_per_record():
    # a converter that emits one record per full trace (no trace_index metadata) should still work
    records = [
        SubterraRecord(dataset_id="d", sensor_type=SensorType.GPR, latitude=0.0, longitude=0.0, signal=[1.0])
        for _ in range(4)
    ]
    n_georeferenced = georeference_records_by_trace(records, [(15.0, 41.0), (15.01, 41.01)])
    assert n_georeferenced == 4
    assert len({(r.latitude, r.longitude) for r in records}) == 4


def test_georeference_records_by_trace_empty_input():
    assert georeference_records_by_trace([], [(0.0, 0.0)]) == 0
