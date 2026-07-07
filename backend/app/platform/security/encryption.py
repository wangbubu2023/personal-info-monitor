"""Encryption utilities for sensitive data.

Envelope formats, in descending order of preference on write:

- ``v4:<base64(salt||token)>`` — HKDF-SHA256 (RFC 5869) with a random
  per-record salt. Default for all new writes. Rationale: the app
  ``ENCRYPTION_KEY`` is a machine-generated, full-entropy secret
  (``runtime-secrets.json``), so password-stretching KDFs add CPU cost but no
  security — high iteration counts only compensate for low-entropy human
  passwords. HKDF is the correct primitive for deriving sub-keys from a
  high-entropy master key and runs in microseconds.
- ``v3:<base64(salt||token)>`` — PBKDF2-HMAC-SHA256 with 600,000 iterations.
  Written 2026-04 → 2026-07; still decryptable so we don't force a rewrite of
  every encrypted column during an upgrade.
- ``v2:<base64(salt||token)>`` — PBKDF2-HMAC-SHA256 with 100,000 iterations.
  Legacy format written before 2026-04.
- ``<base64(token)>`` with a fixed static salt and 100,000 iterations — the
  oldest format. Still decryptable for the same reason.

Callers that update a credential row trigger a natural re-encryption which
transparently upgrades the envelope to ``v4:``.

PBKDF2 derivations (v3/v2/legacy reads) are cached per ``(key, salt,
iterations)``: at 600k iterations a single derivation costs ~0.1–0.5s of CPU,
and the same credential rows are re-decrypted on every fetch cycle. The cache
key includes the app key so tests that swap ``ENCRYPTION_KEY`` stay correct.
"""

import base64
import json
import secrets
from functools import lru_cache
from typing import Any, Dict

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.platform.config.settings import get_settings

_LEGACY_STATIC_SALT = b"personal-info-monitor-salt"
_V2_PREFIX = "v2:"
_V3_PREFIX = "v3:"
_V4_PREFIX = "v4:"
_SALT_LENGTH = 16
_HKDF_INFO_V4 = b"pim-credential-envelope-v4"

_ITERATIONS_LEGACY = 100_000
_ITERATIONS_V2 = 100_000
_ITERATIONS_V3 = 600_000
_ITERATIONS_DEFAULT = _ITERATIONS_V3


@lru_cache(maxsize=512)
def _derive_fernet_pbkdf2(encryption_key: str, salt: bytes, iterations: int) -> Fernet:
    """PBKDF2 derivation for the legacy envelopes (v3 / v2 / fixed-salt).

    Cached — see module docstring. Fernet instances are immutable, so sharing
    one per (key, salt, iterations) triple across callers is safe.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    key = base64.urlsafe_b64encode(kdf.derive(encryption_key.encode()))
    return Fernet(key)


def _derive_fernet(salt: bytes, iterations: int = _ITERATIONS_DEFAULT) -> Fernet:
    """Derive a Fernet instance from the app encryption key (PBKDF2 envelopes)."""
    settings = get_settings()
    return _derive_fernet_pbkdf2(settings.encryption_key, salt, iterations)


def _derive_fernet_v4(salt: bytes) -> Fernet:
    """HKDF-SHA256 derivation for the ``v4:`` envelope.

    Not cached: HKDF costs microseconds and v4 salts are per-record random,
    so cache entries would almost never be reused anyway.
    """
    settings = get_settings()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=_HKDF_INFO_V4,
    )
    key = base64.urlsafe_b64encode(hkdf.derive(settings.encryption_key.encode()))
    return Fernet(key)


def _unpack_salted_envelope(encrypted_str: str, prefix: str) -> tuple[bytes, bytes]:
    """Split a ``<prefix><base64(salt||token)>`` envelope into (salt, token)."""
    packed = encrypted_str[len(prefix):]
    raw = base64.urlsafe_b64decode(packed.encode())
    if len(raw) <= _SALT_LENGTH:
        raise ValueError("Invalid encrypted payload")
    return raw[:_SALT_LENGTH], raw[_SALT_LENGTH:]


def _encrypt_bytes(payload: bytes) -> str:
    """Encrypt bytes with a random per-record salt and the current versioned envelope."""
    salt = secrets.token_bytes(_SALT_LENGTH)
    token = _derive_fernet_v4(salt).encrypt(payload)
    packed = base64.urlsafe_b64encode(salt + token).decode()
    return f"{_V4_PREFIX}{packed}"


def _decrypt_bytes(encrypted_str: str) -> bytes:
    """Decrypt any supported envelope: v4 / v3 / v2 / legacy fixed-salt."""
    if encrypted_str.startswith(_V4_PREFIX):
        salt, token = _unpack_salted_envelope(encrypted_str, _V4_PREFIX)
        return _derive_fernet_v4(salt).decrypt(token)

    if encrypted_str.startswith(_V3_PREFIX):
        salt, token = _unpack_salted_envelope(encrypted_str, _V3_PREFIX)
        return _derive_fernet(salt, _ITERATIONS_V3).decrypt(token)

    if encrypted_str.startswith(_V2_PREFIX):
        salt, token = _unpack_salted_envelope(encrypted_str, _V2_PREFIX)
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
        except ValueError:
            pass
    return payload


def encrypt_string(text: str) -> str:
    """Encrypt a plain string."""
    return _encrypt_bytes(text.encode())


def decrypt_string(encrypted_str: str) -> str:
    """Decrypt an encrypted string."""
    return _decrypt_bytes(encrypted_str).decode()
