"""Trusted attestation checks for production Web Clean shadow exports."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Mapping

PROVENANCE_SCHEMA = "pim-web-clean-shadow-export-v1"
PROVENANCE_GENERATOR = "pim-production-shadow-export"
PROVENANCE_KEY_ENV = "PIM_WEB_CLEAN_PROVENANCE_HMAC_KEY"


def provenance_message(provenance: Mapping[str, Any]) -> bytes:
    """Build the canonical signed payload without including the secret itself."""
    fields = (
        str(provenance.get("schema_version") or ""),
        str(provenance.get("generated_by") or ""),
        str(provenance.get("dataset_kind") or ""),
        str(provenance.get("observations_sha256") or ""),
        str(provenance.get("generated_at") or ""),
    )
    return "\n".join(fields).encode("utf-8")


def sign_shadow_provenance(provenance: Mapping[str, Any], *, key: str) -> str:
    """Return the HMAC used by an external trusted export step."""
    if not key:
        raise ValueError("provenance HMAC key is required")
    return hmac.new(key.encode("utf-8"), provenance_message(provenance), hashlib.sha256).hexdigest()


def verify_shadow_provenance(
    provenance: Mapping[str, Any] | None,
    *,
    key: str | None = None,
) -> bool:
    """Verify an export attestation against the release-environment trust key."""
    if not isinstance(provenance, Mapping):
        return False
    trusted_key = key if key is not None else os.getenv(PROVENANCE_KEY_ENV, "")
    supplied = str(provenance.get("attestation_hmac_sha256") or "")
    if len(trusted_key) < 32 or len(supplied) != 64:
        return False
    expected = sign_shadow_provenance(provenance, key=trusted_key)
    return hmac.compare_digest(expected, supplied)
