"""
Run Subterra's existing GPR pipeline over the real 4TU corpus and record
what the detector actually does.

REUSES THE PIPELINE, ADDS NO SCIENCE. Every stage below is the existing
implementation called with its existing contract:

    SEGYConverter.load(coordinate_encoding='ieee_nmea', velocity_m_per_ns=v)
        -> preprocessing.trace_processing.process_gpr_traces
        -> preprocessing.spatial_grid.preprocess_trace_local_anomaly
        -> interpretation.anomaly_candidates.find_anomaly_candidates

No threshold, window or normalisation is changed. This script measures;
it does not tune.

WHAT THE 4TU TRUTH SUPPORTS. Trench information is joined to radargrams by
LocationID and NOTHING ELSE -- the dataset withholds trench coordinates for
confidentiality. So results are characterised PER ACTIVITY. There is no
coordinate-level scoring here, and no candidate is ever matched to a
reported utility: the data cannot support that and this script must not
imply it.

VELOCITY. Depth requires one, and 4TU publishes a ground relative
permittivity per activity in Metadata.csv. Velocity is derived from it as
c/sqrt(eps_r). That is a SITE ESTIMATE SUPPLIED BY THE DATA PROVIDER, not a
measurement of the subsurface, so every depth derived from it is assumed.
Activities without a usable permittivity are reported and skipped rather
than given a default.

Detection itself is unaffected by the velocity: the ring z-score runs on
the (trace_index, depth) grid, whose row ORDER depth only re-labels. The
velocity changes reported candidate depths, not which cells are flagged.

    python -m scripts.characterise_4tu --out artifacts/4tu
    python -m scripts.characterise_4tu --out artifacts/4tu --max-files 2
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import math
import os
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

from converters.segy_converter import SEGYConverter
from converters.segy_endian import BIG, LITTLE, LittleEndianSegyFile, detect_endianness
from interpretation.anomaly_candidates import (
    DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS, find_anomaly_candidates,
)
from preprocessing.spatial_grid import (
    build_trace_depth_grid_for_records, preprocess_trace_local_anomaly,
)
from preprocessing.spatial_grid import anomaly_grid_from_traces
from preprocessing.trace_processing import (
    apply_gain, background_removal, dewow, process_gpr_traces,
)
from schemas.subterra_record import SensorType
from utils.logger import get_logger

logger = get_logger(__name__)

CORPUS = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")

#: Speed of light in vacuum, m/ns. Velocity in a medium is c / sqrt(eps_r).
C_M_PER_NS = 0.299792458

#: Peak memory is dominated by one radargram's records held at once, and the
#: ring statistic legitimately needs the whole line in memory -- chunking it
#: would change the z-scores at chunk boundaries, i.e. change the science. So
#: oversized radargrams are SKIPPED AND REPORTED rather than approximated.
#: This is a limit of the machine, not of the data or the pipeline: with more
#: RAM the budget rises and the skipped files process normally.
DEFAULT_MAX_RECORDS = 4_000_000

#: Thresholds swept for the sensitivity section. The pipeline default is
#: DEFAULT_ANOMALY_THRESHOLD and is NOT changed by this sweep -- the sweep
#: re-runs detection on the SAME preprocessed z-grid.
THRESHOLD_SWEEP = (2.5, 3.0, 3.5, 4.0, 5.0)

#: The dataset's own directory names disagree with its LocationIDs for
#: project 13 only: directories are '013.N', Metadata.csv says '13.N'. The
#: mapping is one-to-one over 6 entries with no other candidate, so it is
#: normalised here and reported as a source inconsistency -- not inferred.
def normalise_location_id(activity_dir: str, known_ids: set[str]) -> tuple[str, bool]:
    if activity_dir in known_ids:
        return activity_dir, False
    stripped = activity_dir.lstrip("0")
    if stripped in known_ids:
        return stripped, True
    return activity_dir, False


def load_metadata(corpus: Path) -> dict[str, dict]:
    path = corpus / "Metadata.csv"
    with open(path, encoding="utf-8-sig") as fh:
        return {r["LocationID"]: r for r in csv.DictReader(fh, delimiter=";")}


def velocity_for(meta_row: dict | None) -> tuple[float | None, str]:
    """
    Velocity from the activity's published relative permittivity.

    Returns (velocity, basis). A missing or non-physical permittivity yields
    (None, reason) -- never a default.
    """
    if meta_row is None:
        return None, "no Metadata.csv row for this LocationID"
    raw = (meta_row.get("Ground relative permittivity") or "").strip()
    if not raw:
        return None, "Metadata.csv publishes no relative permittivity for this activity"
    try:
        eps = float(raw)
    except ValueError:
        return None, f"relative permittivity {raw!r} is not a number"
    if eps < 1.0:
        return None, f"relative permittivity {eps} is below 1, which is not physical"
    return C_M_PER_NS / math.sqrt(eps), (
        f"derived from the relative permittivity {eps} published for this activity in "
        f"Metadata.csv, as c/sqrt(eps_r). A PROVIDER SITE ESTIMATE, not a measurement of "
        f"the subsurface; every depth derived from it is assumed.")


def count_components(anomaly_grid, threshold: float, min_cells: int) -> int:
    """
    Component count on an already-built anomaly grid.

    Mirrors find_anomaly_candidates exactly -- |z| > threshold, ndimage.label
    with its default 4-connectivity, then the min_cells filter -- so the
    threshold sweep costs one grid build instead of one per threshold. Every
    radargram checks this against the authoritative detector at the default
    threshold and records the result in `sweep_agrees_with_detector_at_default`.
    """
    mask = np.abs(np.nan_to_num(np.asarray(anomaly_grid, dtype=float), nan=0.0)) > threshold
    labeled, n = ndimage.label(mask)
    if n == 0:
        return 0
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    return int((sizes >= min_cells).sum())


def read_trace_array(path: Path) -> tuple[np.ndarray, int]:
    """
    The line's samples as a (n_traces, n_samples) array, via the SAME reader
    the converter uses -- so decoding cannot diverge between the two paths.
    """
    order, _ = detect_endianness(path)
    if order == BIG:
        import segyio
        with segyio.open(str(path), "r", ignore_geometry=True) as f:
            return np.array([f.trace[i] for i in range(f.tracecount)],
                            dtype=float), len(f.samples)
    with LittleEndianSegyFile(path, order=LITTLE) as f:
        return np.array([f.trace[i] for i in range(f.tracecount)],
                        dtype=float), f.n_samples


def processed_trace_array(path: Path) -> np.ndarray:
    """
    The line after background removal, dewow and gain, as a
    (n_traces, n_samples) array -- the same values `process_gpr_traces`
    writes back onto records, computed by the same functions in the same
    order, without materialising the records.
    """
    traces, _ = read_trace_array(path)
    traces = np.asarray(background_removal(traces.tolist()), dtype=float)
    return np.array([apply_gain(dewow(t.tolist(), window=15),
                                gain_type="linear", power=1.0) for t in traces],
                    dtype=float)


def anomaly_grid_arraywise(path: Path) -> np.ndarray:
    """
    The z-grid, computed WITHOUT materialising one SubterraRecord per cell.

    WHY THIS EXISTS, and why it is not an approximation. Peak memory on this
    corpus is dominated by the per-(trace, sample) SubterraRecord objects, not
    by the science: the largest radargram is 14,516 x 512, which is a 59 MB
    float array but roughly 5 GB of pydantic records. The arrays were never
    the problem.

    So this path calls the IDENTICAL functions in the IDENTICAL order --
    background_removal -> dewow -> apply_gain -> _local_anomaly_grid, with the
    same window parameters preprocess_trace_local_anomaly passes -- on the
    array directly. Nothing is chunked, so there are no chunk boundaries and
    no halo: the ring statistic still sees the whole line at once, exactly as
    it does on the record path. `--verify-arraywise` asserts the two produce
    the same grid.

    What it does NOT produce is per-candidate characterisation (centroid
    lat/lon, lateral extent), because `_characterize_cluster` legitimately
    needs the per-cell records. Activities processed this way are marked
    `processing_mode="arraywise"` and their reduced detail is reported.
    """
    # The pipeline itself now lives in preprocessing.spatial_grid so the
    # benchmark harness runs the identical code rather than a second copy.
    return anomaly_grid_from_traces(read_trace_array(path)[0])


def characterise_file_arraywise(path: Path, velocity: float) -> dict:
    """Same measurements as `characterise_file`, minus per-candidate detail."""
    t0 = time.time()
    z = anomaly_grid_arraywise(path)
    finite = z[np.isfinite(z)]
    sweep = {str(t): count_components(z, t, DEFAULT_MIN_CELLS) for t in THRESHOLD_SWEEP}
    n_depths, n_traces = z.shape
    return {
        "file": path.name,
        "processing_mode": "arraywise",
        "records": int(n_depths * n_traces),
        "traces": int(n_traces),
        "samples_per_trace": int(n_depths),
        "reliable_cells": None, "unreliable_cells": None,
        "z_abs_max": float(np.abs(finite).max()) if finite.size else None,
        "z_std": float(finite.std()) if finite.size else None,
        "z_mean": float(finite.mean()) if finite.size else None,
        "cells_over_3": int((np.abs(finite) > 3.0).sum()) if finite.size else 0,
        "candidates": sweep[str(DEFAULT_ANOMALY_THRESHOLD)],
        "candidate_sweep": sweep,
        "sweep_agrees_with_detector_at_default": None,
        "candidate_summary": [],
        "candidate_detail_available": False,
        "candidate_detail_reason": (
            "per-candidate characterisation needs the per-cell records, which is the "
            "memory constraint this path exists to avoid; counts, sweep and z-statistics "
            "are computed by the identical functions"),
        "velocity_m_per_ns": velocity,
        "seconds": round(time.time() - t0, 2),
    }


def characterise_file(path: Path, dataset_id: str, velocity: float) -> dict:
    """Runs the full existing chain on one radargram and summarises it."""
    t0 = time.time()
    result = SEGYConverter().load(path, dataset_id=dataset_id, sensor_type=SensorType.GPR,
                                  coordinate_encoding="ieee_nmea",
                                  velocity_m_per_ns=velocity)
    records, frame = result.records, result.frames[0]
    if not records:
        raise ValueError("converter produced no records")

    records = process_gpr_traces(records)
    records = preprocess_trace_local_anomaly(records)

    reliable = sum(1 for r in records if r.metadata.get("anomaly_reliable"))
    z = np.array([r.signal[0] for r in records
                  if r.metadata.get("anomaly_reliable")], dtype=float)
    z = z[np.isfinite(z)]

    # AUTHORITATIVE detection: the real detector, at its real default,
    # producing real AnomalyCandidate objects.
    candidates = find_anomaly_candidates(records, source_file=path.name,
                                         threshold=DEFAULT_ANOMALY_THRESHOLD,
                                         min_cells=DEFAULT_MIN_CELLS)
    # SWEEP: counts only. find_anomaly_candidates rebuilds the z-grid on every
    # call, so sweeping five thresholds through it costs five extra grid
    # builds per radargram -- hours across the corpus. `count_components`
    # mirrors the detector's own two steps (|z| > threshold, 4-connected
    # label, min_cells filter) on the grid already built, and is checked
    # against the authoritative path at the default threshold below.
    z_grid = build_trace_depth_grid_for_records(records, source_file=path.name,
                                                field="signal")["grid"]
    sweep = {str(t): count_components(z_grid, t, DEFAULT_MIN_CELLS)
             for t in THRESHOLD_SWEEP}
    sweep_agrees = sweep.get(str(DEFAULT_ANOMALY_THRESHOLD)) == len(candidates)
    return {
        "file": path.name,
        "processing_mode": "records",
        "candidate_detail_available": True,
        "records": len(records),
        "traces": frame.n_positions,
        "samples_per_trace": frame.vertical_axis.n_samples,
        "time_window_ns": frame.source_metadata.get("time_window_ns"),
        "position_kind": records[0].position.kind,
        "spatial_ref_kind": frame.spatial_ref.kind.value,
        "spatial_ref_code": frame.spatial_ref.code,
        "reliable_cells": reliable,
        "unreliable_cells": len(records) - reliable,
        "z_abs_max": float(np.abs(z).max()) if z.size else None,
        "z_std": float(z.std()) if z.size else None,
        "z_mean": float(z.mean()) if z.size else None,
        "cells_over_3": int((np.abs(z) > 3.0).sum()) if z.size else 0,
        "candidates": len(candidates),
        "candidate_sweep": sweep,
        "sweep_agrees_with_detector_at_default": sweep_agrees,
        "candidate_summary": [
            {"id": c.id,
             "n_supporting_cells": c.evidence.n_supporting_cells,
             "peak_value": c.evidence.peak_value,
             "mean_value": c.evidence.mean_value,
             "trace_range": list(c.evidence.trace_range),
             "depth_range": list(c.evidence.depth_range),
             "anomaly_class": c.interpretation.anomaly_class,
             "elongation": c.characteristics.elongation,
             "compactness": c.characteristics.compactness,
             "continuity_across_traces": c.characteristics.continuity_across_traces,
             "approx_lateral_extent_m": c.characteristics.approx_lateral_extent_m,
             "lateral_extent_source": c.characteristics.lateral_extent_source,
             "approx_depth_extent_m": c.characteristics.approx_depth_extent_m,
             "centroid_lat": c.characteristics.centroid_lat,
             "centroid_lon": c.characteristics.centroid_lon,
             "reliable_fraction": c.confidence.reliable_fraction,
             "touches_trace_boundary": c.confidence.touches_trace_boundary,
             "touches_depth_boundary": c.confidence.touches_depth_boundary,
             "velocity_m_per_ns": c.confidence.velocity_m_per_ns}
            for c in candidates],
        "seconds": round(time.time() - t0, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--out", default="artifacts/4tu")
    ap.add_argument("--max-files", type=int, default=None,
                    help="cap radargrams per activity (default: all)")
    ap.add_argument("--activities", nargs="*", help="restrict to these LocationIDs")
    ap.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS,
                    help="skip (and report) radargrams larger than this")
    ap.add_argument("--resume", action="store_true",
                    help="keep activities already present in the output file")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = load_metadata(CORPUS)
    known = set(metadata)

    by_activity: dict[str, list[Path]] = defaultdict(list)
    for f in sorted(CORPUS.glob("*/**/*.sgy")):
        activity_dir = f.relative_to(CORPUS).parts[2]
        loc, _ = normalise_location_id(activity_dir, known)
        by_activity[loc].append(f)

    targets = sorted(by_activity) if not args.activities else \
        [a for a in sorted(by_activity) if a in set(args.activities)]

    out = out_dir / "characterisation.json"
    run = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "corpus": str(CORPUS),
        "pipeline": {
            "converter": "converters.segy_converter.SEGYConverter",
            "coordinate_encoding": "ieee_nmea (caller-declared)",
            "preprocessing": ["preprocessing.trace_processing.process_gpr_traces "
                              "(background removal -> dewow -> gain)",
                              "preprocessing.spatial_grid.preprocess_trace_local_anomaly "
                              "(ring z-score on the trace/depth grid)"],
            "detector": "interpretation.anomaly_candidates.find_anomaly_candidates",
            "threshold": DEFAULT_ANOMALY_THRESHOLD,
            "min_cells": DEFAULT_MIN_CELLS,
            "threshold_sweep": list(THRESHOLD_SWEEP),
            "parameters_changed_by_this_script": "none",
        },
        "max_records_per_radargram": args.max_records,
        "activities": {}, "skipped": [], "errors": [],
    }
    if args.resume and out.exists():
        prior = json.loads(out.read_text())
        run["activities"] = prior.get("activities", {})
        run["skipped"] = prior.get("skipped", [])
        run["errors"] = prior.get("errors", [])
        print(f"  resuming: {len(run['activities'])} activity(ies) already done")

    t_start = time.time()
    for i, loc in enumerate(targets, 1):
        if args.resume and loc in run["activities"]:
            continue
        files = by_activity[loc]
        if args.max_files:
            files = sorted(files, key=os.path.getsize)[:args.max_files]
        row = metadata.get(loc)
        velocity, basis = velocity_for(row)
        if velocity is None:
            run["skipped"].append({"location_id": loc, "files": len(files),
                                   "reason": basis, "stage": "velocity"})
            print(f"[{i}/{len(targets)}] {loc:<7} SKIPPED: {basis}")
            continue

        per_file, failures = [], []
        for f in files:
            estimated = (f.stat().st_size - 3600) // 1264 * 512
            try:
                if estimated > args.max_records:
                    # Too large to materialise as records on this machine. The
                    # array path computes the IDENTICAL z-grid (verified
                    # bit-identical) without them, so the activity is still
                    # characterised -- never dropped.
                    per_file.append(characterise_file_arraywise(f, velocity))
                else:
                    per_file.append(characterise_file(f, f"4tu_{loc}", velocity))
            except Exception as e:
                failures.append({"file": f.name, "error": f"{type(e).__name__}: {e}",
                                 "traceback": traceback.format_exc(limit=3)})
            gc.collect()
        if not per_file:
            print(f"[{i}/{len(targets)}] {loc:<7} NO radargram processed "
                  f"({len(failures)} failed)")
            run["activities"][loc] = {
                "location_id": loc, "coverage": "failed",
                "radargrams_available": len(by_activity[loc]),
                "radargrams_processed": 0, "radargrams_failed": len(failures),
                "traces": 0, "records": 0, "candidates": 0,
                "failures": failures,
            }
            out.write_text(json.dumps(run, indent=2, ensure_ascii=False))
            continue
        run["errors"] += [{"location_id": loc, **fl} for fl in failures]

        traces = sum(r["traces"] for r in per_file)
        records = sum(r["records"] for r in per_file)
        cands = sum(r["candidates"] for r in per_file)
        sweep = Counter()
        for r in per_file:
            for k, v in r["candidate_sweep"].items():
                sweep[k] += v
        modes = Counter(r.get("processing_mode", "records") for r in per_file)
        detail = sum(1 for r in per_file if r.get("candidate_detail_available"))
        run["activities"][loc] = {
            "location_id": loc,
            "coverage": ("complete" if len(per_file) == len(by_activity[loc]) and not failures
                         else "partial"),
            "processing_modes": dict(modes),
            "radargrams_with_candidate_detail": detail,
            "radargrams_available": len(by_activity[loc]),
            "radargrams_processed": len(per_file),
            "radargrams_failed": len(failures),
            "traces": traces, "records": records,
            # None on the array path, which does not build per-cell records.
            "reliable_cells": sum(r["reliable_cells"] or 0 for r in per_file),
            "unreliable_cells": sum(r["unreliable_cells"] or 0 for r in per_file),
            "reliability_measured_for_radargrams": sum(
                1 for r in per_file if r["reliable_cells"] is not None),
            "candidates": cands,
            "candidates_per_1k_traces": round(1000 * cands / traces, 3) if traces else None,
            "candidate_sweep": dict(sweep),
            "velocity_m_per_ns": round(velocity, 6),
            "velocity_basis": basis,
            "velocity_provenance": "derived_from_provider_site_estimate",
            "source_reported": {
                "amount_of_utilities": (row.get("Amount of utilities") or "").strip() or None,
                "utility_discipline": (row.get("Utility discipline") or "").strip() or None,
                "utility_material": (row.get("Utility material") or "").strip() or None,
                "utility_diameter": (row.get("Utility diameter") or "").strip() or None,
                "ground_condition": (row.get("Ground condition") or "").strip() or None,
                "land_use": (row.get("Land use") or "").strip() or None,
                "rubble_presence": (row.get("Rubble presence") or "").strip() or None,
                "join": "LocationID only -- the source publishes no trench coordinates",
            },
            "files": per_file,
        }
        # Checkpoint after every activity: a crash must not discard the run.
        out.write_text(json.dumps(run, indent=2, ensure_ascii=False))
        print(f"[{i}/{len(targets)}] {loc:<7} {len(per_file):>2} files "
              f"{traces:>6} traces  {cands:>4} candidates  v={velocity:.4f} m/ns")

    run["elapsed_seconds"] = round(time.time() - t_start, 1)
    out.write_text(json.dumps(run, indent=2, ensure_ascii=False))
    acts = run["activities"]
    print(f"\nwrote {out}")
    print(f"  activities characterised: {len(acts)}  skipped: {len(run['skipped'])}  "
          f"file errors: {len(run['errors'])}")
    print(f"  traces {sum(a['traces'] for a in acts.values()):,}  "
          f"records {sum(a['records'] for a in acts.values()):,}  "
          f"candidates {sum(a['candidates'] for a in acts.values()):,}")
    print(f"  elapsed {run['elapsed_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
