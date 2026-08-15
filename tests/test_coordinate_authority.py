"""
SEG-Y header positions are authoritative; KMZ is the fallback.

Established by measurement (see ingestion/kmz_georeference.py): the INGV
headers are a real per-trace acquisition track agreeing with the KMZ to
~1 m over a 17 m line, with track lengths matching to 0.02%. The module
previously documented them as a static placeholder and discarded them.

These tests pin the resulting contract:
  - a usable header position is NEVER overwritten by the KMZ
  - the KMZ IS used when the headers cannot supply a geographic position
  - every record says where its position came from
  - KMZ direction is MEASURED when a second source exists, not assumed
"""
from pathlib import Path

import numpy as np
import pytest

from ingestion.kmz_georeference import (
    DirectionVerification, georeference_records_by_trace, parse_kmz,
    records_needing_kmz_fallback, verify_kmz_direction,
)
from schemas.spatial import (
    GeographicPosition, NoPosition, PositionKind, ProjectedPosition,
)
from schemas.subterra_record import SensorType, SubterraRecord

TRACK = [(15.0130, 41.0534), (15.0135, 41.0536)]

#: The real INGV fixtures. Untracked (datasets/ is gitignored), so every test
#: touching them skips when they are absent -- the pattern six other test
#: modules already use.
INGV_DIR = Path("datasets/downloads/multiline_C1T_0001_0002_extracted")
INGV_LINES = {"C1T_7,5_0001": INGV_DIR / "C1T_7,5_0001.SGY",
              "C1T_7,5_0002": INGV_DIR / "C1T_7,5_0002.SGY"}
INGV_KMZ = INGV_DIR / "ANF_CARRELLO.kmz"
INGV_PRESENT = INGV_KMZ.exists() and all(p.exists() for p in INGV_LINES.values())


def _header_track(path: Path) -> list[tuple[float, float]]:
    """
    Per-trace SourceX/SourceY, scaled by the file's own SourceGroupScalar.

    Read from the trace headers, where SEG-Y puts them (bytes 73-80). No CRS
    is applied and none is needed: the numbers are already metres, which is
    what makes the length comparison below possible without asserting a
    projection the file never declares.
    """
    import segyio

    with segyio.open(str(path), "r", ignore_geometry=True) as f:
        out = []
        for i in range(f.tracecount):
            header = f.header[i]
            scalar = header[segyio.TraceField.SourceGroupScalar] or 1
            factor = 1.0 / abs(scalar) if scalar < 0 else float(scalar)
            out.append((header[segyio.TraceField.SourceX] * factor,
                        header[segyio.TraceField.SourceY] * factor))
        return out


def _planar_length_m(xy: list[tuple[float, float]]) -> float:
    """Track length straight from projected metres -- no reprojection."""
    return float(sum(np.hypot(xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1])
                     for i in range(len(xy) - 1)))


def _geographic_length_m(lonlat: list[tuple[float, float]]) -> float:
    from fusion.sensor_fusion import haversine_m

    return float(sum(haversine_m(lonlat[i][1], lonlat[i][0],
                                 lonlat[i + 1][1], lonlat[i + 1][0])
                     for i in range(len(lonlat) - 1)))


def _records(position_factory, n_traces=4):
    return [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.GPR,
            latitude=0.0, longitude=0.0, position=position_factory(t),
            frame_id="ds:line", depth=0.1 * s, signal=[1.0],
            metadata={"source_file": "line.SGY", "trace_index": t, "sample_index": s},
        )
        for t in range(n_traces) for s in range(2)
    ]


# --- when the header gives a geographic position, it wins ---

def test_geographic_header_position_does_not_need_the_kmz_fallback():
    recs = _records(lambda t: GeographicPosition(lat=41.0 + t * 1e-4, lon=15.0 + t * 1e-4))
    assert records_needing_kmz_fallback(recs) is False


def test_kmz_sets_a_geographic_position_and_keeps_the_header_values():
    """
    M3: `position` is the single source of spatial truth, so a KMZ track --
    which IS a real geographic position -- sets it. The file's own header
    coordinates are not lost; SEGYConverter keeps them in metadata.
    """
    recs = _records(lambda t: ProjectedPosition(easting=501134.0 + t, northing=4544705.0 + t))
    for r in recs:
        r.metadata["segy_x"], r.metadata["segy_y"] = r.position.easting, r.position.northing
    before = [(r.metadata["segy_x"], r.metadata["segy_y"]) for r in recs]

    georeference_records_by_trace(recs, TRACK)

    assert all(r.position.kind == PositionKind.GEOGRAPHIC for r in recs)
    assert [(r.metadata["segy_x"], r.metadata["segy_y"]) for r in recs] == before
    assert all(r.metadata["position_source"] == "kmz_fallback" for r in recs)


