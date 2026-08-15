"""
Identifying which SEG-Y elevation field holds the ellipsoidal GNSS height.

WHY THIS COULD HAVE GONE WRONG. Two candidate fields differ by ~44 m, and the
temptation is to pick the larger one because it "looks like" an ellipsoidal
height. That is not evidence. The test that settles it compares BOTH fields
against an independent national terrain model, and the two hypotheses make
predictions ~44 m apart -- far enough that a half-metre reference decides it.

THE CIRCULARITY THAT HAD TO BE AVOIDED. `SubterraRecord.elevation` is derived
from one of the two candidates. Using it as the reference would have been asking
a field to referee itself. Everything here is decoded from the raw trace-header
bytes, and the reference is AHN, a separate dataset acquired from PDOK.

WHAT IS STILL NOT ESTABLISHED. Which field is the surface elevation says nothing
about where the depth axis begins. The author is explicit that no time-zero
correction and no air-gap removal were applied, so the ground surface does not
correspond to depth zero. That blocker is untouched.
"""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from scripts.identify_segy_elevation_field import (
    NL_TERRAIN_RANGE, PUBLISHED_GEOID_SEPARATION, RECEIVER_GROUP_ELEVATION,
    SOURCE_SURFACE_ELEVATION, SOURCE_X, SOURCE_Y, nmea_to_degrees,
    read_trace_headers, site_of, spatial_behaviour, statistics,
)

ARTIFACT = Path("artifacts/4tu/elevation_field.json")
NEEDS_ARTIFACT = pytest.mark.skipif(
    not ARTIFACT.exists(),
    reason="run scripts/identify_segy_elevation_field.py to produce the artifact")


def _segy(n_traces=3, n_samples=4, receiver=28.4, source=72.35,
          lat_nmea=5214.3379, lon_nmea=651.0929, format_code=3) -> bytes:
    """
    A minimal little-endian SEG-Y with the 4TU layout.

    Constructed to exercise the DECODER, not to represent a survey; no result
    derived from it is reported as science.
    """
    binary = bytearray(400)
    binary[20:22] = struct.pack("<h", n_samples)
    binary[24:26] = struct.pack("<h", format_code)
    out = bytearray(3200) + binary
    for _ in range(n_traces):
        head = bytearray(240)
        head[RECEIVER_GROUP_ELEVATION:RECEIVER_GROUP_ELEVATION + 4] = struct.pack("<f", receiver)
        head[SOURCE_SURFACE_ELEVATION:SOURCE_SURFACE_ELEVATION + 4] = struct.pack("<f", source)
        head[SOURCE_X:SOURCE_X + 4] = struct.pack("<f", lon_nmea)
        head[SOURCE_Y:SOURCE_Y + 4] = struct.pack("<f", lat_nmea)
        head[68:70] = struct.pack("<h", 1)       # elevation scalar
        head[70:72] = struct.pack("<h", -1000)   # coordinate scalar
        out += head + bytes(n_samples * 2)
    return bytes(out)


# ---------------------------------------------------------------------------
# header interpretation
# ---------------------------------------------------------------------------

def test_the_two_elevation_fields_are_read_from_the_documented_bytes():
    """41-44 and 45-48, the SEG-Y rev1 positions -- not swapped, not guessed."""
    assert RECEIVER_GROUP_ELEVATION == 40   # byte 41, 0-based
    assert SOURCE_SURFACE_ELEVATION == 44   # byte 45, 0-based


def test_both_fields_are_decoded_distinctly(tmp_path):
    path = tmp_path / "a.sgy"
    path.write_bytes(_segy(receiver=28.4, source=72.35))
    headers = read_trace_headers(path)

    assert headers["receiver_group_elevation"] == pytest.approx([28.4] * 3, abs=1e-4)
    assert headers["source_surface_elevation"] == pytest.approx([72.35] * 3, abs=1e-4)
    assert not np.allclose(headers["receiver_group_elevation"],
                           headers["source_surface_elevation"])


def test_the_scalars_are_read_and_reported(tmp_path):
    """
    Read and surfaced rather than applied: these files carry IEEE floats where
    the standard specifies scaled integers, so a scalar must not be multiplied
    into a value that was never scaled.
    """
    path = tmp_path / "a.sgy"
    path.write_bytes(_segy())
    headers = read_trace_headers(path)

    assert headers["elevation_scalars"] == [1]
    assert headers["coordinate_scalars"] == [-1000]


