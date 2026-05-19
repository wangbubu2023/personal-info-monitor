"""Remove legacy source categories and priority fields.

Revision ID: 20260407_0008
Revises: 20260407_0007
Create Date: 2026-04-07 23:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260407_0008"
down_revision = "20260407_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "sources" in table_names:
        source_columns = {column["name"] for column in inspector.get_columns("sources")}
        if "category_id" in source_columns or "priority" in source_columns:
            with op.batch_alter_table("sources") as batch_op:
                if "category_id" in source_columns:
                    batch_op.drop_column("category_id")
                if "priority" in source_columns:
                    batch_op.drop_column("priority")

    if "categories" in table_names:
        op.drop_table("categories")


def downgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("sources") as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_foreign_key("fk_sources_category_id_categories", "categories", ["category_id"], ["id"])
