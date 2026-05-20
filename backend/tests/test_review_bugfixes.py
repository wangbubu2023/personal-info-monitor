import asyncio
import base64
import json
from datetime import timedelta

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.api.dashboard import _today_window_utc_naive
from app.collectors import get_collector
from app.config import get_settings
from app.platform.runtime.lifespan import _mask_secret
from app.models.content import Content
from app.platform.security.encryption import decrypt_data, encrypt_data


def _legacy_fixed_salt_encrypt(payload: dict) -> str:
    settings = get_settings()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"personal-info-monitor-salt",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.encryption_key.encode()))
    token = Fernet(key).encrypt(json.dumps(payload).encode())
    return base64.urlsafe_b64encode(token).decode()


def _legacy_v2_encrypt(payload: dict) -> str:
    import secrets as _secrets

    settings = get_settings()
    salt = _secrets.token_bytes(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.encryption_key.encode()))
    token = Fernet(key).encrypt(json.dumps(payload).encode())
    packed = base64.urlsafe_b64encode(salt + token).decode()
    return f"v2:{packed}"


def test_encrypt_data_roundtrip_uses_v3_envelope():
    encrypted = encrypt_data({"foo": "bar"})
    assert encrypted.startswith("v3:")
    assert decrypt_data(encrypted) == {"foo": "bar"}


def test_decrypt_data_supports_fixed_salt_legacy_payload():
    legacy = _legacy_fixed_salt_encrypt({"legacy": True})
    assert decrypt_data(legacy) == {"legacy": True}


def test_decrypt_data_supports_v2_payload():
    legacy = _legacy_v2_encrypt({"legacy_v2": True})
    assert legacy.startswith("v2:")
    assert decrypt_data(legacy) == {"legacy_v2": True}


def test_encrypt_data_uses_600k_iterations():
    """Guard-rail test: catch accidental downgrades of PBKDF2 work factor."""
    from app.utils import encryption

    assert encryption._ITERATIONS_DEFAULT >= 600_000
    assert encryption._ITERATIONS_V3 == 600_000


def test_collector_factory_supports_rss():
    collector = get_collector("rss")
    assert collector.__class__.__name__ == "RSSCollector"


def test_content_repr_handles_missing_title():
    content = Content(title=None)
    rendered = repr(content)
    assert "Content" in rendered


def test_asyncio_run_works_for_coroutines():
    async def _add(a: int, b: int) -> int:
        return a + b

    assert asyncio.run(_add(1, 2)) == 3
    assert asyncio.run(_add(4, 5)) == 9


def test_mask_secret_hides_sensitive_token():
    assert _mask_secret("") == "(not set)"
    assert _mask_secret("abcd") == "****"
    assert _mask_secret("abcdefghijklmnopqrstuvwxyz") == "abcd...wxyz"


def test_dashboard_today_window_is_utc_naive_and_24h():
    start_utc, end_utc = _today_window_utc_naive()

    assert start_utc.tzinfo is None
    assert end_utc.tzinfo is None
    assert end_utc > start_utc
    assert end_utc - start_utc == timedelta(days=1)
