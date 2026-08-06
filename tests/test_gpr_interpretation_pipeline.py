"""
Integration test for the REAL SUBSURFACE INTERPRETATION pipeline:

  georeferenced depth samples -> trace preprocessing -> local anomaly
  detection -> spatial anomaly grid -> DEM/elevation alignment -> sensor
  fusion

using a synthetic 72-trace, multi-depth-sample fixture shaped exactly
like SEGYConverter's real output (one record per (trace, depth) sample,
sharing metadata trace_index/source_file, placeholder (0,0) coordinates
pre-georeferencing) plus a synthetic KMZ-style GPS track -- mirroring the
real C1T_7,5_0001.SGY + ANF_CARRELLO.kmz case end to end without
requiring segyio or the real files.
"""
import numpy as np
import pytest

from schemas.subterra_record import SubterraRecord, SensorType
from ingestion.kmz_georeference import georeference_records_by_trace
from preprocessing.trace_processing import process_gpr_traces
from preprocessing.spatial_grid import preprocess_trace_local_anomaly, build_trace_depth_grid_for_records
from preprocessing.dem_alignment import align_records_with_dem
from fusion.sensor_fusion import fuse_datasets, multimodal_only

N_TRACES = 72
N_DEPTHS = 60  # scaled down from the real file's 482 for test speed; still "multiple depth samples per trace"
MAX_DEPTH_M = 7.0  # matches the real file's ~7m max depth (0.293ns interval @ 0.1 m/ns velocity)


def _make_raw_segy_shaped_records(dataset_id="pipeline-integration-test"):
    """
    Mirrors SEGYConverter's exact output shape BEFORE georeferencing: one
    record per (trace, depth) sample, placeholder (0.0, 0.0) coordinates,
    real depth axis, metadata carrying trace_index + source_file -- i.e.
    what ingest_zip_from_url hands to georeference_records_by_trace for
    the real INGV-UNISA dataset.
    """
    records = []
    depths = np.linspace(0, MAX_DEPTH_M, N_DEPTHS)
    for t in range(N_TRACES):
        rng = np.random.default_rng(t)
        waveform = rng.normal(0, 1, N_DEPTHS)
        for s, depth in enumerate(depths):
            records.append(
                SubterraRecord(
                    dataset_id=dataset_id, sensor_type=SensorType.GPR,
                    latitude=0.0, longitude=0.0, depth=float(depth),
                    signal=[float(waveform[s])],
                    metadata={"source_file": "C1T_7,5_0001", "trace_index": t, "sample_index": s},
                )
            )
    return records


def _inject_hyperbola_like_anomaly(records, center_trace=36, center_depth_idx=30, magnitude=20.0, half_width=3):
    """A buried point target shows up as elevated signal across a small span of nearby traces at one depth."""
    for r in records:
        if (
            center_trace - half_width <= r.metadata["trace_index"] <= center_trace + half_width
            and r.metadata["sample_index"] == center_depth_idx
        ):
            r.signal = [r.signal[0] + magnitude]
    return records


def _synthetic_kmz_path():
    """A short line near the real INGV-UNISA site, roughly matching C1T_7,5_0001's known ~17.4m track length."""
    return [(15.013300, 41.053510), (15.013400, 41.053550), (15.013500, 41.053590)]


def _write_tiny_dem_covering(records):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    import tempfile

    lats = [r.latitude for r in records]
    lons = [r.longitude for r in records]
    west, east = min(lons) - 0.001, max(lons) + 0.001
    south, north = min(lats) - 0.001, max(lats) + 0.001
    size = 20
    transform = from_origin(west, north, (east - west) / size, (north - south) / size)

    tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
    data = np.full((size, size), 300.0, dtype="float32")
    with rasterio.open(
        tmp.name, "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(data, 1)
    return tmp.name


def test_end_to_end_pipeline_shapes_and_values():
    records = _make_raw_segy_shaped_records()
    assert len(records) == N_TRACES * N_DEPTHS

    records = _inject_hyperbola_like_anomaly(records)

    # 1. Georeferencing (the real KMZ-based fix from the ingestion pipeline)
    n_traces_georeferenced = georeference_records_by_trace(records, _synthetic_kmz_path())
    assert n_traces_georeferenced == N_TRACES
    assert all((r.latitude, r.longitude) != (0.0, 0.0) for r in records)

    by_trace_pos = {}
    for r in records:
        by_trace_pos.setdefault(r.metadata["trace_index"], set()).add((r.latitude, r.longitude))
    assert all(len(v) == 1 for v in by_trace_pos.values())  # every sample of a trace shares one position
    assert len(by_trace_pos) == N_TRACES

    # 2. Trace preprocessing (dewow / background removal / gain)
    records = process_gpr_traces(records)
    assert all("processing_applied" in r.metadata for r in records)
    assert all(len(r.signal) == 1 for r in records)  # per-sample shape preserved
    assert all(r.depth is not None for r in records)  # real depth axis untouched, not synthetic
    assert sorted({round(r.depth, 6) for r in records}) == sorted({round(d, 6) for d in np.linspace(0, MAX_DEPTH_M, N_DEPTHS)})

    # 3. Local anomaly detection (trace x depth aware, not naive per-record)
    records = preprocess_trace_local_anomaly(records)  # default axis-aware trace/depth windows
    assert all("pre_anomaly_signal" in r.metadata for r in records)
    spike_records = [
        r for r in records
        if r.metadata["trace_index"] == 36 and r.metadata["sample_index"] == 30
    ]
    assert len(spike_records) == 1
    assert abs(spike_records[0].signal[0]) > 3.0  # injected anomaly stands out as a real z-score outlier

    # 4. Spatial anomaly grid: dense (trace x depth) representation, depth preserved (not collapsed)
    grid_result = build_trace_depth_grid_for_records(records)
    assert grid_result["grid"].shape == (N_DEPTHS, N_TRACES)
    assert len(grid_result["depths"]) == N_DEPTHS  # full depth resolution retained
    n_valid = int(np.isfinite(grid_result["grid"]).sum())
    n_invalid = grid_result["grid"].size - n_valid
    assert n_valid == N_TRACES * N_DEPTHS  # dense: every cell filled, no missing bins
    assert n_invalid == 0

    # 5. DEM/elevation alignment (compatible CRS: both GPR and DEM in EPSG:4326 lat/lon)
    dem_path = _write_tiny_dem_covering(records)
    records = align_records_with_dem(records, dem_path)
    n_aligned = sum(1 for r in records if r.elevation is not None)
    assert n_aligned == len(records)
    assert all(r.metadata.get("absolute_elevation_m") is not None for r in records)

    # 6. Sensor fusion: proves anomaly-processed, trace-structured GPR
    # records fuse correctly once a second co-located sensor exists.
    companion = [
        SubterraRecord(
            dataset_id="companion-seismic", sensor_type=SensorType.SEISMIC,
            latitude=records[0].latitude, longitude=records[0].longitude, signal=[1.0],
        )
    ]
    samples = fuse_datasets(records + companion, radius_m=50.0)
    multi = multimodal_only(samples)
    assert len(multi) >= 1
    assert {"gpr", "seismic"}.issubset(set(multi[0].sensor_types))
