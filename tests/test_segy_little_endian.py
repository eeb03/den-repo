"""
Little-endian SEG-Y support.

The contract these tests pin, in order of importance:

1. **Big-endian behaviour cannot change.** Little-endian is a rescue path,
   reached only when the big-endian reading is invalid. Any file segyio
   could already open still goes to segyio, so no existing dataset can be
   rerouted no matter what the detector concludes. The first two tests
   assert that asymmetry directly, because everything else depends on it.
2. Malformed input fails with a message that says what was actually found,
   rather than being decoded approximately.
3. Semantics the bytes cannot settle -- what a coordinate field *means* --
   stay caller declarations, never inference.
"""
import struct

import pytest

from converters.segy_endian import (
    BIG, HEADER_BYTES, LITTLE, LittleEndianSegyFile, SegyEndianError,
    SegyFormatError, detect_endianness, int32_as_float32, nmea_to_degrees,
)

# --- a minimal synthetic SEG-Y writer, so edge cases are exact ---

_WIDTH = {2: 4, 3: 2, 5: 4, 8: 1}
_CODE = {2: "i", 3: "h", 5: "f", 8: "b"}


def write_segy(path, order=LITTLE, *, n_traces=4, n_samples=8, fmt=3,
               interval=98, delay=0, delay_scalar=1, coord_scalar=-1000,
               source_x=0, source_y=0, trailing=b"", body_override=None):
    """Builds a SEG-Y file byte by byte in the requested order."""
    s = ">" if order == BIG else "<"
    out = bytearray(b"\x00" * 3200)                       # textual header
    bh = bytearray(b"\x00" * 400)
    bh[16:18] = struct.pack(s + "h", interval)
    bh[20:22] = struct.pack(s + "h", n_samples)
    bh[24:26] = struct.pack(s + "h", fmt)
    out += bh
    if body_override is not None:
        out += body_override
        path.write_bytes(bytes(out))
        return path
    for t in range(n_traces):
        th = bytearray(b"\x00" * 240)
        th[68:70] = struct.pack(s + "h", delay_scalar)
        th[70:72] = struct.pack(s + "h", coord_scalar)
        th[72:76] = struct.pack(s + "i", source_x)
        th[76:80] = struct.pack(s + "i", source_y)
        th[80:84] = struct.pack(s + "i", t * 20)          # GroupX, mm
        th[108:110] = struct.pack(s + "h", delay)
        th[114:116] = struct.pack(s + "h", n_samples)
        out += th
        out += struct.pack(f"{s}{n_samples}{_CODE[fmt]}",
                           *[(t * 10 + i) for i in range(n_samples)])
    out += trailing
    path.write_bytes(bytes(out))
    return path


# --- 1. the safety asymmetry: big-endian always wins ---

def test_big_endian_file_is_detected_as_big(tmp_path):
    p = write_segy(tmp_path / "be.sgy", order=BIG)
    order, evidence = detect_endianness(p)
    assert order == BIG
    assert evidence["big"]["valid"] is True


def test_little_endian_is_only_reached_when_big_endian_is_invalid(tmp_path):
    """
    The whole regression-safety argument in one assertion: the detector
    returns little ONLY when the big-endian reading failed its checks.
    """
    p = write_segy(tmp_path / "le.sgy", order=LITTLE)
    order, evidence = detect_endianness(p)
    assert order == LITTLE
    assert evidence["big"]["valid"] is False      # never chosen over a valid big
    assert evidence["little"]["valid"] is True


def test_a_valid_big_endian_reading_is_never_overridden(tmp_path):
    """Even when the little-endian reading also happens to look plausible."""
    p = write_segy(tmp_path / "be2.sgy", order=BIG, fmt=2, n_samples=4)
    order, evidence = detect_endianness(p)
    assert order == BIG
    if evidence["little"]["valid"]:               # if both were plausible...
        assert order == BIG                        # ...big still wins


