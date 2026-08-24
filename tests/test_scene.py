"""
The reconstructed-scene payload: `schemas.scene` and `api.scene`.

What must stay true regardless of what a dataset holds:

  * a scene is never resolved unless `fusion.vertical_reference.assess`
    itself says ABSOLUTE_ELEVATION -- this module adds no second gate
  * a candidate with no geographic position is reported unavailable, never
    placed at (0, 0)
  * an elevation is only ever DERIVED (surface minus depth, adjusted by a
    declared offset when one relates the depth axis) -- never a second,
    unaccountable number
  * `validation_status` says "not independently validated" on every
    payload this module produces, resolved or not
"""
from __future__ import annotations

import pytest

from api import candidates as candidate_service
from database.records_store import clear_records_cache, save_records
from database.frames_store import save_frames
from schemas.spatial import (
    AxisKind, CRSKind, CRSProvenance, GeographicPosition, OffsetEvidence, OriginReference,
    SpatialRef, VerticalAxis, VerticalDatum, VerticalRelationshipKind,
)
from schemas.scene import compute_absolute_elevation
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame

NAP = VerticalDatum(code="NAP", provenance=CRSProvenance.SUPPLIED_BY_CALLER, name="test")


def _axis(kind, origin, datum=None, offset=None):
    return VerticalAxis(kind=kind, units="m", origin=origin, positive_down=True,
                        vertical_datum=datum, origin_offset=offset)


def _frame(dataset_id, fid, axis, modality=SensorType.GPR):
    return SurveyFrame(
        frame_id=fid, dataset_id=dataset_id, modality=modality, source_format="x",
        spatial_ref=SpatialRef(kind=CRSKind.GEOGRAPHIC), vertical_axis=axis)


def _offset(offset_m, measured_from=OriginReference.DEPTH_AXIS_ORIGIN):
    from schemas.spatial import DepthOriginOffset
    return DepthOriginOffset(offset_m=offset_m, measured_from=measured_from,
                             evidence=OffsetEvidence.USER_DECLARATION, supplied_by="test")


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    from configs import settings as settings_mod
    monkeypatch.setattr(type(settings_mod.settings), "processed_dir",
                        property(lambda self: tmp_path))
    clear_records_cache()
    yield tmp_path
    clear_records_cache()


@pytest.fixture
def no_declarations(monkeypatch):
    monkeypatch.setattr(candidate_service, "_newest_declaration_at",
                        lambda db, dataset_id: None)


# --- compute_absolute_elevation: pure arithmetic, no declaration involved ---

def test_no_offset_is_surface_minus_depth():
    assert compute_absolute_elevation(100.0, 2.0, None) == 98.0


def test_a_relating_offset_shifts_the_result():
    off = _offset(0.45)
    # ground sits at +0.45 on the axis, so depth 2.0 is 1.55 below ground
    assert compute_absolute_elevation(100.0, 2.0, off) == pytest.approx(98.45)


def test_a_non_relating_offset_is_ignored():
    """A phase-centre/housing offset answers a different question and must not silently apply."""
    off = _offset(0.45, measured_from=OriginReference.SENSOR_PHASE_CENTRE)
    assert compute_absolute_elevation(100.0, 2.0, off) == 98.0


# --- build_scene: the gate is assess(), not a second opinion ---

def test_no_subsurface_or_surface_frame_is_unresolved(isolated_store):
    from api.scene import build_scene
    save_frames("ds-empty", [])
    payload = build_scene(db=None, dataset_id="ds-empty")
    assert payload.resolved is False
    assert payload.surface is None
    assert payload.candidates == []
    assert "independently validated" in payload.validation_status


def test_frames_present_but_datum_undeclared_is_unresolved(isolated_store):
    from api.scene import build_scene
    sub = _frame("ds1", "ds1:line", _axis(AxisKind.DEPTH_M, "instrument time zero"))
    sur = _frame("ds1", "ds1:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds1", [sub, sur])
    payload = build_scene(db=None, dataset_id="ds1")
    assert payload.resolved is False
    assert payload.vertical_relationship is not None
    assert payload.vertical_relationship.kind != VerticalRelationshipKind.ABSOLUTE_ELEVATION
    assert payload.missing  # something actionable is named
    assert payload.surface is None


