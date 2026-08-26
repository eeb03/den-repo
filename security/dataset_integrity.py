"""
Dataset integrity signing: proves a dataset's stored records/frames are
byte-for-byte what Subterra itself last signed. This is an
AUTHENTICITY/TAMPER-EVIDENCE claim, never a physical-truth claim --
signing a digest does not mean the underlying measurement is correct,
independently verified, or Grade A/B evidence (see `schemas.segmentation.
EvidenceGrade`). It means these specific stored bytes have not silently
changed since the server itself sealed them.

WHY A SIGNATURE, NOT A PLAIN CHECKSUM. A checksum recomputed and compared
against a value stored in the SAME database an attacker who modified the
data could also modify offers no real protection -- it is exactly as
tamperable as the data itself (this platform already has one such
checksum, `Dataset.checksum`, a hash of the RAW SOURCE FILE for dedup/
change-detection, which is a different, narrower concern this module
does not touch or replace). A cryptographic SIGNATURE only adds real
value when the private key is not co-located with what it protects, and
its PUBLIC key can be published (`GET /api/integrity/public_key`) so an
independent verifier -- not just this server's own self-report -- can
check a signature without trusting a "verified: true" response at query
time.

WHAT IS COVERED, AND WHAT IS NOT. The digest covers exactly the
dataset's stored records file and its stored survey-frames file (the
scientific payload) -- read as raw bytes from disk, never a
re-serialization of the loaded objects, so signing and verifying can
never disagree about field ordering or float formatting. It does NOT
cover the SQL `Dataset` row's own fields (name, license, owner, quality
score, ...); those are a separate concern this milestone does not claim
to protect.

KEY MANAGEMENT. One Ed25519 keypair per deployment, read from
`settings.integrity_signing_private_key` (a base64-encoded 32-byte
seed). Empty means signing is UNAVAILABLE -- this module never
generates a key inside a request handler or at settings load: a key
regenerated on every restart would produce signatures no later process
could verify, which is a worse, more misleading state than "not
configured" (a real, reportable absence, not silently swallowed).
`generate_signing_key()` exists for a deployment's own one-time setup,
called by a human running a script, never by the running application.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from utils.checksum import sha256_of_file

ALGORITHM = "ed25519"

#: Stand-in digest for "this artifact does not exist" -- a dataset that
#: predates frame coverage has no frames file at all. Distinguishable from
#: any real SHA-256 hex digest (wrong length/alphabet), so it can never
#: collide with a real file's hash.
NO_FRAMES_SENTINEL = "no-frames-file"


class SigningUnavailable(RuntimeError):
    """Raised when no signing key is configured. Never silently worked around."""


@dataclass
class IntegritySignature:
    dataset_id: str
    digest_sha256: str
    signature_b64: str
    public_key_b64: str
    algorithm: str
    signed_at: str

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "digest_sha256": self.digest_sha256,
            "signature_b64": self.signature_b64,
            "public_key_b64": self.public_key_b64,
            "algorithm": self.algorithm,
            "signed_at": self.signed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IntegritySignature":
        return cls(
            dataset_id=data["dataset_id"], digest_sha256=data["digest_sha256"],
            signature_b64=data["signature_b64"], public_key_b64=data["public_key_b64"],
            algorithm=data["algorithm"], signed_at=data["signed_at"],
        )


def generate_signing_key() -> str:
    """
    A fresh base64-encoded Ed25519 private-key seed, for a deployment's
    own one-time setup (run once, save the result as
    INTEGRITY_SIGNING_PRIVATE_KEY, never regenerate). Not called by the
    running application itself -- see the module docstring.
    """
    key = Ed25519PrivateKey.generate()
    return base64.b64encode(key.private_bytes_raw()).decode()


def _load_private_key(b64_seed: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(b64_seed))


def public_key_b64(b64_seed: str) -> str:
    """The public key an independent verifier needs -- safe to publish."""
    return base64.b64encode(_load_private_key(b64_seed).public_key().public_bytes_raw()).decode()


def dataset_digest(records_path: Path, frames_path: Optional[Path]) -> str:
    """
    A SHA-256 digest over the dataset's actual stored bytes on disk --
    the records file (required) and the frames file (when it exists).
    Hashing FILE BYTES directly, not the loaded/deserialized objects, is
    what lets `sign` and `verify` agree byte-for-byte without ever having
    to worry about re-serialization producing a different string for
    identical data.
    """
    records_hash = sha256_of_file(records_path)
    frames_hash = sha256_of_file(frames_path) if frames_path and frames_path.exists() else NO_FRAMES_SENTINEL
    return hashlib.sha256(f"{records_hash}:{frames_hash}".encode()).hexdigest()


def sign_dataset(
    dataset_id: str, records_path: Path, frames_path: Optional[Path], private_key_b64: str,
) -> IntegritySignature:
    """
    Computes the current digest and signs it. Raises `SigningUnavailable`
    if `private_key_b64` is empty -- checked here, not left to a caller,
    so every caller gets the same honest refusal rather than a confusing
    downstream cryptography error.
    """
    if not private_key_b64:
        raise SigningUnavailable(
            "dataset integrity signing is not configured for this deployment "
            "(settings.integrity_signing_private_key is empty)"
        )
    digest = dataset_digest(records_path, frames_path)
    signature = _load_private_key(private_key_b64).sign(digest.encode())
    return IntegritySignature(
        dataset_id=dataset_id, digest_sha256=digest,
        signature_b64=base64.b64encode(signature).decode(),
        public_key_b64=public_key_b64(private_key_b64), algorithm=ALGORITHM,
        signed_at=datetime.now(timezone.utc).isoformat(),
    )


def verify_dataset(
    records_path: Path, frames_path: Optional[Path], stored: IntegritySignature,
) -> tuple[bool, str]:
    """
    Returns `(verified, reason)`. TWO DISTINCT failure modes, never
    collapsed into one unexplained `False`:

    - the CURRENT digest does not match the SIGNED digest -- the stored
      bytes changed since signing (reprocessing, corruption, or
      tampering; this function cannot tell which, and does not guess).
    - the digest matches, but the signature itself does not verify
      against it -- the signature or public key was corrupted or forged.
    """
    current_digest = dataset_digest(records_path, frames_path)
    if current_digest != stored.digest_sha256:
        return False, (
            f"the dataset's stored records/frames no longer match what was signed "
            f"(signed digest {stored.digest_sha256[:16]}..., current digest "
            f"{current_digest[:16]}...) -- the data changed since it was last signed, "
            f"whether by reprocessing, corruption, or tampering; this check cannot "
            f"tell which"
        )
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(stored.public_key_b64))
        public_key.verify(base64.b64decode(stored.signature_b64), current_digest.encode())
    except InvalidSignature:
        return False, (
            "the digest matches the one signed, but the signature itself does not "
            "verify against it -- the signature or public key is corrupted or forged"
        )
    return True, "the digest matches the one signed, and the signature verifies against it"
