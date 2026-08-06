"""
Dataset Downloader: resumable, retrying, checksum-verifying, dedupe-aware
downloads from public dataset sources (Zenodo, OpenTopography, USGS, ...).

Phase 1 ships the download-manager mechanics (resume/retry/checksum/dedupe)
against arbitrary URLs. Source-specific connectors (Zenodo API search,
OpenTopography catalog browsing, etc.) are a Phase 2 item — see
ingestion/sources.py for the registry stub that they plug into.
"""
import time
from pathlib import Path

import requests

from configs.settings import settings
from utils.checksum import sha256_of_file
from utils.logger import get_logger

logger = get_logger(__name__)


class DownloadError(RuntimeError):
    pass


SUPPORTED_EXTENSIONS = {".csv", ".xyz", ".tsv", ".sgy", ".segy", ".las", ".laz", ".tif", ".tiff"}


def extract_zip_and_find_supported_files(zip_path: str | Path, extract_to: str | Path | None = None) -> list[Path]:
    """
    Extracts a zip archive and returns every contained file (recursively,
    including subdirectories) whose extension has a registered converter.
    Files with no matching converter (e.g. proprietary .dt format, .txt
    readmes, preview images) are silently skipped -- callers should check
    for an empty result and report that clearly rather than assume success.
    """
    import zipfile

    zip_path = Path(zip_path)
    extract_to = Path(extract_to) if extract_to else zip_path.parent / f"{zip_path.stem}_extracted"
    extract_to.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_to)

    found = sorted(
        p for p in extract_to.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and not p.name.startswith("._")  # macOS AppleDouble sidecar files -- Finder metadata,
        and "__MACOSX" not in p.parts     # not real data, despite sharing the real file's extension
    )
    logger.info(f"extract_zip_and_find_supported_files: {zip_path.name} -> {len(found)} supported file(s) found")
    return found


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