def test_a_fully_declared_pair_resolves_with_no_candidates(isolated_store, no_declarations):
    """Resolved does not require candidates to exist -- zero is a real, meaningful answer."""
    from api.scene import build_scene

    sub = _frame("ds2", "ds2:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds2", "ds2:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds2", [sub, sur])
    save_records("ds2", [])

    payload = build_scene(db=None, dataset_id="ds2")
    assert payload.resolved is True
    assert payload.vertical_relationship.kind == VerticalRelationshipKind.ABSOLUTE_ELEVATION
    assert payload.candidates == []
    assert payload.surface is not None
    assert payload.surface.point_count_total == 0
    assert "independently validated" in payload.validation_status


def _anomaly_records(dataset_id, source_file, with_elevation):
    """One 8x40 GPR line with a real anomaly block, matching the pattern
    already established in tests/test_anomaly_candidates.py."""
    records = []
    for t in range(8):
        for d in range(40):
            value = 9.0 if (3 <= t <= 5 and 18 <= d <= 20) else 0.0
            records.append(SubterraRecord(
                dataset_id=dataset_id, sensor_type=SensorType.GPR,
                latitude=52.0, longitude=6.0,
                position=GeographicPosition(lat=52.0, lon=6.0),
                elevation=250.0 if with_elevation else None,
                depth=round(d * 0.01, 6), signal=[value],
                metadata={"source_file": source_file, "trace_index": t,
                         "sample_index": d, "anomaly_reliable": True},
            ))
    return records


def test_a_resolved_scene_places_a_candidate_with_a_derived_elevation(isolated_store, no_declarations):
    from api.scene import build_scene

    sub = _frame("ds3", "ds3:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds3", "ds3:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds3", [sub, sur])
    save_records("ds3", _anomaly_records("ds3", "line.SGY", with_elevation=True))
    candidate_service.generate(db=None, dataset_id="ds3")

    payload = build_scene(db=None, dataset_id="ds3")
    assert payload.resolved is True
    assert len(payload.candidates) >= 1
    c = payload.candidates[0]
    assert c.position.available is True
    assert c.position.lat == pytest.approx(52.0)
    assert c.elevation.available is True
    # depth midpoint of the candidate's spanned rows, surface 250.0 minus that depth
    expected = compute_absolute_elevation(250.0, c.elevation.depth_m, None)
    assert c.elevation.elevation_m == pytest.approx(expected)
    assert "derived" in c.elevation.provenance


def test_a_candidate_without_dem_alignment_reports_elevation_unavailable(isolated_store, no_declarations):
    """No .elevation on the records means no surface elevation to subtract from -- not a guess."""
    from api.scene import build_scene

    sub = _frame("ds4", "ds4:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds4", "ds4:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds4", [sub, sur])
    save_records("ds4", _anomaly_records("ds4", "line.SGY", with_elevation=False))
    candidate_service.generate(db=None, dataset_id="ds4")

    payload = build_scene(db=None, dataset_id="ds4")
    assert payload.resolved is True
    assert len(payload.candidates) >= 1
    c = payload.candidates[0]
    assert c.elevation.available is False
    assert c.elevation.elevation_m is None
    assert "never aligned with a DEM" in c.elevation.reason


def test_a_candidate_with_no_position_is_reported_unavailable_not_fabricated(isolated_store, no_declarations):
    """Mirrors tests/test_anomaly_candidates.py::test_unpositioned_lines_still_report_no_extent."""
    from api.scene import build_scene

    sub = _frame("ds5", "ds5:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds5", "ds5:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds5", [sub, sur])
    records = []
    for t in range(8):
        for d in range(40):
            value = 9.0 if (3 <= t <= 5 and 18 <= d <= 20) else 0.0
            records.append(SubterraRecord(
                dataset_id="ds5", sensor_type=SensorType.GPR,
                depth=round(d * 0.01, 6), signal=[value],
                metadata={"source_file": "line.SGY", "trace_index": t,
                         "sample_index": d, "anomaly_reliable": True},
            ))
    save_records("ds5", records)
    candidate_service.generate(db=None, dataset_id="ds5")

    payload = build_scene(db=None, dataset_id="ds5")
    assert len(payload.candidates) >= 1
    c = payload.candidates[0]
    assert c.position.available is False
    assert c.position.lat is None and c.position.lon is None
    assert "no geographic position" in c.position.reason


