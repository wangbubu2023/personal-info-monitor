"""Decrypt the stored credentials blob for a Source.auth_config.

The blob is a Fernet-encrypted JSON string that may contain ``username``,
``password``, ``cookies`` (a free-form mapping of name → value), and/or
``cookie_mode``. Cookies are normalised through ``normalize_cookie_dict`` so
downstream code can rely on a uniform ``dict[str, str]`` shape.

Returning ``{}`` on any decrypt/parse failure is intentional: an unreadable
credential blob must not crash fetch, it must degrade to unauthenticated
collection (and surface as a warning elsewhere).
"""

from __future__ import annotations

import json

from app.utils.cookies import normalize_cookie_dict
from app.utils.logger import get_logger
from app.utils.url import normalize_host

logger = get_logger(__name__)


def try_parse_auth_credentials(auth_config) -> dict:
    if not auth_config or not getattr(auth_config, "credentials", None):
        return {}
    site_host = normalize_host(getattr(auth_config, "site_url", ""))
    try:
        from app.utils.encryption import decrypt_data

        raw = decrypt_data(auth_config.credentials)
        if isinstance(raw, str):
            creds = json.loads(raw)
            if isinstance(creds, dict):
                if "cookies" in creds:
                    creds["cookies"] = normalize_cookie_dict(
                        creds.get("cookies"),
                        site_host=site_host,
                    )
                return creds
            return {}
        if isinstance(raw, dict):
            if "cookies" in raw:
                raw["cookies"] = normalize_cookie_dict(
                    raw.get("cookies"),
                    site_host=site_host,
                )
            return raw
        return {}
    except Exception as exc:  # noqa: BLE001 - decrypt/parse may raise many error classes
        logger.debug(
            "Failed to parse auth credentials for config %s: %s",
            getattr(auth_config, "id", "unknown"),
            exc,
        )
        return {}