def test_kmz_only_runs_when_the_headers_could_not_supply_a_position():
    """The guard, not the mutation, is what protects header authority."""
    usable = _records(lambda t: GeographicPosition(lat=41.0 + t * 1e-4, lon=15.0))
    assert records_needing_kmz_fallback(usable) is False


# --- when the header cannot supply one, the KMZ is used ---

def test_projected_header_without_a_crs_still_needs_the_fallback():
    """Projected easting/northing cannot become lat/lon without a CRS."""
    recs = _records(lambda t: ProjectedPosition(easting=501134.0 + t, northing=4544705.0 + t))
    assert records_needing_kmz_fallback(recs) is True


def test_absent_header_position_needs_the_fallback():
    recs = _records(lambda t: NoPosition(reason="headers are (0, 0)"))
    assert records_needing_kmz_fallback(recs) is True


def test_empty_input_needs_no_fallback():
    assert records_needing_kmz_fallback([]) is False


def test_fallback_populates_legacy_latitude_longitude():
    recs = _records(lambda t: NoPosition(reason="headers are (0, 0)"))
    n = georeference_records_by_trace(recs, TRACK)
    assert n == 4
    assert all(r.latitude != 0.0 and r.longitude != 0.0 for r in recs)
    assert len({(r.latitude, r.longitude) for r in recs}) == 4  # one per trace


# --- provenance is always recorded ---

def test_kmz_fallback_records_its_provenance():
    recs = _records(lambda t: NoPosition(reason="headers are (0, 0)"))
    georeference_records_by_trace(recs, TRACK)
    assert all(r.metadata["position_source"] == "kmz_fallback" for r in recs)
    assert all(r.metadata["georeferenced_from_kmz"] is True for r in recs)


@pytest.mark.skipif(
    not __import__("pathlib").Path(
        "datasets/downloads/multiline_C1T_0001_0002_extracted/C1T_7,5_0001.SGY").exists(),
    reason="INGV SEG-Y fixture not present locally",
)
def test_segy_converter_records_header_provenance():
    from pathlib import Path
    from converters.segy_converter import SEGYConverter
    recs = SEGYConverter().convert(
        Path("datasets/downloads/multiline_C1T_0001_0002_extracted/C1T_7,5_0001.SGY"),
        dataset_id="ds", sensor_type=SensorType.GPR)
    assert recs[0].metadata["position_source"] == "segy_header"
    assert recs[0].position.kind == PositionKind.PROJECTED


# --- direction verification is measured, not assumed ---

def _straight_reference(track, n):
    """n evenly spaced (lon, lat) points along `track` -- a perfect match."""
    from ingestion.kmz_georeference import resample_path_by_arc_length
    return [tuple(p) for p in resample_path_by_arc_length(track, n)]


def test_direction_verified_when_as_recorded_fits_far_better():
    track = [(15.000, 41.000), (15.000, 41.001), (15.000, 41.002)]
    reference = _straight_reference(track, 20)
    result = verify_kmz_direction(reference, track, applies_to="line1")
    assert result.verified is True
    assert result.residual_as_recorded_m < result.residual_reversed_m
    assert result.improvement_ratio > 2.0


def test_direction_not_verified_when_the_orderings_are_indistinguishable():
    """A symmetric reference cannot discriminate; the honest answer is 'unverified'."""
    track = [(15.000, 41.000), (15.000, 41.001)]
    midpoint = [(15.000, 41.0005)] * 8
    result = verify_kmz_direction(midpoint, track, applies_to="line1")
    assert result.verified is False


def test_direction_verification_is_scoped_to_one_line():
    """Not a universal claim about all KMZ/SEG-Y datasets."""
    track = [(15.000, 41.000), (15.000, 41.002)]
    result = verify_kmz_direction(_straight_reference(track, 10), track, applies_to="C1T_7,5_0001")
    assert result.applies_to == "C1T_7,5_0001"
    assert result.n_traces == 10
    assert "residual" in result.method


def test_direction_verification_handles_degenerate_input():
    result = verify_kmz_direction([(15.0, 41.0)], TRACK, applies_to="line1")
    assert result.verified is False
    assert np.isnan(result.residual_as_recorded_m)


