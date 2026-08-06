"""
Tests for the explicit spatial representation (schemas/spatial.py) and its
integration into SubterraRecord.

The property under test throughout: a record can never be in a state where
"no position" is indistinguishable from "someone forgot to set a position".
"""
import pytest
from pydantic import ValidationError

from schemas.spatial import (
    Assumption, AxisKind, CRSKind, GeographicPosition, LocalCartesianPosition,
    NoPosition, OdometryPosition, PositionKind, ProjectedPosition, SpatialRef,
    VerticalAxis, assert_position_matches_ref,
)
from schemas.subterra_record import LEGACY_PLACEHOLDER_REASON, SensorType, SubterraRecord


def _rec(**kw):
    base = dict(dataset_id="d", sensor_type=SensorType.GPR)
    base.update(kw)
    return SubterraRecord(**base)


# --- the five kinds are genuinely distinct ---

def test_all_five_position_kinds_are_representable_and_distinct():
    positions = [
        GeographicPosition(lat=41.0, lon=15.0),
        ProjectedPosition(easting=501134.03, northing=4544705.58),
        LocalCartesianPosition(x=12.5, y=0.0),
        OdometryPosition(along_track_m=12.47),
        NoPosition(reason="instrument provides no horizontal position"),
    ]
    kinds = [p.kind for p in positions]
    assert kinds == [
        PositionKind.GEOGRAPHIC, PositionKind.PROJECTED, PositionKind.LOCAL_CARTESIAN,
        PositionKind.ODOMETRY, PositionKind.NONE,
    ]
    assert len(set(kinds)) == 5


def test_no_position_requires_a_reason():
    """The whole point of NoPosition is that it records WHY."""
    with pytest.raises(ValidationError):
        NoPosition()
    with pytest.raises(ValidationError):
        NoPosition(reason="")


def test_projected_position_accepts_utm_magnitudes():
    """
    A UTM northing must not be range-checked as if it were a latitude.
    This is exactly what breaks LASConverter today.
    """
    p = ProjectedPosition(easting=500000.0, northing=4500000.0)
    assert (p.easting, p.northing) == (500000.0, 4500000.0)
    with pytest.raises(ValidationError):
        GeographicPosition(lat=4500000.0, lon=500000.0)


def test_odometry_position_defaults_to_on_track():
    p = OdometryPosition(along_track_m=3.25)
    assert p.cross_track_m == 0.0 and p.path_id is None


# --- discriminated union round-trips through serialization ---

@pytest.mark.parametrize("position", [
    GeographicPosition(lat=41.0, lon=15.0),
    ProjectedPosition(easting=501134.03, northing=4544705.58),
    LocalCartesianPosition(x=1.0, y=2.0),
    OdometryPosition(along_track_m=9.0, cross_track_m=0.5, path_id="run3"),
    NoPosition(reason="no GNSS on this cart"),
])
def test_position_survives_a_json_round_trip(position):
    """Records are persisted as JSONL, so the discriminator must survive it."""
    r = _rec(latitude=1.0, longitude=2.0, position=position)
    restored = SubterraRecord.model_validate_json(r.model_dump_json())
    assert restored.position == position
    assert restored.position.kind == position.kind


# --- legacy derivation: adding a required field breaks nothing ---

def test_position_is_derived_from_legacy_coordinates():
    """Existing callers that pass only lat/lon still construct successfully."""
    r = _rec(latitude=41.0, longitude=15.0)
    assert r.position.kind == PositionKind.GEOGRAPHIC
    assert (r.position.lat, r.position.lon) == (41.0, 15.0)


def test_legacy_zero_zero_becomes_no_position_not_null_island():
    """
    The placeholder SEGYConverter wrote for every un-georeferenced trace must
    not load as a real position in the Gulf of Guinea.
    """
    r = _rec(latitude=0.0, longitude=0.0)
    assert r.position.kind == PositionKind.NONE
    assert r.position.reason == LEGACY_PLACEHOLDER_REASON


def test_explicit_position_overrides_legacy_derivation():
    """A converter that knows better is never second-guessed by the heuristic."""
    r = _rec(latitude=0.0, longitude=0.0,
             position=ProjectedPosition(easting=501134.03, northing=4544705.58))
    assert r.position.kind == PositionKind.PROJECTED
    assert r.position.easting == 501134.03
    assert (r.latitude, r.longitude) == (0.0, 0.0)  # explicit values are honoured as given


def test_stored_records_without_position_still_load():
    """Backward compatibility with JSONL written before M1."""
    legacy = ('{"dataset_id":"d","sensor_type":"gpr","latitude":41.0,"longitude":15.0,'
              '"elevation":null,"timestamp":null,"depth":1.0,"signal":[1.0],'
              '"metadata":{},"ground_truth":"none","confidence":null}')
    r = SubterraRecord.model_validate_json(legacy)
    assert r.position.kind == PositionKind.GEOGRAPHIC
    assert r.depth == 1.0 and r.signal == [1.0]


def test_frame_id_defaults_to_none():
    assert _rec(latitude=1.0, longitude=2.0).frame_id is None


# --- frame-level reference types ---

def test_epsg_code_rejected_for_non_earth_referenced_frames():
    """An odometry frame has no EPSG identity; claiming one is a category error."""
    for kind in (CRSKind.ENGINEERING, CRSKind.ACQUISITION, CRSKind.UNKNOWN):
        with pytest.raises(ValidationError):
            SpatialRef(kind=kind, code="EPSG:4326")
    SpatialRef(kind=CRSKind.ACQUISITION, name="wheel odometry, origin at run start")


def test_projected_ref_may_omit_its_code():
    """SEG-Y gives easting/northing without ever declaring the projection."""
    ref = SpatialRef(kind=CRSKind.PROJECTED, code=None, name="undeclared")
    assert ref.kind == CRSKind.PROJECTED and ref.code is None


def test_position_kind_must_agree_with_frame_crs_kind():
    ref = SpatialRef(kind=CRSKind.PROJECTED)
    assert_position_matches_ref(ProjectedPosition(easting=1.0, northing=2.0), ref)
    with pytest.raises(ValueError, match="contradicts frame"):
        assert_position_matches_ref(GeographicPosition(lat=1.0, lon=2.0), ref)


def test_vertical_axis_records_how_depth_was_derived():
    """An assumed velocity conversion must be visible in the data, not just a docstring."""
    axis = VerticalAxis(
        kind=AxisKind.TWO_WAY_TIME_NS, units="ns", origin="instrument time-zero",
        positive_down=True, n_samples=482, sample_interval=0.293,
        conversion={"method": "constant_velocity", "velocity_m_per_ns": 0.1},
    )
    assert axis.conversion["velocity_m_per_ns"] == 0.1
    assert VerticalAxis(kind=AxisKind.NONE, units="", origin="n/a",
                        positive_down=True).conversion is None


def test_assumption_defaults_to_unverified():
    a = Assumption(key="gpr_velocity", value=0.1, basis="assumed default")
    assert a.verified is False
