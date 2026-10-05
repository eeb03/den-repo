"""
PR and FP-per-line curves for the calibrated Candidate V2 experiment.

    python -m scripts.plot_candidate_v2_calibrated

Reads artifacts/bam/v2cal/{dev,heldout}_report.json; writes
docs/research/figures/candidate_v2_calibrated_{dev,heldout}.png.
Arms keep a fixed colour and marker everywhere (validated categorical
slots 1-4, light surface); identity is also carried by marker and legend.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ARMS = [("production", "A production", "#2a78d6", "s"),
        ("envelope", "B envelope", "#eb6834", "^"),
        ("v2_prev", "C previous V2", "#1baf7a", "D"),
        ("v2_cal", "D calibrated V2 (frozen)", "#eda100", "o")]
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e6e5df"


def plot(report: dict, title: str, out: Path):
    ev = report["evaluation"]
    sids = [s for s, r in ev.items() if r["arms"]["v2_cal"]["at_operating_point"]["opportunities"]]
    fig, axes = plt.subplots(2, len(sids), figsize=(4.2 * len(sids), 7.4), squeeze=False)
    for c, sid in enumerate(sids):
        r = ev[sid]
        name = sid.replace("_3D_Dataset_", " ").replace("_GHz_", " GHz ").replace("_", ".")
        for row, (xk, xlab, logx) in enumerate([("precision", "precision", False),
                                                ("false_positives_per_line", "false positives per line", True)]):
            ax = axes[row][c]
            for key, label, col, mk in ARMS:
                a = r["arms"][key]
                cur = [p for p in a["curve"] if p["recall"] is not None and p[xk] is not None
                       and (not logx or p[xk] > 0)]
                cur.sort(key=lambda p: p["threshold"])
                ax.plot([p[xk] for p in cur], [p["recall"] for p in cur], color=col, lw=2, label=label)
                op = a["at_operating_point"]
                if op[xk if xk != "false_positives_per_line" else "false_positives_per_line"] is not None \
                        and op["recall"] is not None and (not logx or op[xk] > 0):
                    ax.plot([op[xk]], [op["recall"]], marker=mk, ms=9, color=col, mec="#fcfcfb", mew=2)
            if logx:
                ax.set_xscale("log")
                ax.axvline(2.0, color=MUTED, lw=1, ls=":")
            ax.axhline(0.75, color=MUTED, lw=1, ls=":")
            ax.set_ylim(0, 1.02)
            ax.set_xlabel(xlab, color=INK)
            ax.set_ylabel(f"recall ({r['depth_rule'].split(' ')[0]})", color=INK)
            ax.grid(color=GRID, lw=0.8)
            for s in ax.spines.values():
                s.set_color(GRID)
            ax.tick_params(colors=MUTED)
            if row == 0:
                ax.set_title(f"{name}\n{r['object_type']}", color=INK, fontsize=10)
    axes[0][0].legend(loc="lower left", fontsize=8, frameon=False)
    fig.suptitle(title, color=INK)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, facecolor="#fcfcfb")
    print("wrote", out)


def main() -> int:
    base = Path("artifacts/bam/v2cal")
    figs = Path("docs/research/figures")
    for phase, title in (("dev", "Development (Rot00) - markers: operating points; dotted: recall 0.75, 2 FP/line"),
                         ("heldout", "Held-out Rot90, frozen configuration - markers: operating points")):
        p = base / f"{phase}_report.json"
        if p.exists():
            plot(json.loads(p.read_text()), title, figs / f"candidate_v2_calibrated_{phase}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
