"""
The SEG-Y time axis: DelayRecordingTime, its scalar, and the sample interval.

WHAT THE STANDARD SAYS. SEG-Y rev 1 puts the recording delay in trace-header
bytes 109-110 and the scalar "to be applied to times" in bytes 215-216 (0 means
1; positive multiplies; negative divides by its magnitude; +-1, 10, 100, 1000,
10000 are the permitted values). segyio builds its sample axis exactly that
way. Subterra's GPR files use the same fields with the time units shifted
(interval in picoseconds, delay in nanoseconds), which is why the interval is
divided by 1000 and the axis is labelled ns.

TWO DIALECTS THE BYTES CANNOT TELL APART.
- 4TU (little-endian): delay 2641 with time scalar -1000 -> 2.641 ns. Standard.
- Falerii Novi (big-endian, a MATGPR export): delay 10342 with time scalar 0,
  documented by ADS as a ~10 ns delay with 2e-10 s sampling. The delay is
  written in the SAME unit as the sample interval (picoseconds), so the
  standard reading gives 10342 ns -- a thousandfold too large.
With a scalar of 0 a delay of 20 is 20 ns under one and 0.02 ns under the
other; both are plausible. So the Falerii reading is a CALLER DECLARATION
(`delay_encoding="sample_interval_unit"`), never inferred, like
`coordinate_encoding`.

THE BUG THIS ALSO FIXES. The little-endian reader took its "delay scalar" from
byte 69 -- the ELEVATION scalar -- and then divided by a hard-coded 1000. On
4TU that matched the standard by coincidence (elevation scalar 1, time scalar
-1000); on any file where the two scalars differ it was wrong.
"""
import struct

import pytest

from converters.segy_converter import SEGYConverter
from converters.segy_time import (
    DELAY_ENCODINGS, start_time_from_header, validate_delay_encoding,
)
from schemas.subterra_record import SensorType

BIG, LITTLE = ">", "<"


def write_segy(path, order=BIG, *, n_traces=3, n_samples=400, interval=200, delay=0,
               time_scalar=0, elevation_scalar=1, fmt=5, delays=None):
    """A minimal SEG-Y with the timing fields set explicitly.

    `delays`, when given, sets DelayRecordingTime per trace instead of `delay`.
    """
    code = {3: "h", 5: "f"}[fmt]
    out = bytearray(b"\x40" * 3200)
    bh = bytearray(400)
    bh[16:18] = struct.pack(order + "h", interval)
    bh[20:22] = struct.pack(order + "h", n_samples)
    bh[24:26] = struct.pack(order + "h", fmt)
    out += bh
    for t in range(n_traces):
        th = bytearray(240)
        th[0:4] = struct.pack(order + "i", t + 1)
        th[68:70] = struct.pack(order + "h", elevation_scalar)
        th[70:72] = struct.pack(order + "h", -100)
        th[72:76] = struct.pack(order + "i", 28194532 + t)
        th[76:80] = struct.pack(order + "i", 468650626)
        th[108:110] = struct.pack(order + "h", delays[t] if delays else delay)
        th[114:116] = struct.pack(order + "h", n_samples)
        th[116:118] = struct.pack(order + "h", interval)
        th[214:216] = struct.pack(order + "h", time_scalar)
        out += th
        out += struct.pack(f"{order}{n_samples}{code}",
                           *[(t * 10 + i) for i in range(n_samples)])
    path.write_bytes(bytes(out))
    return path


def _load(path, sensor_type=SensorType.GPR, **kw):
    return SEGYConverter().load(path, dataset_id="t", sensor_type=sensor_type, **kw)


def _axis(result):
    """The time axis of trace 0, in sample order."""
    recs = [r for r in result.records if r.metadata["trace_index"] == 0]
    key = "two_way_time_ns" if "two_way_time_ns" in recs[0].metadata else "two_way_time_ms"
    return [r.metadata[key] for r in recs], recs


def _assumptions(result):
    return {a.key: a for a in result.frames[0].assumptions}


# ---------------------------------------------------------------------------
# the declaration
# ---------------------------------------------------------------------------

def test_both_encodings_are_known_and_standard_is_one_of_them():
    assert set(DELAY_ENCODINGS) == {"segy_standard", "sample_interval_unit"}
    validate_delay_encoding("segy_standard")
    validate_delay_encoding("sample_interval_unit")


