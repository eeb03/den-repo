"""
Operator view for picking a first-break reference, WITHOUT Method C.

Renders, for each file, the early part of the raw section (variable density,
every trace) and the median trace plus a few individual traces as wiggles on a
sample-accurate time grid. An operator reads the first break from these plots
and records it in `benchmark/timing/timezero_references.json` with an
uncertainty. Only afterwards is Method C run against the recorded picks
(`scripts/validate_timezero_method_c.py`).

INDEPENDENCE IS STRUCTURAL: this module does not import `preprocessing.time_zero`
(a test asserts it), computes no threshold, and prints no candidate onset. It
rebuilds traces itself from (source_file, trace_index, sample_index) exactly
as stored, so what the operator sees is the converter's output and nothing else.

    python -m scripts.timezero_operator_view --out artifacts/timezero_operator_view \
        segy:path/to/line.sgy mala:path/to/line.rd3 ...
"""
from __future__ import annotations

import argparse
import logging
import statistics
from pathlib import Path

from schemas.subterra_record import SensorType

logging.disable(logging.CRITICAL)


def load(kind: str, path: Path, **kw):
    """The converter's own output for one file (no velocity is ever supplied)."""
    if kind == "segy":
        from converters.segy_converter import SEGYConverter
        return SEGYConverter().load(path, dataset_id="view", sensor_type=SensorType.GPR, **kw)
    if kind == "mala":
        from converters.mala_converter import MALAConverter
        return MALAConverter().load(path, dataset_id="view")
    if kind == "gssi":
        from converters.gssi_converter import GSSIConverter
        return GSSIConverter().load(path, dataset_id="view")
    if kind == "ids":
        from converters.ids_dt_converter import IDSDTConverter
        return IDSDTConverter().load(path, dataset_id="view")
    raise ValueError(f"unknown kind {kind!r}")


def traces_of(records) -> tuple[list[list[float]], list[float]]:
    """Whole traces in stored sample order, and the raw time axis of the first."""
    by: dict = {}
    for r in records:
        by.setdefault((r.metadata.get("source_file", ""), r.metadata["trace_index"]), []).append(r)
    traces, times = [], None
    for key in sorted(by):
        recs = sorted(by[key], key=lambda r: r.metadata["sample_index"])
        traces.append([r.signal[0] for r in recs])
        if times is None:
            times = [r.metadata["two_way_time_ns"] for r in recs]
    return traces, times


def render(name: str, traces, times, out: Path, window_ns: float) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dt = times[1] - times[0]
    n = min(len(times), max(10, int(window_ns / dt)))
    t = times[:n]
    section = [tr[:n] for tr in traces]
    median = [statistics.median(tr[i] for tr in section) for i in range(n)]
    flat = sorted(v for tr in section for v in tr)
    lo, hi = flat[int(0.02 * len(flat))], flat[int(0.98 * len(flat)) - 1]

    fig, (a, b) = plt.subplots(1, 2, figsize=(16, 9), gridspec_kw={"width_ratios": [1.2, 1]})
    a.imshow([[section[j][i] for j in range(len(section))] for i in range(n)], aspect="auto",
             cmap="gray", vmin=lo, vmax=hi, extent=[0, len(section), t[-1] + dt / 2, t[0] - dt / 2])
    a.set_xlabel("trace"); a.set_ylabel("raw two-way time (ns)")
    a.set_title(f"{name}: raw section, first {t[-1] - t[0]:.1f} ns")
    span = max(abs(v) for v in median) or 1.0
    for k, j in enumerate(range(0, len(section), max(1, len(section) // 5))[:5]):
        tr = section[j]
        s = max(abs(v) for v in tr) or 1.0
        b.plot([v / s for v in tr], t, lw=0.6, alpha=0.5, label=f"trace {j}")
    b.plot([v / span for v in median], t, "k", lw=1.6, label="median trace")
    b.invert_yaxis()
    b.set_yticks([t[i] for i in range(0, n, max(1, n // 40))])
    b.tick_params(axis="y", labelsize=7)
    b.grid(True, axis="y", lw=0.3)
    b.set_xlabel("amplitude (each trace / its own max)")
    b.set_title(f"dt = {dt:.4f} ns; sample 0 at {t[0]:.3f} ns")
    b.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    path = out / f"{name}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def median_table(traces, times, n: int) -> str:
    """The median trace, sample by sample, so a pick can be read to the sample."""
    rows = []
    for i in range(min(n, len(times))):
        m = statistics.median(tr[i] for tr in traces)
        rows.append(f"{i:4d} {times[i]:9.4f} ns {m:14.2f}")
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--window-ns", type=float, default=40.0)
    ap.add_argument("--table-samples", type=int, default=0)
    ap.add_argument("files", nargs="+", help="kind:path[:delay_encoding]")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for spec in args.files:
        kind, rest = spec.split(":", 1)
        kw = {}
        if kind == "segy" and rest.endswith(":sample_interval_unit"):
            rest, kw = rest.rsplit(":", 1)[0], {"delay_encoding": "sample_interval_unit"}
        path = Path(rest)
        traces, times = traces_of(load(kind, path, **kw).records)
        name = "_".join(list(path.parts[-3:-1]) + [path.stem])
        for ch in " ,()":
            name = name.replace(ch, "_")
        png = render(name, traces, times, args.out, args.window_ns)
        print(f"{png}  traces={len(traces)} samples={len(times)} "
              f"start={times[0]:.4f} dt={times[1] - times[0]:.4f}")
        if args.table_samples:
            print(median_table(traces, times, args.table_samples))


if __name__ == "__main__":
    main()
