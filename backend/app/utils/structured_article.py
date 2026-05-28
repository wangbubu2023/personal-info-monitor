"""Structured article-body extraction from publisher HTML.

Many news sites ship the canonical article body in JSON-LD, Next.js data,
or other page-owned JSON before client-side paywall widgets alter the DOM.
This helper extracts only same-page structured data; it does not change
headers, clear cookies, block scripts, or call archival services.
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from bs4 import BeautifulSoup

from app.utils.text import normalize_article_text, strip_html_tags


ARTICLE_TYPES = {
    "article",
    "newsarticle",
    "blogposting",
    "reportagenewsarticle",
    "scholarlyarticle",
    "socialmediaposting",
}

BODY_KEYS = (
    "articleBody",
    "body",
    "bodyText",
    "BodyPlainText",
    "content",
    "contentHtml",
    "html",
    "text",
)


@dataclass(frozen=True)
class StructuredArticleExtraction:
    text: str
    method: str
    title: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)


def _loads_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty json")
    return json.loads(text)


def _iter_json_nodes(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_nodes(child)


def _node_type_names(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type") or node.get("type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(item or "").strip().lower() for item in values if str(item or "").strip()}


def _clean_candidate_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = "\n\n".join(_clean_candidate_text(item) for item in value)
    elif isinstance(value, dict):
        for key in BODY_KEYS:
            if key in value:
                return _clean_candidate_text(value.get(key))
        value = " ".join(str(v) for v in value.values() if isinstance(v, str))
    else:
        value = str(value)

    text = html_lib.unescape(value).replace("\\n", "\n")
    if "<" in text and ">" in text:
        text = strip_html_tags(text)
    return normalize_article_text(text).strip()


def _title_from_node(node: dict[str, Any]) -> str | None:
    for key in ("headline", "name", "title"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_article_text(value).strip()
    return None


def _best_body_from_node(node: dict[str, Any]) -> tuple[str, str] | None:
    candidates: list[tuple[str, str]] = []
    for key in BODY_KEYS:
        if key in node:
            text = _clean_candidate_text(node.get(key))
            if text:
                candidates.append((key, text))
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item[1]))


def _extract_from_json_ld(soup: BeautifulSoup, min_chars: int) -> StructuredArticleExtraction | None:
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text() or ""
        try:
            data = _loads_json(raw.replace("\r", "").replace("\t", ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        best: StructuredArticleExtraction | None = None
        for node in _iter_json_nodes(data):
            if not isinstance(node, dict):
                continue
            type_names = _node_type_names(node)
            if type_names and not (type_names & ARTICLE_TYPES):
                continue
            body = _best_body_from_node(node)
            if not body:
                continue
            body_key, text = body
            if len(text) < min_chars:
                continue
            candidate = StructuredArticleExtraction(
                text=text,
                method="json_ld",
                title=_title_from_node(node),
                signals={"body_key": body_key, "chars": len(text)},
            )
            if best is None or len(candidate.text) > len(best.text):
                best = candidate
        if best:
            return best
    return None


def _extract_from_next_data(soup: BeautifulSoup, min_chars: int) -> StructuredArticleExtraction | None:
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return None
    try:
        data = _loads_json(script.string or script.get_text() or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    best: tuple[str, str] | None = None
    title: str | None = None
    for node in _iter_json_nodes(data):
        if isinstance(node, dict):
            if not title:
                title = _title_from_node(node)
            body = _best_body_from_node(node)
            if body and len(body[1]) >= min_chars and (best is None or len(body[1]) > len(best[1])):
                best = body
    if not best:
        return None
    body_key, text = best
    return StructuredArticleExtraction(
        text=text,
        method="next_data",
        title=title,
        signals={"body_key": body_key, "chars": len(text)},
    )


def extract_structured_article(
    html: str,
    *,
    min_chars: int = 120,
) -> StructuredArticleExtraction | None:
    """Return the best same-page structured article body, if available."""
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    for extractor in (
        _extract_from_json_ld,
        _extract_from_next_data,
    ):
        result = extractor(soup, min_chars)
        if result:
            return result
    return None


__all__ = ["StructuredArticleExtraction", "extract_structured_article"]
