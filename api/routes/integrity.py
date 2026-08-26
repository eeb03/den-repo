"""
Dataset integrity signing: the one endpoint that is not scoped to a
dataset -- the deployment's own public key, published so an independent
verifier can check a signature (`GET /api/datasets/{id}/verify_integrity`)
without trusting this server's own "verified: true" response at query
time. See `security.dataset_integrity` for what a signature does and does
not claim.

No authentication: a public key is public by definition. Publishing it
reveals nothing that isn't already implied by every signature this
deployment produces.
"""
from __future__ import annotations

from fastapi import APIRouter

from configs.settings import settings
from security.dataset_integrity import ALGORITHM, public_key_b64

router = APIRouter()


@router.get("/public_key")
def get_public_key():
    """
    `available: false` (never an error) is the honest answer for a
    deployment that has not configured `integrity_signing_private_key` --
    the same "not configured, not broken" distinction this platform
    already draws everywhere else.
    """
    if not settings.integrity_signing_private_key:
        return {
            "available": False,
            "reason": "dataset integrity signing is not configured for this deployment",
        }
    return {
        "available": True,
        "algorithm": ALGORITHM,
        "public_key_b64": public_key_b64(settings.integrity_signing_private_key),
    }
