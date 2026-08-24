"""
AffineTie: the 2D counterpart of GeoTie, for a frame whose native position
is a genuine local (x, y) rather than a single along-track scalar.

An engineering (LOCAL_CARTESIAN) frame knows its own local coordinate and
nothing about where that frame sits on Earth. An affine tie is somebody
ASSERTING the correspondence between local (x, y) and real (lat, lon), with
their name on it -- and the positions that result are DERIVED from an
assertion, never observed by an instrument. These tests pin that the
distinction survives, that a tie cannot be built from degenerate geometry,
and that GeoTie's own behaviour is completely unaffected.

FIXTURE ONLY: no real dataset currently held by Subterra ever produces a
LocalCartesianPosition record (confirmed by inspection -- no converter
constructs one). The control points below are a mathematical fixture for
unit testing, clearly synthetic, and never touch the real evidence pipeline.
"""
import math

import numpy as np
import pytest

from ingestion.affine_tie import (
    AffineTieError, apply_affine_tie, affine_tie_assumption, build_affine_tie,
    fit_affine, invert_affine, tied_spatial_ref_for_affine,
)
from schemas.spatial import (
    AffineControlPoint, AffineTie, AffineTieStatus, LocalCartesianPosition, NoPosition,
    OdometryPosition, PositionKind, effective_position, has_geographic_coordinates,
    position_provenance, POSITION_NATIVE, POSITION_REGISTERED,
)
from schemas.subterra_record import SensorType, SubterraRecord

# A known exact affine map: lat = 41.0 + 0.001*x ; lon = 15.0 + 0.001*y.
# 0.001 deg is ~111 m at the equator -- these points span ~100 m, a
# plausible engineering-frame scale.
def _true(x, y):
    return 41.0 + 0.001 * x, 15.0 + 0.001 * y


P0 = AffineControlPoint(x=0.0, y=0.0, lat=_true(0, 0)[0], lon=_true(0, 0)[1], label="origin")
P1 = AffineControlPoint(x=100.0, y=0.0, lat=_true(100, 0)[0], lon=_true(100, 0)[1])
P2 = AffineControlPoint(x=0.0, y=100.0, lat=_true(0, 100)[0], lon=_true(0, 100)[1])
P3 = AffineControlPoint(x=100.0, y=100.0, lat=_true(100, 100)[0], lon=_true(100, 100)[1])
THREE = [P0, P1, P2]
FOUR = [P0, P1, P2, P3]


def _local_records(n_x=5, n_y=1, frame_id="ds:frame", spacing=10.0):
    records = []
    i = 0
    for xi in range(n_x):
        for yi in range(n_y):
            records.append(SubterraRecord(
                dataset_id="ds", sensor_type=SensorType.GPR,
                position=LocalCartesianPosition(x=xi * spacing, y=yi * spacing),
                frame_id=frame_id, signal=[1.0], depth=0.5,
                metadata={"source_file": "line.dt", "trace_index": i, "sample_index": 0},
            ))
            i += 1
    return records


# --- Phase 6.1/6.2: exact and overdetermined fits ------------------------

def test_exact_three_point_fit_recovers_the_known_map():
    (a, b, e, c, d, f), quality = fit_affine(THREE)
    assert a == pytest.approx(0.001, abs=1e-9)
    assert b == pytest.approx(0.0, abs=1e-9)
    assert e == pytest.approx(41.0, abs=1e-6)
    assert c == pytest.approx(0.0, abs=1e-9)
    assert d == pytest.approx(0.001, abs=1e-9)
    assert f == pytest.approx(15.0, abs=1e-6)
    assert quality.checkable is False
    assert quality.rms_residual_m is None
    assert quality.max_residual_m is None


def test_overdetermined_four_point_fit_is_checkable():
    (a, b, e, c, d, f), quality = fit_affine(FOUR)
    # The fourth point lies exactly on the same true map, so the fit is
    # still (near) exact, but now CHECKABLE -- quality is measured, not
    # assumed absent.
    assert quality.checkable is True
    assert quality.n_control_points == 4
    assert quality.rms_residual_m == pytest.approx(0.0, abs=1e-3)


def test_known_noisy_control_points_report_a_real_residual():
    noisy_lat, noisy_lon = _true(100, 100)
    noisy = AffineControlPoint(x=100.0, y=100.0, lat=noisy_lat + 0.0005, lon=noisy_lon)
    tie = build_affine_tie(THREE + [noisy], supplied_by="test rig")
    assert tie.rms_residual_m is not None
    assert tie.rms_residual_m > 1.0  # 0.0005 deg lat is ~55 m of injected error
    assert tie.max_residual_m >= tie.rms_residual_m


