"""One HTML-to-Markdown protocol for extraction, Reader and export."""

from __future__ import annotations

from app.platform.export.html_markdown import render_html_markdown

from .html_standardizer import standardize_html


def html_to_markdown(html: str, *, base_url: str = "", standardize: bool = True) -> str:
    source = standardize_html(html, base_url=base_url).html if standardize else str(html or "")
    return render_html_markdown(source)