# --- 2. malformed input fails clearly ---

def test_file_shorter_than_a_header_is_refused(tmp_path):
    p = tmp_path / "stub.sgy"
    p.write_bytes(b"\x00" * 100)
    with pytest.raises(SegyEndianError) as e:
        detect_endianness(p)
    assert "shorter than a SEG-Y header" in str(e.value)
    assert "100" in str(e.value)


def test_empty_file_is_refused(tmp_path):
    p = tmp_path / "empty.sgy"
    p.write_bytes(b"")
    with pytest.raises(SegyEndianError):
        detect_endianness(p)


def test_header_valid_in_neither_order_is_refused_with_both_readings(tmp_path):
    p = tmp_path / "junk.sgy"
    body = bytearray(b"\x00" * HEADER_BYTES)
    body[3200 + 24:3200 + 26] = b"\x7f\x7f"       # 32639 either way: undefined
    body[3200 + 20:3200 + 22] = b"\x7f\x7f"
    p.write_bytes(bytes(body) + b"\x00" * 1000)
    with pytest.raises(SegyEndianError) as e:
        detect_endianness(p)
    msg = str(e.value)
    assert "not readable in either byte order" in msg
    assert "malformed, truncated, or not SEG-Y" in msg


def test_trace_length_that_does_not_divide_the_body_is_rejected(tmp_path):
    """The second, independent check: a plausible format code is not enough."""
    p = write_segy(tmp_path / "ragged.sgy", order=LITTLE, n_samples=8, fmt=3,
                   body_override=b"\x01" * 999)
    with pytest.raises(SegyEndianError):
        detect_endianness(p)


def test_ibm_float_is_refused_by_name_not_decoded_approximately(tmp_path):
    p = write_segy(tmp_path / "ibm.sgy", order=LITTLE, fmt=3)
    raw = bytearray(p.read_bytes())
    raw[3200 + 24:3200 + 26] = struct.pack("<h", 1)      # IBM 4-byte float
    p.write_bytes(bytes(raw))
    with pytest.raises(SegyFormatError) as e:
        LittleEndianSegyFile(p)
    assert "IBM 4-byte floating point" in str(e.value)


def test_truncated_body_is_refused(tmp_path):
    p = write_segy(tmp_path / "trunc.sgy", order=LITTLE, n_samples=8, fmt=3)
    raw = p.read_bytes()
    p.write_bytes(raw[:HEADER_BYTES + 100])              # less than one trace
    with pytest.raises(SegyEndianError) as e:
        LittleEndianSegyFile(p)
    assert "truncated" in str(e.value)


def test_trailing_bytes_are_ignored_with_a_warning(tmp_path, caplog):
    p = write_segy(tmp_path / "tail.sgy", order=LITTLE, n_traces=3,
                   n_samples=8, fmt=3, trailing=b"\x00" * 7)
    with LittleEndianSegyFile(p) as f:
        assert f.tracecount == 3
    assert any("trailing byte" in r.message for r in caplog.records)


def test_reading_a_trace_out_of_range_raises(tmp_path):
    p = write_segy(tmp_path / "small.sgy", order=LITTLE, n_traces=2)
    with LittleEndianSegyFile(p) as f:
        with pytest.raises(IndexError):
            f.trace[5]


# --- 3. the reader presents a segyio-shaped surface ---

@pytest.mark.parametrize("fmt", [2, 3, 5, 8])
def test_every_supported_sample_format_round_trips(tmp_path, fmt):
    p = write_segy(tmp_path / f"f{fmt}.sgy", order=LITTLE, n_traces=3,
                   n_samples=6, fmt=fmt)
    with LittleEndianSegyFile(p) as f:
        assert f.tracecount == 3
        assert len(f.samples) == 6
        assert list(f.trace[1]) == [pytest.approx(10 + i) for i in range(6)]


