"""
Provenance must report a DECLARED acquisition-elevation datum.

A vertical_datum declaration with applies_to="acquisition_elevation" is
written to `SurveyFrame.acquisition_elevation_datum` (api/spatial.py), and the
spatial assessment and fusion both read it. The provenance projection did not:
after the declaration, /api/provenance still reported the elevation as "the
source declares NO vertical datum" and the frame's only datum entry as
unavailable -- contradicting what was persisted.

The raw record metadata stays "UNDECLARED" on purpose (the file declares
none); the frame is where the caller's declaration lives, so the projection
has to consult it. It is reported as SUPPLIED_BY_CALLER, never as something
the source declared.
"""
import pytest

from converters.segy_converter import SEGYConverter
from schemas.provenance import ProvenanceClass, frame_provenance, record_provenance
from schemas.spatial import AcquisitionElevationDatum, CRSProvenance, VerticalDatum
from schemas.subterra_record import SensorType
from tests.test_segy_scalar_exponent_encoding import write_big_endian_segy

EGM2008 = VerticalDatum(code="EPSG:3855", provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                        name="EGM2008 height")


def _load(tmp_path):
    res = SEGYConverter().load(write_big_endian_segy(tmp_path / "fn.segy"), dataset_id="fn",
                               sensor_type=SensorType.GPR,
                               coordinate_encoding="int32_scalar_exponent")
    return res.records[0], res.frames[0]


def _by_quantity(entries):
    return {e.quantity: e for e in entries}


def _declare(frame):
    frame.acquisition_elevation_datum = AcquisitionElevationDatum(
        datum=EGM2008, field="ReceiverGroupElevation")
    return frame


def test_undeclared_elevation_is_still_reported_as_undeclared(tmp_path):
    record, frame = _load(tmp_path)
    elev = _by_quantity(record_provenance(record, frame))["elevation"]
    assert elev.provenance == ProvenanceClass.INFERRED
    assert "NO vertical datum" in elev.basis
    assert "acquisition_elevation_datum" not in _by_quantity(frame_provenance(frame))


def test_record_elevation_reports_the_declared_datum_as_supplied_by_caller(tmp_path):
    record, frame = _load(tmp_path)
    elev = _by_quantity(record_provenance(record, _declare(frame)))["elevation"]

    assert elev.provenance == ProvenanceClass.SUPPLIED_BY_CALLER
    assert "EPSG:3855" in elev.basis
    assert "NO vertical datum" not in elev.basis
    assert elev.value == pytest.approx(203.14)


def test_the_raw_record_metadata_is_not_rewritten(tmp_path):
    record, frame = _load(tmp_path)
    record_provenance(record, _declare(frame))
    assert record.metadata["acquisition_elevation_datum"] == "UNDECLARED"


def test_frame_provenance_reports_the_acquisition_elevation_datum_separately(tmp_path):
    _, frame = _load(tmp_path)
    q = _by_quantity(frame_provenance(_declare(frame)))

    aed = q["acquisition_elevation_datum"]
    assert aed.provenance == ProvenanceClass.SUPPLIED_BY_CALLER
    assert aed.value == "EPSG:3855"
    assert aed.source == "SurveyFrame.acquisition_elevation_datum"
    # The depth axis is still unreferenced, and that entry must keep saying so.
    assert q["vertical_datum"].provenance == ProvenanceClass.UNAVAILABLE


def test_record_provenance_carries_the_frame_level_entry_too(tmp_path):
    record, frame = _load(tmp_path)
    q = _by_quantity(record_provenance(record, _declare(frame)))
    assert q["acquisition_elevation_datum"].value == "EPSG:3855"
