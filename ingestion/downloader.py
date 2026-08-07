"""
Dataset Downloader: resumable, retrying, checksum-verifying, dedupe-aware
downloads from public dataset sources (Zenodo, OpenTopography, USGS, ...).

Phase 1 ships the download-manager mechanics (resume/retry/checksum/dedupe)
against arbitrary URLs. Source-specific connectors (Zenodo API search,
OpenTopography catalog browsing, etc.) are a Phase 2 item — see
ingestion/sources.py for the registry stub that they plug into.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from configs.settings import settings
from utils.checksum import sha256_of_file
from utils.logger import get_logger

logger = get_logger(__name__)


class DownloadError(RuntimeError):
    pass


def _is_real_data_file(p: Path) -> bool:
    """Excludes macOS AppleDouble sidecars -- Finder metadata that shares the
    real file's extension but contains none of its data."""
    return p.is_file() and not p.name.startswith("._") and "__MACOSX" not in p.parts


@dataclass
class ArchiveScan:
    """What an archive actually contains, classified rather than filtered.

    `recognized_unsupported` exists because silently dropping proprietary
    files made a zip of IDS GeoRadar .dt data indistinguishable from a zip
    with nothing of interest in it. Callers can now say which it is.
    """
    extract_dir: Path
    supported: list[Path] = field(default_factory=list)
    recognized_unsupported: list[tuple[Path, str]] = field(default_factory=list)

    def unsupported_summary(self) -> dict[str, int]:
        """{format description: file count} for the recognised-but-unreadable files."""
        counts: dict[str, int] = {}
        for _path, description in self.recognized_unsupported:
            counts[description] = counts.get(description, 0) + 1
        return counts


def scan_archive(zip_path: str | Path, extract_to: str | Path | None = None) -> ArchiveScan:
    """
    Extracts a zip archive and classifies every file inside it (recursively)
    against the converter registry -- the single source of truth for what
    the platform can read.
    """
    import zipfile

    from converters.registry import classify_file

    zip_path = Path(zip_path)
    extract_to = Path(extract_to) if extract_to else zip_path.parent / f"{zip_path.stem}_extracted"
    extract_to.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_to)

    scan = ArchiveScan(extract_dir=extract_to)
    for p in sorted(extract_to.rglob("*")):
        if not _is_real_data_file(p):
            continue
        classification, detail = classify_file(p)
        if classification == "supported":
            scan.supported.append(p)
        elif classification == "recognized_unsupported":
            scan.recognized_unsupported.append((p, detail))

    logger.info(
        f"scan_archive: {zip_path.name} -> {len(scan.supported)} supported file(s), "
        f"{len(scan.recognized_unsupported)} recognised-but-unsupported "
        f"({scan.unsupported_summary() or 'none'})"
    )
    return scan


def extract_zip_and_find_supported_files(zip_path: str | Path, extract_to: str | Path | None = None) -> list[Path]:
    """Backward-compatible view over `scan_archive`: supported files only."""
    return scan_archive(zip_path, extract_to).supported


def download_file(
    url: str,
    dest_filename: str | None = None,
    expected_sha256: str | None = None,
    max_retries: int = 3,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """
    Download a file with resume support (HTTP Range) and retry-with-backoff.
    Skips the download entirely if a matching file already exists (dedupe).
    """
    dest_filename = dest_filename or url.split("/")[-1].split("?")[0] or "download.bin"
    dest_path = settings.downloads_dir / dest_filename

    if dest_path.exists() and expected_sha256:
        if sha256_of_file(dest_path) == expected_sha256:
            logger.info(f"Skipping download, checksum already matches: {dest_filename}")
            return dest_path
        logger.warning(f"Existing file {dest_filename} failed checksum check — re-downloading.")

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            resume_byte_pos = dest_path.stat().st_size if dest_path.exists() else 0
            headers = {"Range": f"bytes={resume_byte_pos}-"} if resume_byte_pos else {}

            with requests.get(url, headers=headers, stream=True, timeout=30) as r:
                if r.status_code == 416:
                    # Requested range not satisfiable -> file's already complete
                    break
                r.raise_for_status()

                mode = "ab" if resume_byte_pos and r.status_code == 206 else "wb"
                with open(dest_path, mode) as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)

            if expected_sha256:
                actual = sha256_of_file(dest_path)
                if actual != expected_sha256:
                    raise DownloadError(
                        f"Checksum mismatch for {dest_filename}: expected {expected_sha256}, got {actual}"
                    )

            logger.info(f"Downloaded {dest_filename} ({dest_path.stat().st_size} bytes, attempt {attempt})")
            return dest_path

        except (requests.RequestException, DownloadError) as e:
            logger.warning(f"Download attempt {attempt}/{max_retries} failed for {url}: {e}")
            if attempt >= max_retries:
                raise DownloadError(f"Failed to download {url} after {max_retries} attempts") from e
            time.sleep(2**attempt)  # exponential backoff

    return dest_path
