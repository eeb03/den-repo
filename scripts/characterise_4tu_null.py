"""
Null/background behaviour of the detector on the 4TU corpus.

4TU contains no designated background or control activity -- every survey
was walked where a trench was planned, so there is no "known-empty" ground
to measure a false-alarm rate against. The available substitute is the
permutation null already used for the INGV baseline: run the SAME detector
on data whose lateral structure has been destroyed but whose dimensions and
value multiset are identical. Anything the detector reports at or below that
rate is consistent with chance.

TRACE-ORDER PERMUTATION is the null used here. It permutes whole traces, so
each trace keeps its internal depth structure and only trace-to-trace
adjacency is destroyed -- the appropriate null for a detector whose
candidates are laterally connected components.
`assert_trace_permutation_equivalence` proves the cheap form (permute the
PROCESSED array) equals permuting raw traces and re-running the chain, so
the shortcut is verified rather than assumed.

This script MEASURES. It changes no threshold and no window.

    python -m scripts.characterise_4tu_null --out artifacts/4tu --files 40 --draws 30
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

from interpretation.anomaly_candidates import DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS
from preprocessing.spatial_grid import _local_anomaly_grid
from scripts.characterise_4tu import (
    CORPUS, load_metadata, normalise_location_id, processed_trace_array, velocity_for,
)
from utils.logger import get_logger
from validation.null_models import empirical_p_value, trace_permutation

logger = get_logger(__name__)


def count_candidates(anomaly: np.ndarray, threshold: float, min_cells: int) -> int:
    """
    The detector's component count on an anomaly grid.

    Mirrors find_anomaly_candidates' own two steps exactly -- |z| > threshold,
    then ndimage.label with default 4-connectivity, then the min_cells filter --
    without building AnomalyCandidate objects, which the null does not need.
    """
    mask = np.abs(np.nan_to_num(anomaly, nan=0.0)) > threshold
    labeled, n = ndimage.label(mask)
    if n == 0:
        return 0
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    return int((sizes >= min_cells).sum())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--out", default="artifacts/4tu")
    ap.add_argument("--files", type=int, default=40, help="radargrams to sample")
    ap.add_argument("--draws", type=int, default=30, help="null draws per radargram")
    ap.add_argument("--seed", type=int, default=20260807)
    args = ap.parse_args()

    metadata = load_metadata(CORPUS)
    known = set(metadata)
    all_files = sorted(glob.glob(str(CORPUS / "*/**/*.sgy"), recursive=True))
    rng_pick = random.Random(args.seed)
    sample = sorted(rng_pick.sample(all_files, min(args.files, len(all_files))))

    rng = np.random.default_rng(args.seed)
    rows, skipped = [], []
    t0 = time.time()
    for i, f in enumerate(sample, 1):
        path = Path(f)
        loc, _ = normalise_location_id(path.relative_to(CORPUS).parts[2], known)
        velocity, basis = velocity_for(metadata.get(loc))
        if velocity is None:
            skipped.append({"file": path.name, "location_id": loc, "reason": basis})
            continue
        try:
            # The PROCESSED array, before the anomaly step: the null permutes
            # this, then the identical ring statistic runs on each draw. Built
            # by `processed_trace_array`, which is the same functions in the
            # same order as the record path and is asserted bit-identical to
            # it -- and which does not materialise millions of records, so this
            # no longer exhausts memory on the larger radargrams.
            processed = processed_trace_array(path)              # (n_traces, n_samples)
            observed_grid = _local_anomaly_grid(processed.T)
            observed = count_candidates(observed_grid, DEFAULT_ANOMALY_THRESHOLD,
                                        DEFAULT_MIN_CELLS)
            draws = np.array([
                count_candidates(_local_anomaly_grid(trace_permutation(processed, rng).T),
                                 DEFAULT_ANOMALY_THRESHOLD, DEFAULT_MIN_CELLS)
                for _ in range(args.draws)], dtype=float)
            rows.append({
                "file": path.name, "location_id": loc,
                "shape": list(processed.shape),
                "observed_candidates": observed,
                "null_mean": float(draws.mean()), "null_max": float(draws.max()),
                "null_p95": float(np.percentile(draws, 95)),
                "p_value": empirical_p_value(float(observed), draws),
                "draws": args.draws,
            })
            print(f"[{i}/{len(sample)}] {path.name:<12} {loc:<7} observed={observed:<4} "
                  f"null mean={draws.mean():.2f} max={draws.max():.0f} "
                  f"p={rows[-1]['p_value']:.3f}")
        except Exception as e:
            skipped.append({"file": path.name, "location_id": loc,
                            "reason": f"{type(e).__name__}: {e}"})

    obs = np.array([r["observed_candidates"] for r in rows], dtype=float)
    nul = np.array([r["null_mean"] for r in rows], dtype=float)
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "null_model": "trace_permutation",
        "null_model_rationale": (
            "4TU has no designated background or control activity -- every survey was "
            "walked where a trench was planned -- so a false-alarm rate against known-empty "
            "ground cannot be measured. This permutation null is the available substitute."),
        "threshold": DEFAULT_ANOMALY_THRESHOLD, "min_cells": DEFAULT_MIN_CELLS,
        "parameters_changed_by_this_script": "none",
        "seed": args.seed, "files_sampled": len(sample), "files_measured": len(rows),
        "draws_per_file": args.draws,
        "observed_total": int(obs.sum()) if obs.size else 0,
        "null_mean_total": float(nul.sum()) if nul.size else 0.0,
        "observed_mean_per_file": float(obs.mean()) if obs.size else None,
        "null_mean_per_file": float(nul.mean()) if nul.size else None,
        "files_with_observed_above_null_p95": int(sum(
            1 for r in rows if r["observed_candidates"] > r["null_p95"])),
        "files_with_p_below_0_05": int(sum(1 for r in rows if r["p_value"] < 0.05)),
        "per_file": rows, "skipped": skipped,
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "null.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {out_dir / 'null.json'}")
    print(f"  measured {len(rows)} file(s), skipped {len(skipped)}")
    if obs.size:
        print(f"  observed {obs.sum():.0f} candidates vs null mean {nul.sum():.1f}")
        print(f"  files above their own null p95: {out['files_with_observed_above_null_p95']}"
              f"/{len(rows)};  p<0.05: {out['files_with_p_below_0_05']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
