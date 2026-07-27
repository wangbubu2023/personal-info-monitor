"""Auth Archive (ZIP) safe streaming parser & security unpacker.

Protections:
1. Anti-Zip-Bomb: Single file max 100MB, total max 500MB, compression ratio max 100:1.
2. Anti-Zip-Slip: Rejects path traversal ('../') or absolute path entries.
3. Anti-Symlink: Ignores or rejects symbolic/hard links.
"""

import io
import os
import uuid
import zipfile

from sqlalchemy.orm import Session

from app.models.paid_matrix import AuthArchiveExtraction
from app.utils.datetime import utcnow_naive

# 安全限制门禁
MAX_SINGLE_FILE_BYTES = 100 * 1024 * 1024  # 100MB
MAX_TOTAL_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500MB
MAX_COMPRESSION_RATIO = 100.0  # 100:1
MAX_ENTRY_COUNT = 10000


class ArchiveSecurityError(Exception):
    """Archive 安全违规异常。"""

    pass


def validate_and_inspect_zip(zip_bytes: bytes) -> tuple[int, int, float, list[zipfile.ZipInfo]]:
    """安全地流式解析 Zip 数据，全面核验 Zip Bomb / Zip Slip / Symlink 等攻击。"""
    compressed_size = len(zip_bytes)
    if compressed_size == 0:
        raise ArchiveSecurityError("Empty archive file.")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r")
    except (OSError, zipfile.BadZipFile) as err:
        raise ArchiveSecurityError(f"Malformed or corrupted zip archive: {err}") from err

    infolist = zf.infolist()
    entry_count = len(infolist)
    if entry_count > MAX_ENTRY_COUNT:
        raise ArchiveSecurityError(f"Archive entry count {entry_count} exceeds maximum allowed ({MAX_ENTRY_COUNT}).")

    total_uncompressed_bytes = 0
    safe_entries = []

    for info in infolist:
        name = info.filename

        # 1. Zip Slip 校验 (防路径穿越)
        normalized_name = os.path.normpath(name)
        if (
            normalized_name.startswith("..")
            or normalized_name.startswith("/")
            or ".." in name.split("/")
            or name.startswith("\\")
        ):
            raise ArchiveSecurityError(f"Zip Slip detected in entry path: '{name}'. Operation rejected.")

        # 2. Symlink 校验
        # 在 standard zip format 中，Unix symlink mode 比特位在 external_attr >> 16
        unix_mode = info.external_attr >> 16
        if unix_mode and (unix_mode & 0o120000 == 0o120000):
            raise ArchiveSecurityError(f"Symlink entry detected: '{name}'. Operation rejected.")

        # 3. 单文件解压体积限制
        if info.file_size > MAX_SINGLE_FILE_BYTES:
            raise ArchiveSecurityError(
                f"Entry '{name}' uncompressed size ({info.file_size} bytes) exceeds max limit ({MAX_SINGLE_FILE_BYTES} bytes)."
            )

        total_uncompressed_bytes += info.file_size
        safe_entries.append(info)

    # 4. 总解压体积限制
    if total_uncompressed_bytes > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise ArchiveSecurityError(
            f"Total uncompressed size ({total_uncompressed_bytes} bytes) exceeds limit ({MAX_TOTAL_UNCOMPRESSED_BYTES} bytes)."
        )

    # 5. 压缩比限制 (Zip Bomb 识别)
    ratio = total_uncompressed_bytes / max(1, compressed_size)
    if ratio > MAX_COMPRESSION_RATIO:
        raise ArchiveSecurityError(
            f"Suspicious compression ratio ({ratio:.1f}:1) exceeds safety threshold ({MAX_COMPRESSION_RATIO}:1). Potential Zip Bomb rejected."
        )

    return entry_count, total_uncompressed_bytes, ratio, safe_entries


def extract_auth_archive_safely(
    db: Session,
    archive_name: str,
    zip_bytes: bytes,
) -> AuthArchiveExtraction:
    """提取并记录受权 Archive 解压过程。"""
    now = utcnow_naive()
    try:
        entry_count, uncompressed_bytes, ratio, _ = validate_and_inspect_zip(zip_bytes)
        extraction = AuthArchiveExtraction(
            id=str(uuid.uuid4()),
            archive_name=archive_name,
            entry_count=entry_count,
            uncompressed_bytes=uncompressed_bytes,
            compression_ratio=ratio,
            status="success",
            rejection_reason=None,
            created_at=now,
        )
    except ArchiveSecurityError as err:
        extraction = AuthArchiveExtraction(
            id=str(uuid.uuid4()),
            archive_name=archive_name,
            entry_count=0,
            uncompressed_bytes=0,
            compression_ratio=1.0,
            status="rejected",
            rejection_reason=str(err),
            created_at=now,
        )

    db.add(extraction)
    db.commit()
    db.refresh(extraction)
    return extraction
