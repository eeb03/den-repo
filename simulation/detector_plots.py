"""
Figures for the detector-saturation experiment (docs/detector-saturation-experiment.md).

* pr_<split>.png -- precision-recall and FP-per-scan vs recall, every detector
  x background arm, primary condition; frozen operating points circled.
* conditions_<split>.png -- recall vs FP/scan per condition (sampling x
  noise), mean-trace arm.
* examples.png -- test B-scans chosen by a FIXED rule (first test scene in
  sorted order of each kind, judged on the hyperbola stack at its frozen
  threshold, primary condition): a correct detection, a missed target, and a
  false positive. All three detectors' detections are drawn; truth is the
  predicted top-echo curve and the target centre.

    python -m simulation.detector_plots --corpus artifacts/simulation/corpus_s0 \
        --report artifacts/simulation/detector_experiment/report.json --out docs/figures
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from benchmark.hyperbola_stack import estimate_time_zero  # noqa: E402
from simulation.background_benchmark import score_located  # noqa: E402
from simulation.detector_comparison import (  # noqa: E402
    BACKGROUNDS, CONDITIONS, PRIMARY_ARM, PRIMARY_CONDITION, THRESHOLDS, _locate, condition_line, detector_grid,
)
from simulation.interface import load_line  # noqa: E402

DETS = ("ring", "ring_widened", "hyperbola_stack")
COLOURS = {"ring": "#7f7f7f", "ring_widened": "#1f77b4", "hyperbola_stack": "#d62728"}
STYLES = {"mean_trace_subtraction": "-", "no_background_removal": ":", "target_free_reference_oracle": "--"}


def _curve(entry, split):
    pts = [(float(t), r) for t, r in entry[split]["curve"].items()]
    pts.sort()
    return pts


def pr_figure(report: dict, split: str, out: Path) -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5))
    freeze = report["freeze"]["detectors"]
    for det in DETS:
        for arm, ls in STYLES.items():
            key = f"{PRIMARY_CONDITION}|{det}|{arm}"
            if key not in report["results"] or split not in report["results"][key]:
                continue
            pts = _curve(report["results"][key], split)
            rec = [r["recall"] or 0 for _, r in pts]
            prec = [r["precision"] if r["precision"] is not None else np.nan for _, r in pts]
            fp = [max(r["fp_per_scan"], 1e-3) for _, r in pts]
            label = f"{det} / {arm.replace('_', ' ')}"
            a1.plot(rec, prec, ls, color=COLOURS[det], label=label, marker=".")
            a2.plot(fp, rec, ls, color=COLOURS[det], marker=".")
            thr = freeze[det]["threshold"]
            if thr is not None and arm == PRIMARY_ARM:
                r = report["results"][key][split]["curve"][str(thr)]
                a1.plot(r["recall"] or 0, r["precision"] or np.nan, "o", ms=11, mfc="none", color=COLOURS[det])
                a2.plot(max(r["fp_per_scan"], 1e-3), r["recall"] or 0, "o", ms=11, mfc="none", color=COLOURS[det])
    a1.set(xlabel="recall (targets)", ylabel="precision (detections)", xlim=(0, 1), ylim=(0, 1.02),
           title=f"Precision-recall, {split} split")
    a2.set(xscale="log", xlabel="false positives per scan (strict)", ylabel="recall", ylim=(0, 1),
           title="FP per scan vs recall")
    a2.axvline(1.0, color="k", lw=0.6, ls="--")
    a1.legend(fontsize=7, loc="upper right")
    fig.suptitle(f"SIMULATION ONLY - {PRIMARY_CONDITION}; circles = frozen operating points", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / f"detector_saturation_pr_{split}.png", dpi=130)
    plt.close(fig)


def conditions_figure(report: dict, split: str, out: Path) -> None:
    fig, axes = plt.subplots(1, len(CONDITIONS), figsize=(4 * len(CONDITIONS), 4), sharey=True)
    for ax, cond in zip(axes, CONDITIONS):
        for det in DETS:
            key = f"{cond}|{det}|{PRIMARY_ARM}"
            if key not in report["results"] or split not in report["results"][key]:
                continue
            pts = _curve(report["results"][key], split)
            ax.plot([max(r["fp_per_scan"], 1e-3) for _, r in pts], [r["recall"] or 0 for _, r in pts],
                    color=COLOURS[det], marker=".", label=det)
        ax.set(xscale="log", title=cond.replace("|", "\n"), xlabel="FP per scan")
        ax.axvline(1.0, color="k", lw=0.6, ls="--")
    axes[0].set_ylabel("recall")
    axes[0].legend(fontsize=8)
    fig.suptitle(f"SIMULATION ONLY - mean-trace subtraction, {split} split", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / f"detector_saturation_conditions_{split}.png", dpi=130)
    plt.close(fig)


def _run(line, det, cfg, thr, f):
    tz = estimate_time_zero(line.traces, line.dt_s, line.time_offset_s)
    z, v_hat = detector_grid(det, cfg, BACKGROUNDS[PRIMARY_ARM](line), line, tz, f)
    located = _locate(line, z, v_hat, thr)
    return located, score_located(line, located)


def examples_figure(corpus: Path, report: dict, out: Path) -> dict:
    meta = json.loads((corpus / "index.json").read_text())["scenes"]
    freeze = report["freeze"]["detectors"]
    test = sorted(s for s, e in meta.items() if e["split"] == "test")
    picks: dict[str, str] = {}
    cache = {}
    for sid in test:
        line = condition_line(load_line(corpus / sid), PRIMARY_CONDITION)
        f = float(meta[sid]["centre_frequency_hz"])
        d = freeze["hyperbola_stack"]
        located, score = _run(line, "hyperbola_stack", d["config"], d["threshold"], f)
        cache[sid] = (line, f)
        hit = any(t["detected"] for t in score["targets"])
        miss = any(not t["detected"] for t in score["targets"])
        if hit and "correct detection" not in picks:
            picks["correct detection"] = sid
        if miss and "missed target" not in picks:
            picks["missed target"] = sid
        if score["fp_strict"] > 0 and "false positive" not in picks:
            picks["false positive"] = sid
        if len(picks) == 3:
            break
    fig, axes = plt.subplots(1, len(picks), figsize=(6 * len(picks), 5))
    for ax, (kind, sid) in zip(np.atleast_1d(axes), picks.items()):
        line, f = cache[sid]
        img = BACKGROUNDS[PRIMARY_ARM](line)
        t_ns = line.sample_times_s * 1e9
        x = line.midpoint_x_m
        lim = np.percentile(np.abs(img), 99)
        ax.imshow(img.T, aspect="auto", cmap="gray", vmin=-lim, vmax=lim,
                  extent=[x[0], x[-1], t_ns[-1], t_ns[0]])
        for tg in line.truth["targets"]:
            top = [np.nan if v is None else v * 1e9 for v in tg["predicted_events"]["top"]["two_way_time_s"]]
            ax.plot(x, top, color="yellow", lw=0.8)
            ax.axvline(tg["geometry"]["centre_x_m"], color="yellow", lw=0.5, ls=":")
        for det, marker in (("ring", "s"), ("ring_widened", "^"), ("hyperbola_stack", "o")):
            d = freeze[det]
            if d["threshold"] is None:
                continue
            located, _ = _run(line, det, d["config"], d["threshold"], f)
            ax.plot([p["x"] for p in located], [p["t"] * 1e9 for p in located], marker, mfc="none",
                    color=COLOURS[det], ms=9, mew=1.5, ls="none", label=f"{det} @ {d['threshold']}")
        e = meta[sid]
        ax.set(title=f"{kind}: {sid}\n{e['centre_frequency_hz'] / 1e9:g} GHz, eps_r {e['soil_relative_permittivity']:.1f}, "
                     f"{', '.join(e['labels']) or 'empty'}", xlabel="x (m)", ylabel="two-way time (ns)")
        ax.legend(fontsize=7, loc="lower right")
    fig.suptitle("SIMULATION ONLY - test split, mean-trace subtraction, 20 spp + 4TU-median noise. "
                 "Yellow: predicted top echo / target centre.", fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "detector_saturation_examples.png", dpi=120)
    plt.close(fig)
    return picks


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("docs/figures"))
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    report = json.loads(args.report.read_text())
    for split in ("test", "val"):
        pr_figure(report, split, args.out)
        conditions_figure(report, split, args.out)
    print(json.dumps(examples_figure(args.corpus, report, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
