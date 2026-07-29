from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, inspect, text


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260729_0039_m4_audit_hardening.py"
    )
    spec = importlib.util.spec_from_file_location("m4_audit_hardening", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_m4_audit_hardening_fails_closed_without_deleting_duplicate_audits(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'duplicate-audits.db'}")
    metadata = MetaData()
    Table(
        "local_capture_audits",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("task_token_hash", String(100), nullable=False),
        Column("created_at", DateTime, nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO local_capture_audits (id, task_token_hash, created_at)
                VALUES
                    ('audit-1', 'duplicate-token-hash', CURRENT_TIMESTAMP),
                    ('audit-2', 'duplicate-token-hash', CURRENT_TIMESTAMP)
                """
            )
        )
        migration = _load_migration()
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            with pytest.raises(
                RuntimeError,
                match=r"1 duplicate task-token hash group\(s\).*2 immutable audit row\(s\)",
            ):
                migration.upgrade()

        audit_count = connection.execute(
            text("SELECT COUNT(*) FROM local_capture_audits")
        ).scalar_one()
        index_names = {
            row["name"] for row in inspect(connection).get_indexes("local_capture_audits")
        }

    assert audit_count == 2
    assert "uq_local_capture_task_token_hash" not in index_names
