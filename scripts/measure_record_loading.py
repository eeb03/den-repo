"""
Where record loading actually spends its time and memory.

    python scripts/measure_record_loading.py --dataset <id>

WHY THIS EXISTS RATHER THAN A GUESS. Stage 15 measured that two concurrent
consumers of the same dataset took ~66 s each where sequentially they took 6.8 s
and 18.4 s. "The cache is too small" is the obvious explanation and it is not
obviously right: the cache holds one dataset and both consumers wanted the SAME
dataset, so a size bound cannot be what they collided on. This script measures
the alternatives instead of arguing about them.

It reports parse counts alongside wall clock, because "was the work done twice"
is a number and not a stopwatch reading.

Nothing here writes to a dataset and nothing manufactures data: it runs against
a corpus already held.
"""
from __future__ import annotations

import argparse
import gc
import json
import resource
import threading
import time
import tracemalloc
from pathlib import Path

from configs.settings import settings
from database import records_store
from database.records_store import clear_records_cache, load_records


def rss_mb() -> float:
    """Resident set size. ru_maxrss is bytes on macOS, kilobytes on Linux."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024 * 1024) if raw > 10_000_000 else raw / 1024


class ParseCounter:
    """Counts real parses, so cache behaviour is observed rather than inferred."""

    def __init__(self):
        self.count = 0
        self._real = records_store._parse

    def __enter__(self):
        def counted(path):
            self.count += 1
            return self._real(path)

        records_store._parse = counted
        return self

    def __exit__(self, *exc):
        records_store._parse = self._real


def timed(label: str, fn):
    gc.collect()
    before = rss_mb()
    started = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - started
    after = rss_mb()
    return {"stage": label, "seconds": round(elapsed, 3),
            "rss_before_mb": round(before, 1), "rss_after_mb": round(after, 1),
            "rss_delta_mb": round(after - before, 1)}, result


def stage_breakdown(path: Path) -> list[dict]:
    """
    Split the parse into its parts: file read, line split, JSON decode, and
    pydantic construction. Only the last is expensive if the model is the cost.
    """
    from schemas.subterra_record import SubterraRecord

    out = []
    started = time.perf_counter()
    text = path.read_text()
    out.append({"stage": "read file", "seconds": round(time.perf_counter() - started, 3)})

    started = time.perf_counter()
    lines = [line for line in text.split("\n") if line.strip()]
    out.append({"stage": "split lines", "seconds": round(time.perf_counter() - started, 3),
                "n_lines": len(lines)})

    started = time.perf_counter()
    decoded = [json.loads(line) for line in lines]
    out.append({"stage": "json.loads", "seconds": round(time.perf_counter() - started, 3)})

    started = time.perf_counter()
    built = [SubterraRecord.model_validate(d) for d in decoded]
    out.append({"stage": "pydantic construct (from dict)",
                "seconds": round(time.perf_counter() - started, 3)})

    del decoded
    started = time.perf_counter()
    again = [SubterraRecord.model_validate_json(line) for line in lines]
    out.append({"stage": "pydantic model_validate_json (the real path)",
                "seconds": round(time.perf_counter() - started, 3)})

    del built, again, lines, text
    gc.collect()
    return out


def measure_object_footprint(path: Path) -> dict:
    """
    What one materialised record set actually costs in memory.

    Measured by parsing UNDER tracemalloc rather than by tracing a copy of an
    already-parsed list: `list(records)` copies pointers, not records, so
    tracing that reports a couple of megabytes and badly understates the real
    cost. RSS is reported alongside because tracemalloc sees Python
    allocations and not the allocator's retained arenas.
    """
    gc.collect()
    before_rss = rss_mb()
    tracemalloc.start()
    records = _parse_fresh(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    after_rss = rss_mb()
    n = len(records)
    del records
    gc.collect()
    return {
        "traced_peak_mb": round(peak / 1048576, 1),
        "rss_delta_mb": round(after_rss - before_rss, 1),
        "bytes_per_record": round(peak / n) if n else None,
    }


def _parse_fresh(path: Path):
    from schemas.subterra_record import SubterraRecord

    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(SubterraRecord.model_validate_json(line))
    return out


def concurrent_trial(dataset_id: str, both_cached: bool) -> dict:
    """
    Two consumers at once, as the radargram page issues them.

    `both_cached=False` reproduces the shipped arrangement, where the candidate
    path passes use_cache=False and therefore parses its own copy while the
    trace-grid path parses another.
    """
    clear_records_cache()
    gc.collect()
    results: dict[str, float] = {}
    barrier = threading.Barrier(2)

    def consumer(name: str, use_cache: bool):
        barrier.wait()
        started = time.perf_counter()
        records = load_records(dataset_id, use_cache=use_cache)
        results[name] = time.perf_counter() - started
        results[f"{name}_n"] = len(records)

    with ParseCounter() as counter:
        before = rss_mb()
        threads = [
            threading.Thread(target=consumer, args=("trace_grid", True)),
            threading.Thread(target=consumer, args=("candidates", both_cached)),
        ]
        wall = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.perf_counter() - wall
        after = rss_mb()

    return {
        "arrangement": "both cached" if both_cached else "one bypasses the cache (shipped)",
        "wall_seconds": round(wall, 3),
        "trace_grid_seconds": round(results.get("trace_grid", 0), 3),
        "candidates_seconds": round(results.get("candidates", 0), 3),
        "parses": counter.count,
        "rss_delta_mb": round(after - before, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    path = settings.processed_dir / f"{args.dataset}.jsonl"
    if not path.exists():
        print(f"no records file for {args.dataset}")
        return 1

    report: dict = {
        "dataset_id": args.dataset,
        "file_mb": round(path.stat().st_size / 1048576, 1),
        "measurements": [],
    }

    # --- 1. a cold parse ----------------------------------------------------
    clear_records_cache()
    with ParseCounter() as counter:
        entry, records = timed("cold load (cache empty)", lambda: load_records(args.dataset))
        entry["parses"] = counter.count
        entry["n_records"] = len(records)
    report["measurements"].append(entry)
    report["n_records"] = len(records)
    report["object_footprint"] = measure_object_footprint(path)

    # --- 2. a warm hit, WHILE the first result is still referenced ----------
    with ParseCounter() as counter:
        entry, second = timed("warm load (cache hit)", lambda: load_records(args.dataset))
        entry["parses"] = counter.count
    report["measurements"].append(entry)
    del second

    # --- 3. a cache bypass while the cached copy is still resident ----------
    # This is the shipped candidate path, and the condition that matters: a
    # second full record set materialised while the first is alive.
    with ParseCounter() as counter:
        entry, third = timed("bypass while cached copy resident",
                             lambda: load_records(args.dataset, use_cache=False))
        entry["parses"] = counter.count
    report["measurements"].append(entry)
    del third
    del records
    gc.collect()

    # --- 4. a bypass with nothing else resident ------------------------------
    clear_records_cache()
    with ParseCounter() as counter:
        entry, fourth = timed("bypass with nothing else resident",
                              lambda: load_records(args.dataset, use_cache=False))
        entry["parses"] = counter.count
    report["measurements"].append(entry)
    del fourth
    gc.collect()

    # --- 5. where the parse time goes ---------------------------------------
    report["parse_breakdown"] = stage_breakdown(path)

    # --- 6. concurrency, both arrangements ----------------------------------
    report["concurrency"] = [
        concurrent_trial(args.dataset, both_cached=False),
        concurrent_trial(args.dataset, both_cached=True),
    ]

    clear_records_cache()
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")

    print(f"dataset {args.dataset}  {report['file_mb']} MB  "
          f"{report['n_records']} records")
    fp = report["object_footprint"]
    print(f"  materialised footprint: {fp['traced_peak_mb']} MB traced "
          f"({fp['bytes_per_record']} bytes/record), rss +{fp['rss_delta_mb']} MB")
    print()
    for m in report["measurements"]:
        print(f"  {m['stage']:<40} {m['seconds']:>7.3f}s  parses={m['parses']}  "
              f"rss +{m['rss_delta_mb']} MB")
    print()
    print("  parse breakdown:")
    for s in report["parse_breakdown"]:
        print(f"    {s['stage']:<44} {s['seconds']:>7.3f}s")
    print()
    print("  concurrency:")
    for c in report["concurrency"]:
        print(f"    {c['arrangement']:<40} wall={c['wall_seconds']:>7.3f}s  "
              f"parses={c['parses']}  rss +{c['rss_delta_mb']} MB")
        print(f"      trace_grid={c['trace_grid_seconds']}s  candidates={c['candidates_seconds']}s")
    if args.out:
        print(f"\n  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
