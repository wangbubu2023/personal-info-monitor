from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.domains.fetch.auth_zip import (
    ArchiveSecurityError,
    extract_auth_archive_safely,
    parse_auth_export_zip,
    validate_and_inspect_zip,
)
from app.domains.fetch.local_capture import (
    MAX_READER_DOC_BODY_CHARS,
    MAX_READER_DOC_TITLE_CHARS,
    issue_local_capture_task_token,
    process_local_capture,
    verify_origin_allowlist,
    verify_task_token,
)
from app.models.auth_assistant import AuthAssistantDevice, AuthAssistantDeviceStatus
from app.models.source import Source


def _load_local_capture_request_model():
    path = Path(__file__).resolve().parents[1] / "app" / "interfaces" / "http" / "paid_matrix.py"
    spec = importlib.util.spec_from_file_location("paid_matrix_http_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LocalCaptureRequest


@pytest.fixture
def sync_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_m4_03_local_capture_is_server_allowlisted_and_one_time(sync_db: Session):
    source = Source(
        name="Bloomberg Premium",
        url="https://bloomberg.com",
        type="website",
        auth_required=True,
        enabled=True,
    )
    device = AuthAssistantDevice(
        name="Local Capture Browser",
        token_hash="capture-device-token-hash",
        status=AuthAssistantDeviceStatus.ACTIVE,
    )
    sync_db.add_all([source, device])
    sync_db.commit()

    device_id = str(device.id)
    origin_url = "https://www.bloomberg.com/news/articles/2026-07-24"
    token = issue_local_capture_task_token(sync_db, device_id, origin_url)
    assert verify_task_token(token, device_id, origin_url) is True
    assert verify_task_token(token, "other-device", origin_url) is False

    assert verify_origin_allowlist(origin_url, ["bloomberg.com"]) is True
    assert verify_origin_allowlist("https://bloomberg.com.evil.test", ["bloomberg.com"]) is False
    assert verify_origin_allowlist("https://evil.test/?next=bloomberg.com", ["bloomberg.com"]) is False
    assert verify_origin_allowlist(origin_url, None) is False

    audit = process_local_capture(
        sync_db,
        device_id=device_id,
        task_token=token,
        origin_url=origin_url,
        reader_doc_title="Bloomberg Exclusive",
        reader_doc_body="Purified article body from the local content script.",
    )
    assert audit.device_id == device_id
    assert audit.origin_url == "https://www.bloomberg.com"
    assert audit.reader_doc_checksum

    with pytest.raises(ValueError, match="already been consumed"):
        process_local_capture(
            sync_db,
            device_id=device_id,
            task_token=token,
            origin_url=origin_url,
            reader_doc_title="Bloomberg Exclusive",
            reader_doc_body="Purified article body from the local content script.",
        )

    device.status = AuthAssistantDeviceStatus.REVOKED
    sync_db.commit()
    with pytest.raises(ValueError, match="revoked"):
        issue_local_capture_task_token(sync_db, device_id, origin_url)


def test_m4_03_local_capture_rejects_oversized_reader_documents(sync_db: Session):
    source = Source(
        name="Bloomberg Premium",
        url="https://bloomberg.com",
        type="website",
        auth_required=True,
        enabled=True,
    )
    device = AuthAssistantDevice(
        name="Local Capture Browser",
        token_hash="capture-size-device-token-hash",
        status=AuthAssistantDeviceStatus.ACTIVE,
    )
    sync_db.add_all([source, device])
    sync_db.commit()

    device_id = str(device.id)
    origin_url = "https://www.bloomberg.com/news/articles/2026-07-24"
    token = issue_local_capture_task_token(sync_db, device_id, origin_url)
    LocalCaptureRequest = _load_local_capture_request_model()
    common_request = {
        "device_id": device_id,
        "task_token": token,
        "origin_url": origin_url,
    }

    with pytest.raises(ValidationError, match="reader_doc_title"):
        LocalCaptureRequest(
            **common_request,
            reader_doc_title="t" * (MAX_READER_DOC_TITLE_CHARS + 1),
            reader_doc_body="body",
        )
    with pytest.raises(ValidationError, match="reader_doc_body"):
        LocalCaptureRequest(
            **common_request,
            reader_doc_title="title",
            reader_doc_body="b" * (MAX_READER_DOC_BODY_CHARS + 1),
        )

    with pytest.raises(ValueError, match="title exceeds"):
        process_local_capture(
            sync_db,
            **common_request,
            reader_doc_title="t" * (MAX_READER_DOC_TITLE_CHARS + 1),
            reader_doc_body="body",
        )
    with pytest.raises(ValueError, match="body exceeds"):
        process_local_capture(
            sync_db,
            **common_request,
            reader_doc_title="title",
            reader_doc_body="b" * (MAX_READER_DOC_BODY_CHARS + 1),
        )

    audit = process_local_capture(
        sync_db,
        **common_request,
        reader_doc_title="title",
        reader_doc_body="body",
    )
    assert audit.reader_doc_checksum


def test_m4_05_auth_zip_safety_guards(sync_db: Session):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"kind": "pim.auth_export", "profiles": [{"file": "profiles/doc1.json"}]}),
        )
        archive.writestr("profiles/doc1.json", json.dumps({"kind": "pim.auth_bundle"}))
    safe_bytes = buf.getvalue()
    entry_count, _uncompressed_bytes, _ratio, safe_entries = validate_and_inspect_zip(safe_bytes)
    assert entry_count == 2
    assert set(safe_entries) == {"manifest.json", "profiles/doc1.json"}
    extraction = extract_auth_archive_safely(sync_db, "safe_docs.zip", safe_bytes)
    assert extraction.status == "success"

    buf_slip = io.BytesIO()
    with zipfile.ZipFile(buf_slip, "w") as archive:
        archive.writestr("../../../etc/passwd", "root:x:0:0:")
    with pytest.raises(ArchiveSecurityError, match="Zip Slip"):
        validate_and_inspect_zip(buf_slip.getvalue())

    buf_sym = io.BytesIO()
    with zipfile.ZipFile(buf_sym, "w") as archive:
        info = zipfile.ZipInfo("symlink_entry")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "/etc/shadow")
    with pytest.raises(ArchiveSecurityError, match="Symlink or special"):
        validate_and_inspect_zip(buf_sym.getvalue())

    buf_windows = io.BytesIO()
    with zipfile.ZipFile(buf_windows, "w") as archive:
        archive.writestr(r"..\profile.json", "{}")
    with pytest.raises(ArchiveSecurityError, match="Unsafe archive entry path"):
        validate_and_inspect_zip(buf_windows.getvalue())

    unexpected = io.BytesIO()
    with zipfile.ZipFile(unexpected, "w") as archive:
        archive.writestr("cookies.txt", "secret")
    with pytest.raises(ArchiveSecurityError, match="Unexpected archive member"):
        validate_and_inspect_zip(unexpected.getvalue())


def test_actual_auth_export_parser_uses_hardened_paths():
    bundle = {"kind": "pim.auth_bundle", "site_url": "https://example.com"}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "kind": "pim.auth_export",
                    "profiles": [{"file": "profiles/example.json"}],
                }
            ),
        )
        archive.writestr("profiles/example.json", json.dumps(bundle))
    assert parse_auth_export_zip(
        output.getvalue(),
        export_kind="pim.auth_export",
        bundle_kind="pim.auth_bundle",
    ) == [bundle]

    malicious = io.BytesIO()
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"kind": "pim.auth_export", "profiles": [{"file": "../profile.json"}]}),
        )
        archive.writestr("../profile.json", json.dumps(bundle))
    with pytest.raises(ArchiveSecurityError, match="Zip Slip"):
        parse_auth_export_zip(
            malicious.getvalue(),
            export_kind="pim.auth_export",
            bundle_kind="pim.auth_bundle",
        )
