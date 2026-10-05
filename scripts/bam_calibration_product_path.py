"""
BAM through the PRODUCT path: does the DEPTH_CALIBRATION declaration reproduce
the known-geometry duct depths the research study measured?

    python -m scripts.bam_calibration_product_path [--specimen Pk266] [--out FILE]

Needs `datasets/raw/bam_concrete/<specimen>_Dataset.zip` (Harvard Dataverse
doi:10.7910/DVN/FCMUJQ, CC0; Pk266: 888,611,774 B, MD5 e43ea0991a1e7b842d4e20d89b0b30f7).

WHAT IS INDEPENDENT OF WHAT.
- Calibration reflectors: the four back-wall steps, picked by the research
  script's unchanged pre-registered rule (envelope peaks in object-free windows;
  `scripts/bam_quantitative_validation.py`), depths = fabricated thicknesses
  from the drawings. No duct is used to calibrate.
- Duct times: the research script's unchanged known-position picker
  (`target_time`). Duct depths from the drawings (evidence/bam/specimen_ground_truth.csv).
- Pre-registered here, before any product-path output was seen:
  pick_convention "peak" (envelope peaks), pick_precision_ns 0.1 (~3 samples),
  default leave-one-out tolerance 0.10 m; central line y = 400 mm.

WHAT THE PRODUCT PATH IS. Per-sample SubterraRecords of one real line are saved
to a temporary data root; the declaration is validated and applied by
`api.spatial` (the same functions the HTTP route calls); depth is read back from
the STORED records -- so frame wiring, time-zero application and depth
rederivation are all exercised, not just the fit.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np

from scripts.bam_quantitative_validation import (
    STEP_THICKNESS_MM, backwall_candidates, load_gt, select_backwall, step_of, target_time,
)

PICK_CONVENTION = "peak"
PICK_PRECISION_NS = 0.1
LINE_Y_MM = 400.0


def calibration_points(specimen, times):
    return [{"depth_m": STEP_THICKNESS_MM[specimen][k] / 1000.0, "time_ns": float(times[k]),
             "depth_source": "fabrication_drawing",
             "depth_evidence": (f"Grohmann et al. 2026 (Data in Brief 68:113103) appendix "
                                f"drawings: back-wall step {k} thickness "
                                f"{STEP_THICKNESS_MM[specimen][k]} mm"),
             "reflector_id": f"{specimen}-backwall-step{k}"} for k in range(4)]


def product_path(vol, grid, dt, specimen, scan, points):
    """Store one line, declare the calibration through api.spatial, read depth back."""
    from configs.settings import settings
    from database.frames_store import save_frames
    from database.records_store import load_records, save_records
    from schemas.spatial import AxisKind, CRSKind, SpatialRef, VerticalAxis
    from schemas.spatial_reference import DeclarationKind
    from schemas.subterra_record import GroundTruthLabel, SensorType, SubterraRecord
    from schemas.survey_frame import SurveyFrame

    import api.spatial as service

    dataset_id, frame_id = f"bam_{specimen}", f"bam_{specimen}:{scan}:y{int(LINE_Y_MM)}"
    j = int(np.argmin(np.abs(grid.y - LINE_Y_MM)))
    records = []
    for i in range(vol.shape[0]):
        for k in range(vol.shape[2]):
            records.append(SubterraRecord.model_construct(
                dataset_id=dataset_id, latitude=None, longitude=None, elevation=None,
                depth=None, signal=[float(vol[i, j, k])], sensor_type=SensorType.GPR,
                ground_truth=GroundTruthLabel.NONE, frame_id=frame_id,
                metadata={"source_file": f"{scan}.npy", "trace_index": i, "sample_index": k,
                          "two_way_time_ns": k * dt, "x_mm": float(grid.x[i])}))
    frame = SurveyFrame(
        frame_id=frame_id, dataset_id=dataset_id, modality=SensorType.GPR,
        source_format="npy", source_file=f"{scan}.npy",
        spatial_ref=SpatialRef(kind=CRSKind.UNKNOWN, name="BAM specimen grid (mm)"),
        vertical_axis=VerticalAxis(kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                                   origin="instrument time zero", positive_down=True),
        n_positions=vol.shape[0], position_index_name="trace_index")

    with tempfile.TemporaryDirectory() as root:
        old = settings.data_root
        settings.data_root = Path(root)
        try:
            for name in ("processed", "raw", "metadata"):
                (Path(root) / name).mkdir(parents=True, exist_ok=True)
            save_records(dataset_id, records)
            save_frames(dataset_id, [frame])
            value = service.validate_declaration(
                DeclarationKind.DEPTH_CALIBRATION,
                {"points": points, "pick_convention": PICK_CONVENTION,
                 "pick_precision_ns": PICK_PRECISION_NS})
            applied = service.apply_declaration(
                dataset_id, DeclarationKind.DEPTH_CALIBRATION, value,
                supplied_by="BAM drawings (product-path validation)", frame_id=frame_id,
                declaration_id="product-path-check")
            stored = load_records(dataset_id, use_cache=False)
        finally:
            settings.data_root = old
    by_key = {(r.metadata["trace_index"], r.metadata["sample_index"]): r for r in stored}
    return value["fit"], applied, by_key


def run(specimen: str, scan: str) -> dict:
    from benchmark.bam_ingest import load_scan, load_volume

    s = load_scan(specimen, f"{specimen}_3D_Dataset_{scan}")
    vol, grid = load_volume(s), s.grid
    dt = float(grid.z[1] - grid.z[0])
    targets_all, boreholes_all = load_gt()
    targets = targets_all.get(specimen, [])
    boreholes = [b for b in boreholes_all if b["id"].startswith(specimen)]
    sel = select_backwall(backwall_candidates(vol, grid, dt, targets, boreholes),
                          STEP_THICKNESS_MM[specimen])
    if sel["as_drawn"] is None:
        return {"specimen": specimen, "scan": scan, "status": "no back-wall selection"}
    times = sel["as_drawn"]["times"]
    points = calibration_points(specimen, times)
    try:
        fit, applied, by_key = product_path(vol, grid, dt, specimen, scan, points)
    except Exception as exc:  # a refused calibration is a result, not a crash
        return {"specimen": specimen, "scan": scan, "status": "calibration refused",
                "reason": str(exc), "backwall_times_ns": times}

    rows = []
    for t in targets:
        if "duct" not in t["type"]:
            continue
        tt, contrast = target_time(vol, grid, dt, t, times[step_of(t["x"])])
        i = int(np.argmin(np.abs(grid.x - t["x"])))
        k = int(round(tt / dt))
        rec = by_key[(i, k)]
        d_stored = None if rec.depth is None else rec.depth * 1000.0
        d_direct = (tt - fit["t0_ns"]) * fit["velocity_m_per_ns"] / 2 * 1000.0
        rows.append({"target": t["id"], "type": t["type"], "t_pick_ns": round(tt, 4),
                     "z_top_mm": t["z_top"],
                     "stored_depth_mm": None if d_stored is None else round(d_stored, 1),
                     "fit_depth_mm": round(d_direct, 1),
                     "err_top_mm": None if d_stored is None else round(d_stored - t["z_top"], 1),
                     "stored_record_derivation_id": rec.metadata.get("depth_derivation_id")})
    errs = [r["err_top_mm"] for r in rows if r["err_top_mm"] is not None]
    return {"specimen": specimen, "scan": scan, "status": "calibrated",
            "pre_registered": {"pick_convention": PICK_CONVENTION,
                               "pick_precision_ns": PICK_PRECISION_NS, "line_y_mm": LINE_Y_MM},
            "fit": fit, "frames_changed": applied["frames_changed"],
            "ducts": rows,
            "duct_error_top_mm": {"n": len(errs),
                                  "mean": round(float(np.mean(errs)), 1) if errs else None,
                                  "max_abs": round(float(np.max(np.abs(errs))), 1) if errs else None}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--specimen", default="Pk266")
    ap.add_argument("--scans", nargs="*", default=["1_5_GHz_Rot00", "2_6_GHz_Rot00"])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    out = [run(args.specimen, scan) for scan in args.scans]
    for r in out:
        if r["status"] != "calibrated":
            print(r["specimen"], r["scan"], r["status"], r.get("reason", ""))
            continue
        f = r["fit"]
        print(f"{r['specimen']} {r['scan']}: t0 {f['t0_ns']} ns, v {f['velocity_m_per_ns']} m/ns, "
              f"rms {f['rms_residual_ns']} ns, redundant {f['redundant']}; ducts "
              f"{r['duct_error_top_mm']}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
