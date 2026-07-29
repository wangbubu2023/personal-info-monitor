"""Platform-level export adapters.

The package keeps the public ``MarkdownExporter`` import stable while loading
that optional, frontmatter-backed writer only when callers request it.  This
lets lightweight shared helpers such as ``html_markdown`` remain usable in
extraction and evaluation processes that do not perform file exports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.platform.export.markdown import MarkdownExporter

__all__ = ["MarkdownExporter"]


def __getattr__(name: str) -> Any:
    if name == "MarkdownExporter":
        from app.platform.export.markdown import MarkdownExporter

        return MarkdownExporter
    raise AttributeError(name)
