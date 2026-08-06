"""
IDS GeoRadar .dt ingestion.

Exercised against REAL acquisition data: tests/fixtures/ids_dt_sample.dt is
the verbatim header block plus first 8 trace records of a file from Zenodo
record 14637589 (Guangzhou University GPR dataset). Nothing is synthesised,
so the parser is tested against bytes a real IDS instrument wrote -- but the
fixture is 24 KB rather than the 3.8 GB source archive.

The format is proprietary and undocumented. These tests pin what was
actually established: the acquisition TIME WINDOW is present, in the H
record, and is read from the file rather than assumed. Coordinates and a CRS
are genuinely absent, and depth is not derived, because the only velocity
available is an operator setting -- the adapter must represent all three
states distinctly rather than filling any of them in.
"""
import struct
from pathlib import Path

import numpy as np
import pytest

from converters.ids_dt_converter import (
    IDSDTConverter, IDSDTParseError, derive_time_axis, parse_dt,
)
from converters.registry import (
    KNOWN_UNSUPPORTED_FORMATS, classify_file, get_converter, supported_extensions,
)
from schemas.spatial import AxisKind, CRSKind, CRSProvenance, PositionKind
from schemas.subterra_record import SensorType

FIXTURE = Path("tests/fixtures/ids_dt_sample.dt")
EXPECTED_TRACES = 8
EXPECTED_SAMPLES = 512
EXPECTED_LEN_REC = 1028
EXPECTED_DATA_START = 16448

pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="IDS .dt fixture missing")


@pytest.fixture(scope="module")
def parsed():
    return parse_dt(FIXTURE)


@pytest.fixture(scope="module")
def result():
    return IDSDTConverter().load(FIXTURE, dataset_id="ds", sensor_type=SensorType.GPR)


# --- file discovery ---

def test_dt_is_now_a_readable_format():
    assert ".dt" in supported_extensions()
    assert classify_file("x.dt")[0] == "supported"
    assert get_converter(FIXTURE).format_name == "ids_dt"


def test_dt_graduated_out_of_the_unsupported_map():
    """A format may not be both readable and listed as unreadable."""
    assert ".dt" not in KNOWN_UNSUPPORTED_FORMATS
    assert not (set(KNOWN_UNSUPPORTED_FORMATS) & supported_extensions())


def test_the_ids_sidecar_extension_is_still_only_recognised():
    """.dt_info is named but not claimed as readable -- no parser exists for it."""
    assert ".dt_info" in KNOWN_UNSUPPORTED_FORMATS
    assert ".dt_info" not in supported_extensions()


# --- parsing the real bytes ---

def test_header_magic_and_version(parsed):
    assert parsed["version"] == (4, 0, 0)
    assert parsed["len_rec"] == EXPECTED_LEN_REC


def test_data_start_is_located_from_the_R_sentinel(parsed):
    assert parsed["data_start"] == EXPECTED_DATA_START
    assert parsed["data_start"] % parsed["len_rec"] == 0


def test_trace_and_sample_counts(parsed):
    assert parsed["n_traces"] == EXPECTED_TRACES
    assert parsed["n_samples"] == EXPECTED_SAMPLES
    # samples/trace follows from the declared record length
    assert parsed["n_samples"] == (parsed["len_rec"] - 4) // 2
    assert parsed["trailing_bytes"] == 0


def test_sample_matrix_shape_and_dtype(parsed):
    s = parsed["samples"]
    assert s.shape == (EXPECTED_TRACES, EXPECTED_SAMPLES)
    assert s.dtype == np.dtype("<u2")


def test_samples_carry_real_signal_not_a_flat_line(parsed):
    """
    The source acquisition uses the full 16-bit range. A parser reading the
    wrong offset or endianness would produce a near-constant series, which
    is exactly what a wrong alignment looked like during development.
    """
    s = parsed["samples"]
    assert int(s.max()) > 40000
    assert float(s.std()) > 1000