def test_a_file_that_is_not_the_expected_layout_is_refused(tmp_path):
    """Returned as None rather than reinterpreted until something looks plausible."""
    path = tmp_path / "b.sgy"
    path.write_bytes(_segy(format_code=1))          # IBM float, not int16
    assert read_trace_headers(path) is None

    short = tmp_path / "c.sgy"
    short.write_bytes(b"\x00" * 100)
    assert read_trace_headers(short) is None


def test_trace_count_follows_the_int16_sample_layout(tmp_path):
    path = tmp_path / "a.sgy"
    path.write_bytes(_segy(n_traces=7, n_samples=16))
    headers = read_trace_headers(path)
    assert headers["n_traces"] == 7 and headers["n_samples"] == 16


# ---------------------------------------------------------------------------
# coordinate decoding
# ---------------------------------------------------------------------------

def test_nmea_decoding_places_the_survey_in_the_netherlands(tmp_path):
    path = tmp_path / "a.sgy"
    path.write_bytes(_segy(lat_nmea=5214.3379, lon_nmea=651.0929))
    headers = read_trace_headers(path)

    assert headers["latitude"][0] == pytest.approx(52.2390, abs=1e-3)
    assert headers["longitude"][0] == pytest.approx(6.8515, abs=1e-3)


def test_ddmm_is_not_mistaken_for_decimal_degrees():
    """5214.3379 is 52 deg 14.3379 min, not 5214 degrees."""
    assert nmea_to_degrees(5214.3379) == pytest.approx(52.23896, abs=1e-4)
    assert nmea_to_degrees(651.0929) == pytest.approx(6.85155, abs=1e-4)


def test_site_grouping_handles_two_and_three_digit_sites():
    assert site_of("01.9") == "01"
    assert site_of("010.11") == "010"
    assert site_of("013.2") == "013"


# ---------------------------------------------------------------------------
# no circular validation
# ---------------------------------------------------------------------------

