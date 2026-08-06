"""
MALÅ (Guideline Geo / RAMAC) `.rd3`/`.rad` ingestion.

The contract these tests pin:

1. **The pair is the unit.** A `.rd3` has no header and a `.rad` has no
   samples, so a missing or mismatched sidecar is refused rather than
   worked around with guessed geometry.
2. **Measured stays measured; assumed stays absent.** The time axis comes
   from the instrument and is exact. Depth exists only when a caller
   supplies a velocity -- there is no default, because a fabricated
   velocity produces physical-looking numbers with no basis.
3. **Odometry is not a position on Earth.** The wheel encoder locates a
   trace along its own line. It never becomes a geographic coordinate, and
   an empty `.cor` is an ABSENCE in the survey, not a parse failure.
"""
import struct

import pytest

from converters.mala_converter import (
    MALAConverter, MALAFormatError, antenna_frequency_mhz, derive_along_track,
    derive_time_axis, find_rad, parse_cor, parse_rad, read_rd3,
)
from schemas.subterra_record import SensorType

RAD = """SAMPLES:{samples}
FREQUENCY:5065.200195
DISTANCE FLAG:{dflag}
TIME FLAG:0
TIME INTERVAL: 0.000000
DISTANCE INTERVAL: {dint}
OPERATOR:_
CUSTOMER:_
SITE:{site}
ANTENNAS:{antennas}
ANTENNA SEPARATION: 0.180000
COMMENT:Meas. wheel 100 MHz=3
TIMEWINDOW:{window}
STACKS:4
LAST TRACE:{traces}
STOP POSITION:  7.414449
START POSITION:{start}
POSITIVE DIRECTION:1
"""


def write_pair(tmp_path, stem="LINE1", *, samples=8, traces=5, window=66.334988,
               dint="0.019011", dflag="1", start="0.000000",
               antennas="500 MHz shielded=1", site="_", ext=".rd3", rad_ext=".rad",
               body=None, rad_text=None):
    """Writes a MALÅ pair byte for byte, so edge cases are exact."""
    rad = tmp_path / f"{stem}{rad_ext}"
    rad.write_text(rad_text if rad_text is not None else RAD.format(
        samples=samples, traces=traces, window=window, dint=dint, dflag=dflag,
        start=start, antennas=antennas, site=site))
    binary = tmp_path / f"{stem}{ext}"
    code, width = {".rd3": ("h", 2), ".rd7": ("i", 4)}[ext.lower()]
    if body is None:
        body = b"".join(
            struct.pack(f"<{samples}{code}", *[t * 10 + i for i in range(samples)])
            for t in range(traces))
    binary.write_bytes(body)
    return binary


# --- 1. the pair is the unit ---

def test_missing_rad_is_refused_with_the_reason(tmp_path):
    p = tmp_path / "orphan.rd3"
    p.write_bytes(b"\x00" * 32)
    with pytest.raises(MALAFormatError) as e:
        find_rad(p)
    assert "no .rad sidecar" in str(e.value)
    assert "sample count, time window and trace spacing" in str(e.value)


def test_uppercase_rad_is_found(tmp_path):
    """The TU1208 archive mixes .rd3/.RD3 casing."""
    p = write_pair(tmp_path, rad_ext=".RAD")
    assert find_rad(p).suffix == ".RAD"


def test_binary_that_disagrees_with_last_trace_is_refused(tmp_path):
    p = write_pair(tmp_path, samples=8, traces=5)
    p.write_bytes(p.read_bytes()[: 8 * 2 * 3])          # 3 traces, .rad says 5
    with pytest.raises(MALAFormatError) as e:
        MALAConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    assert "LAST TRACE=5" in str(e.value)
    assert "Refusing to guess" in str(e.value)


def test_ragged_binary_is_refused_not_truncated(tmp_path):
    p = write_pair(tmp_path, samples=8, traces=5)
    p.write_bytes(p.read_bytes() + b"\x01\x02\x03")
    with pytest.raises(MALAFormatError) as e:
        read_rd3(p, 8)
    assert "not a whole number of traces" in str(e.value)
    assert "3 byte(s) left over" in str(e.value)


def test_empty_binary_is_refused(tmp_path):
    p = write_pair(tmp_path, body=b"")
    with pytest.raises(MALAFormatError) as e:
        read_rd3(p, 8)
    assert "empty" in str(e.value)


def test_rad_without_key_value_lines_is_refused(tmp_path):
    p = write_pair(tmp_path, rad_text="this is not a MALA header\n")
    with pytest.raises(MALAFormatError) as e:
        parse_rad(find_rad(p))
    assert "no KEY:value lines" in str(e.value)


