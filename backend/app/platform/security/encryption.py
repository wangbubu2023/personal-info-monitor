"""Encryption utilities for sensitive data.

Envelope formats, in descending order of preference on write:

- ``v3:<base64(salt||token)>`` — PBKDF2-HMAC-SHA256 with 600,000 iterations
  (OWASP 2023 recommended minimum). Default for all new writes.
- ``v2:<base64(salt||token)>`` — PBKDF2-HMAC-SHA256 with 100,000 iterations.
  Legacy format written before 2026-04; still decryptable so we don't force a
  rewrite of every encrypted column during an upgrade.
- ``<base64(token)>`` with a fixed static salt and 100,000 iterations — the
  oldest format. Still decryptable for the same reason.

Callers that update a credential row trigger a natural re-encryption which
transparently upgrades the envelope to ``v3:``.
"""

import base64
import json
import secrets
from typing import Any, Dict

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.platform.config.settings import get_settings

_LEGACY_STATIC_SALT = b"personal-info-monitor-salt"
_V2_PREFIX = "v2:"
_V3_PREFIX = "v3:"
_SALT_LENGTH = 16

_ITERATIONS_LEGACY = 100_000
_ITERATIONS_V2 = 100_000
_ITERATIONS_V3 = 600_000
_ITERATIONS_DEFAULT = _ITERATIONS_V3


def _derive_fernet(salt: bytes, iterations: int = _ITERATIONS_DEFAULT) -> Fernet:
    """Derive a Fernet instance from the app encryption key and provided salt."""
    settings = get_settings()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    key = base64.urlsafe_b64encode(
        kdf.derive(settings.encryption_key.encode())
    )

    return Fernet(key)


def _encrypt_bytes(payload: bytes) -> str:
    """Encrypt bytes with a random per-record salt and the current versioned envelope."""
    salt = secrets.token_bytes(_SALT_LENGTH)
    token = _derive_fernet(salt, _ITERATIONS_V3).encrypt(payload)
    packed = base64.urlsafe_b64encode(salt + token).decode()
    return f"{_V3_PREFIX}{packed}"


def _decrypt_bytes(encrypted_str: str) -> bytes:
    """Decrypt any supported envelope: v3 / v2 / legacy fixed-salt."""
    if encrypted_str.startswith(_V3_PREFIX):
        packed = encrypted_str[len(_V3_PREFIX):]
        raw = base64.urlsafe_b64decode(packed.encode())
        if len(raw) <= _SALT_LENGTH:
            raise ValueError("Invalid encrypted payload")
        salt = raw[:_SALT_LENGTH]
        token = raw[_SALT_LENGTH:]
        return _derive_fernet(salt, _ITERATIONS_V3).decrypt(token)

    if encrypted_str.startswith(_V2_PREFIX):
        packed = encrypted_str[len(_V2_PREFIX):]
        raw = base64.urlsafe_b64decode(packed.encode())
        if len(raw) <= _SALT_LENGTH:
            raise ValueError("Invalid encrypted payload")
        salt = raw[:_SALT_LENGTH]
        token = raw[_SALT_LENGTH:]
        return _derive_fernet(salt, _ITERATIONS_V2).decrypt(token)

    # Legacy fixed-salt payload (oldest format).
    token = base64.urlsafe_b64decode(encrypted_str.encode())
    return _derive_fernet(_LEGACY_STATIC_SALT, _ITERATIONS_LEGACY).decrypt(token)


def encrypt_data(data: Dict[str, Any]) -> str:
    """Encrypt a dictionary to a string."""
    if not isinstance(data, dict):
        raise TypeError("encrypt_data expects a dict payload")
    json_str = json.dumps(data)
    return _encrypt_bytes(json_str.encode())


def decrypt_data(encrypted_str: str) -> Dict[str, Any] | str:
    """Decrypt a string back to a dictionary.

    Returns str only for backward compatibility with historically double-serialized
    payloads that are still being read from database.
    """
    decrypted = _decrypt_bytes(encrypted_str)
    payload = json.loads(decrypted.decode())
    if isinstance(payload, str):
        # Legacy records may have been encrypted from json.dumps(dict) string.
        try:
            reparsed = json.loads(payload)
            if isinstance(reparsed, dict):
                return reparsed
        except Exception:
            pass
    return payload


def encrypt_string(text: str) -> str:
    """Encrypt a plain string."""
    return _encrypt_bytes(text.encode())


def decrypt_string(encrypted_str: str) -> str:
    """Decrypt an encrypted string."""
    return _decrypt_bytes(encrypted_str).decode()
