"""Compatibility shim for the canonical sources-domain monitor service."""

from app.domains.sources.monitoring import MonitorService

__all__ = ["MonitorService"]
