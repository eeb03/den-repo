"""
interpretation/spatial_evidence.py: Stage A -- every individual measurement
above the anomaly-evidence threshold, exposed as its own point.

What must stay true regardless of what a dataset holds:

  * a measurement's evidence value is read verbatim from record.signal --
    never a second, independently-computed statistic
  * a measurement with no real geographic position is never placed --
    counted as excluded, never assigned (0, 0) or any other coordinate
  * depth is DERIVED only when a velocity was actually recorded, never
    silently treated as MEASURED
  * no clustering, grouping, or interpolation happens anywhere in this module
"""
from __future__ import annotations

import pytest

from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD
from interpretation.candidate_intelligence import DepthCertainty, LocalisationCertainty
from interpretation.spatial_evidence import find_spatial_evidence_samples
from schemas.spatial import (
    AxisKind, CRSKind, CRSProvenance, GeographicPosition, NoPosition, OdometryPosition,
    ProjectedPosition, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame

# Same fixture CRS/point as tests/test_cross_crs_fusion.py: UTM zone 33N,
# easting/northing near Foggia, Italy, landing at (lon=15.0, lat=41.05).
UTM33N = "EPSG:32633"
E, N = 500_000.0, 4_544_705.0

_NO_VERTICAL_AXIS = VerticalAxis(
    kind=AxisKind.NONE, units="none",
    origin="not applicable: these fixtures exercise horizontal position only",
    positive_down=True,
)


def _frame(frame_id, code=UTM33N):
    return SurveyFrame(
        frame_id=frame_id, dataset_id=frame_id.split(":")[0],
        modality=SensorType.GPR, source_format="segy",
        spatial_ref=SpatialRef(
            kind=CRSKind.PROJECTED, code=code,
            crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER if code else CRSProvenance.NONE,
            horizontal_units="m",
        ),
        vertical_axis=_NO_VERTICAL_AXIS,
    )


def _record(trace_index, depth, value, source_file="line.SGY", position=None,
            latitude=None, longitude=None, elevation=None, reliable=True,
            velocity=None, extra_metadata=None, frame_id=None):
    metadata = {
        "source_file": source_file, "trace_index": trace_index,
        "anomaly_reliable": reliable,
    }
    if velocity is not None:
        metadata["velocity_m_per_ns"] = velocity
    if extra_metadata:
        metadata.update(extra_metadata)
    kwargs = dict(
        dataset_id="ds", sensor_type=SensorType.GPR, depth=depth, signal=[value],
        elevation=elevation, metadata=metadata, frame_id=frame_id,
    )
    if position is not None:
        kwargs["position"] = position
    elif latitude is not None and longitude is not None:
        kwargs["latitude"] = latitude
        kwargs["longitude"] = longitude
    return SubterraRecord(**kwargs)


def _line(n_traces=8, n_depths=10, anomaly_traces=(3, 4), anomaly_depths=(5, 6),
          value=9.0, **record_kwargs):
    records = []
    for t in range(n_traces):
        for d in range(n_depths):
            v = value if (t in anomaly_traces and d in anomaly_depths) else 0.0
            records.append(_record(t, round(d * 0.01, 6), v, **record_kwargs))
    return records


# --- inclusion: measured -> spatial evidence sample -----------------------

def test_a_qualifying_measurement_with_real_position_becomes_a_sample():
    records = _line(latitude=52.0, longitude=6.0)
    result = find_spatial_evidence_samples(records)
    assert len(result.samples) > 0
    s = result.samples[0]
    assert s.localisation == LocalisationCertainty.SPATIALLY_REGISTERED
    assert s.lat == 52.0 and s.lon == 6.0


def test_evidence_value_is_read_verbatim_from_signal_not_recomputed():
    records = _line(latitude=52.0, longitude=6.0, value=7.25)
    result = find_spatial_evidence_samples(records)
    assert result.samples
    for s in result.samples:
        assert s.evidence_value == 7.25


def test_reliable_flag_survives_from_metadata():
    records = _line(latitude=52.0, longitude=6.0, reliable=False)
    result = find_spatial_evidence_samples(records)
    assert result.samples
    assert all(s.reliable is False for s in result.samples)


# --- depth certainty: DERIVED only with a recorded velocity ----------------

def test_depth_is_derived_when_velocity_recorded():
    records = _line(latitude=52.0, longitude=6.0, velocity=0.1)
    result = find_spatial_evidence_samples(records)
    assert result.samples
    for s in result.samples:
        assert s.depth_certainty == DepthCertainty.DERIVED
        assert "0.1" in s.depth_certainty_reason


def test_depth_is_unavailable_with_no_velocity_never_measured():
    records = _line(latitude=52.0, longitude=6.0)
    result = find_spatial_evidence_samples(records)
    assert result.samples
    for s in result.samples:
        assert s.depth_certainty == DepthCertainty.UNAVAILABLE
        assert s.depth_certainty != DepthCertainty.MEASURED


# --- position honesty: never fabricate X/Y ---------------------------------

def test_missing_position_is_excluded_and_counted_not_placed():
    records = _line(position=NoPosition(reason="no coordinates supplied"))
    result = find_spatial_evidence_samples(records)
    assert result.samples == []
    assert result.excluded_unpositioned_count > 0
    assert result.n_above_threshold == result.excluded_unpositioned_count


def test_odometry_only_position_is_frame_relative_and_excluded():
    """Along-track distance is a real answer -- and not a coordinate this field can plot."""
    records = _line(position=OdometryPosition(along_track_m=12.5))
    result = find_spatial_evidence_samples(records)
    assert result.samples == []
    assert result.excluded_unpositioned_count > 0


def test_legacy_zero_zero_placeholder_is_not_treated_as_real_position():
    records = _line(latitude=0.0, longitude=0.0)
    result = find_spatial_evidence_samples(records)
    # SubterraRecord's own model_validator maps exact (0,0) to NoPosition.
    assert result.samples == []
    assert result.excluded_unpositioned_count > 0


# --- sparsity: no interpolation, no padding --------------------------------

def test_sparse_evidence_stays_sparse():
    """Only cells that actually exceed threshold appear -- neighbours do not."""
    records = _line(n_traces=8, n_depths=10, anomaly_traces=(3,), anomaly_depths=(5,),
                    latitude=52.0, longitude=6.0)
    result = find_spatial_evidence_samples(records)
    # Exactly the one injected anomalous cell, nothing interpolated around it.
    assert len(result.samples) == 1
    assert result.samples[0].trace_index == 3
    assert result.samples[0].depth_m == 0.05


def test_values_at_or_below_threshold_are_never_included():
    records = _line(anomaly_traces=(), latitude=52.0, longitude=6.0)  # nothing exceeds threshold
    result = find_spatial_evidence_samples(records)
    assert result.samples == []
    assert result.n_above_threshold == 0
    assert "no measurement exceeded" in result.reason_if_empty


# --- empty-state honesty: distinguish WHY it's empty -----------------------

def test_no_anomaly_preprocessing_reports_that_reason():
    records = [
        SubterraRecord(dataset_id="ds", sensor_type=SensorType.GPR, depth=0.1, signal=[9.0],
                       latitude=52.0, longitude=6.0,
                       metadata={"source_file": "line.SGY", "trace_index": 0})
        # no anomaly_reliable -- preprocessing never ran
    ]
    result = find_spatial_evidence_samples(records)
    assert result.samples == []
    assert "gpr_local_anomaly" in result.reason_if_empty


def test_no_trace_addressable_data_reports_that_reason():
    """A depth-slice CSV (no trace_index at all) is a structurally different modality, not a gap."""
    records = [
        SubterraRecord(dataset_id="ds", sensor_type=SensorType.GPR, depth=0.1, signal=[9.0],
                       latitude=52.0, longitude=6.0, metadata={})
    ]
    result = find_spatial_evidence_samples(records)
    assert result.samples == []
    assert "no genuine multi-sample GPR trace data" in result.reason_if_empty


def test_above_threshold_but_all_unpositioned_reports_that_reason():
    records = _line(position=NoPosition(reason="none"))
    result = find_spatial_evidence_samples(records)
    assert result.samples == []
    assert "usable geographic position" in result.reason_if_empty


# --- no cross-line mixing: same rule as candidate generation ----------------

def test_two_lines_are_each_considered_independently():
    line_a = _line(source_file="a.SGY", latitude=52.0, longitude=6.0, velocity=0.1)
    line_b = _line(source_file="b.SGY", latitude=53.0, longitude=7.0)  # no anomaly preprocessing
    for r in line_b:
        del r.metadata["anomaly_reliable"]
    result = find_spatial_evidence_samples(line_a + line_b)
    assert result.samples
    assert all(s.source_file == "a.SGY" for s in result.samples)


# --- serialization ----------------------------------------------------------

def test_result_round_trips_through_json():
    records = _line(latitude=52.0, longitude=6.0)
    result = find_spatial_evidence_samples(records)
    dumped = result.model_dump(mode="json")
    assert dumped["threshold"] == DEFAULT_ANOMALY_THRESHOLD
    assert len(dumped["samples"]) == len(result.samples)


# --- Stage A.1: reprojected (PROJECTED + declared CRS) positions -----------

def test_projected_position_with_declared_crs_becomes_a_sample():
    """The exact new capability: no native geographic position, but the
    frame declares a transformable CRS, so `geographic_views` supplies one."""
    frame_id = "ds:line"
    frames = {frame_id: _frame(frame_id)}
    records = _line(position=ProjectedPosition(easting=E, northing=N), frame_id=frame_id)
    result = find_spatial_evidence_samples(records, frames=frames)
    assert result.samples
    s = result.samples[0]
    assert s.localisation == LocalisationCertainty.SPATIALLY_REGISTERED
    assert s.lon == pytest.approx(15.0, abs=1e-6)
    assert s.lat == pytest.approx(41.05, abs=0.05)


def test_reprojected_sample_reason_names_the_transform_not_a_measurement():
    """The scientific rule under test: a transform is not the same claim as
    a native geographic position, and the two must not read identically."""
    frame_id = "ds:line"
    frames = {frame_id: _frame(frame_id)}
    records = _line(position=ProjectedPosition(easting=E, northing=N), frame_id=frame_id)
    result = find_spatial_evidence_samples(records, frames=frames)
    assert result.samples
    reason = result.samples[0].localisation_reason
    assert "transform" in reason
    assert "not an independently verified geodetic position" in reason
    # And the native-position path's own reason is a strictly different claim.
    native = _line(latitude=52.0, longitude=6.0)
    native_result = find_spatial_evidence_samples(native)
    assert native_result.samples[0].localisation_reason != reason


def test_projected_position_without_frames_argument_stays_excluded():
    """Backward compatibility: omitting `frames` must behave exactly as
    before Stage A.1 -- a PROJECTED position never becomes evidence."""
    records = _line(position=ProjectedPosition(easting=E, northing=N))
    result = find_spatial_evidence_samples(records)
    assert result.samples == []
    assert result.excluded_unpositioned_count > 0


def test_projected_position_with_no_declared_crs_stays_excluded():
    """A frame present but with no declared CRS is not transformable at any
    effort -- this must not be treated as a guessable case."""
    frame_id = "ds:line"
    frames = {frame_id: _frame(frame_id, code=None)}
    records = _line(position=ProjectedPosition(easting=E, northing=N), frame_id=frame_id)
    result = find_spatial_evidence_samples(records, frames=frames)
    assert result.samples == []
    assert result.excluded_unpositioned_count > 0


def test_reprojection_never_mutates_the_records_own_position_or_coordinates():
    """Raw coordinates must remain recoverable: the transform is read-only."""
    frame_id = "ds:line"
    frames = {frame_id: _frame(frame_id)}
    records = _line(position=ProjectedPosition(easting=E, northing=N), frame_id=frame_id)
    find_spatial_evidence_samples(records, frames=frames)
    for r in records:
        assert r.position.kind == "projected"
        assert r.position.easting == E and r.position.northing == N
        assert r.latitude is None and r.longitude is None


def test_has_geographic_coordinates_is_unaffected_by_reprojection():
    """`schemas.spatial.has_geographic_coordinates` is used across the whole
    codebase (report, 3D viewer, lateral extent); Stage A.1 must not make it
    lie about a record whose own position is still PROJECTED."""
    from schemas.spatial import has_geographic_coordinates

    frame_id = "ds:line"
    frames = {frame_id: _frame(frame_id)}
    records = _line(position=ProjectedPosition(easting=E, northing=N), frame_id=frame_id)
    find_spatial_evidence_samples(records, frames=frames)
    assert all(has_geographic_coordinates(r) is False for r in records)
