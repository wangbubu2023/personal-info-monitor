"""Platform-level export adapters.

Phase 5 step 11 of the refactor relocates the per-content exporters into the
platform layer. As of this step the package contains:

* :mod:`app.platform.export.markdown` — canonical home for
  :class:`MarkdownExporter`, the YAML-frontmatter Markdown writer used by
  ``contents/{id}/export-md`` and the ``maintenance`` task that fans out
  bulk exports. Previously lived at ``app.exporters.markdown_exporter``;
  that module is preserved as a re-export shim through Phase 7.

The legacy ``app.exporters`` namespace remains importable so existing
callers (CLI maintenance tasks, the contents-CRUD download endpoint, and
any external automation that imported the old path) keep working without
modification while we migrate them in Phase 7.
"""

from app.platform.export.markdown import MarkdownExporter

__all__ = ["MarkdownExporter"]
