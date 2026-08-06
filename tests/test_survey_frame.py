"""
Tests for SurveyFrame, the frames store, and the SEG-Y converter's frame
emission.

The properties under test: a frame is deterministically identified, never
spans more than one source file, preserves provenance the records alone
cannot carry, and can be reconstructed for datasets ingested before frames
existed.

FOLLOW-UP (opened by M1, deliberately NOT resolved here):
    Validate SEG-Y SourceX/SourceY positions against the KMZ-derived survey
    track before treating them as authoritative georeferencing.

    M1 measured 67 distinct header positions across the 72 traces of
    C1T_7,5_0001.SGY. ingestion/kmz_georeference.py documents these headers
    as a single static placeholder repeated on every trace. Both cannot be
    right. Until that is settled, `position` preserves the header values as
    ProjectedPosition (strictly better than the pre-M1 behaviour of
    discarding them into (0,0)) but nothing in the platform treats them as
    a georeferenced track, and the KMZ path is unchanged.
"""
from pathlib import Path

import pytest

from converters.base import BaseConverter
from database.frames_store import (
    frames_by_id, load_frames, save_frames, synthesize_frames_from_records,
)
from schemas.spatial import (
    AxisKind, CRSKind, NoPosition, PositionKind, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame, make_frame_id

DATA = Path("datasets/downloads/multiline_C1T_0001_0002_extracted")
LINE = DATA / "C1T_7,5_0001.SGY"


def _frame(**kw):
    base = dict(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy", source_file="line.SGY",
        spatial_ref=SpatialRef(kind=CRSKind.UNKNOWN),
        vertical_axis=VerticalAxis(kind=AxisKind.NONE, units="", origin="n/a", positive_down=True),
    )
    base.update(kw)
    return SurveyFrame(**base)


# --- identity ---

def test_frame_id_is_dataset_scoped_and_deterministic():
    assert make_frame_id("ds1", "C1T_7,5_0001.SGY") == "ds1:C1T_7,5_0001"
    assert make_frame_id("ds1", Path("/a/b/C1T_7,5_0001.SGY")) == "ds1:C1T_7,5_0001"
    assert make_frame_id("ds1", "x.SGY") == make_frame_id("ds1", "x.SGY")


def test_same_filename_in_different_datasets_does_not_collide():
    """The INGV archive ships three extracted copies of the same 50 filenames."""
    assert make_frame_id("ds1", "C1T_7,5_0001.SGY") != make_frame_id("ds2", "C1T_7,5_0001.SGY")


# --- storage ---

def test_frames_round_trip_through_the_store(tmp_path, monkeypatch):
    from configs import settings as settings_mod
    monkeypatch.setattr(type(settings_mod.settings), "processed_dir",
                        property(lambda self: tmp_path))
    frames = [_frame(frame_id="ds:a", source_file="a.SGY"),
              _frame(frame_id="ds:b", source_file="b.SGY")]
    save_frames("ds", frames)
    loaded = load_frames("ds")
    assert loaded == frames
    assert sorted(frames_by_id(loaded)) == ["ds:a", "ds:b"]


def test_load_frames_returns_empty_for_a_dataset_without_a_frame_file(tmp_path, monkeypatch):
    """Datasets ingested before M1 must not raise -- callers fall back to synthesis."""
    from configs import settings as settings_mod
    monkeypatch.setattr(type(settings_mod.settings), "processed_dir",
                        property(lambda self: tmp_path))
    assert load_frames("never-ingested") == []


# --- reconstruction for pre-M1 datasets ---

def _legacy_records(source_file="old.SGY", n_traces=3):
    return [
        SubterraRecord(
            dataset_id="ds", sensor_type=SensorType.GPR, latitude=0.0, longitude=0.0,
            depth=0.1 * s, signal=[float(s)],
            metadata={"source_file": source_file, "trace_index": t, "sample_index": s,
                      "two_way_time_ns": 2.0 * s, "velocity_m_per_ns": 0.1, "sample_count": 2},
        )
        for t in range(n_traces) for s in range(2)
    ]


def test_synthesized_frame_is_marked_as_reconstructed():
    frames = synthesize_frames_from_records(_legacy_records())
    assert len(frames) == 1
    marker = frames[0].assumption("frame_reconstructed")
    assert marker is not None and marker.value is True and marker.verified is False


def test_synthesis_produces_one_frame_per_source_file():
    records = _legacy_records("a.SGY") + _legacy_records("b.SGY")
    frames = synthesize_frames_from_records(records)
    assert sorted(f.source_file for f in frames) == ["a.SGY", "b.SGY"]
    assert len({f.frame_id for f in frames}) == 2


def test_synthesis_recovers_the_time_axis_but_not_an_invented_crs():
    frame = synthesize_frames_from_records(_legacy_records())[0]
    assert frame.vertical_axis.kind == AxisKind.TWO_WAY_TIME_NS
    assert frame.vertical_axis.conversion["velocity_m_per_ns"] == 0.1
    # Records only ever stored bare lat/lon, so the CRS is genuinely unrecoverable.
    assert frame.spatial_ref.kind == CRSKind.UNKNOWN
    assert frame.n_positions == 3


def test_synthesis_of_empty_input_is_empty():
    assert synthesize_frames_from_records([]) == []


# --- SEG-Y frame emission (real file) ---

@pytest.mark.skipif(not LINE.exists(), reason="INGV SEG-Y fixture not present locally")
class TestSegyFrame:
    @pytest.fixture(scope="class")
    def result(self):
        from converters.segy_converter import SEGYConverter
        return SEGYConverter().load(LINE, dataset_id="ds", sensor_type=SensorType.GPR)

    def test_one_frame_per_file(self, result):
        assert len(result.frames) == 1
        assert result.frames[0].frame_id == "ds:C1T_7,5_0001"

    def test_every_record_points_at_that_frame(self, result):
        assert {r.frame_id for r in result.records} == {"ds:C1T_7,5_0001"}

    def test_convert_and_load_return_the_same_records(self):
        """convert() must stay a thin view over load(), not a second code path."""
        from converters.segy_converter import SEGYConverter
        c = SEGYConverter()
        a = c.convert(LINE, dataset_id="ds", sensor_type=SensorType.GPR)
        b = c.load(LINE, dataset_id="ds", sensor_type=SensorType.GPR).records
        assert len(a) == len(b)
        assert [r.to_flat_dict() for r in a[:50]] == [r.to_flat_dict() for r in b[:50]]

    def test_projected_header_coordinates_are_preserved_not_discarded(self, result):
        """
        The pre-M1 converter overwrote these UTM values with (0.0, 0.0).
        The legacy fields still show that; `position` no longer does.
        """
        r = result.records[0]
        assert r.position.kind == PositionKind.PROJECTED
        assert r.position.easting == pytest.approx(501134.03, abs=0.01)
        assert r.position.northing == pytest.approx(4544705.58, abs=0.01)
        assert (r.latitude, r.longitude) == (0.0, 0.0)  # legacy view unchanged

    def test_frame_declares_projected_crs_without_inventing_an_epsg_code(self, result):
        ref = result.frames[0].spatial_ref
        assert ref.kind == CRSKind.PROJECTED
        assert ref.code is None  # SEG-Y never declares which projection
        assert ref.horizontal_units == "m"

    def test_frame_records_the_assumed_velocity_as_an_assumption(self, result):
        a = result.frames[0].assumption("gpr_velocity")
        assert a is not None and a.value == 0.1 and a.verified is False
        assert "assumed default" in a.basis

    def test_frame_reports_whether_header_positions_vary_per_trace(self, result):
        """
        Whether header coordinates are a real per-trace track or one static
        value repeated changes what downstream lateral-extent maths may do
        with them, so the frame states which it observed.

        MEASURED on C1T_7,5_0001.SGY: 67 distinct (easting, northing) pairs
        across 72 traces -- they DO vary.

        This contradicts ingestion/kmz_georeference.py's docstring, which
        states these headers "carry the SAME static placeholder value on
        every single trace -- there is no real per-trace position in the
        SEG-Y at all". That claim is not true for this file.

        The test asserts only what was measured. It does NOT assert that
        these are valid survey positions: 67-of-72 distinct is consistent
        with a genuine track, and equally consistent with header noise or a
        field that means something else. See the FOLLOW-UP note at the top
        of this module before treating them as authoritative.
        """
        a = result.frames[0].assumption("per_trace_position")
        assert a is not None
        assert a.value == "varies"
        assert a.verified is True
        assert "67 distinct header position(s) across 72 traces" in a.basis

    def test_frame_describes_the_time_axis_and_its_depth_conversion(self, result):
        axis = result.frames[0].vertical_axis
        assert axis.kind == AxisKind.TWO_WAY_TIME_NS and axis.units == "ns"
        assert axis.n_samples == 482
        assert axis.sample_interval == pytest.approx(0.293, abs=1e-6)
        assert axis.conversion["method"] == "constant_velocity"
        assert axis.conversion["target_axis"] == AxisKind.DEPTH_M.value

    def test_frame_carries_provenance(self, result):
        f = result.frames[0]
        assert f.source_format == "segy"
        assert f.source_file == "C1T_7,5_0001.SGY"
        assert f.modality == SensorType.GPR
        assert f.n_positions == 72
        assert f.position_index_name == "trace_index"
        assert f.source_metadata["sample_count"] == 482


# --- the default shim keeps pre-frame converters working ---

class _UnmigratedConverter(BaseConverter):
    """A converter that only implements convert(), as all of them did before M1.

    Deliberately a local stand-in rather than a real converter: every
    registered converter now emits frames, so using one here would silently
    stop testing the shim the moment it was migrated.
    """
    format_name = "unmigrated"
    supported_extensions = (".none",)

    def convert(self, path, dataset_id, sensor_type, **kwargs):
        return [SubterraRecord(dataset_id=dataset_id, sensor_type=sensor_type,
                               latitude=41.0, longitude=15.0, signal=[1.0])]


def test_base_load_shim_wraps_convert_without_frames():
    result = _UnmigratedConverter().load("x.none", dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)
    assert len(result.records) == 1
    assert result.frames == []          # unmigrated converter: no frame yet
    assert result.records[0].position.kind == PositionKind.GEOGRAPHIC


def test_synthesis_covers_converters_that_emit_no_frames():
    """The ingest routes fall back to synthesis exactly for this case."""
    result = _UnmigratedConverter().load("x.none", dataset_id="ds", sensor_type=SensorType.MAGNETOMETER)
    frames = synthesize_frames_from_records(result.records)
    assert len(frames) == 1
    assert frames[0].assumption("frame_reconstructed").value is True
