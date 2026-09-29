"""
`coordinate_encoding="int32_scalar_exponent"`: scalars that are powers of ten.

THE REAL FILE THAT NEEDED THIS. The ADS "Beneath the Surface of Roman
Republican Cities" SEG-Y (Falerii Novi field 5, doi 10.5284/1052663) writes
SourceGroupScalar = ElevationScalar = -2 and means 10^-2: the first trace's
SourceX 28194532 is 281945.32 m E in UTM 33N, and ReceiverGroupElevation 20314
is 203.14 m. Read by the SEG-Y standard (-2 => divide by 2) the same bytes put
the survey at 14,097,266 m E -- which, with EPSG:32633 declared, the converter
silently turned into a point in the Indian Ocean -- and the standard path does
not read the elevation fields at all.

Like `ieee_nmea`, nothing in the bytes distinguishes the two conventions, so
this is a CALLER DECLARATION, never inferred, and the standard remains the
default. The header values below are copied from that real file.
"""
import struct

import pytest

from converters.segy_converter import (
    COORDINATE_ENCODINGS, SEGYConverter, validate_coordinate_encoding,
)
from schemas.subterra_record import SensorType

#: Falerii_Novi_field_5_0001_raw.segy, trace 1 (big-endian, format 5).
FN_SOURCE_X = 28194532
FN_SOURCE_Y = 468650626
FN_RECEIVER_ELEVATION = 20314
FN_SOURCE_ELEVATION = 20315
FN_SCALAR = -2


def write_big_endian_segy(
    path, *, n_traces=2, n_samples=4, interval=200,
    source_x=FN_SOURCE_X, source_y=FN_SOURCE_Y,
    coord_scalar=FN_SCALAR, elevation_scalar=FN_SCALAR,
    receiver_elevation=FN_RECEIVER_ELEVATION, source_elevation=FN_SOURCE_ELEVATION,
):
    """A minimal standard (big-endian, IEEE float) SEG-Y with the ADS header layout."""
    s = ">"
    out = bytearray(b"\x40" * 3200)  # EBCDIC spaces
    bh = bytearray(400)
    bh[16:18] = struct.pack(s + "h", interval)
    bh[20:22] = struct.pack(s + "h", n_samples)
    bh[24:26] = struct.pack(s + "h", 5)  # 4-byte IEEE float
    out += bh
    for t in range(n_traces):
        th = bytearray(240)
        th[0:4] = struct.pack(s + "i", t + 1)
        th[40:44] = struct.pack(s + "i", receiver_elevation)
        th[44:48] = struct.pack(s + "i", source_elevation)
        th[68:70] = struct.pack(s + "h", elevation_scalar)
        th[70:72] = struct.pack(s + "h", coord_scalar)
        th[72:76] = struct.pack(s + "i", source_x)
        th[76:80] = struct.pack(s + "i", source_y)
        th[88:90] = struct.pack(s + "h", 1)  # coordinate units: length
        th[114:116] = struct.pack(s + "h", n_samples)
        th[116:118] = struct.pack(s + "h", interval)
        out += th
        out += struct.pack(f"{s}{n_samples}f", *[float(t * 10 + i) for i in range(n_samples)])
    path.write_bytes(bytes(out))
    return path


def _load(path, **kw):
    return SEGYConverter().load(path, dataset_id="fn5", sensor_type=SensorType.GPR, **kw)


# ---------------------------------------------------------------------------
# the declaration itself
# ---------------------------------------------------------------------------

def test_the_encoding_is_a_known_declaration():
    assert "int32_scalar_exponent" in COORDINATE_ENCODINGS
    validate_coordinate_encoding("int32_scalar_exponent")  # must not raise


# ---------------------------------------------------------------------------
# horizontal position
# ---------------------------------------------------------------------------

def test_coordinates_are_scaled_by_ten_to_the_scalar(tmp_path):
    rec = _load(write_big_endian_segy(tmp_path / "fn.segy"),
                coordinate_encoding="int32_scalar_exponent").records[0]

    assert rec.position.kind == "projected"
    assert rec.position.easting == pytest.approx(281945.32, abs=1e-6)
    assert rec.position.northing == pytest.approx(4686506.26, abs=1e-6)


