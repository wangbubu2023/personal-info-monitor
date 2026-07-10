"""Find and optionally repair losslessly reversible mojibake RSS titles.

Dry-run by default. Use ``--apply`` to create a SQLite backup and update only
rows whose title still matches the scanned value.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.config import get_settings

_MOJIBAKE_MARKERS = frozenset("ÃÂâåæçäéèðþ")


@dataclass(frozen=True)
class RepairCandidate:
    content_id: str
    source_name: str
    external_id: str
    original: str
    repaired: str
    encoding: str


def _suspicion_score(value: str) -> int:
    score = sum(4 for char in value if 0x80 <= ord(char) <= 0x9F)
    score += sum(1 for char in value if char in _MOJIBAKE_MARKERS)
    score += value.count("�") * 8
    score += sum(value.count(marker) * 2 for marker in ("â€", "Ã", "Â", "å°", "ä¸", "æ–"))
    return score


def _cjk_count(value: str) -> int:
    return sum(1 for char in value if "\u3400" <= char <= "\u9fff")


def repair_title_losslessly(value: str) -> tuple[str, str] | None:
    """Return ``(fixed, source_encoding)`` only for a strong, strict repair."""
    if not value or "�" in value:
        return None
    original_score = _suspicion_score(value)
    candidates: list[tuple[int, str, str]] = []
    for encoding in ("latin-1", "cp1252"):
        try:
            repaired = value.encode(encoding, errors="strict").decode("utf-8", errors="strict")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired == value:
            continue
        improvement = original_score - _suspicion_score(repaired)
        cjk_gain = _cjk_count(repaired) - _cjk_count(value)
        if improvement >= 3 and (cjk_gain > 0 or original_score >= 5):
            candidates.append((improvement + cjk_gain, repaired, encoding))
    if not candidates:
        return None
    _, repaired, encoding = max(candidates, key=lambda item: item[0])
    return repaired, encoding


def find_candidates(
    connection: sqlite3.Connection,
    *,
    content_ids: Iterable[str] = (),
    include_user_edited: bool = False,
) -> list[RepairCandidate]:
    ids = [value.strip() for value in content_ids if value.strip()]
    where = ["lower(s.type) = 'rss'"]
    params: list[str] = []
    if not include_user_edited:
        where.append("coalesce(c.is_user_edited, 0) = 0")
    if ids:
        where.append(f"c.id IN ({','.join('?' for _ in ids)})")
        params.extend(ids)
    rows = connection.execute(
        f"""
        SELECT c.id, c.title, coalesce(c.external_id, ''), s.name
        FROM contents AS c
        JOIN sources AS s ON s.id = c.source_id
        WHERE {' AND '.join(where)}
        ORDER BY c.created_at DESC
        """,
        params,
    )
    candidates: list[RepairCandidate] = []
    for content_id, title, external_id, source_name in rows:
        result = repair_title_losslessly(str(title or ""))
        if result is None:
            continue
        repaired, encoding = result
        candidates.append(
            RepairCandidate(
                content_id=str(content_id),
                source_name=str(source_name),
                external_id=str(external_id),
                original=str(title),
                repaired=repaired,
                encoding=encoding,
            )
        )
    return candidates


def _default_database_path() -> Path:
    url = str(get_settings().database_url)
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise SystemExit(f"Only SQLite databases are supported, got: {url}")
    return Path(url.removeprefix(prefix)).expanduser().resolve()


def _backup_database(connection: sqlite3.Connection, database_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = database_path.with_name(f"{database_path.name}.pre-mojibake-{timestamp}.bak")
    with sqlite3.connect(backup_path) as backup:
        connection.backup(backup)
    return backup_path


def apply_candidates(connection: sqlite3.Connection, candidates: Iterable[RepairCandidate]) -> int:
    updated = 0
    with connection:
        for item in candidates:
            cursor = connection.execute(
                """
                UPDATE contents
                SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND title = ?
                """,
                (item.repaired, item.content_id, item.original),
            )
            updated += cursor.rowcount
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="SQLite pim.db path")
    parser.add_argument("--content-id", action="append", default=[], help="Restrict to a content UUID")
    parser.add_argument("--include-user-edited", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Back up the DB and apply strict repairs")
    args = parser.parse_args()

    database_path = (args.database or _default_database_path()).expanduser().resolve()
    if not database_path.is_file():
        raise SystemExit(f"Database not found: {database_path}")
    with sqlite3.connect(database_path) as connection:
        candidates = find_candidates(
            connection,
            content_ids=args.content_id,
            include_user_edited=args.include_user_edited,
        )
        for item in candidates:
            print(f"[{item.encoding}] {item.content_id} | {item.source_name} | {item.external_id}")
            print(f"  - {item.original}")
            print(f"  + {item.repaired}")
        print(f"Candidates: {len(candidates)}")
        if not args.apply:
            print("Dry-run only; rerun with --apply after reviewing every candidate.")
            return 0
        backup_path = _backup_database(connection, database_path)
        updated = apply_candidates(connection, candidates)
        print(f"Backup: {backup_path}")
        print(f"Updated: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
