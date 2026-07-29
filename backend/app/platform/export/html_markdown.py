"""Shared deterministic HTML-to-Markdown rendering."""

from __future__ import annotations

import re

from markdownify import markdownify


def _code_language(element) -> str:
    """Best-effort language marker from ``<pre><code class=...>``."""
    code = element.find("code") if hasattr(element, "find") else None
    classes = code.get("class", []) if code is not None else []
    for item in classes if isinstance(classes, (list, tuple)) else [classes]:
        value = str(item or "")
        for prefix in ("language-", "lang-"):
            if value.startswith(prefix):
                return value[len(prefix):][:40]
    return ""


_CONVERT_TAGS = [
    "a", "article", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "img", "li", "ol", "p", "pre", "strong", "table",
    "tbody", "td", "th", "thead", "tr", "ul",
]


def render_html_markdown(html: str) -> str:
    """Render already-normalized HTML with stable formatting settings."""
    rendered = markdownify(
        str(html or ""),
        heading_style="ATX",
        bullets="-",
        convert=_CONVERT_TAGS,
        code_language_callback=_code_language,
    )
    rendered = re.sub(r"[ \t]+\n", "\n", rendered or "")
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()
