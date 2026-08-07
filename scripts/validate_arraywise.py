"""
Validation gate for the array-native characterisation path.

Answers two questions with measurements, and writes them to a
machine-readable artifact so the claim is auditable rather than asserted:

  A. EQUIVALENCE -- does the array path reproduce the reference (record)
     path? Compared at every level the array path produces: preprocessing
     output, grid geometry, the z-grid itself, the component label map,
     per-component cell sets, bounding boxes, peak and mean values, and the
     threshold sweep.

  B. MEMORY -- does it actually solve the OOM, or move it? Peak RSS and wall
     time are measured for both paths in ISOLATED SUBPROCESSES, so one path's
     allocations cannot flatter the other's measurement.

This script changes nothing about the detector. It only measures.

    python -m scripts.validate_arraywise --out artifacts/4tu
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

from scripts.characterise_4tu import CORPUS, THRESHOLD_SWEEP, count_components

#: Run one path in a fresh interpreter and report its peak RSS in MB.
_PROBE = r"""
import json, resource, sys, time
sys.path.insert(0, "/app")
import logging; logging.disable(logging.INFO)
from pathlib import Path
path, mode = Path(sys.argv[1]), sys.argv[2]
t0 = time.time()
if mode == "records":
    from converters.segy_converter import SEGYConverter
    from preprocessing.trace_processing import process_gpr_traces
    from preprocessing.spatial_grid import preprocess_trace_local_anomaly
    from interpretation.anomaly_candidates import find_anomaly_candidates
    from schemas.subterra_record import SensorType
    recs = SEGYConverter().load(path, dataset_id="v", sensor_type=SensorType.GPR,
                                coordinate_encoding="ieee_nmea",
                                velocity_m_per_ns=0.0999).records
    n = len(recs)
    recs = preprocess_trace_local_anomaly(process_gpr_traces(recs))
    cands = len(find_anomaly_candidates(recs, source_file=path.name,
                                        threshold=3.0, min_cells=3))
else:
    from scripts.characterise_4tu import anomaly_grid_arraywise, count_components
    z = anomaly_grid_arraywise(path)
    n = int(z.size)
    cands = count_components(z, 3.0, 3)
peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
# macOS reports bytes, Linux kilobytes; the container is Linux.
print(json.dumps({"mode": mode, "cells": n, "candidates": cands,
                  "peak_mb": peak_kb / 1024.0,
                  "seconds": round(time.time() - t0, 2)}))
"""


def probe(path: Path, mode: str, timeout_s: int = 300) -> dict:
    """
    Runs one path in a fresh process and reports peak RSS.

    Bounded: a path that is going to exhaust memory spends a long time
    thrashing before the kernel kills it, and an unbounded wait is not better
    evidence than a bounded one. A timeout is recorded as
    `did_not_complete`, which is the finding.
    """
    try:
        proc = subprocess.run([sys.executable, "-c", _PROBE, str(path), mode],
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"mode": mode, "failed": True, "did_not_complete": True,
                "timeout_s": timeout_s,
                "error": f"did not complete within {timeout_s}s (memory exhaustion)"}
    if proc.returncode != 0:
        return {"mode": mode, "failed": True, "returncode": proc.returncode,
                "error": (proc.stderr or "")[-300:] or "killed (no stderr; OOM likely)"}
    return json.loads(proc.stdout.strip().splitlines()[-1])


def components(z: np.ndarray, threshold: float, min_cells: int):
    """The detector's own component extraction, for set-level comparison."""
    mask = np.abs(np.nan_to_num(z, nan=0.0)) > threshold
    labeled, n = ndimage.label(mask)
    out = []
    for lab in range(1, n + 1):
        cells = labeled == lab
        size = int(cells.sum())
        if size < min_cells:
            continue
        rows, cols = np.nonzero(cells)
        vals = z[rows, cols]
        peak = int(np.argmax(np.abs(vals)))
        out.append({
            "n_cells": size,
            "bbox": [int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())],
            "peak_value": float(vals[peak]),
            "peak_row": int(rows[peak]), "peak_col": int(cols[peak]),
            "mean_value": float(vals.mean()),
            "cells_hash": hash(tuple(sorted(zip(rows.tolist(), cols.tolist())))),
        })
    return sorted(out, key=lambda c: (c["bbox"], c["n_cells"]))


