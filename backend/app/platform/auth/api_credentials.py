"""Decrypt the credentials blob attached to an :class:`APIConfig` row.

The blob is a Fernet-encrypted JSON dict that holds ``api_key`` plus
provider-specific ``additional`` keys (e.g. ``api_base``). Swallows all
decrypt / JSON errors and returns ``{}``; callers treat an empty dict
as "no credentials present", which is the desired failure mode for UI
masking and scheduler enrichment paths.

Phase 4 step 3 of the refactor lifted this helper out of
``app.api.configs_common_auth``. The legacy
``app.api.configs_common_auth.decrypt_api_credentials`` re-exports this
implementation; both paths return the same object.
"""

from __future__ import annotations

import json

from app.models.auth_config import APIConfig
from app.platform.security.encryption import decrypt_data


def decrypt_api_credentials(config: APIConfig) -> dict:
    """Best-effort decrypt API credentials JSON.

    Swallows all decrypt errors and returns ``{}`` — callers treat an
    empty dict as "no credentials present", which is the desired failure
    mode for UI masking and scheduler enrichment paths.
    """
    try:
        if not config.encrypted_credentials:
            return {}
        raw = decrypt_data(config.encrypted_credentials)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        return {}
    except Exception:  # noqa: BLE001 - opaque decrypt / JSON path, UI degrades to "no creds"
        return {}
