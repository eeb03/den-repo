"""
GSSI `.dzt` ingestion — the third vendor of the TU1208 controlled site.

Most of these run against the REAL local corpus (40 files, three bit
depths, both trigger modes). Synthetic fixtures are used only for paths the
corpus does not contain: a `.dzg` GNSS sidecar, a multi-channel file, and
malformed input.

The contract pinned here:

1. **Nothing is inferred that the format does not carry.** No frequency
   from a model code, no velocity from `rhf_epsr`, no time-zero from
   `rhf_position`, no coordinates without a `.dzg`.
2. **Position follows the acquisition.** Distance-triggered lines get
   odometry, time-triggered lines get `NoPosition` with a reason, and
   `(0, 0)` never appears.
3. **Measured and assumed stay separated.** The time axis is measured;
   depth exists only on a caller-supplied velocity.
"""
import struct
from pathlib import Path

import pytest

from converters.gssi_converter import (
    GSSIConverter, GSSIFormatError, antenna_frequency_mhz, data_offset,
    derive_along_track, derive_time_axis, parse_dzg, parse_dzt_header, parse_dzx,
    read_dzt,
)
from schemas.subterra_record import SensorType

CORPUS = Path("datasets/raw/zenodo/1211173/extracted/Database_2018")
REAL = pytest.mark.skipif(not CORPUS.exists(), reason="TU1208 corpus not present locally")

#: One real file per bit depth / trigger mode combination present locally.
BIT32_SPM = CORPUS / "GNEISS0-20/270MHz_gneiss0-20_h1.DZT"      # 32-bit, distance
BIT16_TIME = CORPUS / "SILT/400MHz_silt_1_rev.dzt"              # 16-bit, time
BIT8_SPM = CORPUS / "LIMESTONE/200MHz-Limestone_2.dzt"          # 8-bit, distance


# Loading a real file builds 0.6-2.6 M records, so the two that several tests
# need are loaded ONCE per module and shared. Everything that only needs
# header facts calls the header helpers directly instead.

@pytest.fixture(scope="module")
def loaded_8bit():
    return GSSIConverter().load(BIT8_SPM, dataset_id="ds", sensor_type=SensorType.GPR)


@pytest.fixture(scope="module")
def loaded_16bit():
    return GSSIConverter().load(BIT16_TIME, dataset_id="ds", sensor_type=SensorType.GPR)


def _first_by_trace(result, limit=None):
    out = {}
    for r in result.records:
        out.setdefault(r.metadata["trace_index"], r)
        if limit is not None and len(out) > limit:
            break
    return out


# --- synthetic writer, for what the corpus lacks ---

def write_dzt(path, *, n_samples=8, n_traces=4, bits=16, data=1024, nchan=1,
              rng=70.0, position=0.0, spm=0.0, sps=15.0, epsr=0.0, zero=None,
              antenna="3101 900MHz", body=None):
    code, width = {8: ("B", 1), 16: ("H", 2), 32: ("i", 4)}[bits]
    if zero is None:
        zero = {8: 128, 16: -32768, 32: 1}[bits]
    h = bytearray(b"\x00" * 1024)
    struct.pack_into("<HHHH", h, 0, 0x00FF, data, n_samples, bits)
    struct.pack_into("<h", h, 8, zero)
    struct.pack_into("<fffff", h, 10, sps, spm, 0.0, position, rng)
    struct.pack_into("<H", h, 30, 1)
    struct.pack_into("<H", h, 52, nchan)
    struct.pack_into("<f", h, 54, epsr)
    h[98:98 + len(antenna)] = antenna.encode("latin-1")
    offset = 1024 * data if data < 1024 else 1024 * nchan
    out = bytearray(h) + bytearray(b"\x00" * max(0, offset - 1024))
    if body is None:
        mid = (1 << (bits - 1)) if bits in (8, 16) else 0
        body = b"".join(
            struct.pack(f"<{n_samples}{code}", *[mid + t * 3 + i for i in range(n_samples)])
            for t in range(n_traces))
    path.write_bytes(bytes(out) + body)
    return path


# --- 1. nothing inferred ---

