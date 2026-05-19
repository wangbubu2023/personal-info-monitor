"""Extra coverage for :mod:`app.utils.encryption`."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet

from app.config import get_settings
from app.utils.encryption import (
    _LEGACY_STATIC_SALT,
    _SALT_LENGTH,
    _V2_PREFIX,
    decrypt_data,
    decrypt_string,
    encrypt_data,
    encrypt_string,
)


def _derive(salt: bytes, iterations: int) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    key = base64.urlsafe_b64encode(kdf.derive(get_settings().encryption_key.encode()))
    return Fernet(key)


class TestEncryptData:
    def test_roundtrip_dict(self):
        payload = {"hello": "world", "num": 1}
        encrypted = encrypt_data(payload)
        assert encrypted.startswith("v3:")
        assert decrypt_data(encrypted) == payload

    def test_rejects_non_dict(self):
        with pytest.raises(TypeError):
            encrypt_data("not a dict")  # type: ignore[arg-type]


class TestEncryptString:
    def test_roundtrip(self):
        encrypted = encrypt_string("secret value")
        assert decrypt_string(encrypted) == "secret value"


class TestLegacyEnvelopes:
    def test_decrypts_v2_envelope(self):
        salt = b"0123456789abcdef"
        assert len(salt) == _SALT_LENGTH
        fernet = _derive(salt, 100_000)
        token = fernet.encrypt(json.dumps({"legacy": True}).encode())
        packed = base64.urlsafe_b64encode(salt + token).decode()
        encrypted = f"{_V2_PREFIX}{packed}"
        assert decrypt_data(encrypted) == {"legacy": True}

    def test_decrypts_legacy_static_salt(self):
        fernet = _derive(_LEGACY_STATIC_SALT, 100_000)
        token = fernet.encrypt(json.dumps({"legacy": "static"}).encode())
        encoded = base64.urlsafe_b64encode(token).decode()
        assert decrypt_data(encoded) == {"legacy": "static"}

    def test_v3_invalid_short_payload(self):
        # less than salt length
        bad = "v3:" + base64.urlsafe_b64encode(b"short").decode()
        with pytest.raises(ValueError):
            decrypt_data(bad)

    def test_v2_invalid_short_payload(self):
        bad = "v2:" + base64.urlsafe_b64encode(b"short").decode()
        with pytest.raises(ValueError):
            decrypt_data(bad)


class TestDoubleSerializedLegacy:
    def test_rewraps_json_string_payload(self):
        salt = b"0123456789abcdef"
        fernet = _derive(salt, 600_000)
        # Payload is json.dumps(dict-as-string)
        inner_json = json.dumps({"key": "value"})
        outer = json.dumps(inner_json).encode()
        token = fernet.encrypt(outer)
        packed = base64.urlsafe_b64encode(salt + token).decode()
        encrypted = f"v3:{packed}"
        assert decrypt_data(encrypted) == {"key": "value"}

    def test_returns_string_when_not_json(self):
        salt = b"0123456789abcdef"
        fernet = _derive(salt, 600_000)
        outer = json.dumps("plain string").encode()
        token = fernet.encrypt(outer)
        packed = base64.urlsafe_b64encode(salt + token).decode()
        encrypted = f"v3:{packed}"
        # decrypt_data returns the raw string when re-parsing fails
        assert decrypt_data(encrypted) == "plain string"
