"""Platform-level export adapters.

Phase 5 step 11 of the refactor relocates the per-content exporters into the
platform layer. As of this step the package contains:

* :mod:`app.platform.export.markdown` — canonical home for
  :class:`MarkdownExporter`, the YAML-frontmatter Markdown writer used by
  ``contents/{id}/export-md`` and the ``maintenance`` task that fans out
  bulk exports. Previously lived at ``app.exporters.markdown_exporter``;
  the legacy shim was retired by the post-Phase-7 audit after the two
  remaining callers were migrated to import from this package directly.
"""

from app.platform.export.markdown import MarkdownExporter

__all__ = ["MarkdownExporter"]
