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
