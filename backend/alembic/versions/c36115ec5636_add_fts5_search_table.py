"""add_fts5_search_table

Revision ID: c36115ec5636
Revises: effcf9c68468
Create Date: 2026-04-06 20:11:03.346606
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c36115ec5636'
down_revision = 'effcf9c68468'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the virtual table
    # We use 'content' option to link to the external 'contents' table
    # This avoids duplicating the full text data in storage while still indexing it.
    op.execute("""
        CREATE VIRTUAL TABLE content_fts USING fts5(
            id UNINDEXED,
            title,
            summary,
            full_content,
            content='contents',
            content_rowid='rowid'
        );
    """)

    # 2. Add Triggers to keep FTS in sync
    op.execute("""
        CREATE TRIGGER contents_ai AFTER INSERT ON contents BEGIN
          INSERT INTO content_fts(rowid, id, title, summary, full_content)
          VALUES (new.rowid, new.id, new.title, new.summary, new.full_content);
        END;
    """)

    op.execute("""
        CREATE TRIGGER contents_ad AFTER DELETE ON contents BEGIN
          INSERT INTO content_fts(content_fts, rowid, id, title, summary, full_content)
          VALUES('delete', old.rowid, old.id, old.title, old.summary, old.full_content);
        END;
    """)

    op.execute("""
        CREATE TRIGGER contents_au AFTER UPDATE ON contents BEGIN
          INSERT INTO content_fts(content_fts, rowid, id, title, summary, full_content)
          VALUES('delete', old.rowid, old.id, old.title, old.summary, old.full_content);
          INSERT INTO content_fts(rowid, id, title, summary, full_content)
          VALUES (new.rowid, new.id, new.title, new.summary, new.full_content);
        END;
    """)

    # 3. Populate existing data
    op.execute("""
        INSERT INTO content_fts(rowid, id, title, summary, full_content)
        SELECT rowid, id, title, summary, full_content FROM contents;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS contents_au")
    op.execute("DROP TRIGGER IF EXISTS contents_ad")
    op.execute("DROP TRIGGER IF EXISTS contents_ai")
    op.execute("DROP TABLE IF EXISTS content_fts")
