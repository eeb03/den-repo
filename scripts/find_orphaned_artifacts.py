"""
Report artifact files whose dataset no longer exists.

READ-ONLY, ON PURPOSE. This prints and exits; it deletes nothing. The files it
finds are the residue of a deletion path that removed one database row and left
everything else, and by the time anybody runs this there is no way to tell from
the outside whether a given file is genuine residue or a dataset mid-import on
another process. A tool that guessed and deleted 167 MB would be a worse bug
than the one it was written to clean up.

`DELETE /api/datasets/{id}` no longer creates these. This exists for what
accumulated before it.

    python -m scripts.find_orphaned_artifacts

To remove them, read the list, satisfy yourself, and delete them yourself.
"""
from pathlib import Path

from api.dataset_lifecycle import ARTIFACT_SUFFIXES
from configs.settings import settings
from database.models import Dataset
from database.session import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        live = {d.id for d in db.query(Dataset).all()}
    finally:
        db.close()

    processed = settings.processed_dir
    by_dataset: dict[str, list[Path]] = {}
    for path in sorted(processed.glob("*")):
        for suffix in ARTIFACT_SUFFIXES:
            if path.name.endswith(suffix):
                by_dataset.setdefault(path.name[: -len(suffix)], []).append(path)
                break

    orphans = {k: v for k, v in by_dataset.items() if k not in live}

    print(f"{len(live)} dataset(s) registered; {len(by_dataset)} with artifacts on disk")
    if not orphans:
        print("no orphaned artifacts")
        return

    total = 0
    print(f"\n{len(orphans)} dataset id(s) have artifacts but no dataset row:\n")
    for dataset_id, paths in sorted(orphans.items()):
        size = sum(p.stat().st_size for p in paths)
        total += size
        print(f"  {dataset_id}  {size / 1e6:8.1f} MB  {', '.join(p.suffix for p in paths)}")
    print(f"\n  total: {total / 1e6:.1f} MB")
    print("\nNothing was deleted. Review the list before removing anything.")


if __name__ == "__main__":
    main()
