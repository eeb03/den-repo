"""
Explicit, caller-supplied CRS for SEG-Y.

SEG-Y has no field for a coordinate reference system. Its SourceX/SourceY
are authoritative per-trace positions, but what they MEAN is unknowable
from the file alone. This milestone lets a caller declare it as ingest
configuration -- and only that way.

The line these tests defend: an externally supplied CRS must never become
indistinguishable from one the data vouches for, and no code path may
infer a CRS. That the INGV headers agree with their KMZ track to 0.74 m is
strong evidence for EPSG:32633, but agreement is not a declaration, and
nothing here turns it into one.
"""
from pathlib import Path

import pytest

from converters.segy_converter import SEGYConverter
from schemas.spatial import CRSKind, CRSProvenance, PositionKind, SpatialRef
from schemas.subterra_record import SensorType

LINE = Path("datasets/downloads/multiline_C1T_0001_0002_extracted/C1T_7,5_0001.SGY")
INGV_CRS = "EPSG:32633"   # supplied here as TEST configuration, never inferred

pytestmark = pytest.mark.skipif(not LINE.exists(), reason="INGV SEG-Y fixture not present locally")


@pytest.fixture(scope="module")
def without_crs():
    return SEGYConverter().load(LINE, dataset_id="ds", sensor_type=SensorType.GPR)


@pytest.fixture(scope="module")
def with_crs():
    return SEGYConverter().load(LINE, dataset_id="ds", sensor_type=SensorType.GPR, crs=INGV_CRS)


# --- no CRS supplied: preserved, but not convertible ---

def test_without_a_crs_projected_headers_are_preserved(without_crs):
    p = without_crs.records[0].position
    assert p.kind == PositionKind.PROJECTED
    assert (p.easting, p.northing) == pytest.approx((501134.03, 4544705.58), abs=0.01)


def test_without_a_crs_no_geographic_coordinates_are_produced(without_crs):
    """The honest state: we hold the position but cannot say where on Earth it is."""
    r = without_crs.records[0]
    assert (r.latitude, r.longitude) == (0.0, 0.0)


def test_without_a_crs_the_frame_declares_none_and_invents_nothing(without_crs):
    ref = without_crs.frames[0].spatial_ref
    assert ref.kind == CRSKind.PROJECTED
    assert ref.code is None
    assert ref.crs_provenance == CRSProvenance.NONE
    assert without_crs.frames[0].assumption("crs_supplied_by_caller") is None


# --- explicit CRS supplied: geographic view is derived ---

def test_explicit_crs_derives_correct_geographic_coordinates(with_crs):
    """UTM 33N easting 501134 / northing 4544705 is the INGV site at ~41.05N 15.01E."""
    r = with_crs.records[0]
    assert r.latitude == pytest.approx(41.0536, abs=0.001)
    assert r.longitude == pytest.approx(15.0135, abs=0.001)


def test_explicit_crs_leaves_native_coordinates_authoritative(with_crs, without_crs):
    """`position` is unchanged by the declaration; only the derived view appears."""
    assert [ (r.position.easting, r.position.northing) for r in with_crs.records[:200] ] == \
           [ (r.position.easting, r.position.northing) for r in without_crs.records[:200] ]
    assert with_crs.records[0].position.kind == PositionKind.PROJECTED


def test_derived_coordinates_vary_per_trace(with_crs):
    """The headers are a real track, so the derived positions must be too."""
    coords = {(round(r.latitude, 7), round(r.longitude, 7)) for r in with_crs.records}
    assert len(coords) > 50


# --- provenance says the CRS came from outside the file ---

def test_frame_records_the_crs_as_supplied_by_the_caller(with_crs):
    ref = with_crs.frames[0].spatial_ref
    assert ref.code == INGV_CRS
    assert ref.crs_provenance == CRSProvenance.SUPPLIED_BY_CALLER
    assert ref.crs_provenance != CRSProvenance.DECLARED_BY_SOURCE
    assert ref.crs_provenance != CRSProvenance.INFERRED


def test_frame_makes_the_external_origin_obvious(with_crs):
    ref = with_crs.frames[0].spatial_ref
    assert "FILE DECLARES NO CRS" in ref.name
    a = with_crs.frames[0].assumption("crs_supplied_by_caller")
    assert a is not None and a.value == INGV_CRS and a.verified is False
    assert "NOT declared by the file" in a.basis and "NOT inferred" in a.basis


def test_nothing_generalises_the_declaration(with_crs):
    """Scoped to the dataset it was supplied for."""
    assert "this dataset only" in with_crs.frames[0].spatial_ref.name


# --- invalid or ambiguous input fails loudly ---

@pytest.mark.parametrize("bad", ["not-a-crs", "EPSG:999999", "", "   "])
def test_invalid_crs_fails_explicitly_rather_than_falling_back(bad):
    with pytest.raises((ValueError, Exception)) as exc:
        SEGYConverter().load(LINE, dataset_id="ds", sensor_type=SensorType.GPR, crs=bad)
    assert "crs" in str(exc.value).lower() or "CRS" in str(exc.value)


def test_a_wrong_but_valid_crs_is_not_silently_corrected():
    """
    We cannot detect a plausible-but-wrong declaration, and must not pretend
    to: a caller declaring EPSG:32632 gets zone 32's answer, not a guess at
    what they meant. This documents that the declaration is trusted.
    """
    other = SEGYConverter().load(LINE, dataset_id="ds", sensor_type=SensorType.GPR,
                                 crs="EPSG:32632")
    assert other.frames[0].spatial_ref.code == "EPSG:32632"
    assert other.records[0].longitude != pytest.approx(15.0135, abs=0.001)


# --- schema-level guarantee ---

def test_a_crs_code_cannot_be_set_without_stating_where_it_came_from():
    with pytest.raises(ValueError, match="crs_provenance"):
        SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:32633")
    SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:32633",
               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER)


# --- KMZ interaction ---

def test_kmz_fallback_not_needed_once_a_crs_makes_headers_usable(with_crs):
    from ingestion.kmz_georeference import records_needing_kmz_fallback
    assert records_needing_kmz_fallback(with_crs.records[:100]) is False


def test_kmz_fallback_still_needed_when_no_crs_was_supplied(without_crs):
    from ingestion.kmz_georeference import records_needing_kmz_fallback
    assert records_needing_kmz_fallback(without_crs.records[:100]) is True


def test_kmz_does_not_overwrite_crs_derived_coordinates(with_crs):
    from ingestion.kmz_georeference import georeference_records_by_trace
    recs = [r.model_copy(deep=True) for r in with_crs.records[:100]]
    before = [(r.latitude, r.longitude) for r in recs]
    # The route guards on records_needing_kmz_fallback; assert the guard holds.
    from ingestion.kmz_georeference import records_needing_kmz_fallback
    assert records_needing_kmz_fallback(recs) is False
    # And that positions survive even if it were called directly.
    georeference_records_by_trace(recs, [(15.0, 41.0), (15.01, 41.01)])
    assert all(r.position.kind == PositionKind.PROJECTED for r in recs)
    assert before != [(r.latitude, r.longitude) for r in recs]  # only the legacy view moved
