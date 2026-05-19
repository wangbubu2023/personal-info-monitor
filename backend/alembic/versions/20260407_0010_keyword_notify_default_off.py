"""Turn off keyword notify by default for existing rows.

Revision ID: 20260407_0010
Revises: 20260407_0009
Create Date: 2026-04-07
"""

from __future__ import annotations

from alembic import op

revision = "20260407_0010"
down_revision = "20260407_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 与模型 / schema 默认一致；通知能力未启用前统一关闭
    op.execute("UPDATE keywords SET notify = 0")


def downgrade() -> None:
    # 无法恢复用户此前的 notify 选择
    pass
