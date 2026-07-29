"""Security validation and bounded reads for Auth ZIP archives."""

from __future__ import annotations

import io
import json
from pathlib import PurePosixPath
import stat
from typing import BinaryIO
import uuid
import zipfile

from sqlalchemy.orm import Session

from app.models.paid_matrix import AuthArchiveExtraction
from app.utils.datetime import utcnow_naive

MAX_COMPRESSED_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_JSON_MEMBER_BYTES = 10 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0
MAX_ENTRY_COUNT = 10000


class ArchiveSecurityError(ValueError):
    """The archive violates a fail-closed security limit."""


def _validate_member_path(name: str) -> str:
    if not name or "\x00" in name or "\\" in name:
        raise ArchiveSecurityError(f"Unsafe archive entry path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise ArchiveSecurityError(f"Zip Slip detected in entry path: {name!r}")
    normalized = path.as_posix()
    if normalized in {".", ""}:
        raise ArchiveSecurityError(f"Unsafe archive entry path: {name!r}")
    return normalized


def _validate_member_type(info: zipfile.ZipInfo) -> None:
    if info.flag_bits & 0x1:
        raise ArchiveSecurityError(f"Encrypted archive entry is not supported: {info.filename!r}")
    unix_mode = info.external_attr >> 16
    if not unix_mode:
        return
    file_type = stat.S_IFMT(unix_mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ArchiveSecurityError(f"Symlink or special archive entry rejected: {info.filename!r}")


ArchiveSource = bytes | bytearray | BinaryIO


def _seekable_source(source: ArchiveSource) -> tuple[BinaryIO, int]:
    if isinstance(source, (bytes, bytearray)):
        payload = bytes(source)
        return io.BytesIO(payload), len(payload)
    try:
        source.seek(0, io.SEEK_END)
        size = int(source.tell())
        source.seek(0)
    except (AttributeError, OSError, ValueError) as exc:
        raise ArchiveSecurityError("Auth archive upload must be seekable") from exc
    return source, size


def validate_and_inspect_zip(zip_source: ArchiveSource) -> tuple[int, int, float, dict[str, zipfile.ZipInfo]]:
    """Validate archive metadata before any member is read."""

    source, compressed_size = _seekable_source(zip_source)
    if compressed_size == 0:
        raise ArchiveSecurityError("Empty archive file")
    if compressed_size > MAX_COMPRESSED_ARCHIVE_BYTES:
        raise ArchiveSecurityError(
            f"Compressed archive size ({compressed_size} bytes) exceeds limit ({MAX_COMPRESSED_ARCHIVE_BYTES} bytes)"
        )

    try:
        with zipfile.ZipFile(source, mode="r") as archive:
            infolist = archive.infolist()
    except (OSError, zipfile.BadZipFile) as err:
        raise ArchiveSecurityError(f"Malformed or corrupted zip archive: {err}") from err

    if len(infolist) > MAX_ENTRY_COUNT:
        raise ArchiveSecurityError(
            f"Archive entry count {len(infolist)} exceeds maximum allowed ({MAX_ENTRY_COUNT})"
        )

    entries: dict[str, zipfile.ZipInfo] = {}
    total_uncompressed_bytes = 0
    total_compressed_members = 0
    for info in infolist:
        name = _validate_member_path(info.filename)
        _validate_member_type(info)
        if name in entries:
            raise ArchiveSecurityError(f"Duplicate archive entry rejected: {name!r}")
        if info.file_size < 0 or info.compress_size < 0:
            raise ArchiveSecurityError(f"Invalid archive size metadata for {name!r}")
        if info.file_size > MAX_SINGLE_FILE_BYTES:
            raise ArchiveSecurityError(
                f"Entry {name!r} uncompressed size ({info.file_size} bytes) exceeds limit ({MAX_SINGLE_FILE_BYTES} bytes)"
            )
        member_ratio = info.file_size / max(1, info.compress_size)
        if info.file_size and member_ratio > MAX_COMPRESSION_RATIO:
            raise ArchiveSecurityError(
                f"Entry {name!r} compression ratio ({member_ratio:.1f}:1) exceeds limit ({MAX_COMPRESSION_RATIO}:1)"
            )
        total_uncompressed_bytes += info.file_size
        total_compressed_members += info.compress_size
        entries[name] = info

        if info.is_dir():
            if name != "profiles" and not name.startswith("profiles/"):
                raise ArchiveSecurityError(f"Unexpected archive directory: {name!r}")
        elif name != "manifest.json" and not (
            name.startswith("profiles/") and PurePosixPath(name).suffix.lower() == ".json"
        ):
            raise ArchiveSecurityError(f"Unexpected archive member path or type: {name!r}")

    if total_uncompressed_bytes > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise ArchiveSecurityError(
            f"Total uncompressed size ({total_uncompressed_bytes} bytes) exceeds limit ({MAX_TOTAL_UNCOMPRESSED_BYTES} bytes)"
        )
    ratio = total_uncompressed_bytes / max(1, total_compressed_members or compressed_size)
    if ratio > MAX_COMPRESSION_RATIO:
        raise ArchiveSecurityError(
            f"Suspicious compression ratio ({ratio:.1f}:1) exceeds safety threshold ({MAX_COMPRESSION_RATIO}:1)"
        )
    return len(infolist), total_uncompressed_bytes, ratio, entries


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_bytes: int = MAX_JSON_MEMBER_BYTES,
) -> bytes:
    if info.is_dir():
        raise ArchiveSecurityError(f"Archive member is a directory: {info.filename!r}")
    if info.file_size > max_bytes:
        raise ArchiveSecurityError(f"Archive JSON member exceeds {max_bytes} bytes: {info.filename!r}")
    with archive.open(info, "r") as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes or len(payload) != info.file_size:
        raise ArchiveSecurityError(f"Archive member size mismatch or limit exceeded: {info.filename!r}")
    return payload


def _read_json_object(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> dict:
    try:
        value = json.loads(_read_member(archive, info).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveSecurityError(f"Archive member contains invalid UTF-8 JSON: {info.filename!r}") from exc
    if not isinstance(value, dict):
        raise ArchiveSecurityError(f"Archive JSON member must contain an object: {info.filename!r}")
    return value


def parse_auth_export_zip(
    zip_source: ArchiveSource,
    *,
    export_kind: str,
    bundle_kind: str,
) -> list[dict]:
    """Validate and parse the actual Auth Assistant export format."""

    _count, _uncompressed, _ratio, entries = validate_and_inspect_zip(zip_source)
    manifest_info = entries.get("manifest.json")
    if manifest_info is None:
        raise ArchiveSecurityError("Auth export zip is missing manifest.json")

    try:
        source, _compressed_size = _seekable_source(zip_source)
        with zipfile.ZipFile(source, mode="r") as archive:
            manifest = _read_json_object(archive, manifest_info)
            if manifest.get("kind") != export_kind:
                raise ArchiveSecurityError("Unsupported auth export kind")
            profiles = manifest.get("profiles")
            if not isinstance(profiles, list):
                raise ArchiveSecurityError("Auth export manifest profiles must be a list")

            bundles: list[dict] = []
            seen_profile_paths: set[str] = set()
            for item in profiles:
                if not isinstance(item, dict) or not isinstance(item.get("file"), str):
                    raise ArchiveSecurityError("Auth export manifest contains an invalid profile entry")
                profile_path = _validate_member_path(item["file"])
                if not profile_path.startswith("profiles/") or PurePosixPath(profile_path).suffix.lower() != ".json":
                    raise ArchiveSecurityError(
                        f"Auth export profile must be a JSON file below profiles/: {profile_path!r}"
                    )
                if profile_path in seen_profile_paths:
                    raise ArchiveSecurityError(f"Auth export manifest repeats profile path: {profile_path!r}")
                seen_profile_paths.add(profile_path)
                info = entries.get(profile_path)
                if info is None:
                    raise ArchiveSecurityError(f"Auth export zip is missing profile: {profile_path!r}")
                bundle = _read_json_object(archive, info)
                if bundle.get("kind") != bundle_kind:
                    raise ArchiveSecurityError(f"Unsupported auth bundle kind in {profile_path!r}")
                bundles.append(bundle)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveSecurityError("Uploaded file is not a valid zip") from exc

    if not bundles:
        raise ArchiveSecurityError("Auth export zip contains no auth bundles")
    return bundles


def extract_auth_archive_safely(
    db: Session,
    archive_name: str,
    zip_bytes: ArchiveSource,
) -> AuthArchiveExtraction:
    """Validate an archive and persist a security-audit result."""

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