def test_header_is_keyed_by_the_same_offsets_segyio_uses(tmp_path):
    """This is what lets the converter share one record-building loop."""
    import segyio
    p = write_segy(tmp_path / "h.sgy", order=LITTLE, source_x=12345,
                   source_y=67890, coord_scalar=-1000)
    with LittleEndianSegyFile(p) as f:
        h = f.header[0]
        assert h.get(segyio.TraceField.SourceX) == 12345
        assert h.get(segyio.TraceField.SourceY) == 67890
        assert h.get(segyio.TraceField.SourceGroupScalar) == -1000
        assert f.bin.get(segyio.BinField.Interval) == 98


def test_sample_axis_matches_segyios_construction(tmp_path):
    p = write_segy(tmp_path / "ax.sgy", order=LITTLE, n_samples=5, interval=200)
    with LittleEndianSegyFile(p) as f:
        assert f.samples == [pytest.approx(i * 0.2) for i in range(5)]


def test_delay_is_scaled_like_the_sample_interval(tmp_path):
    """
    One instrument writes one unit into both time fields. Scaling only the
    interval put the 4TU corpus's start time a thousandfold too high, which
    propagated into depths of hundreds of metres.
    """
    p = write_segy(tmp_path / "d.sgy", order=LITTLE, n_samples=4,
                   interval=100, delay=2641)
    with LittleEndianSegyFile(p) as f:
        assert f.t0 == pytest.approx(2.641)
        assert f.samples[0] == pytest.approx(2.641)
        assert f.samples[-1] == pytest.approx(2.641 + 3 * 0.1)


def test_start_time_beyond_the_window_warns_but_is_reported_as_read(tmp_path, caplog):
    p = write_segy(tmp_path / "far.sgy", order=LITTLE, n_samples=4,
                   interval=100, delay=30_000)          # int16 max is 32767
    with LittleEndianSegyFile(p) as f:
        assert f.samples[0] == pytest.approx(30.0)      # not silently corrected
    assert any("exceeds the" in r.message for r in caplog.records)


# --- coordinate helpers ---

def test_nmea_conversion():
    assert nmea_to_degrees(5214.3369) == pytest.approx(52.238948, abs=1e-6)
    assert nmea_to_degrees(651.0989) == pytest.approx(6.851648, abs=1e-6)
    assert nmea_to_degrees(0.0) == 0.0


def test_nmea_conversion_preserves_sign():
    """A western longitude or southern latitude must survive."""
    assert nmea_to_degrees(-5214.3369) == pytest.approx(-52.238948, abs=1e-6)


def test_int32_as_float32_is_a_pure_reinterpretation():
    assert int32_as_float32(1143129685, LITTLE) == pytest.approx(651.0989, abs=1e-3)


def test_int32_as_float32_is_order_independent_by_construction():
    """
    The integer arriving here was ALREADY decoded in the file's byte order,
    so packing and unpacking in that same order cancels out: the reinterpretation
    depends only on the value's bits. Pinned because it is easy to assume the
    order argument still matters here and to "fix" it wrongly.
    """
    for v in (1143129685, 1168306866, 0):
        assert int32_as_float32(v, BIG) == int32_as_float32(v, LITTLE)


def test_bit_patterns_that_are_not_valid_floats_become_no_position(tmp_path):
    """
    0xFFFFFFFF reinterprets to NaN. A NaN is not a coordinate, so it must be
    declared absent rather than propagated into the spatial model.
    """
    import math
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    assert math.isnan(int32_as_float32(-1, LITTLE))
    p = write_segy(tmp_path / "nan.sgy", order=LITTLE, n_traces=2, n_samples=4,
                   fmt=3, source_x=-1, source_y=-1)
    recs = SEGYConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR,
                                coordinate_encoding="ieee_nmea").records
    assert recs[0].position.kind == "none"
    assert recs[0].latitude is None


# --- converter integration ---

def _le_gpr(tmp_path, **kw):
    return write_segy(tmp_path / "gpr.sgy", order=LITTLE, n_traces=3,
                      n_samples=4, fmt=3, **kw)


