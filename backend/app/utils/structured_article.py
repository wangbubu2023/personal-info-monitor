"""Structured article-body extraction from publisher HTML.

Many news sites ship the canonical article body in JSON-LD, Next.js data,
or other page-owned JSON before client-side paywall widgets alter the DOM.
This helper extracts only same-page structured data; it does not change
headers, clear cookies, block scripts, or call archival services.
"""

from __future__ import annotations

import html as html_lib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

from bs4 import BeautifulSoup

from app.utils.text import normalize_article_text, strip_html_tags
from app.utils.logger import get_logger


logger = get_logger(__name__)


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

_DEFAULT_BODY_MIN_PAGE_RATIO = 0.30
_MIN_VISIBLE_TEXT_CHARS_FOR_RATIO_CHECK = 800
_VISIBLE_TEXT_EXCLUDED_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "title",
    "meta",
    "link",
}


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


def _configured_body_min_page_ratio() -> float:
    raw = os.environ.get("PIM_STRUCTURED_BODY_MIN_RATIO")
    if raw is None:
        return _DEFAULT_BODY_MIN_PAGE_RATIO
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid PIM_STRUCTURED_BODY_MIN_RATIO=%r; using %.2f", raw, _DEFAULT_BODY_MIN_PAGE_RATIO)
        return _DEFAULT_BODY_MIN_PAGE_RATIO
    return max(0.0, min(value, 1.0))


def _visible_page_text(soup: BeautifulSoup) -> str:
    parts: list[str] = []
    for node in soup.find_all(string=True):
        parent = node.parent
        if parent and str(parent.name or "").lower() in _VISIBLE_TEXT_EXCLUDED_TAGS:
            continue
        text = str(node).strip()
        if text:
            parts.append(text)
    return normalize_article_text("\n".join(parts)).strip()


def _passes_page_ratio_check(
    text: str,
    *,
    visible_text_chars: int,
    min_ratio: float,
    method: str,
    body_key: str,
) -> tuple[bool, dict[str, Any]]:
    signals: dict[str, Any] = {
        "visible_text_chars": visible_text_chars,
        "body_min_page_ratio": min_ratio,
    }
    if min_ratio <= 0 or visible_text_chars < _MIN_VISIBLE_TEXT_CHARS_FOR_RATIO_CHECK:
        return True, signals

    ratio = len(text) / max(1, visible_text_chars)
    signals["body_page_ratio"] = round(ratio, 4)
    if ratio >= min_ratio:
        return True, signals

    logger.debug(
        "Structured %s %s too small for visible page text: body=%d visible=%d ratio=%.1f%% < %.1f%%; falling back",
        method,
        body_key,
        len(text),
        visible_text_chars,
        ratio * 100,
        min_ratio * 100,
    )
    signals["rejected_reason"] = "body_page_ratio_too_low"
    return False, signals


def _extract_from_json_ld(
    soup: BeautifulSoup,
    min_chars: int,
    *,
    visible_text_chars: int,
    min_ratio: float,
) -> StructuredArticleExtraction | None:
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
            accepted, ratio_signals = _passes_page_ratio_check(
                text,
                visible_text_chars=visible_text_chars,
                min_ratio=min_ratio,
                method="json_ld",
                body_key=body_key,
            )
            if not accepted:
                continue
            candidate = StructuredArticleExtraction(
                text=text,
                method="json_ld",
                title=_title_from_node(node),
                signals={"body_key": body_key, "chars": len(text), **ratio_signals},
            )
            if best is None or len(candidate.text) > len(best.text):
                best = candidate
        if best:
            return best
    return None


def _extract_from_next_data(
    soup: BeautifulSoup,
    min_chars: int,
    *,
    visible_text_chars: int,
    min_ratio: float,
) -> StructuredArticleExtraction | None:
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
    accepted, ratio_signals = _passes_page_ratio_check(
        text,
        visible_text_chars=visible_text_chars,
        min_ratio=min_ratio,
        method="next_data",
        body_key=body_key,
    )
    if not accepted:
        return None
    return StructuredArticleExtraction(
        text=text,
        method="next_data",
        title=title,
        signals={"body_key": body_key, "chars": len(text), **ratio_signals},
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
    visible_text_chars = len(_visible_page_text(soup))
    min_ratio = _configured_body_min_page_ratio()
    for extractor in (
        _extract_from_json_ld,
        _extract_from_next_data,
    ):
        result = extractor(
            soup,
            min_chars,
            visible_text_chars=visible_text_chars,
            min_ratio=min_ratio,
        )
        if result:
            return result
    return None


__all__ = ["StructuredArticleExtraction", "extract_structured_article"]
