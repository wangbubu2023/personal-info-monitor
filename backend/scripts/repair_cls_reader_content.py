"""Repair 财联社 rows polluted by navigation/footer extraction.

Dry-run by default. ``--apply`` creates a SQLite backup, refetches only
strongly matched polluted rows, and updates them only when CLS' item-scoped
``__NEXT_DATA__.articleDetail`` payload can be extracted.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings
from app.domains.ingest.quality_metadata import merge_content_quality_metadata
from app.utils.structured_article import extract_structured_article

_POLLUTION_MARKERS = (
    "关于我们",
    "网站声明",
    "联系方式",
    "用户反馈",
    "网站地图",
    "关联话题",
    "举报电话",
    "举报邮箱",
    "沪ICP备",
    "沪公网安备",
    "互联网新闻信息服务许可证",
)
_TRANSLATION_CACHE_KEYS = (
    "reader_translated_full_content",
    "reader_translated_body_hash",
    "reader_translation_ready",
    "reader_translation_ratio",
)


@dataclass(frozen=True)
class RepairCandidate:
    content_id: str
    source_name: str
    original_url: str
    title: str
    old_body: str
    old_summary: str
    metadata: dict


@dataclass(frozen=True)
class RepairResult:
    candidate: RepairCandidate
    body: str
    summary: str
    publish_time: str | None
    metadata: dict


def _default_database_path() -> Path:
    url = str(get_settings().database_url)
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise SystemExit(f"Only SQLite databases are supported, got: {url}")
    return Path(url.removeprefix(prefix)).expanduser().resolve()


def _backup_database(connection: sqlite3.Connection, database_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = database_path.with_name(
        f"{database_path.name}.pre-cls-reader-repair-{timestamp}.bak"
    )
    with sqlite3.connect(backup_path) as backup:
        connection.backup(backup)
    return backup_path


def _is_polluted_cls_body(source_name: str, url: str, body: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if "财联社" not in source_name and host not in {"cls.cn", "www.cls.cn"}:
        return False
    marker_hits = sum(1 for marker in _POLLUTION_MARKERS if marker in body)
    return marker_hits >= 4


def find_candidates(
    connection: sqlite3.Connection,
    *,
    content_ids: list[str] | None = None,
    limit: int = 100,
) -> list[RepairCandidate]:
    ids = [value.strip() for value in (content_ids or []) if value.strip()]
    where = ["coalesce(c.is_user_edited, 0) = 0"]
    params: list[object] = []
    if ids:
        where.append(f"c.id IN ({','.join('?' for _ in ids)})")
        params.extend(ids)
    params.append(max(1, limit))
    rows = connection.execute(
        f"""
        SELECT c.id, s.name, c.original_url, c.title,
               coalesce(c.full_content, ''), coalesce(c.summary, ''),
               coalesce(c.metadata, '{{}}')
        FROM contents AS c
        JOIN sources AS s ON s.id = c.source_id
        WHERE {' AND '.join(where)}
        ORDER BY c.created_at DESC
        LIMIT ?
        """,
        params,
    )
    candidates: list[RepairCandidate] = []
    explicit_ids = set(ids)
    for row in rows:
        content_id, source_name, original_url, title, body, summary, raw_metadata = row
        is_cls = (
            "财联社" in str(source_name)
            or (urlparse(str(original_url)).hostname or "").lower() in {"cls.cn", "www.cls.cn"}
        )
        if not is_cls:
            continue
        if str(content_id) not in explicit_ids and not _is_polluted_cls_body(
            str(source_name), str(original_url), str(body)
        ):
            continue
        try:
            metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else dict(raw_metadata)
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        candidates.append(
            RepairCandidate(
                content_id=str(content_id),
                source_name=str(source_name),
                original_url=str(original_url),
                title=str(title),
                old_body=str(body),
                old_summary=str(summary),
                metadata=metadata,
            )
        )
    return candidates


def _fetch_html(url: str, *, timeout_seconds: float) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {"cls.cn", "www.cls.cn"}:
        raise ValueError(f"Refusing non-CLS URL: {url}")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - host allowlisted above
        return response.read().decode("utf-8", errors="replace")


def build_repair(candidate: RepairCandidate, *, timeout_seconds: float = 20) -> RepairResult:
    html = _fetch_html(candidate.original_url, timeout_seconds=timeout_seconds)
    extracted = extract_structured_article(html, min_chars=120)
    if not extracted or extracted.method != "cls_next_data":
        raise ValueError("CLS item-scoped structured body was not found")
    body = extracted.text.strip()
    summary = body.split("\n\n", 1)[-1].strip()
    if not summary or candidate.title not in body:
        raise ValueError("CLS structured body does not match the stored title")

    metadata = dict(candidate.metadata)
    for key in _TRANSLATION_CACHE_KEYS:
        metadata.pop(key, None)
    metadata.update(
        {
            "article_fulltext": True,
            "article_extract_method": "structured:cls_next_data",
            "reader_fulltext_quality_status": "cls_next_data",
            "reader_fulltext_repaired_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    metadata.pop("reader_fulltext_backfill_failed", None)
    metadata.pop("reader_fulltext_backfill_failed_at", None)
    metadata.pop("reader_fulltext_backfill_rejected_status", None)
    metadata = merge_content_quality_metadata(
        metadata,
        title=candidate.title,
        full_content=body,
        summary=summary,
    )

    published_iso = str(extracted.signals.get("published_time") or "").strip()
    publish_time = None
    if published_iso:
        published = datetime.fromisoformat(published_iso)
        publish_time = published.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
    return RepairResult(
        candidate=candidate,
        body=body,
        summary=summary,
        publish_time=publish_time,
        metadata=metadata,
    )


def apply_repairs(connection: sqlite3.Connection, repairs: list[RepairResult]) -> list[str]:
    updated: list[str] = []
    with connection:
        for repair in repairs:
            cursor = connection.execute(
                """
                UPDATE contents
                SET full_content = ?, summary = ?, publish_time = ?,
                    metadata = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND full_content = ? AND coalesce(is_user_edited, 0) = 0
                """,
                (
                    repair.body,
                    repair.summary,
                    repair.publish_time,
                    json.dumps(repair.metadata, ensure_ascii=False),
                    repair.candidate.content_id,
                    repair.candidate.old_body,
                ),
            )
            if cursor.rowcount:
                updated.append(repair.candidate.content_id)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="SQLite pim.db path")
    parser.add_argument("--content-id", action="append", default=[], help="Restrict to a content UUID")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--apply", action="store_true", help="Back up and apply reviewed repairs")
    args = parser.parse_args()

    database_path = (args.database or _default_database_path()).expanduser().resolve()
    if not database_path.is_file():
        raise SystemExit(f"Database not found: {database_path}")

    with sqlite3.connect(database_path) as connection:
        candidates = find_candidates(
            connection,
            content_ids=args.content_id,
            limit=args.limit,
        )
        repairs: list[RepairResult] = []
        for candidate in candidates:
            try:
                repair = build_repair(candidate, timeout_seconds=args.timeout)
            except Exception as exc:  # noqa: BLE001 - report per-row fetch/extraction failure
                print(f"[skip] {candidate.content_id}: {exc}")
                continue
            repairs.append(repair)
            print(f"[repair] {candidate.content_id} | {candidate.source_name}")
            print(f"  URL: {candidate.original_url}")
            print(f"  Body: {len(candidate.old_body)} -> {len(repair.body)} chars")
            print(f"  Proposed:\n{repair.body}")

        print(f"Candidates: {len(candidates)}; repairable: {len(repairs)}")
        if not args.apply:
            print("Dry-run only; rerun with --apply after reviewing every candidate.")
            return 0

        backup_path = _backup_database(connection, database_path)
        updated_ids = apply_repairs(connection, repairs)
        print(f"Backup: {backup_path}")
        print(f"Updated: {len(updated_ids)}")

    if updated_ids:
        from app.platform.workers.postprocess_jobs import ensure_postprocess_jobs

        ensure_postprocess_jobs(
            [(content_id, "repair:cls-next-data-v1") for content_id in updated_ids]
        )
        print(f"Postprocess queued: {len(updated_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
