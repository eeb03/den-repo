"""
SEG-Y carries GPR and seismic alike, but their vertical axes are not
interchangeable.

Before this, SEGYConverter applied `velocity_m_per_ns = 0.1` -- a near-surface
GPR SOIL velocity -- to every sensor_type, so ingesting a seismic SEG-Y
silently produced a depth computed from the wrong physics and presented it as
a measurement. These tests pin that only GPR gets a depth conversion, and that
every other modality keeps its time axis with `depth` unset.

The GPR side must remain bit-identical; that is enforced by
tests/test_gpr_regression_baseline.py, not here.
"""
from pathlib import Path

import pytest

from converters.segy_converter import SEGYConverter
from schemas.spatial import AxisKind
from schemas.subterra_record import SensorType

LINE = Path("datasets/downloads/multiline_C1T_0001_0002_extracted/C1T_7,5_0001.SGY")

pytestmark = pytest.mark.skipif(not LINE.exists(), reason="INGV SEG-Y fixture not present locally")


@pytest.fixture(scope="module")
def gpr():
    return SEGYConverter().load(LINE, dataset_id="ds", sensor_type=SensorType.GPR)


@pytest.fixture(scope="module")
def seismic():
    """The SAME bytes read as seismic. Only the declared modality differs."""
    return SEGYConverter().load(LINE, dataset_id="ds", sensor_type=SensorType.SEISMIC)


# --- GPR keeps its existing behaviour exactly ---

def test_gpr_still_converts_time_to_depth(gpr):
    r = gpr.records[0]
    assert r.depth is not None
    assert r.metadata["two_way_time_ns"] == 0.0
    assert r.metadata["velocity_m_per_ns"] == 0.1
    deep = gpr.records[400]
    assert deep.depth == pytest.approx(deep.metadata["two_way_time_ns"] * 0.1 / 2.0)


def test_gpr_frame_declares_a_nanosecond_axis_with_its_conversion(gpr):
    axis = gpr.frames[0].vertical_axis
    assert axis.kind == AxisKind.TWO_WAY_TIME_NS and axis.units == "ns"
    assert axis.conversion["method"] == "constant_velocity"
    assert axis.conversion["target_axis"] == AxisKind.DEPTH_M.value


# --- non-GPR refuses to fabricate a depth ---

def test_seismic_does_not_receive_a_fabricated_depth(seismic):
    """THE BUG: every record used to get depth = twt * 0.1 / 2, a GPR soil velocity."""
    assert all(r.depth is None for r in seismic.records[:500])


def test_seismic_carries_no_gpr_velocity_anywhere(seismic):
    r = seismic.records[0]
    assert "velocity_m_per_ns" not in r.metadata
    assert "two_way_time_ns" not in r.metadata
    assert r.metadata["two_way_time_ms"] == 0.0


def test_seismic_frame_declares_a_time_axis_and_no_conversion(seismic):
    axis = seismic.frames[0].vertical_axis
    assert axis.kind == AxisKind.TWO_WAY_TIME_MS and axis.units == "ms"
    # Absence of `conversion` is the machine-readable "this is time, not depth".
    assert axis.conversion is None


def test_seismic_frame_records_why_no_depth_was_produced(seismic):
    a = seismic.frames[0].assumption("depth_conversion")
    assert a is not None and a.value == "not applied" and a.verified is True
    assert "velocity model" in a.basis


def test_seismic_frame_declares_itself_unvalidated(seismic):
    """We read the file; we do not claim to support the modality."""
    a = seismic.frames[0].assumption("modality_support")
    assert a is not None and a.verified is False
    assert "UNVALIDATED" in a.value


def test_seismic_time_units_are_an_explicit_unverified_assumption(seismic):
    a = seismic.frames[0].assumption("two_way_time_units")
    assert a.value == "ms" and a.verified is False
    assert "ASSUMED" in a.basis


# --- the signal itself is modality-independent ---

def test_signal_and_trace_identity_are_identical_across_modalities(gpr, seismic):
    """Only the vertical-axis interpretation differs; the samples do not."""
    assert len(gpr.records) == len(seismic.records)
    for g, s in zip(gpr.records[:200], seismic.records[:200]):
        assert g.signal == s.signal
        assert g.metadata["trace_index"] == s.metadata["trace_index"]
        assert g.metadata["sample_index"] == s.metadata["sample_index"]
        assert g.position == s.position


def test_depthless_records_are_skipped_by_trace_local_anomaly_not_crashed(seismic):
    """
    preprocess_trace_local_anomaly requires a real depth per sample. Records
    without one must be passed over with a warning rather than raising.
    """
    from preprocessing.pipeline import run_pipeline
    subset = seismic.records[:2000]
    out = run_pipeline(subset, mode="gpr_local_anomaly")
    assert len(out) == len(subset)
    assert all(r.metadata.get("anomaly_reliable") is None for r in out)


def test_trace_processing_also_skips_depthless_records(seismic):
    from preprocessing.pipeline import run_pipeline
    subset = [r.model_copy(deep=True) for r in seismic.records[:2000]]
    before = [r.signal[0] for r in subset]
    out = run_pipeline(subset, mode="gpr_trace_processing")
    assert [r.signal[0] for r in out] == before