# --- Phase 6.4/6.5/6.6/6.7: degenerate configurations are rejected --------

def test_collinear_control_points_are_rejected():
    collinear = [
        AffineControlPoint(x=0.0, y=0.0, lat=41.0, lon=15.0),
        AffineControlPoint(x=10.0, y=0.0, lat=41.001, lon=15.0),
        AffineControlPoint(x=20.0, y=0.0, lat=41.002, lon=15.0),
    ]
    with pytest.raises(AffineTieError, match="collinear"):
        fit_affine(collinear)


def test_nearly_collinear_control_points_are_rejected_as_numerically_unstable():
    barely_off = [
        AffineControlPoint(x=0.0, y=0.0, lat=41.0, lon=15.0),
        AffineControlPoint(x=1_000_000.0, y=0.0, lat=41.001, lon=15.0),
        AffineControlPoint(x=500_000.0, y=1e-6, lat=41.0005, lon=15.0),
    ]
    with pytest.raises(AffineTieError, match="numerically unstable|collinear"):
        fit_affine(barely_off)


def test_duplicate_source_points_are_rejected():
    with pytest.raises(ValueError, match="distinct \\(x, y\\)"):
        AffineTie(
            control_points=[P0, P1, AffineControlPoint(x=0.0, y=0.0, lat=52.0, lon=4.0)],
            supplied_by="s", a=0, b=0, e=0, c=0, d=0, f=0,
        )


def test_insufficient_control_points_are_rejected_by_the_model():
    with pytest.raises(ValueError, match="at least three control points"):
        AffineTie(control_points=[P0, P1], supplied_by="s", a=0, b=0, e=0, c=0, d=0, f=0)


def test_insufficient_control_points_are_rejected_by_the_fitter():
    with pytest.raises(AffineTieError, match="at least three control points"):
        fit_affine([P0, P1])


def test_non_finite_coordinates_are_rejected():
    bad = [P0, P1, AffineControlPoint(x=float("nan"), y=0.0, lat=41.0, lon=15.0)]
    with pytest.raises(AffineTieError, match="non-finite"):
        fit_affine(bad)


# --- status / verification --------------------------------------------

def test_exact_three_point_tie_is_usable_but_never_verified():
    tie = build_affine_tie(THREE, supplied_by="test rig", max_rms_residual_m=1.0)
    assert tie.verified is False
    assert tie.status == AffineTieStatus.REGISTERED
    assert tie.rms_residual_m is None


def test_high_residual_is_reported_and_not_verified():
    noisy_lat, noisy_lon = _true(100, 100)
    noisy = AffineControlPoint(x=100.0, y=100.0, lat=noisy_lat + 0.01, lon=noisy_lon)  # ~1100 m off
    tie = build_affine_tie(THREE + [noisy], supplied_by="test rig", max_rms_residual_m=5.0)
    assert tie.verified is False
    assert tie.status == AffineTieStatus.REGISTERED_WITH_HIGH_RESIDUAL
    assert tie.rms_residual_m > 5.0


def test_low_residual_within_tolerance_is_verified():
    tie = build_affine_tie(FOUR, supplied_by="test rig", max_rms_residual_m=1.0)
    assert tie.verified is True
    assert tie.status == AffineTieStatus.REGISTERED


# --- reversibility -------------------------------------------------------

def test_the_transform_is_reversible():
    tie = build_affine_tie(THREE, supplied_by="test rig")
    ia, ib, ie, ic, id_, if_ = invert_affine(tie)
    lat, lon = 41.0234, 15.0456
    x = ia * lat + ib * lon + ie
    y = ic * lat + id_ * lon + if_
    back_lat = tie.a * x + tie.b * y + tie.e
    back_lon = tie.c * x + tie.d * y + tie.f
    assert back_lat == pytest.approx(lat, abs=1e-9)
    assert back_lon == pytest.approx(lon, abs=1e-9)


def test_singular_tie_cannot_be_inverted():
    # A hand-constructed degenerate linear part (rank-deficient), bypassing
    # the fitter -- invert_affine must still refuse it.
    degenerate = AffineTie(control_points=THREE, supplied_by="s",
                           a=1.0, b=2.0, e=0.0, c=2.0, d=4.0, f=0.0)
    with pytest.raises(AffineTieError, match="singular"):
        invert_affine(degenerate)


# --- applying a tie to records: additive, never destructive ---------------