def test_missing_required_field_names_itself(tmp_path):
    p = write_pair(tmp_path, rad_text="SAMPLES:8\nDISTANCE FLAG:1\n")
    with pytest.raises(MALAFormatError) as e:
        derive_time_axis(parse_rad(find_rad(p)), find_rad(p))
    assert "TIMEWINDOW" in str(e.value)


def test_non_numeric_field_names_itself_and_its_value(tmp_path):
    p = write_pair(tmp_path, window="not-a-number")
    with pytest.raises(MALAFormatError) as e:
        derive_time_axis(parse_rad(find_rad(p)), find_rad(p))
    assert "'TIMEWINDOW'" in str(e.value) and "not a number" in str(e.value)


@pytest.mark.parametrize("window", ["0.000000", "-5.0"])
def test_non_positive_time_window_is_refused(tmp_path, window):
    p = write_pair(tmp_path, window=window)
    with pytest.raises(MALAFormatError) as e:
        derive_time_axis(parse_rad(find_rad(p)), find_rad(p))
    assert "no time axis exists" in str(e.value)


# --- 2. measured vs assumed ---

def test_time_axis_is_taken_from_the_instrument(tmp_path):
    """TIMEWINDOW / SAMPLES, with no rescaling and nothing assumed."""
    p = write_pair(tmp_path, samples=336, traces=2, window=66.334988)
    axis = derive_time_axis(parse_rad(find_rad(p)), find_rad(p))
    assert axis["n_samples"] == 336
    assert axis["time_window_ns"] == pytest.approx(66.334988)
    assert axis["sample_interval_ns"] == pytest.approx(66.334988 / 336)


def test_no_velocity_means_no_depth(tmp_path):
    p = write_pair(tmp_path)
    res = MALAConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    assert all(r.depth is None for r in res.records)
    assert all(r.metadata["two_way_time_ns"] is not None for r in res.records)
    frame = res.frames[0]
    assert frame.vertical_axis.conversion is None      # machine-readable "no depth"
    assert frame.assumption("depth_conversion").value == "not applied"


def test_a_supplied_velocity_derives_depth_and_is_labelled_assumed(tmp_path):
    p = write_pair(tmp_path, samples=4, traces=2, window=40.0)
    res = MALAConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR,
                               velocity_m_per_ns=0.1)
    r = res.records[1]                                  # sample 1: twt = 10 ns
    assert r.metadata["two_way_time_ns"] == pytest.approx(10.0)
    assert r.depth == pytest.approx(10.0 * 0.1 / 2)
    assert r.metadata["velocity_source"] == "supplied_by_caller"
    a = res.frames[0].assumption("gpr_velocity")
    assert a.verified is False                          # asserted, not measured
    assert "not a measurement of it" in a.basis


@pytest.mark.parametrize("bad", [0.0, 5.0, -0.1, "fast", float("nan")])
def test_an_implausible_velocity_never_becomes_a_depth_axis(tmp_path, bad):
    p = write_pair(tmp_path)
    res = MALAConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR,
                               velocity_m_per_ns=bad)
    assert all(r.depth is None for r in res.records)
    assert res.frames[0].vertical_axis.conversion is None


def test_velocity_error_does_not_claim_the_ids_provenance(tmp_path):
    """The bounds are shared; the justification must not be borrowed."""
    from converters.ids_dt_converter import validate_velocity
    from converters.mala_converter import _VELOCITY_BOUNDS_BASIS
    _, reason = validate_velocity(5.0, bounds_basis=_VELOCITY_BOUNDS_BASIS)
    assert "IDS software" not in reason
    assert "speed of light" in reason
    _, ids_reason = validate_velocity(5.0)
    assert "IDS software" in ids_reason                 # default unchanged


# --- 3. odometry is not a position on Earth ---

def test_distance_triggered_traces_get_an_odometry_position(tmp_path):
    p = write_pair(tmp_path, traces=4, dint="0.02", start="0.000000")
    recs = MALAConverter().load(p, dataset_id="ds",
                                sensor_type=SensorType.GPR).records
    by_trace = {r.metadata["trace_index"]: r for r in recs}
    assert by_trace[0].position.kind == "odometry"
    assert by_trace[3].position.along_track_m == pytest.approx(0.06)
    assert by_trace[0].latitude is None and by_trace[0].longitude is None


def test_start_position_offsets_the_along_track_axis(tmp_path):
    p = write_pair(tmp_path, traces=3, dint="0.02", start="1.500000")
    recs = MALAConverter().load(p, dataset_id="ds",
                                sensor_type=SensorType.GPR).records
    assert recs[0].position.along_track_m == pytest.approx(1.5)