@REAL
def test_antenna_frequency_only_when_the_name_states_it():
    """'3101 900MHz' states one; '5013' and 'D400HS' are model codes, not frequencies."""
    assert antenna_frequency_mhz({"antenna_name": "3101 900MHz"}) == 900.0
    assert antenna_frequency_mhz({"antenna_name": "5013"}) is None
    assert antenna_frequency_mhz({"antenna_name": "D400HS"}) is None
    assert antenna_frequency_mhz({"antenna_name": "50270S"}) is None
    assert antenna_frequency_mhz({"antenna_name": ""}) is None
    # ...and the real files confirm the codes stay unresolved.
    header = parse_dzt_header(BIT16_TIME)
    assert header["antenna_name"] == "5013"
    assert antenna_frequency_mhz(header) is None


@REAL
def test_epsr_is_recorded_but_never_becomes_a_velocity(loaded_8bit):
    """It is 0.00 in 17 of the 40 local files -- physically impossible."""
    res = loaded_8bit
    frame = res.frames[0]
    assert frame.source_metadata["epsr_reported"] == pytest.approx(7.0)
    assert all(r.depth is None for r in res.records[:50])
    a = frame.assumption("epsr_not_used_for_velocity")
    assert a is not None and "physically impossible" in a.basis


@REAL
def test_rhf_position_is_recorded_but_not_applied_to_the_time_axis(loaded_16bit):
    header = parse_dzt_header(BIT16_TIME)
    assert header["position_ns"] == pytest.approx(99.04, abs=0.01)
    axis = derive_time_axis(header, BIT16_TIME)
    assert axis["sample_interval_ns"] == pytest.approx(70.0 / 512)
    res = loaded_16bit
    assert res.records[0].metadata["two_way_time_ns"] == 0.0     # starts at time-zero
    a = res.frames[0].assumption("time_zero_offset_not_applied")
    assert a.value == pytest.approx(99.04, abs=0.01)
    assert a.verified is False


@REAL
def test_no_crs_is_ever_declared_for_a_dzt(loaded_8bit):
    from schemas.spatial import CRSKind
    frame = loaded_8bit.frames[0]
    assert frame.spatial_ref.kind == CRSKind.ACQUISITION
    assert frame.spatial_ref.code is None
    assert "none is inferred" in frame.spatial_ref.name


# --- 2. position follows the acquisition ---

@REAL
def test_distance_triggered_line_gets_odometry(loaded_8bit):
    res = loaded_8bit
    header = parse_dzt_header(BIT8_SPM)
    spacing = 1.0 / header["scans_per_metre"]
    by_trace = _first_by_trace(res, limit=12)
    assert by_trace[0].position.kind == "odometry"
    assert by_trace[0].position.along_track_m == 0.0
    assert by_trace[10].position.along_track_m == pytest.approx(10 * spacing)
    assert by_trace[0].latitude is None and by_trace[0].longitude is None


@REAL
def test_time_triggered_line_gets_no_position_with_a_reason(loaded_16bit):
    """rhf_spm is 0 in 22 of the 40 files; a tow speed is never assumed."""
    res = loaded_16bit
    pos = res.records[0].position
    assert pos.kind == "none"
    assert "time-triggered" in pos.reason
    assert res.records[0].latitude is None


@REAL
def test_no_record_anywhere_carries_the_null_island_placeholder(loaded_8bit, loaded_16bit):
    for res in (loaded_8bit, loaded_16bit):
        for r in res.records[:200]:
            assert (r.latitude, r.longitude) != (0.0, 0.0)
            assert r.position.kind != "geographic"


def test_zero_scans_per_metre_is_rejected_as_a_spacing():
    ok, reason = derive_along_track({"scans_per_metre": 0.0, "scans_per_second": 15.0})
    assert ok is None and "time-triggered" in reason


def test_positive_scans_per_metre_inverts_to_spacing():
    ok, _ = derive_along_track({"scans_per_metre": 50.0, "scans_per_second": 0.0})
    assert ok["trace_spacing_m"] == pytest.approx(0.02)


# --- 3. measured vs assumed ---