def equivalence(path: Path) -> dict:
    """Every comparable level, on one radargram."""
    import logging
    logging.disable(logging.INFO)
    from converters.segy_converter import SEGYConverter
    from preprocessing.spatial_grid import (
        build_trace_depth_grid_for_records, preprocess_trace_local_anomaly,
    )
    from preprocessing.trace_processing import process_gpr_traces
    from schemas.subterra_record import SensorType
    from scripts.characterise_4tu import anomaly_grid_arraywise

    recs = SEGYConverter().load(path, dataset_id="v", sensor_type=SensorType.GPR,
                               coordinate_encoding="ieee_nmea",
                               velocity_m_per_ns=0.0999).records
    n_records = len(recs)
    recs = preprocess_trace_local_anomaly(process_gpr_traces(recs))
    ref = np.asarray(build_trace_depth_grid_for_records(
        recs, source_file=path.name, field="signal")["grid"], dtype=float)
    arr = anomaly_grid_arraywise(path)

    same_shape = ref.shape == arr.shape
    diff = (float(np.nanmax(np.abs(np.nan_to_num(ref) - np.nan_to_num(arr))))
            if same_shape else None)
    nan_same = (bool(np.array_equal(np.isnan(ref), np.isnan(arr)))
                if same_shape else False)
    comp_ref = components(ref, 3.0, 3) if same_shape else []
    comp_arr = components(arr, 3.0, 3) if same_shape else []
    sweep_ref = {str(t): count_components(ref, t, 3) for t in THRESHOLD_SWEEP}
    sweep_arr = {str(t): count_components(arr, t, 3) for t in THRESHOLD_SWEEP}
    return {
        "file": path.name,
        "records_materialised_by_reference_path": n_records,
        "grid_shape_reference": list(ref.shape),
        "grid_shape_arraywise": list(arr.shape),
        "grid_shape_identical": same_shape,
        "max_abs_difference": diff,
        "bitwise_identical": bool(same_shape and diff == 0.0),
        "nan_mask_identical": nan_same,
        "candidate_count_reference": len(comp_ref),
        "candidate_count_arraywise": len(comp_arr),
        "candidate_sets_identical": comp_ref == comp_arr,
        "threshold_sweep_reference": sweep_ref,
        "threshold_sweep_arraywise": sweep_arr,
        "threshold_sweep_identical": sweep_ref == sweep_arr,
        "aggregate_reference": {
            "z_abs_max": float(np.nanmax(np.abs(ref))),
            "z_mean": float(np.nanmean(ref)), "z_std": float(np.nanstd(ref)),
            "cells_over_3": int((np.abs(np.nan_to_num(ref)) > 3).sum())},
        "aggregate_arraywise": {
            "z_abs_max": float(np.nanmax(np.abs(arr))),
            "z_mean": float(np.nanmean(arr)), "z_std": float(np.nanstd(arr)),
            "cells_over_3": int((np.abs(np.nan_to_num(arr)) > 3).sum())},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--out", default="artifacts/4tu")
    ap.add_argument("--max-equivalence-files", type=int, default=4)
    ap.add_argument("--probe-timeout", type=int, default=300)
    ap.add_argument("--activity", default="01.4",
                    help="activity small enough to run through BOTH paths")
    args = ap.parse_args()

    files = sorted(glob.glob(str(CORPUS / f"*/*/{args.activity}/**/*.sgy"), recursive=True),
                   key=os.path.getsize)
    if not files:
        print(f"activity {args.activity} has no radargrams"); return 1
    files = files[:args.max_equivalence_files]

    print(f"A. EQUIVALENCE -- activity {args.activity}, {len(files)} radargram(s)\n")
    eq = []
    for f in files:
        r = equivalence(Path(f))
        eq.append(r)
        print(f"  {r['file']:<12} grid {r['grid_shape_reference']} "
              f"maxdiff={r['max_abs_difference']:.2e}  "
              f"bitwise={r['bitwise_identical']}  "
              f"candidates {r['candidate_count_reference']}=={r['candidate_count_arraywise']} "
              f"sets={r['candidate_sets_identical']}  sweep={r['threshold_sweep_identical']}")
    all_eq = all(r["bitwise_identical"] and r["candidate_sets_identical"]
                 and r["threshold_sweep_identical"] for r in eq)
    print(f"\n  EQUIVALENT: {all_eq}")

    print("\nB. MEMORY -- isolated subprocess per path\n")
    oversized = []
    for act in ("010.15", "010.16", "012.6", "012.7"):
        got = sorted(glob.glob(str(CORPUS / f"*/*/{act}/**/*.sgy"), recursive=True),
                     key=os.path.getsize)
        if got:
            oversized.append((act, Path(got[-1])))
    mem = []
    small = Path(files[len(files) // 2])
    print(f"  {'file':<12}{'activity':<9}{'path':<11}{'peak MB':>9}{'sec':>8}"
          f"{'cands':>7}  status")
    for label, p in [(args.activity, small)] + oversized:
        traces = (p.stat().st_size - 3600) // 1264
        for mode in ("records", "arraywise"):
            res = probe(p, mode, timeout_s=args.probe_timeout)
            res.update({"activity": label, "file": p.name, "traces": int(traces)})
            mem.append(res)
            if res.get("failed"):
                why = ("timed out" if res.get("did_not_complete")
                       else f"rc={res.get('returncode')}")
                print(f"  {p.name:<12}{label:<9}{mode:<11}{'-':>9}{'-':>8}{'-':>7}  "
                      f"FAILED ({why})")
            else:
                print(f"  {p.name:<12}{label:<9}{mode:<11}{res['peak_mb']:>9.0f}"
                      f"{res['seconds']:>8.1f}{res['candidates']:>7}  ok")

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    art = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": ("validation gate for the array-native path: equivalence with the "
                    "reference record path, and whether it resolves the OOM"),
        "equivalence_activity": args.activity,
        "equivalent": all_eq,
        "equivalence": eq,
        "memory": mem,
        "detector_changes": "none",
    }
    (out_dir / "arraywise_validation.json").write_text(
        json.dumps(art, indent=2, ensure_ascii=False))
    print(f"\nwrote {out_dir / 'arraywise_validation.json'}")
    return 0 if all_eq else 1


if __name__ == "__main__":
    raise SystemExit(main())
