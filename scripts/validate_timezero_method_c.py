"""
Baseline accuracy of Method C (direct-wave consensus) against the timing
corpus in validation/timezero_references.json. Method C is run exactly as
production runs it (`resolve_time_zero_for_frame` on the converter's own
records, no declaration present) -- nothing here tunes it.

Per file it reports the file-level pick and its error against the operator
reference, the per-trace picks Method C makes internally (as a distribution,
and as "per-trace pick minus the FILE reference" -- never as per-trace truth,
which does not exist), whether Method C's quiet window (the first
QUIET_SAMPLES samples) overlaps the arrival, and whether two runs agree.

    python -m scripts.validate_timezero_method_c --out artifacts/timezero/method_c_baseline.json
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from pathlib import Path

from preprocessing.time_zero import (
    MAX_CONSENSUS_SPREAD_NS, MIN_PICK_CONFIDENCE, QUIET_SAMPLES, _declared_marker_samples,
    _pick_onset_ns, reconstruct_traces_by_time, resolve_time_zero_for_frame,
)
from scripts.timezero_operator_view import load
from validation.timezero import compare, load_manifest, method_c_uncertainty, summarise

logging.disable(logging.CRITICAL)


def _q(values, q):
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


def _run(frame, records) -> dict:
    r = resolve_time_zero_for_frame(frame, records)
    return {"status": r.status.value, "method": r.method.value, "pick_ns": r.correction_ns,
            "spread_ns": r.spread_ns, "traces_evaluated": r.traces_evaluated,
            "successful_picks": r.successful_picks, "outliers_rejected": r.outliers_rejected,
            "basis": r.basis}


def analyse(path: Path, fmt: str, load_kw: dict, reference_ns=None) -> dict:
    result = load(fmt, path, **(load_kw or {}))
    frame, records = result.frames[0], result.records
    first = _run(frame, records)
    second = _run(frame, records)
    deterministic = all(first[k] == second[k] for k in
                        ("status", "pick_ns", "spread_ns", "successful_picks", "outliers_rejected"))

    by_trace, _ = reconstruct_traces_by_time(records)
    traces = [[r.signal[0] for r in recs] for recs in by_trace.values()]
    times = [r.metadata["two_way_time_ns"] for r in next(iter(by_trace.values()))]
    start, dt = times[0], times[1] - times[0]
    # The same declared marker samples Method C itself drops (GSSI), so the
    # trace-level diagnostics describe what Method C actually sees.
    markers = _declared_marker_samples(frame)
    raw_start = start
    if markers:
        traces = [t[markers:] for t in traces]
        start += markers * dt
    picks = [p[0] + start for p in (_pick_onset_ns(t, dt) for t in traces) if p is not None]

    quiet_sd = [statistics.pstdev(t[:QUIET_SAMPLES]) for t in traces]
    later_sd = [statistics.pstdev(t[QUIET_SAMPLES:2 * QUIET_SAMPLES]) for t in traces]
    out = {
        "path": str(path), "format": fmt, "n_traces": len(traces), "n_samples": len(times),
        "start_ns": raw_start, "sample_interval_ns": dt, "marker_samples_dropped": markers,
        "quiet_window_ns": [start, start + QUIET_SAMPLES * dt],
        "method_c": first, "deterministic": deterministic,
        "trace_level": {
            "n_picked": len(picks), "fraction_picked": len(picks) / len(traces),
            "median_pick_ns": statistics.median(picks) if picks else None,
            "p05_pick_ns": _q(picks, 0.05) if picks else None,
            "p95_pick_ns": _q(picks, 0.95) if picks else None,
            "p95_minus_p05_ns": (_q(picks, 0.95) - _q(picks, 0.05)) if picks else None,
        },
        "quiet_window": {
            "median_sd_first_window": statistics.median(quiet_sd),
            "median_sd_next_window": statistics.median(later_sd),
            "first_two_samples_median": [statistics.median(t[0] for t in traces),
                                         statistics.median(t[1] for t in traces)],
            "median_of_sample_2_onwards": statistics.median(
                statistics.median(t[2:QUIET_SAMPLES]) for t in traces),
        },
    }
    if reference_ns is not None:
        pre = (reference_ns - start) / dt   # after any dropped marker samples
        out["pre_arrival_samples_before_reference"] = round(pre, 2)
        out["quiet_window_overlaps_arrival"] = pre < QUIET_SAMPLES
        if picks:
            dev = [p - reference_ns for p in picks]
            out["trace_level"]["per_trace_minus_file_reference"] = {
                "note": "per-trace Method C picks minus the FILE-level operator reference; "
                        "there is no per-trace reference",
                "median_ns": statistics.median(dev),
                "median_abs_ns": statistics.median(abs(d) for d in dev),
                "p95_abs_ns": _q([abs(d) for d in dev], 0.95),
            }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    corpus = load_manifest()

    rows, comparisons = [], []
    for ref in corpus.references:
        a = analyse(Path(ref.path), ref.format, ref.load, ref.reference_ns)
        c = compare(ref, a["method_c"]["status"], a["method_c"]["pick_ns"],
                    a["sample_interval_ns"])
        comparisons.append(c)
        rows.append({**a, "comparison": c.as_dict()})
        print(f"{ref.reference_id:28s} ref={ref.reference_ns:7.3f}±{ref.uncertainty_ns:<4} "
              f"C={a['method_c']['status']:12s} pick={a['method_c']['pick_ns']!s:8s} "
              f"err={c.signed_error_ns!s:8s} samples={c.error_samples!s:7s} "
              f"picked={a['trace_level']['n_picked']}/{a['n_traces']} "
              f"pre={a['pre_arrival_samples_before_reference']:.1f} det={a['deterministic']}")
    unreferenced = []
    for n in corpus.no_reference:
        a = analyse(Path(n.path), n.format, n.load or {})
        unreferenced.append({**a, "reason_no_reference": n.reason})
        print(f"{Path(n.path).name:28s} (no reference) C={a['method_c']['status']:12s} "
              f"pick={a['method_c']['pick_ns']} picked={a['trace_level']['n_picked']}/"
              f"{a['n_traces']} spread={a['method_c']['spread_ns']} det={a['deterministic']}")

    report = {
        "method_c_parameters": {"QUIET_SAMPLES": QUIET_SAMPLES,
                                "MIN_PICK_CONFIDENCE": MIN_PICK_CONFIDENCE,
                                "MAX_CONSENSUS_SPREAD_NS": MAX_CONSENSUS_SPREAD_NS},
        "summary_by_evidence_type": summarise(comparisons),
        "summary_operator_high_medium_confidence_only": summarise(
            [c for c in comparisons if c.reference.confidence != "low"]),
        "uncertainty": method_c_uncertainty(comparisons),
        "referenced": rows,
        "unreferenced": unreferenced,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: report[k] for k in ("summary_by_evidence_type",
                                             "summary_operator_high_medium_confidence_only",
                                             "uncertainty")}, indent=1))


if __name__ == "__main__":
    main()
