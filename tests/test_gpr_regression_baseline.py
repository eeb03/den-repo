"""
GPR REGRESSION GATE.

Proves that the M1 ingestion refactor changed nothing numerically or
behaviourally in the validated GPR pipeline. Every value below was captured
from the pipeline as it stood at commit 4b9ff0e (the interpretation
baseline), BEFORE any M1 change, and is asserted EXACTLY -- no tolerances.
No processing parameter changed in M1, so any difference at all is a defect,
not drift.

Coverage, per the approved audit:
  raw trace/depth grid, processed grid, anomaly z-grid, candidate counts,
  candidate trace ranges, source-file attribution, coordinate/depth metadata.

Grids are compared by sha256 of their float64 bytes rather than by pinning
34,704 numbers; the digest is exact and a mismatch is a hard failure. Record
equality is checked field-by-field with the two fields M1 legitimately adds
(`position`, `frame_id`) removed, so this asserts everything else is
untouched.

Skipped when the INGV SEG-Y files aren't present locally.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from converters.segy_converter import SEGYConverter
from interpretation.anomaly_candidates import find_anomaly_candidates
from preprocessing.pipeline import run_pipeline
from preprocessing.spatial_grid import _group_by_source_file, _trace_depth_grid
from schemas.subterra_record import SensorType

DATA = Path("datasets/downloads/multiline_C1T_0001_0002_extracted")

#: Fields M1 adds. Excluded from the record-equality digest so this test
#: asserts "everything else is byte-identical".
NEW_FIELDS = {"position", "frame_id"}

BASELINE = {
    "C1T_7,5_0001": {
        "file": "C1T_7,5_0001.SGY",
        "n_records": 34704,
        "shape": (482, 72),
        "n_trace_ids": 72,
        "trace_ids_first_last": (0, 71),
        "n_depths": 482,
        "depth_min": 0.0,
        "depth_max": 7.04665,
        "depth_step": 0.01465,
        "record_digest": "a6f5b1b6dda38c4824de4ee4feba3f52471a7f0a3ef2f1ca0e1cb7ca3ce189f0",
        "raw_digest": "02213b1a146f6461776fbb13da641a07b2a5a950673da43f6f3a3fc308538071",
        "processed_digest": "50d897735cd69fa0837d525ee27516f7de45f453ff991a408715c3775eb6e84e",
        "z_digest": "270dda2739a89d9c902c8ae1fec8d9af1b9fdb99b10fed6595ee77b0b6fb8329",
        "z_std": 0.904066,
        "z_absmax": 4.273256,
        "cells_ge_3": 121,
        "n_candidates": 25,
        "trace_ranges_digest": "48eb6d679d62988338c72c0a7aa9817c25ff08d4f71b40c45277cd3554545d18",
        "depth_ranges_digest": "25a1a59e737a98759d8ced44e35b9f4795b9b9239c12b9691ab788a56f17d7c0",
        "peak_values_digest": "21dc18864c1a82e3db735da67aad827f09542816d337927ebddd259e409a0d37",
    },
    "C1T_7,5_0002": {
        "file": "C1T_7,5_0002.SGY",
        "n_records": 31812,
        "shape": (482, 66),
        "n_trace_ids": 66,
        "trace_ids_first_last": (0, 65),
        "n_depths": 482,
        "depth_min": 0.0,
        "depth_max": 7.04665,
        "depth_step": 0.01465,
        "record_digest": "baf8e4e4490f1d80dbba9a0acd12c9c329a755b6632a64487506f6c7ad595aee",
        "raw_digest": "c66ee5e112add821c08dc8c2bcc09a4df43af1e58376b40ad29bc90ba84691de",
        "processed_digest": "d7d9743ea3c48fe5fd81c4710199ab03f0a706909046bf9ed80e5a117a4d2cdf",
        "z_digest": "b311572febb6408206f7b3db66d138b9d3507d5c99276bd4fb21c2ecff5e9ca8",
        "z_std": 0.845445,
        "z_absmax": 4.361468,
        "cells_ge_3": 73,
        "n_candidates": 12,
        "trace_ranges_digest": "4ba6298ca6ca2f80ce4bfcc48cc3b35b16ae1ebcf6aacba7c61a276dbc8bffd5",
        "depth_ranges_digest": "6d0abea4b3311541baff09b84fdfc4e5975ffb2fc9b88a9c22586eb9a3379f5c",
        "peak_values_digest": "e813ce7ff7dd426dcc771461beca136871c3cffccc1433433f5748cdb9f862df",
    },
}

#: Metadata keys every SEG-Y record carried before M1. None may disappear.
BASELINE_METADATA_KEYS = sorted([
    "sample_count", "sample_index", "sample_interval", "segy_x", "segy_y",
    "source_file", "trace_count", "trace_index", "two_way_time_ns", "velocity_m_per_ns",
])

pytestmark = pytest.mark.skipif(
    not (DATA / "C1T_7,5_0001.SGY").exists(),
    reason="INGV SEG-Y regression fixtures not present locally",
)


def _arr_digest(a) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64).tobytes()).hexdigest()


def _json_digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def _record_digest(records) -> str:
    h = hashlib.sha256()
    for r in records:
        d = r.to_flat_dict()
        for k in NEW_FIELDS:
            d.pop(k, None)
        h.update(json.dumps(d, sort_keys=True, default=str).encode())
    return h.hexdigest()


@pytest.fixture(scope="module", params=sorted(BASELINE))
def line(request):
    """Runs the full pipeline once per line and hands back every stage."""
    name = request.param
    exp = BASELINE[name]
    records = SEGYConverter().convert(
        DATA / exp["file"], dataset_id="regress", sensor_type=SensorType.GPR
    )
    raw_grid, trace_ids, depths = _trace_depth_grid(records)
    record_digest = _record_digest(records)
    # Captured BEFORE preprocessing runs: the pipeline legitimately adds its
    # own keys (processing_applied, anomaly_reliable, pre_anomaly_signal,
    # trace_depth_grid_shape), which is pre-existing behaviour M1 did not
    # touch. What must match the pre-M1 baseline is the CONVERTER's output.
    converter_metadata_keys = sorted(records[0].metadata.keys())

    records = run_pipeline(records, mode="gpr_trace_processing")
    processed_grid, _, _ = _trace_depth_grid(records)

    records = run_pipeline(records, mode="gpr_local_anomaly")
    z_grid, _, _ = _trace_depth_grid(records)

    candidates = find_anomaly_candidates(records, source_file=exp["file"])
    return {
        "name": name, "exp": exp, "records": records, "record_digest": record_digest,
        "converter_metadata_keys": converter_metadata_keys,
        "raw": raw_grid, "processed": processed_grid, "z": z_grid,
        "trace_ids": trace_ids, "depths": depths, "candidates": candidates,
    }


def test_record_fields_unchanged_apart_from_new_ones(line):
    """Every pre-existing record field is byte-identical to the pre-M1 baseline."""
    assert line["record_digest"] == line["exp"]["record_digest"]


def test_metadata_keys_unchanged(line):
    """The converter still emits exactly the metadata keys it emitted pre-M1."""
    assert line["converter_metadata_keys"] == BASELINE_METADATA_KEYS


def test_raw_trace_depth_grid_unchanged(line):
    exp = line["exp"]
    assert line["raw"].shape == exp["shape"]
    assert len(line["records"]) == exp["n_records"]
    assert _arr_digest(line["raw"]) == exp["raw_digest"]


def test_trace_and_depth_axes_unchanged(line):
    exp, depths, tids = line["exp"], line["depths"], line["trace_ids"]
    assert len(tids) == exp["n_trace_ids"]
    assert (tids[0], tids[-1]) == exp["trace_ids_first_last"]
    assert len(depths) == exp["n_depths"]
    assert min(depths) == pytest.approx(exp["depth_min"], abs=0)
    assert round(max(depths), 5) == exp["depth_max"]
    assert round(depths[1] - depths[0], 5) == exp["depth_step"]


def test_processed_grid_unchanged(line):
    assert _arr_digest(line["processed"]) == line["exp"]["processed_digest"]


def test_anomaly_zscore_grid_unchanged(line):
    exp, z = line["exp"], line["z"]
    assert _arr_digest(z) == exp["z_digest"]
    assert round(float(np.nanstd(z)), 6) == exp["z_std"]
    assert round(float(np.nanmax(np.abs(z))), 6) == exp["z_absmax"]
    assert int((np.abs(np.nan_to_num(z)) >= 3.0).sum()) == exp["cells_ge_3"]


def test_candidate_count_unchanged(line):
    assert len(line["candidates"]) == line["exp"]["n_candidates"]


def test_candidate_trace_ranges_unchanged(line):
    ranges = sorted([list(c.evidence.trace_range) for c in line["candidates"]])
    assert _json_digest(ranges) == line["exp"]["trace_ranges_digest"]


def test_candidate_depth_ranges_and_peaks_unchanged(line):
    exp = line["exp"]
    depth_ranges = sorted([[round(x, 6) for x in c.evidence.depth_range] for c in line["candidates"]])
    peaks = sorted(round(c.evidence.peak_value, 9) for c in line["candidates"])
    assert _json_digest(depth_ranges) == exp["depth_ranges_digest"]
    assert _json_digest(peaks) == exp["peak_values_digest"]


def test_source_file_attribution_unchanged(line):
    """No candidate may span more than one source_file, and grouping is unchanged."""
    exp = line["exp"]
    assert sorted(_group_by_source_file(line["records"]).keys()) == [exp["file"]]
    assert {c.evidence.source_file for c in line["candidates"]} == {exp["file"]}


def test_legacy_coordinates_unchanged(line):
    """latitude/longitude keep their pre-M1 values, including the (0,0) fallback."""
    for r in line["records"][:100]:
        assert (r.latitude, r.longitude) == (0.0, 0.0)


# --- named-line candidate counts, the second half of the regression gate ---

UAV = Path("datasets/downloads/INGV-UNISA Site 1 GPR v3_extracted/Site_1/UAV_drone")
NAMED_COUNTS = {"C1T_7,5": 540, "C2T_7,5": 103, "C4T_7,5": 94, "c1_7,5": 173}


@pytest.mark.skipif(not UAV.exists(), reason="INGV UAV lines not present locally")
@pytest.mark.parametrize("stem,expected", sorted(NAMED_COUNTS.items()))
def test_named_line_candidate_counts_unchanged(stem, expected):
    records = SEGYConverter().convert(
        UAV / f"{stem}.SGY", dataset_id="regress", sensor_type=SensorType.GPR
    )
    records = run_pipeline(records, mode="gpr_trace_processing")
    records = run_pipeline(records, mode="gpr_local_anomaly")
    assert len(find_anomaly_candidates(records, source_file=f"{stem}.SGY")) == expected
