"""Add score projection columns to contents.

Revision ID: 20260702_0020
Revises: 20260702_0019
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260702_0020"
down_revision = "20260702_0019"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    rows = bind.execute(sa.text(f"PRAGMA table_info('{table}')")).fetchall()
    return {row[1] for row in rows}


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "contents")
    if "article_score" not in columns:
        op.add_column("contents", sa.Column("article_score", sa.Float(), nullable=True))
    if "final_score" not in columns:
        op.add_column("contents", sa.Column("final_score", sa.Float(), nullable=True))
    if "selection_status" not in columns:
        op.add_column("contents", sa.Column("selection_status", sa.String(length=32), nullable=True))
    if "lane" not in columns:
        op.add_column("contents", sa.Column("lane", sa.String(length=64), nullable=True))

    bind.execute(
        sa.text(
            """
            UPDATE contents
            SET
              article_score = COALESCE(
                article_score,
                CAST(json_extract(metadata, '$.article_score') AS REAL),
                CAST(json_extract(metadata, '$.final_score') AS REAL)
              ),
              final_score = COALESCE(
                final_score,
                CAST(json_extract(metadata, '$.final_score') AS REAL),
                CAST(json_extract(metadata, '$.article_score') AS REAL)
              ),
              selection_status = COALESCE(
                selection_status,
                substr(json_extract(metadata, '$.selection_status'), 1, 32)
              ),
              lane = COALESCE(lane, substr(json_extract(metadata, '$.lane'), 1, 64))
            WHERE metadata IS NOT NULL
            """
        )
    )

    if not _index_exists("contents", "ix_content_article_score"):
        op.create_index("ix_content_article_score", "contents", ["article_score"])
    if not _index_exists("contents", "ix_content_selection_status"):
        op.create_index("ix_content_selection_status", "contents", ["selection_status"])
    if not _index_exists("contents", "ix_content_lane"):
        op.create_index("ix_content_lane", "contents", ["lane"])


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "contents")
    if _index_exists("contents", "ix_content_lane"):
        op.drop_index("ix_content_lane", table_name="contents")
    if _index_exists("contents", "ix_content_selection_status"):
        op.drop_index("ix_content_selection_status", table_name="contents")
    if _index_exists("contents", "ix_content_article_score"):
        op.drop_index("ix_content_article_score", table_name="contents")
    with op.batch_alter_table("contents") as batch:
        if "lane" in columns:
            batch.drop_column("lane")
        if "selection_status" in columns:
            batch.drop_column("selection_status")
        if "final_score" in columns:
            batch.drop_column("final_score")
        if "article_score" in columns:
            batch.drop_column("article_score")