def test_an_unknown_encoding_is_refused():
    with pytest.raises(ValueError, match="delay_encoding"):
        validate_delay_encoding("picoseconds")


# ---------------------------------------------------------------------------
# Falerii-shaped big-endian file
# ---------------------------------------------------------------------------

def test_falerii_delay_declared_in_the_interval_unit_starts_at_10_342_ns(tmp_path):
    result = _load(write_segy(tmp_path / "fn.segy", delay=10342, time_scalar=0),
                   delay_encoding="sample_interval_unit")
    times, recs = _axis(result)

    assert times[0] == pytest.approx(10.342)
    assert times[1] - times[0] == pytest.approx(0.2)
    assert times[-1] == pytest.approx(10.342 + 399 * 0.2)
    # Through the real path, at the converter's default velocity.
    assert recs[0].depth == pytest.approx(0.5171)


def test_without_the_declaration_the_standard_reading_is_kept_and_flagged(tmp_path):
    """No guessing: the standard reading stays, and the frame says why it is
    suspicious and which declaration would change it."""
    result = _load(write_segy(tmp_path / "fn.segy", delay=10342, time_scalar=0))
    times, _ = _axis(result)

    assert times[0] == pytest.approx(10342.0)
    a = _assumptions(result)
    suspect = a["time_axis_start_suspect"]
    assert suspect.verified is False
    assert "exceeds" in suspect.basis
    assert "sample_interval_unit" in suspect.basis
    # Not offered as an instrument time-zero: see the next test.
    assert "time_axis_origin_offset" not in a


def test_a_start_outside_the_window_is_not_a_measured_time_zero(tmp_path):
    """time_zero Method A reports `time_axis_origin_offset` as MEASURED. A
    10342 ns start against an 80 ns window is not a measurement to offer."""
    from preprocessing.time_zero import metadata_instrument_time_zero
    from schemas.time_zero import TimeZeroStatus
    result = _load(write_segy(tmp_path / "fn.segy", delay=10342, time_scalar=0))
    assert metadata_instrument_time_zero(result.frames[0]).status == TimeZeroStatus.UNAVAILABLE


def test_a_real_negative_delay_is_kept(tmp_path):
    """Falerii's own files carry delays down to -13998."""
    result = _load(write_segy(tmp_path / "neg.segy", delay=-13998),
                   delay_encoding="sample_interval_unit")
    assert _axis(result)[0][0] == pytest.approx(-13.998)


# ---------------------------------------------------------------------------
# zero delay is untouched
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("encoding", ["segy_standard", "sample_interval_unit"])
def test_a_zero_delay_axis_is_exactly_segyios(tmp_path, encoding):
    import segyio
    path = write_segy(tmp_path / "z.segy", delay=0, interval=293, n_samples=7)
    with segyio.open(str(path), ignore_geometry=True) as f:
        expected = [float(s) for s in f.samples]

    times, _ = _axis(_load(path, delay_encoding=encoding))
    assert times == expected        # bit-identical, not approximate
    assert "time_axis_origin_offset" not in _assumptions(_load(path))


# ---------------------------------------------------------------------------
# little-endian: the time scalar, never the elevation scalar
# ---------------------------------------------------------------------------

def test_4tu_shaped_little_endian_file_is_unchanged(tmp_path):
    result = _load(write_segy(tmp_path / "le.sgy", LITTLE, fmt=3, interval=97,
                              delay=2641, time_scalar=-1000, elevation_scalar=1))
    times, _ = _axis(result)
    assert times[0] == 2641 / 1000
    assert times[1] == 2641 / 1000 + 97 / 1000.0


def test_the_elevation_scalar_cannot_change_the_time_axis(tmp_path):
    """Fails under the old reader, which took its time scalar from byte 69:
    an elevation scalar of -100 made it 2641 * 0.01 / 1000 = 0.02641 ns."""
    result = _load(write_segy(tmp_path / "le.sgy", LITTLE, fmt=3, interval=97,
                              delay=2641, time_scalar=-1000, elevation_scalar=-100))
    assert _axis(result)[0][0] == pytest.approx(2.641)


