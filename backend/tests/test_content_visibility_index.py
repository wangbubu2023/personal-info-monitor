from __future__ import annotations

from sqlalchemy import create_engine, func, select, text

from app.database import Base
from app.domains.ingest.visibility import visible_content_clause
from app.models import Content


def test_visible_content_query_uses_duplicate_group_expression_index(tmp_path):
    """Guard against the 34k-row correlated-subquery regression.

    Timing assertions are noisy in CI; the stable contract is that SQLite's
    inner correlated lookup uses the expression index instead of scanning the
    contents table once per legacy duplicate row.
    """

    engine = create_engine(f"sqlite:///{tmp_path / 'visibility.db'}")
    Base.metadata.create_all(engine)
    statement = select(func.count(Content.id)).where(visible_content_clause())
    compiled = statement.compile(engine, compile_kwargs={"literal_binds": True})

    with engine.connect() as connection:
        index_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='index' AND name='ix_contents_dup_group_id'"
            )
        ).scalar_one()
        plan = connection.exec_driver_sql(f"EXPLAIN QUERY PLAN {compiled}").all()

    assert "json_extract(metadata, '$.duplicate_group_id')" in index_sql
    assert any("ix_contents_dup_group_id" in str(row[-1]) for row in plan), plan