def test_surface_points_are_bounded_and_flagged_when_downsampled(isolated_store, no_declarations, monkeypatch):
    from api import scene as scene_mod
    monkeypatch.setattr(scene_mod, "MAX_SURFACE_POINTS", 5)

    sub = _frame("ds6", "ds6:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds6", "ds6:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds6", [sub, sur])
    records = [
        SubterraRecord(dataset_id="ds6", sensor_type=SensorType.DEM,
                       latitude=52.0 + i * 0.001, longitude=6.0, elevation=100.0 + i,
                       position=GeographicPosition(lat=52.0 + i * 0.001, lon=6.0))
        for i in range(20)
    ]
    save_records("ds6", records)

    payload = scene_mod.build_scene(db=None, dataset_id="ds6")
    assert payload.resolved is True
    assert payload.surface.point_count_total == 20
    assert len(payload.surface.points) == 5
    assert payload.surface.downsampled is True


def test_cross_dataset_surface_via_surface_dataset_id(isolated_store, no_declarations):
    """The GPR + DEM shape this platform actually ingests: two datasets, not one."""
    from api.scene import build_scene

    sub = _frame("ds7-gpr", "ds7-gpr:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds7-dem", "ds7-dem:tile", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds7-gpr", [sub])
    save_frames("ds7-dem", [sur])
    save_records("ds7-gpr", [])
    save_records("ds7-dem", [
        SubterraRecord(dataset_id="ds7-dem", sensor_type=SensorType.DEM,
                       latitude=52.0, longitude=6.0, elevation=123.0,
                       position=GeographicPosition(lat=52.0, lon=6.0)),
    ])

    payload = build_scene(db=None, dataset_id="ds7-gpr", surface_dataset_id="ds7-dem")
    assert payload.resolved is True
    assert payload.surface.dataset_id == "ds7-dem"
    assert payload.surface.point_count_total == 1


def _evidence_records(dataset_id, source_file, with_elevation, with_velocity, latitude=52.0, longitude=6.0):
    """One 8x40 GPR line with a real anomaly block, same shape as
    _anomaly_records but exposing per-record position/velocity control for
    Stage A evidence tests."""
    records = []
    for t in range(8):
        for d in range(40):
            value = 9.0 if (3 <= t <= 5 and 18 <= d <= 20) else 0.0
            metadata = {"source_file": source_file, "trace_index": t,
                       "sample_index": d, "anomaly_reliable": True}
            if with_velocity:
                metadata["velocity_m_per_ns"] = 0.1
            records.append(SubterraRecord(
                dataset_id=dataset_id, sensor_type=SensorType.GPR,
                latitude=latitude, longitude=longitude,
                position=GeographicPosition(lat=latitude, lon=longitude),
                elevation=250.0 if with_elevation else None,
                depth=round(d * 0.01, 6), signal=[value],
                metadata=metadata,
            ))
    return records


def test_resolved_scene_carries_evidence_samples_distinct_from_candidates(isolated_store, no_declarations):
    """Stage A: individually positioned measurements above threshold, not clustered into candidates."""
    from api.scene import build_scene

    sub = _frame("ds10", "ds10:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds10", "ds10:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds10", [sub, sur])
    save_records("ds10", _evidence_records("ds10", "line.SGY", with_elevation=True, with_velocity=True))

    payload = build_scene(db=None, dataset_id="ds10")
    assert payload.resolved is True
    assert payload.evidence is not None
    assert len(payload.evidence.samples) > 0
    s = payload.evidence.samples[0]
    assert s.position.available is True
    assert s.position.lat == pytest.approx(52.0)
    assert s.elevation.available is True
    assert s.evidence_value == 9.0
    # Evidence samples are individual measurements, not the grouped candidate set.
    assert len(payload.evidence.samples) != len(payload.candidates)


def test_evidence_elevation_uses_the_same_arithmetic_as_candidates(isolated_store, no_declarations):
    from api.scene import build_scene

    sub = _frame("ds11", "ds11:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds11", "ds11:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds11", [sub, sur])
    save_records("ds11", _evidence_records("ds11", "line.SGY", with_elevation=True, with_velocity=True))

    payload = build_scene(db=None, dataset_id="ds11")
    s = payload.evidence.samples[0]
    expected = compute_absolute_elevation(250.0, s.elevation.depth_m, None)
    assert s.elevation.elevation_m == pytest.approx(expected)
    assert "derived" in s.elevation.provenance


def test_evidence_without_dem_alignment_reports_elevation_unavailable(isolated_store, no_declarations):
    from api.scene import build_scene

    sub = _frame("ds12", "ds12:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds12", "ds12:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds12", [sub, sur])
    save_records("ds12", _evidence_records("ds12", "line.SGY", with_elevation=False, with_velocity=True))

    payload = build_scene(db=None, dataset_id="ds12")
    assert len(payload.evidence.samples) > 0
    s = payload.evidence.samples[0]
    assert s.elevation.available is False
    assert s.elevation.elevation_m is None
    assert "never aligned with a DEM" in s.elevation.reason


def test_evidence_without_velocity_is_derived_certainty_unavailable_not_measured(isolated_store, no_declarations):
    from api.scene import build_scene

    sub = _frame("ds13", "ds13:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds13", "ds13:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds13", [sub, sur])
    save_records("ds13", _evidence_records("ds13", "line.SGY", with_elevation=True, with_velocity=False))

    payload = build_scene(db=None, dataset_id="ds13")
    assert len(payload.evidence.samples) > 0
    from interpretation.candidate_intelligence import DepthCertainty
    for s in payload.evidence.samples:
        assert s.elevation.depth_certainty == DepthCertainty.UNAVAILABLE


def test_evidence_with_no_trace_addressable_data_reports_honest_empty_reason(isolated_store, no_declarations):
    """A depth-slice CSV (no trace_index) resolves the scene but carries no evidence field data."""
    from api.scene import build_scene

    sub = _frame("ds14", "ds14:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds14", "ds14:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds14", [sub, sur])
    save_records("ds14", [
        SubterraRecord(dataset_id="ds14", sensor_type=SensorType.GPR,
                       latitude=52.0, longitude=6.0,
                       position=GeographicPosition(lat=52.0, lon=6.0),
                       depth=0.1, signal=[9.0], metadata={}),
    ])

    payload = build_scene(db=None, dataset_id="ds14")
    assert payload.resolved is True
    assert payload.evidence is not None
    assert payload.evidence.samples == []
    assert "no genuine multi-sample GPR trace data" in payload.evidence.reason


def test_evidence_excludes_unpositioned_measurements_and_counts_them(isolated_store, no_declarations):
    from api.scene import build_scene

    sub = _frame("ds15", "ds15:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds15", "ds15:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds15", [sub, sur])
    records = []
    for t in range(8):
        for d in range(40):
            value = 9.0 if (3 <= t <= 5 and 18 <= d <= 20) else 0.0
            records.append(SubterraRecord(
                dataset_id="ds15", sensor_type=SensorType.GPR,
                depth=round(d * 0.01, 6), signal=[value],
                metadata={"source_file": "line.SGY", "trace_index": t,
                         "sample_index": d, "anomaly_reliable": True},
            ))
    save_records("ds15", records)

    payload = build_scene(db=None, dataset_id="ds15")
    assert payload.evidence.samples == []
    assert payload.evidence.excluded_unpositioned_count > 0


#: Same fixture CRS/point as tests/test_cross_crs_fusion.py and
#: tests/test_spatial_evidence.py: UTM zone 33N, landing at (lon=15.0, lat=41.05).
UTM33N = "EPSG:32633"
PROJ_E, PROJ_N = 500_000.0, 4_544_705.0


def _evidence_records_projected(dataset_id, source_file, frame_id, with_elevation, with_velocity):
    """Same shape as `_evidence_records`, but the GPR line's own position is
    PROJECTED (as a real SEG-Y header position is) rather than geographic --
    Stage A.1 fixture."""
    from schemas.spatial import ProjectedPosition

    records = []
    for t in range(8):
        for d in range(40):
            value = 9.0 if (3 <= t <= 5 and 18 <= d <= 20) else 0.0
            metadata = {"source_file": source_file, "trace_index": t,
                       "sample_index": d, "anomaly_reliable": True}
            if with_velocity:
                metadata["velocity_m_per_ns"] = 0.1
            records.append(SubterraRecord(
                dataset_id=dataset_id, sensor_type=SensorType.GPR,
                position=ProjectedPosition(easting=PROJ_E, northing=PROJ_N),
                frame_id=frame_id,
                elevation=250.0 if with_elevation else None,
                depth=round(d * 0.01, 6), signal=[value],
                metadata=metadata,
            ))
    return records


def test_resolved_scene_with_projected_gpr_gets_reprojected_evidence(isolated_store, no_declarations):
    """Stage A.1: a real-shaped SEG-Y line (PROJECTED position, declared CRS,
    no native lat/lon) still produces positioned evidence samples once the
    scene resolves -- via the same reprojection fusion already uses."""
    from api.scene import build_scene
    from schemas.spatial import CRSKind, CRSProvenance, SpatialRef

    frame_id = "ds17:line"
    sub = SurveyFrame(
        frame_id=frame_id, dataset_id="ds17", modality=SensorType.GPR, source_format="segy",
        spatial_ref=SpatialRef(kind=CRSKind.PROJECTED, code=UTM33N,
                               crs_provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                               horizontal_units="m"),
        vertical_axis=_axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP),
    )
    sur = _frame("ds17", "ds17:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds17", [sub, sur])
    save_records("ds17", _evidence_records_projected(
        "ds17", "line.SGY", frame_id, with_elevation=True, with_velocity=True))

    payload = build_scene(db=None, dataset_id="ds17")
    assert payload.resolved is True
    assert payload.evidence is not None
    assert payload.evidence.samples, "reprojected PROJECTED position must still yield evidence"
    s = payload.evidence.samples[0]
    assert s.position.available is True
    assert s.position.lon == pytest.approx(15.0, abs=1e-6)
    assert s.position.lat == pytest.approx(41.05, abs=0.05)
    # The declared-CRS-transform claim must read differently from a native fix.
    assert "not an independently verified geodetic position" in s.position.reason


