import hashlib
from pathlib import Path


def sha256_of_file(path: str | Path, chunk_size: int = 8192) -> str:
    """Compute a streaming SHA-256 checksum without loading the whole file into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksum(path: str | Path, expected_sha256: str) -> bool:
    return sha256_of_file(path) == expected_sha256