def test_the_investigation_never_uses_subterras_own_elevation_as_truth():
    """
    `SubterraRecord.elevation` is derived from one of the candidates. Using it
    as the reference would be asking a field to referee itself. Checked by
    parsing the imports, so a name in prose cannot fail it and a real import
    cannot hide.
    """
    import ast

    tree = ast.parse(Path("scripts/identify_segy_elevation_field.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for forbidden in ("database.records_store", "schemas.subterra_record",
                      "converters.segy_converter", "api"):
        assert not any(name.startswith(forbidden) for name in imported), \
            f"the reference must be independent of {forbidden}"


def test_the_reference_is_a_separate_dataset_with_recorded_provenance():
    from scripts.identify_segy_elevation_field import AHN_DIR

    assert AHN_DIR.name == "dtm_05m"
    assert "pdok" in str(AHN_DIR)


# ---------------------------------------------------------------------------
# residual and statistics behaviour
# ---------------------------------------------------------------------------

def test_statistics_ignore_missing_cells_rather_than_treating_them_as_zero():
    residual = np.array([1.0, 2.0, np.nan, 3.0])
    s = statistics(residual)
    assert s["n"] == 3 and s["mean"] == pytest.approx(2.0)


def test_statistics_report_no_sample_rather_than_a_zero():
    assert statistics(np.array([np.nan, np.nan]))["n"] == 0


def test_a_terrain_value_outside_the_plausible_range_is_rejected():
    """AHN's nodata is a huge float; a fill value must not become a measurement."""
    assert NL_TERRAIN_RANGE[0] < 0 < NL_TERRAIN_RANGE[1] < 3.4e38


# ---------------------------------------------------------------------------
# distinguishing a geoid from an instrument offset
# ---------------------------------------------------------------------------

def test_a_constant_offset_is_not_mistaken_for_a_spatial_field():
    """
    An antenna height or a fixed software constant would be CONSTANT. The fit
    must not report a constant as strongly spatial.
    """
    per_activity = [{"site": s, "matched_to_ahn": 10,
                     "source_minus_receiver_mean": 44.0}
                    for s in ("a", "b", "c", "d", "e")]
    centroids = {s: (51.0 + i * 0.5, 5.0) for i, s in enumerate("abcde")}

    fit = spatial_behaviour(per_activity, centroids)
    assert fit["offset_spread_m"] == pytest.approx(0.0, abs=1e-9)
    assert fit["varies_spatially"] is False
    assert fit["r_squared"] is None, "a constant has no spatial variance to explain"
    assert fit["correlation_with_latitude"] is None


def test_a_latitude_dependent_offset_is_recovered():
    per_activity = [{"site": s, "matched_to_ahn": 10,
                     "source_minus_receiver_mean": 50.0 - 1.675 * (51.0 + i * 0.5)}
                    for i, s in enumerate("abcde")]
    centroids = {s: (51.0 + i * 0.5, 5.0) for i, s in enumerate("abcde")}

    fit = spatial_behaviour(per_activity, centroids)
    assert fit["varies_spatially"] is True
    assert fit["r_squared"] == pytest.approx(1.0, abs=1e-6)
    assert fit["planar_fit"]["per_degree_latitude"] == pytest.approx(-1.675, abs=1e-3)


def test_too_few_sites_is_unresolved_rather_than_fitted():
    """Three points define a plane exactly; a fit through them proves nothing."""
    fit = spatial_behaviour(
        [{"site": s, "matched_to_ahn": 1, "source_minus_receiver_mean": 44.0}
         for s in "ab"],
        {"a": (51.0, 5.0), "b": (52.0, 5.0)})
    assert fit["available"] is False


def test_the_published_reference_is_labelled_external_and_unverified():
    """
    An external claim is not a Subterra measurement, and the report must not
    let the two blur.
    """
    assert "EXTERNAL REFERENCE" in PUBLISHED_GEOID_SEPARATION["status"]
    assert "not verified by Subterra" in PUBLISHED_GEOID_SEPARATION["status"]
    assert PUBLISHED_GEOID_SEPARATION["source"]
    assert PUBLISHED_GEOID_SEPARATION["retrieved"]


# ---------------------------------------------------------------------------
# the measured result
# ---------------------------------------------------------------------------

@NEEDS_ARTIFACT
def test_the_receiver_field_tracks_the_independent_nap_surface():
    overall = json.loads(ARTIFACT.read_text())["overall"]
    receiver = overall["receiver_minus_ahn"]

    assert receiver["n"] > 100_000
    assert abs(receiver["mean"]) < 2.0, "bytes 41-44 agree with AHN to within metres"


@NEEDS_ARTIFACT
def test_the_source_field_sits_a_geoid_separation_above_the_nap_surface():
    overall = json.loads(ARTIFACT.read_text())["overall"]
    source = overall["source_minus_ahn"]

    assert 40.0 < source["mean"] < 47.0, \
        "bytes 45-48 sit within the published NL geoid separation range above NAP"


@NEEDS_ARTIFACT
def test_the_two_hypotheses_are_separated_by_far_more_than_the_reference_error():
    """
    The whole test rests on this: the predictions differ by ~44 m while the
    reference is accurate to ~1 m, so the comparison is not marginal.
    """
    overall = json.loads(ARTIFACT.read_text())["overall"]
    separation = abs(overall["source_minus_ahn"]["mean"]
                     - overall["receiver_minus_ahn"]["mean"])
    assert separation > 40.0
    assert overall["receiver_minus_ahn"]["sd"] < separation / 10


@NEEDS_ARTIFACT
def test_the_difference_behaves_spatially_not_instrumentally():
    fit = json.loads(ARTIFACT.read_text())["spatial_behaviour_of_the_difference"]

    assert fit["n_sites"] >= 10
    assert fit["r_squared"] > 0.95
    assert abs(fit["correlation_with_latitude"]) > 0.95
    assert fit["residual_sd_about_plane_m"] < 0.5
    assert fit["offset_spread_m"] > 1.0, "a constant would rule the geoid out"


@NEEDS_ARTIFACT
def test_the_evidence_spans_many_activities_not_one_line():
    report = json.loads(ARTIFACT.read_text())
    assert report["activities_examined"] >= 100
    assert report["activities_matched"] >= 50
