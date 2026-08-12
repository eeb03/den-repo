"""
Bulk SubterraRecord storage. The metadata registry (Dataset table) stays
lean in Postgres; the actual per-record payloads (which can run into the
millions for LiDAR/SEG-Y) are stored as newline-delimited JSON under
datasets/processed/. Swap this for a proper time-series/columnar store
(e.g. TimescaleDB, Parquet + DuckDB) when volume demands it — the
call sites (fusion, benchmark, training) don't need to change.
"""
import json
import threading
from pathlib import Path

from configs.settings import settings
from schemas.subterra_record import SubterraRecord

# --------------------------------------------------------------------------
# Single-entry parse cache
#
# One dataset workspace page load calls load_records SIX times for the SAME
# dataset -- /info, /provenance/{id}/frames, /overlays/{id}/layers,
# /overlays/compose, /trace_grid and the viewer's /points -- and each call
# re-read the whole file and re-validated every line. Measured: 9.93 s per
# parse for a 157,040-record corpus, which is most of the 75 s that page took
# to settle.
#
# The cache holds exactly ONE dataset, and that is a deliberate bound rather
# than a simplification: a parsed 157,040-record corpus measures ~411 MB of
# Python objects, so holding all six datasets would trade a latency problem
# for a memory one. One entry is also sufficient, because the six calls that
# cost the page its time are all for the same dataset.
#
# The parse happens while the lock is held. That is intentional: the six calls
# arrive concurrently, so releasing the lock to parse would let all six miss
# and parse the same file anyway, and the first page load -- the slow one --
# would gain nothing. FastAPI runs these handlers in its threadpool where the
# GIL already serialises this CPU-bound work, so the lock costs no parallelism
# that existed.
#
# CONTRACT: a caller that uses the cache must not mutate the records it gets
# back. Every write path passes use_cache=False for exactly that reason.
# --------------------------------------------------------------------------
_CACHE_LOCK = threading.Lock()
_cache_identity: tuple | None = None
_cache_records: list[SubterraRecord] | None = None


def _path_for(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.jsonl"


def _identity(path: Path) -> tuple | None:
    """
    What makes a cached parse still valid: the same file, unmodified.

    mtime alone is not enough -- a rewrite within one timestamp tick would go
    unnoticed -- so size travels with it, and save_records invalidates
    explicitly rather than relying on either.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


def clear_records_cache() -> None:
    """Drops the cached parse. Called on every write, and by tests."""
    global _cache_identity, _cache_records
    with _CACHE_LOCK:
        _cache_identity, _cache_records = None, None


def _parse(path: Path) -> list[SubterraRecord]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(SubterraRecord.model_validate_json(line))
    return records


def save_records(dataset_id: str, records: list[SubterraRecord]) -> Path:
    path = _path_for(dataset_id)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r.to_flat_dict(), default=str) + "\n")
    clear_records_cache()
    return path


def load_records(dataset_id: str, *, use_cache: bool = True) -> list[SubterraRecord]:
    """
    Parses this dataset's records, reusing the last parse when the file on
    disk is provably unchanged.

    Pass `use_cache=False` when you intend to MUTATE the records you get
    back. The cached list is shared between callers, so mutating it would
    corrupt what every later reader sees. The returned list is always a fresh
    list object, so appending to or sorting the result is safe either way --
    it is the records themselves that must not be modified.
    """
    path = _path_for(dataset_id)
    if not path.exists():
        return []
    if not use_cache:
        return _parse(path)

    identity = _identity(path)
    if identity is None:                      # raced with a delete; don't cache
        return _parse(path)

    global _cache_identity, _cache_records
    with _CACHE_LOCK:
        if identity != _cache_identity or _cache_records is None:
            _cache_records = _parse(path)
            _cache_identity = identity
        return list(_cache_records)


def load_all_records(dataset_ids: list[str] | None = None) -> list[SubterraRecord]:
    ids = dataset_ids or [p.stem for p in settings.processed_dir.glob("*.jsonl")]
    all_records: list[SubterraRecord] = []
    for did in ids:
        all_records.extend(load_records(did))
    return all_records
