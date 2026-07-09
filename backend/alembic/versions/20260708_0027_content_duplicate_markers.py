"""Add content duplicate markers.

Revision ID: 20260708_0027
Revises: 20260702_0026
Create Date: 2026-07-08
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from alembic import op


revision = "20260708_0027"
down_revision = "20260702_0026"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def _add_column_once(column: sa.Column) -> None:
    if not _column_exists("contents", column.name):
        op.add_column("contents", column)


def _create_index_once(index_name: str, columns: list[str]) -> None:
    if not _index_exists("contents", index_name):
        op.create_index(index_name, "contents", columns, unique=False)


def _drop_index_once(index_name: str) -> None:
    if _index_exists("contents", index_name):
        op.drop_index(index_name, table_name="contents")


def _drop_column_once(column_name: str) -> None:
    if _column_exists("contents", column_name):
        op.drop_column("contents", column_name)


def _loads_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except Exception:  # noqa: BLE001 - migration should skip malformed legacy metadata
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _backfill_existing_duplicate_groups() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, fetched_at, created_at, metadata "
            "FROM contents WHERE metadata IS NOT NULL"
        )
    ).mappings()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    metadatas: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = _loads_metadata(row["metadata"])
        group_id = str(metadata.get("duplicate_group_id") or "").strip()
        if not group_id:
            continue
        row_id = str(row["id"])
        metadatas[row_id] = metadata
        grouped[group_id].append(dict(row))

    update_sql = sa.text(
        "UPDATE contents "
        "SET is_duplicate = :is_duplicate, duplicate_of = :duplicate_of, metadata = :metadata "
        "WHERE id = :id"
    )
    for members in grouped.values():
        if len(members) < 2:
            continue
        canonical = min(
            members,
            key=lambda row: (
                row["fetched_at"] is None,
                str(row["fetched_at"] or row["created_at"] or ""),
                str(row["id"]),
            ),
        )
        canonical_id = str(canonical["id"])
        for member in members:
            member_id = str(member["id"])
            metadata = dict(metadatas.get(member_id) or {})
            is_duplicate = member_id != canonical_id
            if is_duplicate:
                metadata["is_duplicate"] = True
                metadata["duplicate_of"] = canonical_id
            else:
                metadata["is_duplicate"] = False
                metadata.pop("duplicate_of", None)
            bind.execute(
                update_sql,
                {
                    "id": member_id,
                    "is_duplicate": is_duplicate,
                    "duplicate_of": canonical_id if is_duplicate else None,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                },
            )


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("contents"):
        return
    _add_column_once(sa.Column("is_duplicate", sa.Boolean(), nullable=True))
    _add_column_once(sa.Column("duplicate_of", sa.String(), nullable=True))
    _create_index_once("ix_content_is_duplicate", ["is_duplicate"])
    _create_index_once("ix_content_duplicate_of", ["duplicate_of"])
    _backfill_existing_duplicate_groups()


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("contents"):
        return
    _drop_index_once("ix_content_duplicate_of")
    _drop_index_once("ix_content_is_duplicate")
    _drop_column_once("duplicate_of")
    _drop_column_once("is_duplicate")
