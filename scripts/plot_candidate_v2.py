"""
Precision-recall and FP/line-recall curves for the Candidate V2 experiment.

    venv/bin/python -m scripts.plot_candidate_v2 [results.json] [out.png]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

COLORS = {"production": "#7f7f7f", "envelope": "#1f77b4", "v2": "#d62728"}


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/bam/candidate_v2/results.json")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/research/figures/candidate_v2_pr.png")
    res = json.loads(src.read_text())
    scans = [("development", "Pk266 1.5 GHz (DEV)", res["development"]["evaluation"])]
    scans += [("test", k.replace("_Rot00", "").replace("_", " ") + " (TEST)", v) for k, v in res["test"].items()]
    fig, axes = plt.subplots(2, len(scans), figsize=(4.2 * len(scans), 7.5))
    for col, (_, title, ev) in enumerate(scans):
        rule = "L-XZ" if ev["depth_scoreable"] else "L-X only"
        for arm, a in ev["arms"].items():
            c = [p for p in a["curve"] if p["recall"] is not None]
            r = [p["recall"] for p in c]
            axes[0, col].plot(r, [p["precision"] or 0 for p in c], ".-", ms=3, color=COLORS[arm], label=arm)
            axes[1, col].plot(r, [p["false_positives_per_line"] for p in c], ".-", ms=3, color=COLORS[arm], label=arm)
            op = a["at_frozen_operating_point"]
            axes[0, col].plot(op["recall"], op["precision"], "o", mfc="none", ms=9, color=COLORS[arm])
            axes[1, col].plot(op["recall"], op["false_positives_per_line"], "o", mfc="none", ms=9, color=COLORS[arm])
        axes[0, col].set_title(f"{title}\n[{rule}]", fontsize=9)
        axes[0, col].set_xlabel("recall"); axes[0, col].set_ylabel("precision")
        axes[1, col].set_xlabel("recall"); axes[1, col].set_ylabel("false positives / line")
        axes[1, col].set_yscale("log")
        for ax in axes[:, col]:
            ax.set_xlim(0, 1.02); ax.grid(alpha=0.3)
            ax.axvline(0.8, ls=":", c="k", lw=0.8); ax.axvline(0.9, ls=":", c="k", lw=0.8)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle("BAM: production vs envelope (E1) vs Candidate V2 (circles = frozen operating points)",
                 fontsize=10)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
