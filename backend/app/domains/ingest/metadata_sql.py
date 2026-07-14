"""SQL expressions for indexed ingest metadata fields."""

from __future__ import annotations

from sqlalchemy import func, literal_column


# SQLite only matches an expression index when the indexed expression appears
# textually in the statement. ``literal()`` still compiles as a bind parameter,
# so keep this application-owned JSON path as a SQL literal instead.
_DUPLICATE_GROUP_JSON_PATH = literal_column("'$.duplicate_group_id'")


def duplicate_group_id_expression(metadata_column):
    """Return the expression covered by ``ix_contents_dup_group_id``."""
    return func.json_extract(metadata_column, _DUPLICATE_GROUP_JSON_PATH)


__all__ = ["duplicate_group_id_expression"]
