"""Runtime-secrets lifecycle: fail closed on corruption, generate only when absent."""

from __future__ import annotations

import json

import pytest

from app.platform.config.settings import (
    RuntimeSecretsError,
    _ensure_runtime_secrets,
    _read_runtime_secrets,
    _runtime_secrets_path,
)


def test_missing_file_reads_as_empty(tmp_path):
    assert _read_runtime_secrets(tmp_path / "runtime-secrets.json") == {}


def test_valid_file_round_trips(tmp_path):
    path = tmp_path / "runtime-secrets.json"
    path.write_text(
        json.dumps(
            {
                "ENCRYPTION_KEY": "enc",
                "PIM_API_KEY": "api",
                "BOOTSTRAP_TOKEN": "boot",
            }
        ),
        encoding="utf-8",
    )
    assert _read_runtime_secrets(path) == {
        "ENCRYPTION_KEY": "enc",
        "PIM_API_KEY": "api",
        "BOOTSTRAP_TOKEN": "boot",
    }


def test_absent_file_generates_fresh_secrets(tmp_path):
    secrets = _ensure_runtime_secrets(str(tmp_path))
    assert secrets["ENCRYPTION_KEY"]
    assert secrets["PIM_API_KEY"]
    assert secrets["BOOTSTRAP_TOKEN"]
    # Persisted for next boot.
    assert _runtime_secrets_path(str(tmp_path)).exists()


def test_corrupt_json_fails_closed_without_overwrite(tmp_path):
    path = _runtime_secrets_path(str(tmp_path))
    path.write_text("{not valid json", encoding="utf-8")
    original = path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeSecretsError):
        _read_runtime_secrets(path)

    # Must not silently regenerate / overwrite the corrupt file.
    with pytest.raises(RuntimeSecretsError):
        _ensure_runtime_secrets(str(tmp_path))
    assert path.read_text(encoding="utf-8") == original


def test_non_object_payload_fails_closed(tmp_path):
    path = _runtime_secrets_path(str(tmp_path))
    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    with pytest.raises(RuntimeSecretsError):
        _read_runtime_secrets(path)


def test_partial_dict_preserves_existing_key(tmp_path):
    """A valid object missing some keys is upgraded, never key-rotated."""
    path = _runtime_secrets_path(str(tmp_path))
    path.write_text(json.dumps({"ENCRYPTION_KEY": "keep-me"}), encoding="utf-8")

    secrets = _ensure_runtime_secrets(str(tmp_path))
    assert secrets["ENCRYPTION_KEY"] == "keep-me"
    assert secrets["PIM_API_KEY"]
    assert secrets["BOOTSTRAP_TOKEN"]
    assert json.loads(path.read_text(encoding="utf-8"))["ENCRYPTION_KEY"] == "keep-me"
