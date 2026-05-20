"""Compatibility shim — Markdown exporter moved to :mod:`app.platform.export.markdown`.

Phase 5 step 11 of the modular refactor relocated :class:`MarkdownExporter`
under the platform layer. This module is preserved as a re-export bridge so
existing callers (``api/contents_crud.py``, the maintenance task
``app.tasks.maintenance_tasks``, and any external automation/scripts that
imported ``app.exporters.markdown_exporter``) keep working unchanged until
they are migrated in Phase 7.
"""

from app.platform.export.markdown import MarkdownExporter

__all__ = ["MarkdownExporter"]
