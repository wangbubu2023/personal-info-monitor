"""Platform-level AuthConfig credential decryption.

Phase 5 step 9 of the module refactor relocates ``decrypt_auth_credentials``
out of ``app.api.configs_common_auth`` so domain code can consume it
without violating the ``domains → api`` import boundary (蓝图 §2.3 phase=5
rule: "business domains must not depend on the HTTP interfaces layer").

The function takes an :class:`~app.models.auth_config.AuthConfig` row and
returns the decrypted credential payload as a plain dict — or ``{}`` on any
decrypt / JSON failure (the UI gracefully degrades to "no creds" rather
than crashing the request). Anything HTTP-shaped (``serialize_*``,
``mask_api_key``) stays in the API layer; this module is pure
infrastructure.

The legacy ``app.api.configs_common_auth.decrypt_auth_credentials`` symbol
is re-exported through that module so the HTTP-layer callers
(``configs_api_auth.serialize_auth_config``,
``configs_common_cookies.serialize_auth_cookies_payload``,
``configs_common`` aggregator facade) keep working unchanged.
"""

from __future__ import annotations

import json

from app.models.auth_config import AuthConfig
from app.platform.security.encryption import decrypt_data


def decrypt_auth_credentials(config: AuthConfig) -> dict:
    """Return the decrypted ``credentials`` payload, or ``{}`` on any failure."""
    if not config.credentials:
        return {}
    try:
        raw = decrypt_data(config.credentials)
        if isinstance(raw, str):
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 - opaque decrypt / JSON path; UI degrades to "no creds"
        return {}
