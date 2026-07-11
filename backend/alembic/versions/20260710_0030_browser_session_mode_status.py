"""Add browser session mode and unverified state.

Revision ID: 20260710_0030
Revises: 20260710_0029
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260710_0030"
down_revision = "20260710_0029"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("browser_sessions", "session_mode"):
        op.add_column(
            "browser_sessions",
            sa.Column(
                "session_mode",
                sa.String(length=32),
                nullable=False,
                server_default="persistent_profile",
            ),
        )

    # Legacy Auth Bundle imports stored the storage_state directory as
    # user_data_dir, which made storage-state sessions look like real persistent
    # profiles. Mark those rows explicitly and clear the fake profile pointer.
    op.execute(
        """
        UPDATE browser_sessions
        SET session_mode = 'storage_state', user_data_dir = NULL
        WHERE storage_state_path IS NOT NULL
          AND (metadata LIKE '%last_bundle_import%' OR profile_name LIKE 'bundle-%')
        """
    )


def downgrade() -> None:
    if _has_column("browser_sessions", "session_mode"):
        op.drop_column("browser_sessions", "session_mode")