@pytest.mark.parametrize("encoding", ["segy_standard", "sample_interval_unit"])
def test_both_byte_orders_build_the_same_axis(tmp_path, encoding):
    kw = dict(fmt=3, interval=200, delay=10342, time_scalar=0, elevation_scalar=-2)
    be, _ = _axis(_load(write_segy(tmp_path / "be.sgy", BIG, **kw), delay_encoding=encoding))
    le, _ = _axis(_load(write_segy(tmp_path / "le.sgy", LITTLE, **kw), delay_encoding=encoding))
    assert be == le


# ---------------------------------------------------------------------------
# scalar semantics (SEG-Y rev 1, bytes 215-216)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scalar, expected", [(0, 50.0), (1, 50.0), (10, 500.0),
                                              (-10, 5.0), (-1000, 0.05)])
def test_the_time_scalar_follows_the_standard(scalar, expected):
    assert start_time_from_header(50, scalar, "segy_standard") == pytest.approx(expected)


def test_the_scalar_applies_before_the_interval_unit_conversion():
    assert start_time_from_header(50, 10, "sample_interval_unit") == pytest.approx(0.5)


@pytest.mark.parametrize("scalar", [7, -3, 20000, -32768])
def test_a_scalar_the_standard_does_not_permit_is_refused(scalar):
    with pytest.raises(ValueError, match="215"):
        start_time_from_header(50, scalar, "segy_standard")


def test_a_non_standard_scalar_in_a_file_is_refused_not_decoded(tmp_path):
    with pytest.raises(ValueError, match="215"):
        _load(write_segy(tmp_path / "bad.segy", delay=100, time_scalar=7))


# ---------------------------------------------------------------------------
# one axis per file only when the file really has one
# ---------------------------------------------------------------------------

def test_a_gpr_file_whose_delay_varies_by_trace_is_refused(tmp_path):
    """Every held file (4TU, Falerii, INGV: 2,084) has one delay per file.
    A file that does not would get trace 0's axis on every trace."""
    path = write_segy(tmp_path / "var.segy", delays=[100, 100, 250])
    with pytest.raises(ValueError, match="DelayRecordingTime varies"):
        _load(path, delay_encoding="sample_interval_unit")


# ---------------------------------------------------------------------------
# non-GPR SEG-Y keeps the standard, in milliseconds
# ---------------------------------------------------------------------------

def test_seismic_segy_keeps_segyios_standard_axis(tmp_path):
    import segyio
    path = write_segy(tmp_path / "seis.segy", delay=100, time_scalar=0, interval=4000)
    with segyio.open(str(path), ignore_geometry=True) as f:
        expected = [float(s) for s in f.samples]

    times, recs = _axis(_load(path, sensor_type=SensorType.SEISMIC))
    assert times == expected
    assert recs[0].depth is None


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def test_the_frame_explains_where_the_first_sample_starts(tmp_path):
    result = _load(write_segy(tmp_path / "fn.segy", delay=10342, time_scalar=0),
                   delay_encoding="sample_interval_unit")
    a = _assumptions(result)

    offset = a["time_axis_origin_offset"]
    assert offset.value == pytest.approx(10.342)
    assert offset.verified is False
    for fact in ("10342", "bytes 109-110", "215-216", "sample_interval_unit", "200"):
        assert fact in offset.basis

    declared = a["segy_delay_encoding"]
    assert declared.value == "sample_interval_unit"
    assert declared.verified is False

    meta = result.frames[0].source_metadata
    assert meta["segy_delay_recording_time_raw"] == 10342
    assert meta["segy_time_scalar_raw"] == 0
    assert meta["segy_delay_encoding"] == "sample_interval_unit"


def test_the_default_encoding_adds_no_declaration_assumption(tmp_path):
    result = _load(write_segy(tmp_path / "le.sgy", LITTLE, fmt=3, interval=97,
                              delay=2641, time_scalar=-1000))
    assert "segy_delay_encoding" not in _assumptions(result)
    assert _assumptions(result)["time_axis_origin_offset"].value == pytest.approx(2.641)


def test_time_zero_method_a_receives_the_normalised_start(tmp_path):
    from preprocessing.time_zero import metadata_instrument_time_zero
    result = _load(write_segy(tmp_path / "fn.segy", delay=10342, time_scalar=0),
                   delay_encoding="sample_interval_unit")
    assert metadata_instrument_time_zero(result.frames[0]).correction_ns == pytest.approx(10.342)