def test_with_the_declared_crs_the_survey_lands_at_falerii_novi(tmp_path):
    """The real site is ~42.29 N, 12.36 E -- not the Indian Ocean."""
    rec = _load(write_big_endian_segy(tmp_path / "fn.segy"),
                coordinate_encoding="int32_scalar_exponent", crs="EPSG:32633").records[0]

    assert rec.latitude == pytest.approx(42.29, abs=0.02)
    assert rec.longitude == pytest.approx(12.36, abs=0.02)


def test_a_positive_scalar_multiplies_by_ten_to_the_scalar(tmp_path):
    rec = _load(write_big_endian_segy(tmp_path / "fn.segy", source_x=2819, source_y=46865,
                                      coord_scalar=2),
                coordinate_encoding="int32_scalar_exponent").records[0]

    assert rec.position.easting == pytest.approx(281900.0)
    assert rec.position.northing == pytest.approx(4686500.0)


# ---------------------------------------------------------------------------
# acquisition elevation
# ---------------------------------------------------------------------------

def test_elevation_is_read_and_scaled_by_ten_to_the_elevation_scalar(tmp_path):
    rec = _load(write_big_endian_segy(tmp_path / "fn.segy"),
                coordinate_encoding="int32_scalar_exponent").records[0]

    assert rec.elevation == pytest.approx(203.14, abs=1e-9)
    assert rec.metadata["segy_source_surface_elevation_m"] == pytest.approx(203.15, abs=1e-9)


def test_the_elevation_scalar_is_independent_of_the_coordinate_scalar(tmp_path):
    rec = _load(write_big_endian_segy(tmp_path / "fn.segy", elevation_scalar=-1,
                                      receiver_elevation=2031),
                coordinate_encoding="int32_scalar_exponent").records[0]

    assert rec.elevation == pytest.approx(203.1, abs=1e-9)
    assert rec.position.easting == pytest.approx(281945.32, abs=1e-6)


def test_no_datum_is_claimed_for_the_elevation(tmp_path):
    """The file declares none; ADS's documentation says EGM2008, but that is a
    dataset-level declaration for the vertical-reference workflow, not something
    this generic converter may assert."""
    rec = _load(write_big_endian_segy(tmp_path / "fn.segy"),
                coordinate_encoding="int32_scalar_exponent").records[0]

    assert rec.metadata["acquisition_elevation_datum"] == "UNDECLARED"
    assert rec.metadata["acquisition_elevation_source"] == "segy_receiver_group_elevation"


def test_a_zero_elevation_field_is_no_elevation(tmp_path):
    """0 in the field means 'not recorded', exactly as on the ieee_nmea path."""
    rec = _load(write_big_endian_segy(tmp_path / "fn.segy", receiver_elevation=0),
                coordinate_encoding="int32_scalar_exponent").records[0]

    assert rec.elevation is None
    assert "acquisition_elevation_m" not in rec.metadata


# ---------------------------------------------------------------------------
# the default is untouched, and the declaration is recorded
# ---------------------------------------------------------------------------

def test_the_default_still_follows_the_seg_y_standard(tmp_path):
    """Same bytes, no declaration: -2 still divides by 2 and elevation is not
    read, so every pinned int32_scaled record (e.g. INGV) is unchanged."""
    rec = _load(write_big_endian_segy(tmp_path / "fn.segy")).records[0]

    assert rec.position.easting == pytest.approx(FN_SOURCE_X / 2)
    assert rec.elevation is None


def test_the_frame_flags_the_undeclared_datum_without_4tu_specific_claims(tmp_path):
    """The frame's datum note must describe THIS file, not the Netherlands corpus."""
    frame = _load(write_big_endian_segy(tmp_path / "fn.segy"),
                  coordinate_encoding="int32_scalar_exponent").frames[0]

    notes = [a for a in frame.assumptions if a.key == "acquisition_elevation_datum"]
    assert len(notes) == 1
    assert notes[0].value is None
    assert notes[0].verified is False
    assert "Netherlands" not in notes[0].basis
    assert "43.948" not in notes[0].basis


def test_the_declaration_is_recorded_on_the_frame_as_unverified(tmp_path):
    frame = _load(write_big_endian_segy(tmp_path / "fn.segy"),
                  coordinate_encoding="int32_scalar_exponent").frames[0]

    declared = [a for a in frame.assumptions if a.key == "segy_coordinate_encoding"]
    assert len(declared) == 1
    assert declared[0].value == "int32_scalar_exponent"
    assert declared[0].verified is False