def test_verified_direction_is_recorded_on_every_record():
    recs = _records(lambda t: NoPosition(reason="headers are (0, 0)"))
    verification = DirectionVerification(
        verified=True, applies_to="line", method="test", n_traces=4,
        residual_as_recorded_m=0.74, residual_reversed_m=9.50,
    )
    georeference_records_by_trace(recs, TRACK, direction=verification)
    meta = recs[0].metadata
    assert meta["kmz_direction_verified"] is True
    assert meta["kmz_direction_verification"]["applies_to"] == "line"
    assert meta["kmz_direction_verification"]["residual_as_recorded_m"] == 0.74
    assert meta["kmz_direction_verification"]["improvement_ratio"] == pytest.approx(12.838, abs=0.01)


def test_unverified_direction_remains_the_default():
    """Backward compatible: without a second source, nothing is claimed."""
    recs = _records(lambda t: NoPosition(reason="headers are (0, 0)"))
    georeference_records_by_trace(recs, TRACK)
    assert recs[0].metadata["kmz_direction_verified"] is False
    assert "kmz_direction_verification" not in recs[0].metadata


# --------------------------------------------------------------------------
# The measurement itself, against the real files
# --------------------------------------------------------------------------
#
# Everything above constructs its records. These two read the fixtures, so
# they are the tests that would actually catch the project re-adopting the
# "static placeholder" reading that once justified discarding a real track.

@pytest.mark.skipif(not INGV_PRESENT, reason="INGV SEG-Y + KMZ fixture not present")
@pytest.mark.parametrize("stem", sorted(INGV_LINES))
def test_ingv_header_positions_vary_per_trace(stem):
    """
    Refutes the placeholder reading directly: the headers MOVE.

    Per-trace variation is what SEG-Y specifies -- SourceX/SourceY are trace
    header fields -- so a file whose every trace shared one position would be
    the anomaly, not this. Asserted as a relationship (most traces distinct,
    and the track advances) rather than as a copied count, so the test states
    the finding rather than a transcription of it.
    """
    xy = _header_track(INGV_LINES[stem])

    assert len(xy) > 1
    assert len(set(xy)) > 1, "a single repeated position IS the placeholder claim"
    assert len(set(xy)) >= 0.9 * len(xy), "the track should be near-fully distinct"

    steps = [np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(xy, xy[1:])]
    assert min(steps) >= 0.0
    assert np.median(steps) > 0.1, "consecutive traces should advance, not jitter"

    # Not every step is non-zero, and that is a real property of the data
    # rather than a defect: the instrument was stationary for the opening
    # traces of a line. Recorded so the near-fully-distinct bound above is
    # understood rather than tuned.
    stationary = [i for i, s in enumerate(steps) if s == 0.0]
    assert all(i < 10 for i in stationary), (
        f"{stem}: zero-length steps should be confined to the start of the "
        f"line, got {stationary}")


@pytest.mark.skipif(not INGV_PRESENT, reason="INGV SEG-Y + KMZ fixture not present")
@pytest.mark.parametrize("stem", sorted(INGV_LINES))
def test_ingv_header_track_length_agrees_with_the_kmz(stem):
    """
    The cross-check that settled which source is authoritative.

    Two independent measurements of the same line: the trace headers, in
    projected metres, and the KMZ polyline, in degrees over the ellipsoid.
    They are compared by LENGTH, which needs no reprojection and so asserts
    no CRS the file does not declare.
    """
    header_len = _planar_length_m(_header_track(INGV_LINES[stem]))
    kmz_len = _geographic_length_m(parse_kmz(INGV_KMZ)[stem])

    assert header_len > 1.0 and kmz_len > 1.0
    assert header_len == pytest.approx(kmz_len, rel=0.01), (
        f"{stem}: header track {header_len:.2f} m vs KMZ {kmz_len:.2f} m")


@pytest.mark.skipif(not INGV_PRESENT, reason="INGV SEG-Y + KMZ fixture not present")
@pytest.mark.parametrize("stem", sorted(INGV_LINES))
def test_the_headers_are_a_finer_track_than_the_kmz(stem):
    """
    Why the headers win where both exist: more points over the same line.
    This is the substantive reason the fallback is a FALLBACK.
    """
    assert len(_header_track(INGV_LINES[stem])) > len(parse_kmz(INGV_KMZ)[stem])