def test_evidence_samples_are_bounded_and_flagged_when_downsampled(isolated_store, no_declarations, monkeypatch):
    from schemas import scene as scene_schema
    monkeypatch.setattr(scene_schema, "MAX_EVIDENCE_SAMPLES", 1)

    sub = _frame("ds16", "ds16:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds16", "ds16:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds16", [sub, sur])
    save_records("ds16", _evidence_records("ds16", "line.SGY", with_elevation=True, with_velocity=True))

    from api import scene as scene_mod
    monkeypatch.setattr(scene_mod, "MAX_EVIDENCE_SAMPLES", 1)
    payload = scene_mod.build_scene(db=None, dataset_id="ds16")
    assert payload.evidence.point_count_total > 1
    assert len(payload.evidence.samples) == 1
    assert payload.evidence.downsampled is True


def test_validation_status_never_claims_validated(isolated_store, no_declarations):
    """Every payload this module produces says the same honest thing, resolved or not."""
    from api.scene import build_scene
    save_frames("ds8", [])
    unresolved = build_scene(db=None, dataset_id="ds8")

    sub = _frame("ds9", "ds9:line",
                _axis(AxisKind.DEPTH_M, "ground surface at each trace", NAP))
    sur = _frame("ds9", "ds9:dem", _axis(AxisKind.ELEVATION_M, "raster band 1 value", NAP),
                modality=SensorType.DEM)
    save_frames("ds9", [sub, sur])
    save_records("ds9", [])
    resolved = build_scene(db=None, dataset_id="ds9")

    for payload in (unresolved, resolved):
        assert "independently validated" in payload.validation_status
        dumped = payload.model_dump(mode="json")
        assert "validated" not in {k for k in dumped if isinstance(dumped.get(k), bool)}