def test_converter_reads_a_little_endian_file(tmp_path):
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    p = _le_gpr(tmp_path)
    res = SEGYConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    assert len(res.records) == 3 * 4
    assert res.frames[0].source_metadata["segy_byte_order"] == "little"


def test_little_endian_frame_records_the_detection_evidence(tmp_path):
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    p = _le_gpr(tmp_path)
    frame = SEGYConverter().load(p, dataset_id="ds",
                                 sensor_type=SensorType.GPR).frames[0]
    a = frame.assumption("segy_byte_order")
    assert a is not None and a.value == "little"
    assert a.verified is True                    # detected, not assumed
    assert "self-inconsistent" in a.basis


def test_coordinate_encoding_must_be_declared_not_guessed(tmp_path):
    """An unrecognised value is refused rather than quietly defaulted."""
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    p = _le_gpr(tmp_path)
    with pytest.raises(ValueError) as e:
        SEGYConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR,
                             coordinate_encoding="probably_floats")
    assert "Nothing is inferred here" in str(e.value)


def test_default_encoding_treats_coordinates_as_the_standard_says(tmp_path):
    """
    The same bytes read the standard way stay projected. Nothing infers that
    a large integer 'must really be' a float.
    """
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    p = _le_gpr(tmp_path, source_x=1143129685, source_y=1168306866)
    recs = SEGYConverter().load(p, dataset_id="ds",
                                sensor_type=SensorType.GPR).records
    assert recs[0].position.kind == "projected"
    assert recs[0].latitude is None


def test_ieee_nmea_encoding_yields_a_geographic_position(tmp_path):
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    p = _le_gpr(tmp_path, source_x=1143129685, source_y=1168306866)
    res = SEGYConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR,
                               coordinate_encoding="ieee_nmea")
    pos = res.records[0].position
    assert pos.kind == "geographic"
    assert pos.lat == pytest.approx(52.2389, abs=1e-3)
    assert pos.lon == pytest.approx(6.8516, abs=1e-3)
    a = res.frames[0].assumption("segy_coordinate_encoding")
    assert a is not None and a.verified is False   # a declaration, not a finding


def test_ieee_nmea_ignores_the_coordinate_scalar(tmp_path):
    """Applying it as well would divide the position by 1000."""
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    a = _le_gpr(tmp_path, source_x=1143129685, source_y=1168306866,
                coord_scalar=-1000)
    ra = SEGYConverter().load(a, dataset_id="ds", sensor_type=SensorType.GPR,
                              coordinate_encoding="ieee_nmea").records[0]
    b = write_segy(tmp_path / "b.sgy", order=LITTLE, n_traces=3, n_samples=4,
                   fmt=3, source_x=1143129685, source_y=1168306866, coord_scalar=1)
    rb = SEGYConverter().load(b, dataset_id="ds", sensor_type=SensorType.GPR,
                              coordinate_encoding="ieee_nmea").records[0]
    assert ra.position.lat == rb.position.lat


# --- big-endian frames must not gain any of the new material ---

def test_big_endian_frames_are_untouched_by_the_new_reader(tmp_path):
    """
    A big-endian frame must not acquire the little-endian assumptions. The
    INGV regression digests cover records; this covers the frame.
    """
    from converters.segy_converter import SEGYConverter
    from schemas.subterra_record import SensorType
    p = write_segy(tmp_path / "be.sgy", order=BIG, n_traces=2, n_samples=4, fmt=3)
    frame = SEGYConverter().load(p, dataset_id="ds",
                                 sensor_type=SensorType.GPR).frames[0]
    assert frame.assumption("segy_byte_order") is None
    assert frame.assumption("segy_coordinate_encoding") is None
    assert frame.assumption("time_axis_origin_offset") is None
    assert frame.source_metadata["segy_byte_order"] == "big"
