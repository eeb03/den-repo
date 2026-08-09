"""
Password hashing.

WHY PBKDF2-HMAC-SHA256 AND NOT bcrypt/argon2.

  - It is in the standard library (`hashlib.pbkdf2_hmac`), so this adds NO
    dependency to a project that currently has none for authentication. Nothing
    here is invented: PBKDF2 is specified in RFC 8018, is NIST-recommended, and
    is the algorithm behind Django's default hasher. The encoded format below
    is Django's, for the same reason -- it is a format people can read.

  - bcrypt SILENTLY TRUNCATES the password at 72 bytes. Everything past that is
    ignored, so a long passphrase is quietly weaker than the user believes and
    two different passwords sharing a 72-byte prefix verify against the same
    hash. PBKDF2 has no such limit: the password is HMAC'd, so its full length
    contributes. That is the specific failure this module is written to avoid.

  - argon2 is the better modern choice on memory-hardness, but it needs a
    compiled dependency (argon2-cffi). If that is ever added, `verify()` can
    keep reading `pbkdf2_sha256$` hashes while `hash_password` emits argon2 --
    the encoded prefix exists precisely so the scheme can be migrated without
    invalidating every existing password.

Verification is constant-time via `hmac.compare_digest`, so a timing signal
cannot be used to recover a hash byte by byte.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
#: OWASP's floor for PBKDF2-HMAC-SHA256 at the time of writing. Stored inside
#: each hash, so raising it later does not invalidate existing passwords.
ITERATIONS = 600_000
SALT_BYTES = 16

#: Long enough to be a real passphrase, short enough that a megabyte of input
#: cannot be used to burn CPU. PBKDF2 hashes the whole thing either way.
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 1024


class WeakPassword(ValueError):
    """The password does not meet the stated minimum."""


def validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPassword(
            f"password must be at most {MAX_PASSWORD_LENGTH} characters"
        )


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """Returns `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`."""
    validate_password(password)
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded: str | None) -> bool:
    """
    True when `password` matches `encoded`. Never raises on a malformed hash --
    a corrupt or absent hash is a failed login, not a 500.
    """
    if not encoded or not isinstance(password, str):
        return False
    try:
        algorithm, iterations, salt_b64, hash_b64 = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt_b64),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, base64.b64decode(hash_b64))
