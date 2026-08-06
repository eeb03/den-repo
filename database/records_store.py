"""
Bulk SubterraRecord storage. The metadata registry (Dataset table) stays
lean in Postgres; the actual per-record payloads (which can run into the
millions for LiDAR/SEG-Y) are stored as newline-delimited JSON under
datasets/processed/. Swap this for a proper time-series/columnar store
(e.g. TimescaleDB, Parquet + DuckDB) when volume demands it — the
call sites (fusion, benchmark, training) don't need to change.
"""
import json
from pathlib import Path

from configs.settings import settings
from schemas.subterra_record import SubterraRecord


def _path_for(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.jsonl"


def save_records(dataset_id: str, records: list[SubterraRecord]) -> Path:
    path = _path_for(dataset_id)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r.to_flat_dict(), default=str) + "\n")
    return path


def load_records(dataset_id: str) -> list[SubterraRecord]:
    path = _path_for(dataset_id)
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(SubterraRecord.model_validate_json(line))
    return records


def load_all_records(dataset_ids: list[str] | None = None) -> list[SubterraRecord]:
    ids = dataset_ids or [p.stem for p in settings.processed_dir.glob("*.jsonl")]
    all_records: list[SubterraRecord] = []
    for did in ids:
        all_records.extend(load_records(did))
    return all_records
