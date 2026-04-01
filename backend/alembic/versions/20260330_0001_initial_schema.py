"""Initial schema baseline.

Revision ID: 20260330_0001
Revises:
Create Date: 2026-03-30 20:30:00
"""

from __future__ import annotations

from alembic import op

from app.database import Base
from app import models  # noqa: F401  # Ensure models are imported into metadata

# revision identifiers, used by Alembic.
revision = "20260330_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