def test_a_time_triggered_line_gets_no_along_track_coordinate(tmp_path):
    """Inventing distance from an assumed tow speed would fabricate geometry."""
    p = write_pair(tmp_path, dflag="0")
    res = MALAConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    assert res.records[0].position.kind == "none"
    assert "not distance-triggered" in res.records[0].position.reason


def test_zero_distance_interval_is_rejected(tmp_path):
    ok, reason = derive_along_track({"DISTANCE FLAG": "1", "DISTANCE INTERVAL": "0.0"})
    assert ok is None and "unusable" in reason


def test_an_empty_cor_is_an_absence_not_a_failure(tmp_path):
    """All 321 Hillside .cor files are zero bytes: the survey had no GNSS."""
    p = write_pair(tmp_path)
    (tmp_path / "LINE1.cor").write_bytes(b"")
    res = MALAConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    assert parse_cor(tmp_path / "LINE1.cor") == []
    assert res.records[0].position.kind == "odometry"
    a = res.frames[0].assumption("gnss_absent")
    assert a is not None and "ABSENCE in the survey, not a read failure" in a.basis


def test_a_missing_cor_behaves_like_an_empty_one(tmp_path):
    assert parse_cor(tmp_path / "nope.cor") == []


def test_a_populated_cor_yields_geographic_positions(tmp_path):
    p = write_pair(tmp_path, traces=3)
    (tmp_path / "LINE1.cor").write_text(
        "1\t2022-06-01\t10:00:00\t54.0500\tN\t2.8000\tW\t1\t8\n"
        "2\t2022-06-01\t10:00:01\t54.0501\tN\t2.8001\tW\t1\t8\n")
    res = MALAConverter().load(p, dataset_id="ds", sensor_type=SensorType.GPR)
    r = res.records[0]
    assert r.position.kind == "geographic"
    assert r.position.lat == pytest.approx(54.05)
    assert r.position.lon == pytest.approx(-2.80)       # W applied
    assert r.metadata["position_source"] == "mala_cor_gnss"


def test_cor_hemisphere_letters_are_applied(tmp_path):
    (tmp_path / "s.cor").write_text("1\td\tt\t33.9\tS\t151.2\tE\t1\t8\n")
    assert parse_cor(tmp_path / "s.cor") == [(1, -33.9, 151.2)]


def test_traces_without_a_fix_fall_back_to_odometry(tmp_path):
    """A partial GNSS record must not silently georeference the whole line."""
    p = write_pair(tmp_path, traces=3)
    (tmp_path / "LINE1.cor").write_text("1\td\tt\t54.05\tN\t2.80\tW\t1\t8\n")
    recs = MALAConverter().load(p, dataset_id="ds",
                                sensor_type=SensorType.GPR).records
    by_trace = {r.metadata["trace_index"]: r for r in recs}
    assert by_trace[0].position.kind == "geographic"
    assert by_trace[2].position.kind == "odometry"


def test_frame_declares_no_crs_for_an_odometry_line(tmp_path):
    from schemas.spatial import CRSKind
    p = write_pair(tmp_path)
    frame = MALAConverter().load(p, dataset_id="ds",
                                 sensor_type=SensorType.GPR).frames[0]
    assert frame.spatial_ref.kind == CRSKind.ACQUISITION
    assert frame.spatial_ref.code is None
    assert "none is inferred" in frame.spatial_ref.name


# --- header helpers and registry wiring ---

@pytest.mark.parametrize("raw,expected", [
    ("500 MHz shielded=1", 500.0), ("250 MHz shielded", 250.0),
    ("800 MHz shielded=0", 800.0), ("", None), ("unshielded", None)])
def test_antenna_frequency_parsing(raw, expected):
    assert antenna_frequency_mhz({"ANTENNAS": raw}) == expected


def test_rd7_is_read_as_32_bit(tmp_path):
    p = write_pair(tmp_path, ext=".rd7", samples=4, traces=2)
    rows, n = read_rd3(p, 4)
    assert n == 2 and rows[1] == [10, 11, 12, 13]


def test_registry_routes_rd3_and_names_the_sidecars(tmp_path):
    from pathlib import Path
    from converters.registry import classify_file, supported_extensions
    assert {".rd3", ".rd7"} <= supported_extensions()
    assert classify_file(Path("a.rd3")) == ("supported", "mala")
    kind, detail = classify_file(Path("a.rad"))
    assert kind == "recognized_unsupported" and "sidecar" in detail


def test_unsupported_binary_extension_is_refused(tmp_path):
    p = write_pair(tmp_path)
    with pytest.raises(MALAFormatError) as e:
        read_rd3(p.with_suffix(".rd9"), 8)
    assert "unsupported MALA binary extension" in str(e.value)
