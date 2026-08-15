"""
Safe receipt of an uploaded file.

THE EXISTING UPLOAD PATH IS NOT SAFE, and this module exists partly to avoid
inheriting it. `api/routes/datasets.py::ingest_dataset` writes to
`settings.raw_dir / file.filename` with the client's filename unmodified, so:

  - a filename of `../processed/<uuid>.jsonl` escapes raw_dir and can overwrite
    an existing dataset's persisted records;
  - two users uploading `line1.sgy` silently overwrite each other;
  - a failed write leaves a truncated file that looks like a real one.

Every upload here lands in its OWN directory named for its job id, so a
collision is not merely unlikely but unrepresentable, and no upload can reach a
path outside that directory regardless of what the client claims its file is
called. The file is written to a `.part` name and renamed only once it is
complete, so a partial upload is never mistaken for a finished one.
"""
from __future__ import annotations

import re
import shutil
import hashlib
from pathlib import Path

from configs.settings import settings

#: Uploads live under raw/imports/<job_id>/ -- one directory per job.
IMPORT_SUBDIR = "imports"

#: Refused above this. A local single-worker deployment has no streaming-to-
#: object-store path, so an unbounded upload is an unbounded disk write. This
#: is a deliberately conservative constant rather than a setting, because
#: configs/ is a frozen path in this change.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB

#: Read size for streaming the upload to disk without loading it into memory.
CHUNK_BYTES = 1024 * 1024

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadTooLarge(Exception):
    """Raised when an upload exceeds MAX_UPLOAD_BYTES."""


class EmptyUpload(Exception):
    """Raised when an upload contains no bytes."""


def sanitize_filename(name: str | None) -> str:
    """
    Reduce a client-supplied filename to something that cannot leave its
    directory.

    Only the final path component survives, and only characters that cannot
    form a traversal. Both POSIX and Windows separators are stripped before
    the basename is taken, because a Windows client can send `..\\..\\x.sgy`
    and `Path.name` alone would keep it whole.

    The extension is preserved deliberately: the converter registry dispatches
    on it, so mangling it would turn a supported file into an unknown one.
    """
    raw = (name or "").replace("\\", "/")
    base = Path(raw).name.strip()
    base = base.lstrip(".") or "upload"           # no dotfiles, no bare ".."
    cleaned = _SAFE.sub("_", base).strip("._-") or "upload"
    return cleaned[:180]


def job_dir(job_id: str) -> Path:
    return settings.raw_dir / IMPORT_SUBDIR / job_id


def save_upload(job_id: str, filename: str | None, source) -> tuple[Path, str, int, str]:
    """
    Stream `source` (a file-like object) into this job's own directory.

    Returns (path, stored_filename, size_bytes, sha256). Raises UploadTooLarge
    or EmptyUpload, cleaning up the partial file in both cases -- a rejected
    upload must not leave bytes behind that a later listing could mistake for
    a dataset.

    THE CHECKSUM IS COMPUTED IN THE SAME PASS. `sha256_of_file` would re-read
    the whole file, which for a 2 GiB upload means a second full pass over the
    disk for bytes that were in memory a moment earlier. It is also the
    acquisition's identity, so it must be taken from exactly the bytes that
    were written rather than from whatever is at that path later.
    """
    safe = sanitize_filename(filename)
    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)

    final = directory / safe
    partial = directory / f"{safe}.part"

    size = 0
    digest = hashlib.sha256()
    try:
        with open(partial, "wb") as out:
            while True:
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadTooLarge(
                        f"upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"
                    )
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise EmptyUpload("the uploaded file is empty")
        # Only now is it a real file.
        partial.replace(final)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    return final, safe, size, digest.hexdigest()


def cleanup_job_dir(job_id: str) -> None:
    """Remove a job's upload directory. Used when a job is abandoned."""
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
