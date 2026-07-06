"""Compatibility shim for the canonical ingest-domain content processor."""

from app.domains.ingest.content_processor import (  # noqa: F401
    ContentProcessor,
    ContentTypeStrategy,
    strategy_for,
)

__all__ = ["ContentProcessor", "ContentTypeStrategy", "strategy_for"]
