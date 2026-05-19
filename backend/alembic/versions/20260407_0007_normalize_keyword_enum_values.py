"""Normalize keyword enum values to lowercase storage strings.

Revision ID: 20260407_0007
Revises: 20260407_0006
Create Date: 2026-04-07 12:40:00.000000
"""

from alembic import op


revision = "20260407_0007"
down_revision = "20260407_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE keywords
        SET match_type = CASE match_type
            WHEN 'EXACT' THEN 'exact'
            WHEN 'CONTAINS' THEN 'contains'
            WHEN 'REGEX' THEN 'regex'
            ELSE match_type
        END
        """
    )
    op.execute(
        """
        UPDATE keywords
        SET match_scope = CASE match_scope
            WHEN 'TITLE' THEN 'title'
            WHEN 'CONTENT' THEN 'content'
            WHEN 'TITLE_CONTENT' THEN 'title_content'
            ELSE match_scope
        END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE keywords
        SET match_type = CASE match_type
            WHEN 'exact' THEN 'EXACT'
            WHEN 'contains' THEN 'CONTAINS'
            WHEN 'regex' THEN 'REGEX'
            ELSE match_type
        END
        """
    )
    op.execute(
        """
        UPDATE keywords
        SET match_scope = CASE match_scope
            WHEN 'title' THEN 'TITLE'
            WHEN 'content' THEN 'CONTENT'
            WHEN 'title_content' THEN 'TITLE_CONTENT'
            ELSE match_scope
        END
        """
    )
