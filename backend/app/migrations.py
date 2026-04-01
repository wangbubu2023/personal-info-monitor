"""Alembic migration bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import get_settings
from app.models.runtime_lock import RuntimeLock
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    backend_root = _backend_root()
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def _inspect_schema() -> tuple[bool, bool]:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
    try:
        inspector = inspect(engine)
        has_version_table = inspector.has_table("alembic_version")
        has_legacy_schema = inspector.has_table("sources") and inspector.has_table("contents")
        return has_version_table, has_legacy_schema
    finally:
        engine.dispose()


def run_migrations() -> None:
    """Run Alembic migrations and baseline existing pre-Alembic databases."""
    cfg = _alembic_config()
    has_version_table, has_legacy_schema = _inspect_schema()

    if has_version_table:
        command.upgrade(cfg, "head")
        return

    if has_legacy_schema:
        logger.info("Existing legacy schema detected, stamping Alembic head.")
        command.stamp(cfg, "head")
        # Legacy DBs created before Alembic may miss newer operational tables.
        settings = get_settings()
        engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
        )
        try:
            RuntimeLock.__table__.create(bind=engine, checkfirst=True)
        finally:
            engine.dispose()
        return

    command.upgrade(cfg, "head")
