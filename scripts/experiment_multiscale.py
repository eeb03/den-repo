"""
Multi-scale estimator experiment: baseline vs candidate.

Stages, in the order they MUST run:

    synthetic   the mechanistic falsification test. Width sweep, amplitude
                sweep, noise-only control. If the candidate fails here the
                experiment STOPS -- there is no point asking a benchmark
                whether a mechanism works when the mechanism demonstrably
                does not.

    calibrate   pick the candidate's single global threshold on the ATTESTED
                EMPTY control specimen only, matching the baseline's control
                false-alarm rate. Never looks at Pk266 or 4TU.

    (later stages are run only after these two are reported)

CALIBRATION RULE, pre-specified. The frozen baseline uses ONE global threshold
(3.0) for both BAM frequencies and for 4TU -- it has no per-frequency
calibration. So the candidate gets ONE global threshold too, or it would enjoy
more free parameters than the baseline. It is chosen so the candidate's POOLED
detections-per-line on Pk050 match the baseline's pooled rate, then frozen.

Nothing here writes to an existing artifact. New results go to new filenames so
the frozen baseline artifacts, and anything consuming them, are untouched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from preprocessing.multiscale_anomaly import (
    SCALES, describe_scales, multiscale_anomaly_grid,
)
from preprocessing.spatial_grid import anomaly_grid_from_traces

BASELINE = "baseline_ring"
CANDIDATE = "multiscale_ring"

ESTIMATORS = {
    BASELINE: anomaly_grid_from_traces,
    CANDIDATE: multiscale_anomaly_grid,
}


# --------------------------------------------------------------- synthetic

def _top_hat(width: int, amplitude: float = 1.0, height: int = 10,
             n_traces: int = 160, n_samples: int = 240, noise: float = 0.0,
             seed: int = 0) -> np.ndarray:
    """
    The same construction that demonstrated the baseline failure: a rectangular
    target of a given lateral WIDTH in traces, on a flat (optionally noisy)
    background. Returned as (n_traces, n_samples).
    """
    rng = np.random.default_rng(seed)
    t = rng.normal(scale=noise, size=(n_traces, n_samples)) if noise else np.zeros((n_traces, n_samples))
    c, s = n_traces // 2, n_samples // 2
    lo = c - width // 2
    t[lo:lo + width, s - height // 2:s - height // 2 + height] += amplitude
    return t


def _centre_response(grid: np.ndarray, n_traces: int = 160, n_samples: int = 240) -> float:
    """|z| at the target centre. NaN (unreliable everywhere) reports as nan."""
    v = grid[n_samples // 2, n_traces // 2]
    return float(abs(v)) if np.isfinite(v) else float("nan")


def width_sweep(widths, noise: float = 0.02, seed: int = 11) -> list[dict]:
    rows = []
    for w in widths:
        t = _top_hat(w, noise=noise, seed=seed)
        rows.append({
            "width_traces": int(w),
            "baseline": _centre_response(anomaly_grid_from_traces(t)),
            "candidate": _centre_response(multiscale_anomaly_grid(t)),
        })
    return rows


def amplitude_sweep(amplitudes, width: int = 13, noise: float = 0.02,
                    seed: int = 12) -> list[dict]:
    """
    At a width where the BASELINE is saturated.

    This is the test that separates a genuine scale fix from a blanket
    sensitivity increase: the baseline is exactly amplitude-invariant when
    saturated, so if the candidate is invariant too, it is still saturated and
    any later benchmark gain cannot be attributed to scale recovery.
    """
    rows = []
    for a in amplitudes:
        t = _top_hat(width, amplitude=a, noise=noise, seed=seed)
        rows.append({
            "amplitude": float(a),
            "baseline": _centre_response(anomaly_grid_from_traces(t)),
            "candidate": _centre_response(multiscale_anomaly_grid(t)),
        })
    return rows


def noise_only(n: int = 12, seed: int = 13) -> dict:
    """
    Pure noise, no target. Reports the distribution of |z| for each estimator.

    CAUTION when reading this: white noise turns out NOT to predict real
    radargram behaviour. The two estimators fire at almost the same rate here,
    but on real data the candidate fires 3.5x more on the BAM control and 17x
    more on a 4TU line. An early reading of this result as "comparable noise
    floors, therefore better SNR" was withdrawn for exactly that reason -- see
    docs/detector-multiscale-experiment.md section 0.1. This measurement stands
    only as a statement about white noise.
    """
    out = {}
    for name, est in ESTIMATORS.items():
        peaks, over3 = [], []
        for i in range(n):
            rng = np.random.default_rng(seed + i)
            g = est(rng.normal(size=(160, 240)))
            a = np.abs(np.nan_to_num(g, nan=0.0))
            peaks.append(float(a.max()))
            over3.append(float((a > 3.0).mean()))
        out[name] = {
            "max_abs_z_mean": float(np.mean(peaks)),
            "fraction_over_3_mean": float(np.mean(over3)),
            "fraction_over_3_max": float(np.max(over3)),
        }
    return out


def assess(widths: list[dict], amps: list[dict]) -> dict:
    """
    The falsifiable verdict, decided by pre-stated rules rather than by eye.

    Retention: the candidate must still respond beyond the baseline's measured
    saturation onset. Amplitude: the candidate must not be amplitude-invariant
    where the baseline is.
    """
    def rel(rows, key, lo, hi):
        vals = [r[key] for r in rows if lo <= r["width_traces"] <= hi
                and np.isfinite(r[key])]
        return float(np.mean(vals)) if vals else float("nan")

    narrow_b, narrow_c = rel(widths, "baseline", 1, 3), rel(widths, "candidate", 1, 3)
    wide_b, wide_c = rel(widths, "baseline", 12, 48), rel(widths, "candidate", 12, 48)

    b_amp = [r["baseline"] for r in amps]
    c_amp = [r["candidate"] for r in amps]
    b_invariant = float(np.nanstd(b_amp)) < 1e-6
    c_invariant = float(np.nanstd(c_amp)) < 1e-6

    return {
        "baseline_narrow_mean_abs_z": narrow_b,
        "baseline_wide_mean_abs_z": wide_b,
        "candidate_narrow_mean_abs_z": narrow_c,
        "candidate_wide_mean_abs_z": wide_c,
        "baseline_retention_wide_over_narrow": wide_b / narrow_b if narrow_b else float("nan"),
        "candidate_retention_wide_over_narrow": wide_c / narrow_c if narrow_c else float("nan"),
        "baseline_amplitude_invariant_at_saturated_width": b_invariant,
        "candidate_amplitude_invariant_at_saturated_width": c_invariant,
        "candidate_retains_response_beyond_baseline_saturation": bool(wide_c > wide_b * 1.5),
        "mechanistically_falsified": bool(c_invariant or wide_c <= wide_b * 1.5),
    }


def run_synthetic(out: Path) -> dict:
    widths = [1, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 24, 32, 40, 48, 56, 64]
    amps = [0.1, 1.0, 10.0, 100.0, 1000.0]

    report = {
        "stage": "synthetic_falsification",
        "purpose": ("does the candidate retain discriminative anomaly response "
                    "after the baseline's width-saturation point?"),
        "scales": describe_scales(),
        "asymmetry_note": ("the candidate changes spatial scale only; the baseline "
                           "ring's lateral asymmetry is intentionally preserved"),
        "width_sweep": width_sweep(widths),
        "amplitude_sweep_at_saturated_width_13": amplitude_sweep(amps),
        "noise_only": noise_only(),
    }
    report["verdict"] = assess(report["width_sweep"],
                               report["amplitude_sweep_at_saturated_width_13"])

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))

    print("WIDTH SWEEP  |z| at target centre")
    print(f"  {'width':>6} {'baseline':>10} {'candidate':>10}")
    for r in report["width_sweep"]:
        print(f"  {r['width_traces']:>6} {r['baseline']:>10.3f} {r['candidate']:>10.3f}")

    print("\nAMPLITUDE SWEEP at width 13 (baseline saturated)")
    print(f"  {'amp':>8} {'baseline':>10} {'candidate':>10}")
    for r in report["amplitude_sweep_at_saturated_width_13"]:
        print(f"  {r['amplitude']:>8} {r['baseline']:>10.4f} {r['candidate']:>10.4f}")

    print("\nNOISE ONLY")
    for k, v in report["noise_only"].items():
        print(f"  {k:>16}: max|z| {v['max_abs_z_mean']:.2f}, "
              f"frac>3 {v['fraction_over_3_mean']:.5f}")

    v = report["verdict"]
    print("\nVERDICT")
    print(f"  baseline  narrow {v['baseline_narrow_mean_abs_z']:.3f} -> wide {v['baseline_wide_mean_abs_z']:.3f}"
          f"  (retention {v['baseline_retention_wide_over_narrow']:.3f})")
    print(f"  candidate narrow {v['candidate_narrow_mean_abs_z']:.3f} -> wide {v['candidate_wide_mean_abs_z']:.3f}"
          f"  (retention {v['candidate_retention_wide_over_narrow']:.3f})")
    print(f"  baseline amplitude-invariant when saturated : {v['baseline_amplitude_invariant_at_saturated_width']}")
    print(f"  candidate amplitude-invariant when saturated: {v['candidate_amplitude_invariant_at_saturated_width']}")
    print(f"  MECHANISTICALLY FALSIFIED: {v['mechanistically_falsified']}")
    print(f"  -> {out}")
    return report


# --------------------------------------------------------- baseline identity

def verify_baseline_identity(out: Path, pre_hook: Path | None = None) -> dict:
    """
    Prove the estimator hook left the baseline path bit-identical.

    Runs the PRE-HOOK `benchmark/detection.py` beside the working-tree version
    on the same inputs. Comparing against the committed file is the only check
    that cannot be fooled by a mistake living in both copies.

    `pre_hook` is the committed file, extracted by the caller
    (`git show HEAD:benchmark/detection.py`), because the test container has no
    git binary. Falls back to invoking git where it is available.
    """
    import importlib.util
    import subprocess
    import sys
    import tempfile

    from benchmark.detection import detect_line as hooked

    if pre_hook is not None:
        src = Path(pre_hook).read_text()
        source_note = str(pre_hook)
    else:
        src = subprocess.run(["git", "show", "HEAD:benchmark/detection.py"],
                             capture_output=True, text=True, check=True).stdout
        source_note = "git HEAD:benchmark/detection.py"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(src)
        path = fh.name
    spec = importlib.util.spec_from_file_location("_pre_hook_detection", path)
    pre = importlib.util.module_from_spec(spec)
    sys.modules["_pre_hook_detection"] = pre
    spec.loader.exec_module(pre)

    cases, mismatches = [], 0
    for seed, width in ((1, 1), (2, 3), (3, 13), (4, 0)):
        t = _top_hat(width, noise=0.05, seed=seed) if width else \
            np.random.default_rng(seed).normal(size=(160, 240))
        for thr, mc in ((3.0, 3), (2.5, 3), (4.0, 5)):
            a = [d.__dict__ for d in pre.detect_line(t, "s", 0, threshold=thr, min_cells=mc)]
            b = [d.__dict__ for d in hooked(t, "s", 0, threshold=thr, min_cells=mc)]
            same = a == b
            mismatches += 0 if same else 1
            cases.append({"seed": seed, "width": width, "threshold": thr,
                          "min_cells": mc, "n_detections": len(a), "identical": same})

    report = {
        "stage": "baseline_identity",
        "compared_against": source_note,
        "cases": cases,
        "n_cases": len(cases),
        "mismatches": mismatches,
        "bit_identical": mismatches == 0,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    print(f"baseline identity: {len(cases)} cases, {mismatches} mismatch(es) -> "
          f"bit_identical={report['bit_identical']}")
    print(f"  -> {out}")
    return report


# ------------------------------------------------------------- calibration

#: The frozen baseline applies ONE threshold everywhere -- both BAM
#: frequencies and 4TU. The candidate therefore gets one too, so neither arm
#: has more free parameters than the other.
BASELINE_THRESHOLD = 3.0
MIN_CELLS = 3


def _count_components(z: np.ndarray, threshold: float, min_cells: int) -> int:
    """The frozen detection rule, applied to an already-built grid."""
    from scipy import ndimage
    mask = np.abs(np.nan_to_num(z, nan=0.0)) > threshold
    labeled, n = ndimage.label(mask)
    if n == 0:
        return 0
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    return int((sizes >= min_cells).sum())


def calibrate(out: Path, scans=("1_5_GHz_Rot00", "2_6_GHz_Rot00"),
              grid_lo: float = 2.0, grid_hi: float = 40.0, n_grid: int = 191) -> dict:
    """
    Choose the candidate's single global threshold on Pk050 ALONE.

    Pk050 is the specimen attested to contain no embedded elements. Pk266 and
    4TU are never read here: the threshold is fixed before any target
    performance is observed, which is what makes the later comparison a
    measurement rather than a fit.

    The target is the baseline's POOLED detections-per-line over the same
    control lines, at the baseline's own frozen threshold.
    """
    from benchmark.bam_ingest import line_traces, load_scan, load_volume

    thresholds = np.linspace(grid_lo, grid_hi, n_grid)
    base_hits = 0
    cand_hits = np.zeros(n_grid, dtype=int)
    lines_total = 0
    per_scan = {}

    for suffix in scans:
        scan = load_scan("Pk050", f"Pk050_3D_Dataset_{suffix}")
        vol = load_volume(scan)
        n_lines = vol.shape[1]
        b_here, c_here = 0, np.zeros(n_grid, dtype=int)
        for y in range(n_lines):
            tr = line_traces(vol, y)
            b_here += _count_components(anomaly_grid_from_traces(tr),
                                        BASELINE_THRESHOLD, MIN_CELLS)
            zc = multiscale_anomaly_grid(tr)
            for i, t in enumerate(thresholds):
                c_here[i] += _count_components(zc, float(t), MIN_CELLS)
        del vol
        base_hits += b_here
        cand_hits += c_here
        lines_total += n_lines
        per_scan[suffix] = {"lines": n_lines, "baseline_detections": int(b_here),
                            "baseline_per_line": b_here / n_lines}
        print(f"  {suffix}: {n_lines} control lines, baseline {b_here} detections "
              f"({b_here / n_lines:.4f}/line)")

    target_rate = base_hits / lines_total
    cand_rates = cand_hits / lines_total
    idx = int(np.argmin(np.abs(cand_rates - target_rate)))
    chosen = float(thresholds[idx])

    report = {
        "stage": "calibration",
        "control_specimen": "Pk050",
        "control_is_attested_empty": True,
        "rule": ("single global threshold, matched to the baseline's POOLED "
                 "control detections-per-line; the frozen baseline uses one "
                 "global threshold for both BAM frequencies and 4TU, so the "
                 "candidate gets one too"),
        "target_performance_inspected": False,
        "min_cells": MIN_CELLS,
        "baseline_threshold": BASELINE_THRESHOLD,
        "baseline_control_detections": int(base_hits),
        "control_lines_total": int(lines_total),
        "baseline_control_rate_per_line": target_rate,
        "per_scan": per_scan,
        "candidate_threshold": chosen,
        "candidate_control_detections": int(cand_hits[idx]),
        "candidate_control_rate_per_line": float(cand_rates[idx]),
        "match_error_per_line": float(abs(cand_rates[idx] - target_rate)),
        "search_grid": {"lo": grid_lo, "hi": grid_hi, "n": n_grid},
        "curve": [{"threshold": float(t), "rate_per_line": float(r)}
                  for t, r in zip(thresholds, cand_rates)],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))

    print(f"\nbaseline pooled control rate : {target_rate:.4f} /line "
          f"({base_hits} detections over {lines_total} lines)")
    print(f"candidate threshold chosen   : {chosen:.3f}")
    print(f"candidate control rate       : {cand_rates[idx]:.4f} /line "
          f"({int(cand_hits[idx])} detections)")
    print(f"match error                  : {report['match_error_per_line']:.5f} /line")
    print(f"  -> {out}")
    return report


# --------------------------------------------------------------- evaluation

#: Frozen by the calibration stage on Pk050 alone, BEFORE any target
#: performance was observed. Not to be adjusted after seeing BAM or 4TU.
CANDIDATE_THRESHOLD = 6.800


def _paired_grids(traces):
    """
    Both arms' z-grids from ONE preprocessing pass.

    `anomaly_grid_from_traces` preprocesses then applies the baseline windows;
    `multiscale_anomaly_grid` preprocesses then combines scales. Preprocessing
    is identical and dominates the cost, so it is done once and shared. Tests
    pin that this is equivalent to calling each entry point separately.
    """
    from preprocessing.multiscale_anomaly import combine_scales, preprocess_traces
    from preprocessing.spatial_grid import TRACE_ANOMALY_WINDOWS, _local_anomaly_grid

    grid = preprocess_traces(traces)
    base, _ = _local_anomaly_grid(grid, **TRACE_ANOMALY_WINDOWS)
    return base, combine_scales(grid)


def evaluate_bam(out: Path, scans=("1_5_GHz_Rot00", "2_6_GHz_Rot00")) -> dict:
    """
    The frozen BAM benchmark, both arms, at their calibrated thresholds.

    Uses `benchmark.detection.detect_scan` and `benchmark.scoring` unmodified,
    so scoring semantics are the committed ones. Only the estimator differs.
    """
    from benchmark.bam_ingest import load_scan, load_volume
    from benchmark.bam_truth import load_control, load_targets
    from benchmark.detection import detect_scan
    from benchmark.scoring import score_detection, score_false_alarms
    from preprocessing.multiscale_anomaly import multiscale_anomaly_grid

    arms = {
        BASELINE: (anomaly_grid_from_traces, BASELINE_THRESHOLD),
        CANDIDATE: (multiscale_anomaly_grid, CANDIDATE_THRESHOLD),
    }
    results: dict = {"stage": "bam_evaluation", "arms": {}, "thresholds":
                     {k: v[1] for k, v in arms.items()}, "min_cells": MIN_CELLS}

    for suffix in scans:
        tgt = load_scan("Pk266", f"Pk266_3D_Dataset_{suffix}")
        targets = load_targets(tgt.grid, "Pk266")
        tvol = load_volume(tgt)
        ctl = load_scan("Pk050", f"Pk050_3D_Dataset_{suffix}")
        cvol = load_volume(ctl)

        for name, (est, thr) in arms.items():
            run = detect_scan(tgt, tvol, threshold=thr, min_cells=MIN_CELLS, estimator=est)
            det = score_detection(run, targets).as_dict()
            det["n_detections"] = len(run.detections)
            crun = detect_scan(ctl, cvol, threshold=thr, min_cells=MIN_CELLS, estimator=est)
            fa = score_false_alarms(crun, load_control("Pk050")).as_dict()
            results["arms"].setdefault(name, {})[suffix] = {"detection": det,
                                                            "false_alarms": fa}
            print(f"  {suffix:>14} {name:>16}  TP={det['true_positives']:>4} "
                  f"FP={det['false_positives']:>5} FN={det['false_negatives']:>4} "
                  f"recall={det['recall']:.4f} prec={det['precision']:.4f} "
                  f"F1={det['f1']:.4f}  control={fa['n_detections']} "
                  f"({fa['detections_per_line']:.3f}/line)")
        del tvol, cvol

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1))
    print(f"  -> {out}")
    return results


def evaluate_4tu(out: Path, limit: int | None = None, smoke: bool = False,
                 only: list[str] | None = None, merge_into: Path | None = None) -> dict:
    """
    Per-activity candidate counts for BOTH arms, over the 4TU corpus.

    Walks the corpus once and scores both arms from the SAME preprocessing, so
    the arms are paired by construction over identical file ordering. Feeds
    `benchmark.fourtu_scoring.score_activities` unmodified.

    `--limit` exists ONLY for the non-scoring smoke test; a limited run is
    marked `smoke_test: true` and must never be reported as a benchmark result.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from characterise_4tu import read_trace_array

    from benchmark.fourtu_scoring import ActivityObservation, score_activities
    from benchmark.fourtu_truth import load_truth, normalise_location_id

    root = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")
    activities: dict[str, list[Path]] = {}
    # Most activities keep their lines under `Radargrams/`, but 03.7 and 08.1
    # use `Radarmaps/`. Matching one spelling silently drops those two -- a
    # partial corpus that still looks like a complete run. Match any
    # subdirectory of the activity instead.
    for sgy in sorted(root.glob("*/*/*/*/*.sgy")):
        activities.setdefault(normalise_location_id(sgy.parents[1].name), []).append(sgy)

    locs = sorted(activities)
    if only:
        locs = [l for l in locs if l in set(only)]
    elif limit:
        locs = locs[:limit]

    obs = {BASELINE: {}, CANDIDATE: {}}
    for i, loc in enumerate(locs, 1):
        counts = {BASELINE: 0, CANDIDATE: 0}
        traces_seen = 0
        for f in activities[loc]:
            arr, _ = read_trace_array(f)
            traces_seen += arr.shape[0]
            b, c = _paired_grids(arr)
            counts[BASELINE] += _count_components(b, BASELINE_THRESHOLD, MIN_CELLS)
            counts[CANDIDATE] += _count_components(c, CANDIDATE_THRESHOLD, MIN_CELLS)
        for arm in obs:
            obs[arm][loc] = ActivityObservation(location_id=loc,
                                                candidates=counts[arm], traces=traces_seen)
        print(f"  [{i}/{len(locs)}] {loc}: traces={traces_seen} "
              f"baseline={counts[BASELINE]} candidate={counts[CANDIDATE]}", flush=True)

    if merge_into and Path(merge_into).exists():
        prev = json.loads(Path(merge_into).read_text())["per_activity"]
        for arm in obs:
            for loc, v in prev[arm].items():
                obs[arm].setdefault(loc, ActivityObservation(
                    location_id=loc, candidates=v["candidates"], traces=v["traces"]))

    truth = load_truth()
    report = {
        "stage": "4tu_evaluation",
        "smoke_test": bool(smoke or limit),
        "activities_walked": len(locs),
        "thresholds": {BASELINE: BASELINE_THRESHOLD, CANDIDATE: CANDIDATE_THRESHOLD},
        "min_cells": MIN_CELLS,
        "arms": {arm: score_activities(truth, obs[arm]).as_dict() for arm in obs},
        "per_activity": {arm: {k: {"candidates": v.candidates, "traces": v.traces}
                               for k, v in obs[arm].items()} for arm in obs},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))

    for arm, s in report["arms"].items():
        print(f"  {arm:>16}: AUC={s['density_separation']['auc']} "
              f"rho={s['count_agreement']['spearman_rho']} "
              f"pos_median={s['positive_group']['median_per_1k']} "
              f"zero_median={s['attested_zero_group']['median_per_1k']}")
    print(f"  smoke_test={report['smoke_test']}  -> {out}")
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["synthetic", "verify-baseline", "calibrate",
                                     "bam", "4tu"])
    p.add_argument("--limit", type=int, default=None,
                   help="4tu only: walk N activities as a NON-SCORING smoke test")
    p.add_argument("--only", nargs="*", default=None,
                   help="4tu only: compute just these LocationIDs")
    p.add_argument("--merge-into", type=Path, default=None,
                   help="4tu only: fold in per-activity results from a previous run")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--pre-hook", type=Path, default=None,
                   help="pre-hook benchmark/detection.py, for verify-baseline")
    args = p.parse_args()

    if args.stage == "synthetic":
        out = args.out or Path("artifacts/experiment/multiscale_synthetic.json")
        r = run_synthetic(out)
        return 1 if r["verdict"]["mechanistically_falsified"] else 0
    if args.stage == "verify-baseline":
        out = args.out or Path("artifacts/experiment/baseline_identity.json")
        return 0 if verify_baseline_identity(out, args.pre_hook)["bit_identical"] else 1
    if args.stage == "calibrate":
        out = args.out or Path("artifacts/experiment/multiscale_calibration.json")
        calibrate(out)
        return 0
    if args.stage == "bam":
        out = args.out or Path("artifacts/experiment/multiscale_bam.json")
        evaluate_bam(out)
        return 0
    if args.stage == "4tu":
        default = ("artifacts/experiment/multiscale_4tu_smoke.json" if args.limit
                   else "artifacts/experiment/multiscale_4tu.json")
        evaluate_4tu(args.out or Path(default), limit=args.limit,
                     only=args.only, merge_into=args.merge_into)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
