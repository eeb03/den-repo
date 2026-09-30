"""
Method C on held radar lines, with depth removed and velocity varied.

The picks below were recorded with the depth-ordered reconstruction BEFORE it
was replaced (`preprocessing.time_zero.reconstruct_traces_by_time`); they must
not move, because the picking algorithm did not change -- only what the traces
are assembled from. MALA had no pick at all before (no velocity -> no depth ->
UNAVAILABLE); it now has one from the waveform alone.

Skipped where the held data is absent (the canonical Docker run mounts it).
"""
import logging
import zipfile
from pathlib import Path

import pytest

from preprocessing.time_zero import resolve_time_zero_for_frame
from schemas.subterra_record import SensorType
from schemas.time_zero import TimeZeroStatus

logging.getLogger("converters").setLevel(logging.ERROR)

FOUR_TU = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted/01/01/01.1/"
               "Radargrams/Path8.sgy")
INGV = Path("datasets/downloads/multiline_C1T_0001_0002_extracted/C1T_7,5_0001.SGY")
MALA = Path("datasets/raw/grimsel/ethz-b-000420930/GPR_AU_N-to-S.rd3")
FALERII_ZIP = Path("datasets/raw/ads/falerii_novi_field5/Raw_GPR_profiles_Falerii_Novi_field_5.zip")
FALERII_MEMBER = "Falerii_Novi_field_5_0001_raw.segy"


def _need(path):
    if not path.exists():
        pytest.skip(f"held data not present: {path}")


def _segy(path, **kw):
    from converters.segy_converter import SEGYConverter
    return SEGYConverter().load(path, dataset_id="h", sensor_type=SensorType.GPR, **kw)


def _picks(result):
    """(with depth, depth cleared, depth at a different velocity), raw axis untouched."""
    frame, records = result.frames[0], result.records
    raw = [(r.metadata["two_way_time_ns"], r.signal[0]) for r in records]
    a = resolve_time_zero_for_frame(frame, records)
    for r in records:
        r.depth = None
    b = resolve_time_zero_for_frame(frame, records)
    for r in records:
        r.depth = r.metadata["two_way_time_ns"] * 0.2 / 2
    c = resolve_time_zero_for_frame(frame, records)
    assert [(r.metadata["two_way_time_ns"], r.signal[0]) for r in records] == raw
    return a, b, c


def test_4tu_pick_is_unchanged_and_independent_of_depth_and_velocity():
    _need(FOUR_TU)
    result = _segy(FOUR_TU)
    assert result.records[0].metadata["two_way_time_ns"] == pytest.approx(2.641)
    a, b, c = _picks(result)
    assert a.status == TimeZeroStatus.DERIVED
    assert a.correction_ns == pytest.approx(3.417)
    assert b.correction_ns == a.correction_ns == c.correction_ns


def test_falerii_pick_is_unchanged_and_independent_of_depth_and_velocity(tmp_path):
    _need(FALERII_ZIP)
    with zipfile.ZipFile(FALERII_ZIP) as z:
        z.extract(FALERII_MEMBER, tmp_path)
    result = _segy(tmp_path / FALERII_MEMBER, delay_encoding="sample_interval_unit")
    assert result.records[0].metadata["two_way_time_ns"] == pytest.approx(10.342)
    a, b, c = _picks(result)
    assert a.status == TimeZeroStatus.DERIVED
    # On the RAW axis: 8 ns after the recording starts, not 18.342 after it.
    assert a.correction_ns == pytest.approx(18.342)
    assert b.correction_ns == a.correction_ns == c.correction_ns


def test_ingv_stays_inconclusive_with_or_without_depth():
    _need(INGV)
    a, b, c = _picks(_segy(INGV))
    for r in (a, b, c):
        assert r.status == TimeZeroStatus.INCONCLUSIVE
        assert r.correction_ns is None
    assert a.spread_ns == b.spread_ns == c.spread_ns


def test_mala_is_picked_from_the_waveform_with_no_velocity_at_all():
    _need(MALA)
    from converters.mala_converter import MALAConverter
    result = MALAConverter().load(MALA, dataset_id="h")
    assert all(r.depth is None for r in result.records)
    pick = resolve_time_zero_for_frame(result.frames[0], result.records)
    assert pick.status == TimeZeroStatus.DERIVED
    assert pick.correction_ns == pytest.approx(4.0179, abs=1e-3)
    assert all(r.depth is None for r in result.records)   # nothing invented


def test_method_c_is_deterministic_on_held_data():
    """Same records in, same status, pick, spread and pick counts out -- every run."""
    _need(FOUR_TU)
    result = _segy(FOUR_TU)
    runs = [resolve_time_zero_for_frame(result.frames[0], result.records) for _ in range(3)]
    keys = ("status", "correction_ns", "spread_ns", "successful_picks", "outliers_rejected",
            "traces_evaluated")
    assert len({tuple(getattr(r, k) for k in keys) for r in runs}) == 1