def test_header_records_are_decoded(parsed):
    h = parsed["header"]
    assert h["I"] == "180124AA"
    assert "/" in h["C"] and ":" in h["C"]     # e.g. '01/24/18  hh:mm:ss'
    assert h["FZ"] == "180124AA"
    assert "N_CHANNEL" in h["S"]


def test_trace_markers_are_the_expected_sentinel(parsed):
    assert set(parsed["markers"][:, 0].tolist()) == {ord("R")}


def test_parsing_is_deterministic():
    a, b = parse_dt(FIXTURE), parse_dt(FIXTURE)
    assert np.array_equal(a["samples"], b["samples"])
    assert a["header"] == b["header"]
    assert (a["n_traces"], a["n_samples"]) == (b["n_traces"], b["n_samples"])


# --- malformed input fails explicitly ---

def test_a_non_dt_file_is_rejected_by_magic(tmp_path):
    bad = tmp_path / "bad.dt"
    bad.write_bytes(b"NOTADT" + b"\x00" * 100)
    with pytest.raises(IDSDTParseError, match="magic"):
        parse_dt(bad)


def test_a_file_without_the_R_sentinel_is_rejected(tmp_path):
    """Truncated acquisitions exist in the real archive; they must not parse silently."""
    truncated = tmp_path / "trunc.dt"
    truncated.write_bytes(FIXTURE.read_bytes()[:4096])
    with pytest.raises(IDSDTParseError, match="no 'R' header record"):
        parse_dt(truncated)


def test_an_implausible_record_length_is_rejected(tmp_path):
    bad = tmp_path / "bad.dt"
    bad.write_bytes(b"V" + bytes([4, 0, 0]) + struct.pack("<H", 2) + b"\x00" * 64)
    with pytest.raises(IDSDTParseError, match="record length"):
        parse_dt(bad)


def test_a_header_with_no_trace_records_is_rejected(tmp_path):
    header_only = tmp_path / "empty.dt"
    header_only.write_bytes(FIXTURE.read_bytes()[:EXPECTED_DATA_START])
    with pytest.raises(IDSDTParseError, match="no trace records"):
        parse_dt(header_only)


# --- records ---

def test_record_count_and_signal_round_trip(result, parsed):
    assert len(result.records) == EXPECTED_TRACES * EXPECTED_SAMPLES
    first = result.records[0]
    assert first.signal == [float(parsed["samples"][0, 0])]
    assert first.metadata["trace_index"] == 0
    assert first.metadata["sample_index"] == 0


def test_records_carry_trace_identity_matching_the_segy_shape(result):
    """The existing trace tooling keys on these, so the shape must match."""
    for r in result.records[:50]:
        assert {"source_file", "trace_index", "sample_index"} <= set(r.metadata)
    assert {r.metadata["trace_index"] for r in result.records} == set(range(EXPECTED_TRACES))


def test_convert_matches_load_records():
    c = IDSDTConverter()
    a = c.convert(FIXTURE, dataset_id="ds", sensor_type=SensorType.GPR)
    b = c.load(FIXTURE, dataset_id="ds", sensor_type=SensorType.GPR).records
    assert [r.to_flat_dict() for r in a[:100]] == [r.to_flat_dict() for r in b[:100]]


# --- position and CRS: absence must be represented, never filled in ---

def test_no_coordinates_are_fabricated(result):
    assert all(r.position.kind == PositionKind.NONE for r in result.records[:200])
    assert "no per-trace coordinates" in result.records[0].position.reason


def test_no_crs_is_invented(result):
    ref = result.frames[0].spatial_ref
    assert ref.kind == CRSKind.UNKNOWN
    assert ref.code is None
    assert ref.crs_provenance == CRSProvenance.NONE


def test_position_source_is_recorded_as_none(result):
    assert result.records[0].metadata["position_source"] == "none"


def test_depth_is_unset_despite_a_known_time_axis(result):
    """A measured time axis is not a depth axis: that step needs a real velocity."""
    assert all(r.depth is None for r in result.records[:200])


# --- frame ---

