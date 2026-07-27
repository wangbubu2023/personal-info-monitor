import io
import zipfile
import pytest
from sqlalchemy import create_engine

from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.domains.fetch.auth_zip import (
    ArchiveSecurityError,
    extract_auth_archive_safely,
    validate_and_inspect_zip,
)
from app.domains.fetch.local_capture import (
    generate_task_token,
    process_local_capture,
    verify_origin_allowlist,
    verify_task_token,
)


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


def test_m4_03_local_capture_token_and_origin_allowlist(sync_db: Session):
    device_id = "macbook-pro-m4-sheldon"
    origin_url = "https://bloomberg.com/news/articles/2026-07-24"

    # 1. 生成合法 5分钟 task_token
    token = generate_task_token(device_id, origin_url)
    assert verify_task_token(token, device_id, origin_url) is True
    assert verify_task_token(token, "other-device", origin_url) is False

    # 2. Origin Allowlist 校验
    allowlist = ["bloomberg.com", "wsj.com"]
    assert verify_origin_allowlist(origin_url, allowlist) is True
    assert verify_origin_allowlist("https://evil.com", allowlist) is False

    # 3. 正常接收并净化 ReaderDocument
    audit = process_local_capture(
        sync_db,
        device_id=device_id,
        task_token=token,
        origin_url=origin_url,
        reader_doc_title="Bloomberg Exclusive",
        reader_doc_body="Purified article body from local content script.",
        allowlist=allowlist,
    )
    assert audit.device_id == device_id
    assert audit.origin_url == origin_url
    assert audit.reader_doc_checksum is not None


def test_m4_05_auth_zip_safety_guards(sync_db: Session):
    # 1. 正常 Safe Zip 文件
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc1.txt", "Normal article text content.")
    safe_bytes = buf.getvalue()

    entry_count, uncompressed_bytes, ratio, safe_entries = validate_and_inspect_zip(safe_bytes)
    assert entry_count == 1
    assert len(safe_entries) == 1

    extraction = extract_auth_archive_safely(sync_db, "safe_docs.zip", safe_bytes)
    assert extraction.status == "success"
    assert extraction.rejection_reason is None

    # 2. Zip Slip 恶意攻击防范 (检测 ../)
    buf_slip = io.BytesIO()
    with zipfile.ZipFile(buf_slip, "w") as zf:
        zf.writestr("../../../etc/passwd", "root:x:0:0:")
    slip_bytes = buf_slip.getvalue()

    with pytest.raises(ArchiveSecurityError) as exc_info:
        validate_and_inspect_zip(slip_bytes)
    assert "Zip Slip detected" in str(exc_info.value)

    extraction_slip = extract_auth_archive_safely(sync_db, "malicious_slip.zip", slip_bytes)
    assert extraction_slip.status == "rejected"
    assert "Zip Slip detected" in extraction_slip.rejection_reason



    # 3. Symlink 软链接攻击防范
    buf_sym = io.BytesIO()
    with zipfile.ZipFile(buf_sym, "w") as zf:
        zinfo = zipfile.ZipInfo("symlink_entry")
        # 标志 0o120000 属于 Unix S_IFLNK 软链接
        zinfo.external_attr = 0o120777 << 16
        zf.writestr(zinfo, "/etc/shadow")
    sym_bytes = buf_sym.getvalue()

    with pytest.raises(ArchiveSecurityError) as exc_info:
        validate_and_inspect_zip(sym_bytes)
    assert "Symlink entry detected" in str(exc_info.value)
