"""
Backfill SurveyFrames for datasets ingested before frames existed.

Every dataset ingested from M2 onward gets its frames written at ingest.
Datasets ingested before that have records but no `{dataset_id}.frames.json`,
so `/info` and `/trace_grid` fall back to reconstructing frames on every
request. This makes that reconstruction durable: run once, and the fallback
stops being exercised.

SAFE BY DEFAULT. Nothing is written unless `--apply` is passed; the default
run reports what WOULD happen. Existing frame files are never replaced
unless `--overwrite` is also passed, because a frame written at ingest knows
things a reconstruction cannot (the real source format, the header block,
the declared CRS) and must not be downgraded to an inference.

RECORDS ARE NEVER MODIFIED. This reads `{dataset_id}.jsonl` and writes only
`{dataset_id}.frames.json`.

Reconstructed frames are marked `frame_reconstructed` so nothing downstream
mistakes an inference for something the source file declared -- see
`database/frames_store.py::synthesize_frames_from_records`.

    python -m scripts.backfill_survey_frames                 # dry run, all datasets
    python -m scripts.backfill_survey_frames --apply
    python -m scripts.backfill_survey_frames --apply --dataset abc123
    python -m scripts.backfill_survey_frames --apply --overwrite
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from configs.settings import settings
from database.frames_store import load_frames, save_frames, synthesize_frames_from_records
from schemas.subterra_record import SubterraRecord
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BackfillResult:
    dataset_id: str
    status: str                      # "written" | "would_write" | "skipped" | "empty" | "error"
    frame_count: int = 0
    source_files: list[str] = field(default_factory=list)
    detail: str | None = None

    def line(self) -> str:
        files = ", ".join(self.source_files[:3])
        if len(self.source_files) > 3:
            files += f", +{len(self.source_files) - 3} more"
        return (f"  {self.status:<12} {self.dataset_id:<38} "
                f"{self.frame_count:>3} frame(s)"
                + (f"  [{files}]" if files else "")
                + (f"  -- {self.detail}" if self.detail else ""))


def _records_path(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.jsonl"


def known_dataset_ids() -> list[str]:
    return sorted(p.stem for p in settings.processed_dir.glob("*.jsonl"))


def load_records_for_synthesis(dataset_id: str) -> list[SubterraRecord]:
    """
    Streams the record file, keeping one record per (source_file, trace_index).

    Frame synthesis reads only per-line facts -- source file, sensor type,
    position kind, trace count, whether depths exist, and the acquisition
    metadata every sample of a trace shares -- so one sample per trace
    preserves all of them. A GPR line here is 482 samples per trace, and the
    largest dataset in this archive is ~962,000 records, so loading them all
    to derive a handful of frames would cost roughly 500x more memory than
    the job needs.
    """
    path = _records_path(dataset_id)
    if not path.exists():
        return []
    kept: dict[tuple, SubterraRecord] = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = SubterraRecord.model_validate_json(line)
            key = (record.metadata.get("source_file"), record.metadata.get("trace_index"))
            # First sample of each trace wins; later samples add nothing.
            kept.setdefault(key, record)
    return list(kept.values())


def backfill_dataset(dataset_id: str, apply: bool = False,
                     overwrite: bool = False) -> BackfillResult:
    """Backfills one dataset. Idempotent: an already-covered dataset is skipped."""
    if not _records_path(dataset_id).exists():
        return BackfillResult(dataset_id, "error", detail="no record file found")

    if load_frames(dataset_id) and not overwrite:
        return BackfillResult(dataset_id, "skipped",
                              detail="already has frames (use --overwrite to replace)")

    try:
        records = load_records_for_synthesis(dataset_id)
    except Exception as e:                      # a corrupt line should not abort the run
        return BackfillResult(dataset_id, "error", detail=f"could not read records: {e}")

    if not records:
        return BackfillResult(dataset_id, "empty", detail="record file contains no records")

    frames = synthesize_frames_from_records(records)
    if not frames:
        return BackfillResult(dataset_id, "empty", detail="no frames could be reconstructed")

    sources = sorted({f.source_file or "(unnamed)" for f in frames})
    if apply:
        save_frames(dataset_id, frames)
        return BackfillResult(dataset_id, "written", len(frames), sources)
    return BackfillResult(dataset_id, "would_write", len(frames), sources)


def backfill(dataset_ids: list[str] | None = None, apply: bool = False,
             overwrite: bool = False) -> list[BackfillResult]:
    targets = dataset_ids or known_dataset_ids()
    return [backfill_dataset(d, apply=apply, overwrite=overwrite) for d in targets]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="actually write frame files (default: report only)")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace frames that already exist (downgrades ingest-time "
                             "frames to reconstructions -- rarely what you want)")
    parser.add_argument("--dataset", action="append", dest="datasets",
                        help="limit to this dataset id; repeatable")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    results = backfill(args.datasets, apply=args.apply, overwrite=args.overwrite)

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        mode = "APPLYING" if args.apply else "DRY RUN (pass --apply to write)"
        print(f"\nSurveyFrame backfill -- {mode}")
        print(f"processed dir: {settings.processed_dir}\n")
        for r in results:
            print(r.line())
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        total_frames = sum(r.frame_count for r in results)
        print(f"\n{len(results)} dataset(s): {counts or 'none found'}; "
              f"{total_frames} frame(s) {'written' if args.apply else 'to write'}")

    return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