def test_one_frame_per_file_and_every_record_points_at_it(result):
    assert len(result.frames) == 1
    assert result.frames[0].frame_id == "ds:ids_dt_sample"
    assert {r.frame_id for r in result.records} == {"ds:ids_dt_sample"}


def test_frame_reports_geometry_and_format(result):
    f = result.frames[0]
    assert f.source_format == "ids_dt"
    assert f.n_positions == EXPECTED_TRACES
    assert f.position_index_name == "trace_index"
    assert f.source_metadata["record_length_bytes"] == EXPECTED_LEN_REC
    assert f.source_metadata["ids_version"] == "4.0.0"


def test_frame_carries_the_measured_time_axis(result):
    axis = result.frames[0].vertical_axis
    assert axis.kind == AxisKind.TWO_WAY_TIME_NS
    assert axis.units == "ns"
    assert axis.n_samples == EXPECTED_SAMPLES
    assert axis.sample_interval == pytest.approx(EXPECTED_INTERVAL_NS)
    # Still absent: no depth conversion was applied.
    assert axis.conversion is None


def test_frame_states_the_format_is_reverse_engineered(result):
    a = result.frames[0].assumption("format_specification")
    assert a is not None and a.verified is False
    assert "not publicly specified" in a.basis


def test_frame_states_why_there_are_no_coordinates(result):
    coords = result.frames[0].assumption("coordinates")
    assert coords is not None and coords.verified is True


def test_frame_records_companion_files_without_parsing_them(result):
    """The .ZON siblings are provenance, not interpreted data."""
    companions = result.frames[0].source_metadata["companion_files"]
    assert isinstance(companions, list)
    assert FIXTURE.name not in companions


# --- acquisition time axis, recovered from the H record ----------------------
#
# The window is MEASURED: it is stored in the file, not assumed. Depth is not
# derived from it, because the only velocity available is an operator setting.

EXPECTED_WINDOW_NS = 10.0
EXPECTED_INTERVAL_NS = EXPECTED_WINDOW_NS / EXPECTED_SAMPLES   # 0.01953125 ns


def test_acquisition_block_is_parsed_from_the_H_record(parsed):
    acq = parsed["acquisition"]
    assert acq, "H record acquisition block missing"
    assert len(acq["ascii_fields"]) == 10
    assert len(acq["ints"]) == 11


def test_time_window_is_read_from_the_file(parsed):
    axis = derive_time_axis(parsed["acquisition"], parsed["n_samples"])
    assert axis["time_window_ns"] == pytest.approx(EXPECTED_WINDOW_NS)


def test_sample_interval_is_the_window_divided_by_the_sample_count(parsed):
    axis = derive_time_axis(parsed["acquisition"], parsed["n_samples"])
    assert axis["sample_interval_ns"] == pytest.approx(EXPECTED_INTERVAL_NS)
    assert axis["sample_interval_ns"] * parsed["n_samples"] == pytest.approx(
        axis["time_window_ns"])


def test_the_files_own_cross_checks_agree(parsed):
    """
    The window is stored twice, and the file also records its own vertical
    cell size. Both must corroborate the derived interval for the axis to be
    reported as verified.
    """
    axis = derive_time_axis(parsed["acquisition"], parsed["n_samples"])
    assert axis["duplicate_field_agrees"] is True
    assert axis["stored_cell_size_agrees"] is True
    assert axis["stored_cell_size_s"] == pytest.approx(EXPECTED_INTERVAL_NS * 1e-9)


def test_every_sample_gets_a_two_way_time(result):
    """Time axis reaches the records, monotonic from zero across one trace."""
    trace0 = [r for r in result.records if r.metadata["trace_index"] == 0]
    assert len(trace0) == EXPECTED_SAMPLES
    twt = [r.metadata["two_way_time_ns"] for r in trace0]
    assert twt[0] == 0.0
    assert twt == sorted(twt)
    assert twt[-1] == pytest.approx(EXPECTED_WINDOW_NS - EXPECTED_INTERVAL_NS)
    assert all(
        twt[i + 1] - twt[i] == pytest.approx(EXPECTED_INTERVAL_NS)
        for i in range(len(twt) - 1)
    )