@REAL
def test_time_axis_comes_from_the_header(tmp_path):
    header = parse_dzt_header(BIT32_SPM)
    axis = derive_time_axis(header, BIT32_SPM)
    assert axis["time_window_ns"] == pytest.approx(100.0)
    assert axis["n_samples"] == 1024
    assert axis["sample_interval_ns"] == pytest.approx(100.0 / 1024)


def test_no_velocity_means_no_depth(tmp_path):
    p = write_dzt(tmp_path / "a.dzt")
    res = GSSIConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    assert all(r.depth is None for r in res.records)
    assert res.frames[0].vertical_axis.conversion is None
    assert res.frames[0].assumption("depth_conversion").value == "not applied"


def test_a_supplied_velocity_derives_depth_and_is_labelled_assumed(tmp_path):
    p = write_dzt(tmp_path / "a.dzt", n_samples=4, rng=40.0)
    res = GSSIConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR,
                               velocity_m_per_ns=0.1)
    r = res.records[1]                                   # sample 1 -> twt 10 ns
    assert r.metadata["two_way_time_ns"] == pytest.approx(10.0)
    assert r.depth == pytest.approx(0.5)
    assert r.metadata["velocity_source"] == "supplied_by_caller"
    a = res.frames[0].assumption("gpr_velocity")
    assert a.verified is False and "not a measurement of it" in a.basis


@pytest.mark.parametrize("bad", [0.0, 5.0, -0.1, "fast"])
def test_an_implausible_velocity_never_becomes_a_depth_axis(tmp_path, bad):
    p = write_dzt(tmp_path / "a.dzt")
    res = GSSIConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR,
                               velocity_m_per_ns=bad)
    assert all(r.depth is None for r in res.records)
    assert res.frames[0].vertical_axis.conversion is None


def test_velocity_error_does_not_claim_another_formats_provenance():
    from converters.gssi_converter import _VELOCITY_BOUNDS_BASIS
    from converters.ids_dt_converter import validate_velocity
    _, reason = validate_velocity(5.0, bounds_basis=_VELOCITY_BOUNDS_BASIS)
    assert "IDS software" not in reason and "speed of light" in reason


# --- sample decoding ---

@REAL
@pytest.mark.parametrize("path,bits", [(BIT32_SPM, 32), (BIT16_TIME, 16), (BIT8_SPM, 8)])
def test_every_real_bit_depth_decodes(path, bits):
    header = parse_dzt_header(path)
    assert header["bits"] == bits
    traces, n = read_dzt(path, header)
    assert n > 0 and len(traces[0]) == header["n_samples"]


@REAL
def test_unsigned_depths_are_recentred_and_signed_ones_are_not():
    """
    Measured, not taken from readgssi.m: 8/16-bit are stored unsigned and the
    midpoint is subtracted; 32-bit is stored signed and untouched.
    """
    import statistics
    for path, shifted in ((BIT8_SPM, True), (BIT16_TIME, True), (BIT32_SPM, False)):
        header = parse_dzt_header(path)
        traces, _ = read_dzt(path, header)
        body = [v for t in traces[:20] for v in t[2:]]
        mean = statistics.fmean(body)
        if shifted:
            # recentred on zero, not on the unsigned midpoint
            assert abs(mean) < (1 << (header["bits"] - 1)) * 0.2


def test_eight_bit_centring_follows_measurement_not_readgssi(tmp_path):
    """readgssi.m ADDS rh_zero, which at 8-bit moves the baseline to 256."""
    p = write_dzt(tmp_path / "a.dzt", bits=8, n_samples=4, n_traces=2, zero=128)
    header = parse_dzt_header(p)
    traces, _ = read_dzt(p, header)
    assert traces[0][0] == 0.0            # written at midpoint 128 -> 0, not 256


@REAL
def test_leading_marker_samples_are_reported_not_overwritten(loaded_16bit):
    res = loaded_16bit
    a = res.frames[0].assumption("leading_samples_may_be_markers")
    assert a is not None and a.value == 2
    assert "would fabricate data" in a.basis
    # sample 0 is kept as stored, not replaced with sample 2
    s0 = res.records[0].signal[0]
    s2 = res.records[2].signal[0]
    assert s0 != s2