def test_applying_a_tie_registers_local_cartesian_records():
    tie = build_affine_tie(THREE, supplied_by="test rig")
    records = _local_records(n_x=5, n_y=1)
    n = apply_affine_tie(records, tie)
    assert n == 5
    for r in records:
        assert r.registered_position is not None
        assert r.registered_position.kind == "geographic"
        expected_lat, expected_lon = _true(r.position.x, r.position.y)
        assert r.registered_position.lat == pytest.approx(expected_lat, abs=1e-6)
        assert r.registered_position.lon == pytest.approx(expected_lon, abs=1e-6)


def test_native_position_is_never_modified():
    """Registration, not estimation: the sensor-native coordinate survives."""
    tie = build_affine_tie(THREE, supplied_by="test rig")
    records = _local_records(n_x=3, n_y=1)
    originals = [(r.position.x, r.position.y) for r in records]
    apply_affine_tie(records, tie)
    for r, (ox, oy) in zip(records, originals):
        assert r.position.kind == "local_cartesian"
        assert r.position.x == ox and r.position.y == oy


def test_provenance_distinguishes_registered_from_native():
    tie = build_affine_tie(THREE, supplied_by="test rig")
    records = _local_records(n_x=2, n_y=1)
    apply_affine_tie(records, tie)
    for r in records:
        assert position_provenance(r) == POSITION_REGISTERED
        assert has_geographic_coordinates(r) is True
        assert effective_position(r).kind == "geographic"
    unregistered = _local_records(n_x=1, n_y=1)
    assert position_provenance(unregistered[0]) == POSITION_NATIVE
    assert has_geographic_coordinates(unregistered[0]) is False


def test_applying_a_tie_with_no_local_cartesian_records_is_refused():
    tie = build_affine_tie(THREE, supplied_by="test rig")
    odometry = [SubterraRecord(
        dataset_id="ds", sensor_type=SensorType.GPR,
        position=OdometryPosition(along_track_m=1.0), frame_id="ds:frame",
        signal=[1.0], depth=0.5, metadata={},
    )]
    with pytest.raises(AffineTieError, match="no record carries a local-cartesian position"):
        apply_affine_tie(odometry, tie)


def test_a_tie_scoped_to_one_frame_refuses_a_mixed_multi_frame_input():
    tie = build_affine_tie(THREE, supplied_by="test rig")  # no applies_to
    mixed = _local_records(n_x=2, n_y=1, frame_id="ds:a") + \
        _local_records(n_x=2, n_y=1, frame_id="ds:b")
    with pytest.raises(AffineTieError, match="span 2 frame"):
        apply_affine_tie(mixed, tie)


def test_applies_to_selects_the_named_frame_from_a_mixed_input():
    tie = build_affine_tie(THREE, supplied_by="test rig", applies_to="ds:a")
    mixed = _local_records(n_x=2, n_y=1, frame_id="ds:a") + \
        _local_records(n_x=2, n_y=1, frame_id="ds:b")
    n = apply_affine_tie(mixed, tie)
    assert n == 2
    assert all(r.registered_position is not None for r in mixed if r.frame_id == "ds:a")
    assert all(r.registered_position is None for r in mixed if r.frame_id == "ds:b")


# --- assumption / spatial-ref surfacing -----------------------------------

def test_tie_assumption_names_the_residual_and_status():
    tie = build_affine_tie(FOUR, supplied_by="site survey", max_rms_residual_m=10.0)
    a = affine_tie_assumption(tie)
    assert a.key == "affine_tie"
    assert a.verified == tie.verified
    assert "DERIVED" in a.basis
    assert "not observed by an instrument" in a.basis


def test_exact_tie_assumption_says_not_measurable():
    tie = build_affine_tie(THREE, supplied_by="site survey")
    a = affine_tie_assumption(tie)
    assert "not measurable with three control points" in a.basis


def test_tied_spatial_ref_is_geographic_and_supplied_by_caller():
    from schemas.spatial import CRSProvenance

    tie = build_affine_tie(THREE, supplied_by="site survey")
    ref = tied_spatial_ref_for_affine(tie)
    assert ref.kind == "geographic"
    assert ref.code == "EPSG:4326"
    assert ref.crs_provenance == CRSProvenance.SUPPLIED_BY_CALLER


# --- GeoTie must be completely unaffected ---------------------------------

def test_geo_tie_behaviour_is_unchanged():
    from ingestion.geo_tie import build_geo_tie
    from schemas.spatial import ControlPoint

    tie = build_geo_tie(
        [ControlPoint(along_track_m=0.0, lat=41.0, lon=15.0),
         ControlPoint(along_track_m=100.0, lat=41.001, lon=15.0)],
        supplied_by="site survey",
    )
    assert tie.rms_residual_m is None  # two points: still not checkable, as always
    assert tie.verified is False