def test_the_time_axis_repeats_for_every_trace(result):
    per_trace = {}
    for r in result.records:
        per_trace.setdefault(r.metadata["trace_index"], []).append(
            r.metadata["two_way_time_ns"])
    axes = list(per_trace.values())
    assert len(axes) == EXPECTED_TRACES
    assert all(a == axes[0] for a in axes[1:])


def test_frame_records_the_measured_window_as_verified(result):
    a = result.frames[0].assumption("time_window")
    assert a is not None
    assert a.value == pytest.approx(EXPECTED_WINDOW_NS)
    assert a.verified is True          # both cross-checks agreed
    assert "MEASURED" in a.basis


def test_depth_is_still_not_derived_and_the_velocity_is_flagged(result):
    """A measured time axis must not be silently promoted to a depth axis."""
    assert all(r.depth is None for r in result.records[:200])
    a = result.frames[0].assumption("depth_not_derived")
    assert a is not None and a.verified is False
    assert a.value == pytest.approx(1.0e8)     # operator setting, m/s
    assert "not a site measurement" in a.basis


def test_time_axis_provenance_is_preserved_on_the_frame(result):
    ta = result.frames[0].source_metadata["time_axis"]
    assert ta["time_window_ns"] == pytest.approx(EXPECTED_WINDOW_NS)
    assert ta["n_samples"] == EXPECTED_SAMPLES
    assert ta["configured_velocity_m_per_s"] == pytest.approx(1.0e8)


# --- missing / malformed / implausible metadata must fail loudly -------------

def test_missing_acquisition_block_is_an_explicit_failure():
    with pytest.raises(IDSDTParseError, match="missing or truncated"):
        derive_time_axis({}, 512)


def test_unparseable_window_is_an_explicit_failure():
    acq = {"ascii_fields": [None] * 10, "ints": [0] * 11}
    with pytest.raises(IDSDTParseError, match="not a number"):
        derive_time_axis(acq, 512)


@pytest.mark.parametrize("bad", [0.0, -1e-8, 1.0, 1e3])
def test_implausible_window_is_rejected_rather_than_used(bad):
    """A 1-second 'window' would imply kilometres of penetration."""
    fields = [0.0] * 10
    fields[2] = fields[3] = bad
    with pytest.raises(IDSDTParseError, match="plausible range|not a number"):
        derive_time_axis({"ascii_fields": fields, "ints": [0] * 11}, 512)


def test_zero_samples_is_rejected():
    fields = [0.0] * 10
    fields[2] = fields[3] = 1e-8
    with pytest.raises(IDSDTParseError, match="time axis over"):
        derive_time_axis({"ascii_fields": fields, "ints": [0] * 11}, 0)


def test_a_disagreeing_cell_size_is_reported_not_hidden():
    """
    Observed on v3 files: the stored cell size is half the derived interval.
    The derived value wins and the disagreement is surfaced, never silently
    accepted.
    """
    fields = [0.0] * 10
    fields[2] = fields[3] = 8e-8
    fields[9] = 7.8125e-11            # = window / (samples * 2), not window / samples
    axis = derive_time_axis({"ascii_fields": fields, "ints": [0] * 11}, 512)
    assert axis["stored_cell_size_agrees"] is False
    assert axis["sample_interval_ns"] == pytest.approx(8e-8 / 512 * 1e9)


def test_a_file_whose_time_axis_cannot_be_built_does_not_ingest(tmp_path):
    """Ingestion fails rather than emitting records on a fabricated axis."""
    raw = bytearray(FIXTURE.read_bytes())
    h = parse_dt(FIXTURE)["acquisition"]["h_offset"]
    # blank the ASCII block so the window cannot be read
    raw[h + 4 + 44: h + 4 + 44 + 160] = b" " * 160
    broken = tmp_path / "no_window.dt"
    broken.write_bytes(bytes(raw))
    with pytest.raises(IDSDTParseError):
        IDSDTConverter().load(broken, dataset_id="ds", sensor_type=SensorType.GPR)
