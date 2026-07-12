from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    text,
)


def _load_migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260710_0030_browser_session_mode_status.py"
    spec = importlib.util.spec_from_file_location("browser_session_mode_status", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_import_upgrade_relaxes_legacy_user_data_dir_constraint(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    metadata = MetaData()
    Table(
        "browser_sessions",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("site_url", Text, nullable=False),
        Column("site_host", String(255), nullable=False),
        Column("profile_name", String(255), nullable=False),
        Column("user_data_dir", Text, nullable=False),
        Column("storage_state_path", Text, nullable=True),
        Column("auth_config_id", String(36), nullable=True),
        Column("status", String(32), nullable=False),
        Column("last_validated_at", DateTime, nullable=True),
        Column("last_error", Text, nullable=True),
        Column("metadata", JSON, nullable=True),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
        Column("enabled", Boolean, nullable=False, server_default="1"),
        Column("last_used_at", DateTime, nullable=True),
        Column("failure_count", Integer, nullable=False, server_default="0"),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO browser_sessions (
                    id, site_url, site_host, profile_name, user_data_dir,
                    storage_state_path, status, metadata, created_at, updated_at
                ) VALUES (
                    'session-1', 'https://example.com', 'example.com',
                    'bundle-example', '/tmp/legacy-profile', '/tmp/state.json',
                    'active', '{"last_bundle_import": true}',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )

        migration = _load_migration()
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        columns = {column["name"]: column for column in inspect(connection).get_columns("browser_sessions")}
        row = connection.execute(
            text("SELECT user_data_dir, session_mode FROM browser_sessions WHERE id = 'session-1'")
        ).one()

    assert columns["user_data_dir"]["nullable"] is True
    assert columns["session_mode"]["nullable"] is False
    assert row == (None, "storage_state")
