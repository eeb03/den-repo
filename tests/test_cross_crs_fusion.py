"""
Cross-CRS fusion: a projected survey and a geographic one over the same
ground can finally be clustered together -- but only via a DECLARED CRS.

The rule these tests pin is narrow and deliberate. A projected position
becomes fusable when, and only when, its frame carries a CRS someone
declared. No CRS is ever inferred from the magnitude of the numbers, from a
neighbouring dataset, or from a plausible guess at a UTM zone. A frame with
no declared CRS stays excluded, with the reason, forever.

They also pin the honesty of the result: reprojection never mutates a
record, and a sample built partly from transformed coordinates says so
through `n_reprojected`.
"""
import pytest

from database.frames_store import load_frames_for
from fusion.sensor_fusion import (
    fuse_datasets, geographic_view, geographic_views,
    non_fusable_partitions, partition_by_spatial_ref,
)
from ingestion.crs_transform import CRSTransformError, is_transformable, to_wgs84
from schemas.spatial import (
    AxisKind, CRSKind, CRSProvenance, GeographicPosition, LocalCartesianPosition,
    NoPosition, OdometryPosition, ProjectedPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame

# A real place, so the transform is checkable: UTM zone 33N easting/northing
# near Foggia, Italy -- the region the INGV lines were acquired in.
UTM33N = "EPSG:32633"

#: These tests are about horizontal position only; the vertical axis is
#: declared absent rather than invented.
_NO_VERTICAL_AXIS = VerticalAxis(
    kind=AxisKind.NONE, units="none",
    origin="not applicable: these fixtures exercise horizontal position only",
    positive_down=True,
)
E, N = 500_000.0, 4_544_705.0


def _frame(frame_id, kind, code, provenance=CRSProvenance.SUPPLIED_BY_CALLER):
    return SurveyFrame(
        frame_id=frame_id, dataset_id=frame_id.split(":")[0],
        modality=SensorType.GPR, source_format="segy",
        spatial_ref=SpatialRef(
            kind=kind, code=code,
            crs_provenance=provenance if code else CRSProvenance.NONE,
            horizontal_units="m" if kind == CRSKind.PROJECTED else "deg",
        ),
        vertical_axis=_NO_VERTICAL_AXIS,
    )


def _record(frame_id, position, sensor=SensorType.GPR, dataset_id=None):
    return SubterraRecord(
        dataset_id=dataset_id or frame_id.split(":")[0], sensor_type=sensor,
        position=position, frame_id=frame_id, signal=[1.0], metadata={},
    )


# --- the transform itself ---

def test_declared_crs_is_transformable_and_unknown_is_not():
    assert is_transformable(UTM33N) is True
    assert is_transformable(None) is False
    assert is_transformable("") is False
    assert is_transformable("not a crs") is False


def test_to_wgs84_lands_where_the_projection_says():
    (lat, lon), = to_wgs84(UTM33N, [E], [N])
    # UTM 33N false easting 500000 is the central meridian, 15 deg E.
    assert lon == pytest.approx(15.0, abs=1e-6)
    assert lat == pytest.approx(41.05, abs=0.05)


def test_to_wgs84_is_vectorised_and_order_preserving():
    out = to_wgs84(UTM33N, [E, E + 1000, E + 2000], [N, N, N])
    assert len(out) == 3
    assert out[0][1] < out[1][1] < out[2][1]     # easting increases -> lon increases


def test_to_wgs84_on_empty_input_is_empty():
    assert to_wgs84(UTM33N, [], []) == []


def test_an_uninterpretable_crs_raises_and_names_the_remedy():
    with pytest.raises(CRSTransformError) as e:
        to_wgs84("zone 33 probably", [E], [N])
    assert "EPSG:32633" in str(e.value)


# --- what becomes fusable, and what does not ---

def test_projected_record_with_a_declared_crs_gets_a_geographic_view():
    frame = _frame("ds:proj", CRSKind.PROJECTED, UTM33N)
    r = _record("ds:proj", ProjectedPosition(easting=E, northing=N))
    view = geographic_view(r, {frame.frame_id: frame})
    assert view is not None
    assert view[1] == pytest.approx(15.0, abs=1e-6)


def test_projected_record_without_a_declared_crs_gets_nothing():
    """The whole point: numbers with no declared system stay meaningless."""
    frame = _frame("ds:proj", CRSKind.PROJECTED, None)
    r = _record("ds:proj", ProjectedPosition(easting=E, northing=N))
    assert geographic_view(r, {frame.frame_id: frame}) is None


def test_projected_record_with_no_frame_at_all_gets_nothing():
    r = _record("ds:proj", ProjectedPosition(easting=E, northing=N))
    assert geographic_view(r, {}) is None
    assert geographic_view(r, None) is None


def test_odometry_and_local_are_never_reprojected():
    """A declared CRS on the frame does not make a distance-along-a-line a place."""
    for position in (OdometryPosition(along_track_m=12.0, path_id="l1"),
                     LocalCartesianPosition(x=1.0, y=2.0, origin_description="pit corner"),
                     NoPosition(reason="no positioning was recorded")):
        frame = _frame("ds:x", CRSKind.PROJECTED, UTM33N)
        r = _record("ds:x", position)
        assert geographic_view(r, {frame.frame_id: frame}) is None


def test_geographic_records_are_unaffected_by_frames():
    r = _record("ds:geo", GeographicPosition(lat=41.05, lon=15.0))
    assert geographic_view(r, None) == (41.05, 15.0)
    assert geographic_view(r, {}) == (41.05, 15.0)


def test_views_are_grouped_per_crs_and_keyed_by_identity():
    frames = {"ds:a": _frame("ds:a", CRSKind.PROJECTED, UTM33N),
              "ds:b": _frame("ds:b", CRSKind.PROJECTED, "EPSG:32632")}
    a = _record("ds:a", ProjectedPosition(easting=E, northing=N))
    b = _record("ds:b", ProjectedPosition(easting=E, northing=N))
    views = geographic_views([a, b], frames)
    assert set(views) == {id(a), id(b)}
    # Same easting/northing, different zone -> 6 degrees apart in longitude.
    assert views[id(a)][1] - views[id(b)][1] == pytest.approx(6.0, abs=0.01)


# --- partitioning follows ---

def test_declared_projected_frame_joins_the_geographic_partition():
    frame = _frame("ds:proj", CRSKind.PROJECTED, UTM33N)
    records = [_record("ds:proj", ProjectedPosition(easting=E, northing=N))]
    assert [p.kind for p in partition_by_spatial_ref(records, frames=[frame])] == ["geographic"]
    assert all(p.fusable for p in partition_by_spatial_ref(records, frames=[frame]))


def test_undeclared_projected_frame_stays_excluded_with_its_reason():
    frame = _frame("ds:proj", CRSKind.PROJECTED, None)
    records = [_record("ds:proj", ProjectedPosition(easting=E, northing=N))]
    excluded = non_fusable_partitions(records, frames=[frame])
    assert [p.kind for p in excluded] == ["projected"]
    assert "declares no CRS" in excluded[0].reason
    assert "reprojected" in excluded[0].reason      # says how to fix it


def test_without_frames_behaviour_is_exactly_as_before():
    """The frames argument is additive. Omitting it changes nothing."""
    records = [_record("ds:proj", ProjectedPosition(easting=E, northing=N))]
    assert [p.kind for p in non_fusable_partitions(records)] == ["projected"]
    assert fuse_datasets(records) == []


# --- fusion end to end ---

def test_projected_and_geographic_surveys_over_the_same_ground_fuse():
    """The capability this milestone exists for."""
    lat, lon = to_wgs84(UTM33N, [E], [N])[0]
    frames = [_frame("ds:proj", CRSKind.PROJECTED, UTM33N),
              _frame("ds:geo", CRSKind.GEOGRAPHIC, "EPSG:4326")]
    records = [
        _record("ds:proj", ProjectedPosition(easting=E, northing=N), SensorType.GPR),
        _record("ds:geo", GeographicPosition(lat=lat, lon=lon), SensorType.MAGNETOMETER),
    ]
    samples = fuse_datasets(records, radius_m=5.0, frames=frames)
    assert len(samples) == 1
    assert sorted(samples[0].sensor_types) == ["gpr", "magnetometer"]


def test_the_same_pair_does_not_fuse_without_the_frames():
    lat, lon = to_wgs84(UTM33N, [E], [N])[0]
    records = [
        _record("ds:proj", ProjectedPosition(easting=E, northing=N), SensorType.GPR),
        _record("ds:geo", GeographicPosition(lat=lat, lon=lon), SensorType.MAGNETOMETER),
    ]
    samples = fuse_datasets(records, radius_m=5.0)
    assert all(len(s.sensor_types) == 1 for s in samples)


def test_a_sample_reports_how_many_members_were_reprojected():
    """A centre computed partly from derived coordinates must not pass for measured."""
    lat, lon = to_wgs84(UTM33N, [E], [N])[0]
    frames = [_frame("ds:proj", CRSKind.PROJECTED, UTM33N),
              _frame("ds:geo", CRSKind.GEOGRAPHIC, "EPSG:4326")]
    records = [
        _record("ds:proj", ProjectedPosition(easting=E, northing=N), SensorType.GPR),
        _record("ds:geo", GeographicPosition(lat=lat, lon=lon), SensorType.MAGNETOMETER),
    ]
    sample, = fuse_datasets(records, radius_m=5.0, frames=frames)
    assert sample.n_reprojected == 1
    assert sample.has_geographic_centre


def test_an_all_geographic_sample_reports_no_reprojection():
    frames = [_frame("ds:geo", CRSKind.GEOGRAPHIC, "EPSG:4326")]
    records = [
        _record("ds:geo", GeographicPosition(lat=41.05, lon=15.0), SensorType.GPR),
        _record("ds:geo", GeographicPosition(lat=41.05, lon=15.0), SensorType.MAGNETOMETER),
    ]
    sample, = fuse_datasets(records, radius_m=5.0, frames=frames)
    assert sample.n_reprojected == 0


def test_reprojection_never_mutates_the_record():
    """Acquisition coordinates survive fusion untouched -- fusion is a reader."""
    frame = _frame("ds:proj", CRSKind.PROJECTED, UTM33N)
    r = _record("ds:proj", ProjectedPosition(easting=E, northing=N))
    fuse_datasets([r], radius_m=5.0, frames=[frame])
    assert r.position.kind == "projected"
    assert (r.position.easting, r.position.northing) == (E, N)
    assert r.registered_position is None
    assert r.latitude is None and r.longitude is None


def test_a_broken_crs_loses_only_its_own_group():
    """One bad declaration must not take the rest of the survey down with it."""
    good = _frame("ds:good", CRSKind.PROJECTED, UTM33N)
    bad = SurveyFrame.model_construct(
        frame_id="ds:bad", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy",
        spatial_ref=SpatialRef.model_construct(
            kind=CRSKind.PROJECTED, code="EPSG:999999",
            crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER, horizontal_units="m"),
        vertical_axis=_NO_VERTICAL_AXIS, assumptions=[], source_metadata={},
    )
    a = _record("ds:good", ProjectedPosition(easting=E, northing=N))
    b = _record("ds:bad", ProjectedPosition(easting=E, northing=N))
    views = geographic_views([a, b], {"ds:good": good, "ds:bad": bad})
    assert id(a) in views and id(b) not in views


# --- the store helper the API uses ---

def test_load_frames_for_tolerates_datasets_that_predate_frames():
    assert load_frames_for(["definitely-not-a-dataset"]) == []
    assert load_frames_for([]) == []