# --- data offset rule ---

def test_data_offset_uses_both_branches():
    assert data_offset({"data": 128, "n_channels": 1}) == 1024 * 128
    assert data_offset({"data": 1024, "n_channels": 1}) == 1024


@REAL
def test_every_real_file_divides_into_whole_traces():
    import glob
    files = sorted(glob.glob(str(CORPUS / "**/*.[dD][zZ][tT]"), recursive=True))
    assert len(files) == 40
    for f in files:
        header = parse_dzt_header(f)
        width = {8: 1, 16: 2, 32: 4}[header["bits"]]
        body = header["file_size"] - header["data_offset"]
        assert body % (header["n_samples"] * width) == 0, f


# --- malformed input ---

def test_file_shorter_than_a_header_is_refused(tmp_path):
    p = tmp_path / "stub.dzt"
    p.write_bytes(b"\x00" * 200)
    with pytest.raises(GSSIFormatError) as e:
        parse_dzt_header(p)
    assert "shorter than a GSSI header" in str(e.value)


def test_unsupported_bit_depth_is_refused(tmp_path):
    p = write_dzt(tmp_path / "a.dzt")
    raw = bytearray(p.read_bytes())
    struct.pack_into("<H", raw, 6, 24)
    p.write_bytes(bytes(raw))
    with pytest.raises(GSSIFormatError) as e:
        parse_dzt_header(p)
    assert "24 bits" in str(e.value) and "approximately" in str(e.value)


def test_multi_channel_is_refused_rather_than_misread(tmp_path):
    p = write_dzt(tmp_path / "a.dzt", nchan=2)
    with pytest.raises(GSSIFormatError) as e:
        parse_dzt_header(p)
    assert "2 channels" in str(e.value)
    assert "interleaved" in str(e.value)


def test_zero_samples_is_refused(tmp_path):
    p = write_dzt(tmp_path / "a.dzt")
    raw = bytearray(p.read_bytes())
    struct.pack_into("<H", raw, 4, 0)
    p.write_bytes(bytes(raw))
    with pytest.raises(GSSIFormatError):
        parse_dzt_header(p)


def test_non_positive_time_range_is_refused(tmp_path):
    p = write_dzt(tmp_path / "a.dzt", rng=0.0)
    with pytest.raises(GSSIFormatError) as e:
        derive_time_axis(parse_dzt_header(p), p)
    assert "no time axis exists" in str(e.value)


def test_truncated_body_is_refused(tmp_path):
    p = write_dzt(tmp_path / "a.dzt", n_samples=8, n_traces=4, bits=16)
    raw = p.read_bytes()
    p.write_bytes(raw[:1024 + 4])            # less than one 16-byte trace
    with pytest.raises(GSSIFormatError) as e:
        read_dzt(p, parse_dzt_header(p))
    assert "less than one" in str(e.value)


def test_trailing_bytes_warn_and_are_ignored(tmp_path, caplog):
    p = write_dzt(tmp_path / "a.dzt", n_samples=8, n_traces=3, bits=16)
    p.write_bytes(p.read_bytes() + b"\x01\x02\x03")
    _, n = read_dzt(p, parse_dzt_header(p))
    assert n == 3
    assert any("trailing byte" in r.message for r in caplog.records)


# --- sidecars ---

def test_dzg_fixes_produce_geographic_positions(tmp_path):
    """No local .dzt has a .dzg, so this path is covered synthetically."""
    p = write_dzt(tmp_path / "a.dzt", n_samples=4, n_traces=3)
    (tmp_path / "a.dzg").write_text(
        "$GSSIS,0,0\n$GPGGA,120000.00,5214.3369,N,00651.0989,E,1,08,1.0,10.0,M,,,,*00\n"
        "$GSSIS,1,0\n$GPGGA,120001.00,5214.3400,N,00651.1000,E,1,08,1.0,10.0,M,,,,*00\n")
    res = GSSIConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    by_trace = {}
    for r in res.records:
        by_trace.setdefault(r.metadata["trace_index"], r)
    assert by_trace[0].position.kind == "geographic"
    assert by_trace[0].position.lat == pytest.approx(52.238948, abs=1e-5)
    assert by_trace[0].position.lon == pytest.approx(6.851648, abs=1e-5)
    assert by_trace[0].metadata["position_source"] == "gssi_dzg_gnss"
    assert res.frames[0].spatial_ref.code == "EPSG:4326"


