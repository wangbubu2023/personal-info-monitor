"""Keyword identity column + dedupe + unique (ignore case).

Revision ID: 20260407_0011
Revises: 20260407_0010
Create Date: 2026-04-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.services.keyword_rules import keyword_identity_key

revision = "20260407_0011"
down_revision = "20260407_0010"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    added_keyword_identity = False
    if not _column_exists("keywords", "keyword_identity"):
        op.add_column(
            "keywords",
            sa.Column("keyword_identity", sa.String(512), nullable=True),
        )
        added_keyword_identity = True

    rows = conn.execute(text("SELECT id, keyword, created_at FROM keywords")).fetchall()
    for row in rows:
        kid, kw, _created = row[0], row[1], row[2]
        ident = keyword_identity_key(str(kw or ""))
        conn.execute(
            text("UPDATE keywords SET keyword_identity = :ident WHERE id = :id"),
            {"ident": ident, "id": kid},
        )

    grouped: dict[str, list[tuple[str, str | None]]] = {}
    for row in conn.execute(
        text("SELECT id, keyword_identity, created_at FROM keywords"),
    ).fetchall():
        kid, ident, created = row[0], row[1], row[2]
        if not ident:
            continue
        grouped.setdefault(ident, []).append((kid, created))

    for _ident, items in grouped.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda x: (x[1] or "", x[0]))
        for dup_id, _c in items[1:]:
            conn.execute(text("DELETE FROM keywords WHERE id = :id"), {"id": dup_id})

    if added_keyword_identity:
        with op.batch_alter_table("keywords") as batch_op:
            batch_op.alter_column(
                "keyword_identity",
                existing_type=sa.String(512),
                nullable=False,
            )

    if not _index_exists("keywords", "ix_keywords_keyword_identity"):
        op.create_index(
            "ix_keywords_keyword_identity",
            "keywords",
            ["keyword_identity"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("ix_keywords_keyword_identity", table_name="keywords")
    with op.batch_alter_table("keywords") as batch_op:
        batch_op.drop_column("keyword_identity")
