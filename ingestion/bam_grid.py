"""
Register one BAM benchmark scan as a product dataset with a GRIDDED
ACQUISITION, so it can be calibrated through the normal declaration workflow
and reconstructed as a volume.

WHAT IS AND IS NOT CARRIED IN.
  * The amplitudes: the published 3D `.npy` grid, unchanged (float32), read by
    `benchmark.bam_ingest` -- the reader whose grid mapping and amplitude
    preservation are already established (benchmark.gates:
    'dzt-to-grid-mapping' RESOLVED, 'amplitude_preservation' VALIDATED).
  * The geometry: the X/Y/Z vectors stored IN the archive; their units (mm,
    ns) come from the Dataverse description and are tagged as documentation.
  * NOT the targets. The construction drawings are a separate benchmark layer
    (`evidence/bam/specimen_ground_truth.csv`), only ever read for overlay and
    evaluation. The dataset records which specimen it is, so that overlay can
    be offered -- that link is metadata, not input.
  * NOT a calibration, a time zero, a velocity or a surface reference. Those
    arrive as spatial declarations, by a user, like any other dataset.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np

from schemas.spatial import Assumption, AxisKind, CRSKind, CRSProvenance, SpatialRef, VerticalAxis
from schemas.subterra_record import SensorType
from schemas.survey_frame import SurveyFrame, make_frame_id
from schemas.survey_grid import AxisProvenance, GridAxis, GriddedAcquisition


def register_bam_scan(db, owner_id: str | None, specimen_id: str, scan: str,
                      root: Path | None = None, name: str | None = None) -> str:
    """Create the Dataset row, the grid frame and the stored array. Returns the dataset id."""
    from benchmark.bam_ingest import DEFAULT_ROOT, load_scan, load_volume
    from database.frames_store import save_frames
    from database.grid_store import save_grid
    from database.models import Dataset

    root = root or DEFAULT_ROOT
    scan_id = f"{specimen_id}_3D_Dataset_{scan}"
    s = load_scan(specimen_id, scan_id, root)
    vol = load_volume(s, root).astype(np.float32)
    g = s.grid
    dataset_id = str(uuid.uuid4())
    frame_id = make_frame_id(dataset_id, scan_id)
    doc = "Harvard Dataverse doi:10.7910/DVN/FCMUJQ description (the .npy files carry no unit)"
    geometry = GriddedAcquisition(
        dataset_id=dataset_id, frame_id=frame_id,
        trace_axis=GridAxis(name="x", n=int(g.x.size), origin=float(g.x[0]), step=float(g.x_step),
                            unit="mm", provenance=AxisProvenance.SOURCE_FILE,
                            source="X-values.npy in the archive", unit_provenance=AxisProvenance.DOCUMENTATION),
        line_axis=GridAxis(name="y", n=int(g.y.size), origin=float(g.y[0]), step=float(g.y_step),
                           unit="mm", provenance=AxisProvenance.SOURCE_FILE,
                           source="Y-values.npy in the archive", unit_provenance=AxisProvenance.DOCUMENTATION),
        time_axis=GridAxis(name="two_way_time", n=int(g.z.size), origin=float(g.z[0]),
                           step=float(g.z[1] - g.z[0]), unit="ns", provenance=AxisProvenance.SOURCE_FILE,
                           source="Z-values.npy in the archive; ns corroborated by the DZT header "
                                  "(range 15 ns, 512 samples)",
                           unit_provenance=AxisProvenance.SOURCE_FILE),
        array_file="", array_sha256="",
        amplitude_note=("published 3D .npy grid, values unchanged; grid traces equal Subterra-decoded "
                        "DZT A-scans on samples 2-511 (evidence/bam/results/amplitude_preservation.json)"),
        source={"benchmark_id": s.benchmark_id, "specimen_id": specimen_id, "scan_id": scan_id,
                "archive": s.archive, "volume_member": s.volume_member, "provenance": s.provenance})
    geometry = save_grid(geometry, vol)

    frame = SurveyFrame(
        frame_id=frame_id, dataset_id=dataset_id, modality=SensorType.GPR,
        modality_source="file_header", source_format="bam_npy_grid", source_file=s.volume_member,
        spatial_ref=SpatialRef(kind=CRSKind.ENGINEERING, crs_provenance=CRSProvenance.NONE,
                               name=f"BAM specimen {specimen_id} grid", horizontal_units="mm",
                               origin_description="specimen grid origin (x = 0 at the thick-step "
                                                  "end, y = 0 at one long side), per the publisher"),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="instrument time zero", positive_down=True,
                                   n_samples=int(g.z.size), sample_interval=float(g.z[1] - g.z[0])),
        n_positions=int(g.x.size * g.y.size), position_index_name="grid_node",
        assumptions=[Assumption(key="grid_units", value={"x": "mm", "y": "mm", "z": "ns"},
                                basis=doc, verified=False)],
        source_metadata={"dzt_header": s.dzt_header, "gridded_acquisition": True})
    save_frames(dataset_id, [frame])

    ds = Dataset(id=dataset_id, name=name or f"BAM {specimen_id} {scan.replace('_', ' ')}",
                 source="BAM (Harvard Dataverse)", source_url="https://doi.org/10.7910/DVN/FCMUJQ",
                 license="CC0", sensor_type="gpr", original_format="bam_npy_grid",
                 coordinate_system="local (specimen grid, mm)", frequency=scan.split("_GHz")[0].replace("_", ".") + " GHz",
                 checksum=geometry.array_sha256, record_count=0, owner_id=owner_id,
                 has_ground_truth=True,
                 extra_metadata={"gridded_acquisition": {"frame_id": frame_id, "shape": list(geometry.shape)},
                                 "benchmark": {"benchmark_id": "bam-concrete-gpr", "specimen_id": specimen_id,
                                               "scan_id": scan_id,
                                               "ground_truth_role": "overlay and evaluation only; "
                                                                    "never an input to reconstruction"}})
    db.add(ds)
    db.commit()
    return dataset_id