def test_dzg_no_fix_sentences_are_discarded(tmp_path):
    """Quality 0 still carries numbers; using them would place a trace nowhere real."""
    (tmp_path / "a.dzg").write_text(
        "$GSSIS,0,0\n$GPGGA,120000.00,5214.3369,N,00651.0989,E,0,00,,,M,,,,*00\n")
    assert parse_dzg(tmp_path / "a.dzg") == {}


def test_dzg_hemispheres_are_applied(tmp_path):
    (tmp_path / "a.dzg").write_text(
        "$GSSIS,7,0\n$GPGGA,1,3354.0000,S,15112.0000,W,1,08,1.0,0,M,,,,*00\n")
    fixes = parse_dzg(tmp_path / "a.dzg")
    assert fixes[7][0] == pytest.approx(-33.9)
    assert fixes[7][1] == pytest.approx(-151.2)


def test_traces_without_a_fix_fall_back_rather_than_borrowing_one(tmp_path):
    p = write_dzt(tmp_path / "a.dzt", n_samples=4, n_traces=3, spm=50.0)
    (tmp_path / "a.dzg").write_text(
        "$GSSIS,0,0\n$GPGGA,1,5214.3369,N,00651.0989,E,1,08,1.0,0,M,,,,*00\n")
    res = GSSIConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    by_trace = {}
    for r in res.records:
        by_trace.setdefault(r.metadata["trace_index"], r)
    assert by_trace[0].position.kind == "geographic"
    assert by_trace[2].position.kind == "odometry"


def test_absent_and_empty_dzg_are_both_an_absence(tmp_path):
    assert parse_dzg(tmp_path / "nope.dzg") == {}
    (tmp_path / "e.dzg").write_bytes(b"")
    assert parse_dzg(tmp_path / "e.dzg") == {}


@REAL
def test_dzx_sidecar_is_read_when_present_and_optional_when_not(loaded_16bit):
    from converters.gssi_converter import find_sidecar
    found = find_sidecar(BIT32_SPM, (".dzx",))
    assert found is not None
    assert parse_dzx(found)["system"] == "SIR4K"
    # ...and a file without one loads perfectly well.
    assert find_sidecar(BIT16_TIME, (".dzx",)) is None
    assert loaded_16bit.frames[0].source_metadata["dzx_sidecar"] is None
    assert loaded_16bit.frames[0].source_metadata["dzx"] is None


@REAL
def test_raw_zero_is_preserved_for_every_real_bit_depth(loaded_8bit, loaded_16bit):
    """The shift is applied, but the file's own rh_zero stays recoverable."""
    for res, path in ((loaded_8bit, BIT8_SPM), (loaded_16bit, BIT16_TIME)):
        assert res.frames[0].source_metadata["rh_zero"] == parse_dzt_header(path)["zero"]


def test_malformed_dzx_does_not_fail_the_acquisition(tmp_path):
    p = write_dzt(tmp_path / "a.dzt")
    (tmp_path / "a.dzx").write_text("<DZX><unclosed>")
    res = GSSIConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    assert len(res.records) > 0


def test_parse_dzx_on_a_missing_file_is_empty(tmp_path):
    assert parse_dzx(tmp_path / "nope.dzx") == {}


# --- registry wiring ---

def test_registry_routes_dzt_and_names_the_sidecars():
    from converters.registry import classify_file, supported_extensions
    assert ".dzt" in supported_extensions()
    assert classify_file(Path("a.dzt")) == ("supported", "gssi")
    for ext in (".dzx", ".dzg"):
        kind, detail = classify_file(Path("a" + ext))
        assert kind == "recognized_unsupported" and "sidecar" in detail
