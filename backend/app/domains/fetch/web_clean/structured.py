"""Structured article metadata adapter for JSON-LD, meta and hydration data."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.utils.publish_time import parse_publish_time_text
from app.utils.structured_article import extract_article_page_metadata, extract_structured_article

ARTICLE_TYPES = {
    "article", "newsarticle", "blogposting", "scholarlyarticle",
    "reportagenewsarticle", "socialmediaposting",
}
_MAX_URL_CHARS = 2_048
_MAX_JSON_NODES = 10_000
_MAX_JSON_DEPTH = 64


def _iter_nodes(value: Any) -> Iterable[Any]:
    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack and visited < _MAX_JSON_NODES:
        node, depth = stack.pop()
        visited += 1
        yield node
        if depth >= _MAX_JSON_DEPTH:
            continue
        if isinstance(node, dict):
            stack.extend((child, depth + 1) for child in reversed(tuple(node.values())))
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in reversed(node))


def _type_names(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    return {str(item).lower() for item in (raw if isinstance(raw, list) else [raw]) if item}


def _names(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("name")
        if item and str(item).strip():
            result.append(str(item).strip())
    return result


def _url_value(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            resolved = _url_value(item)
            if resolved:
                return resolved
        return None
    if isinstance(value, dict):
        value = value.get("url") or value.get("@id")
    text = str(value or "").strip()
    return text or None


def _safe_absolute_http_url(value: Any, page_url: str) -> str | None:
    raw = str(value or "").strip()
    if not raw or len(raw) > _MAX_URL_CHARS:
        return None
    absolute = urljoin(str(page_url or "")[:_MAX_URL_CHARS], raw)
    parsed = urlparse(absolute)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return absolute if len(absolute) <= _MAX_URL_CHARS else None


def extract_structured_document(html: str, *, page_url: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "lxml")
    page_meta = extract_article_page_metadata(html, page_url=page_url)
    payload: dict[str, Any] = {
        "canonical_url": page_meta.get("canonical_url"),
        "published_time": page_meta.get("published_time"),
        "published_time_raw": page_meta.get("published_time_raw"),
        "schema_nodes": [],
    }

    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or "").lower()
        value = str(meta.get("content") or "").strip()
        if not value:
            continue
        mapping = {
            "og:title": "title", "twitter:title": "title",
            "author": "author", "article:author": "author",
            "og:site_name": "site_name", "og:locale": "language",
            "og:image": "image", "twitter:image": "image",
            "og:url": "canonical_url",
        }
        if key in mapping and not payload.get(mapping[key]):
            payload[mapping[key]] = (
                _safe_absolute_http_url(value, page_url)
                if mapping[key] in {"image", "canonical_url"}
                else value
            )
    canonical = soup.select_one('link[rel~="canonical"]')
    if canonical and canonical.get("href"):
        safe_canonical = _safe_absolute_http_url(canonical["href"], page_url)
        if safe_canonical:
            payload["canonical_url"] = safe_canonical

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for node in _iter_nodes(data):
            if not isinstance(node, dict) or not (_type_names(node) & ARTICLE_TYPES):
                continue
            payload["schema_nodes"].append(node)
            headline = node.get("headline") or node.get("name")
            if headline and not payload.get("title"):
                payload["title"] = str(headline).strip()
            authors = _names(node.get("author"))
            if authors and not payload.get("author"):
                payload["author"] = ", ".join(authors)
            publisher = _names(node.get("publisher"))
            if publisher and not payload.get("site_name"):
                payload["site_name"] = ", ".join(publisher)
            image = node.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            if isinstance(image, dict):
                image = image.get("url")
            if image and not payload.get("image"):
                payload["image"] = _safe_absolute_http_url(image, page_url)
            raw_date = node.get("datePublished") or node.get("dateModified")
            if raw_date and not payload.get("published_time"):
                payload["published_time"] = parse_publish_time_text(str(raw_date))
                payload["published_time_raw"] = str(raw_date)
            canonical_value = _url_value(node.get("mainEntityOfPage")) or _url_value(node.get("url"))
            if canonical_value and not payload.get("canonical_url"):
                payload["canonical_url"] = _safe_absolute_http_url(canonical_value, page_url)
            language = node.get("inLanguage")
            if language and not payload.get("language"):
                payload["language"] = str(language).strip()

    structured_rejections: list[dict[str, Any]] = []
    structured_body = extract_structured_article(
        html,
        min_chars=120,
        rejections=structured_rejections,
    )
    if structured_body:
        payload["article_text"] = structured_body.text
        payload["article_method"] = structured_body.method
        payload["article_signals"] = structured_body.signals
        if structured_body.title and not payload.get("title"):
            payload["title"] = structured_body.title
    if structured_rejections:
        payload["article_rejections"] = structured_rejections
    return payload


def schema_value(structured: dict[str, Any], path: str) -> Any:
    wanted_type = ""
    field_path = path
    if path.startswith("@") and ":" in path:
        wanted_type, field_path = path[1:].split(":", 1)
    elif path.startswith("@"):
        wanted_type, field_path = path[1:], ""
    for node in structured.get("schema_nodes", []):
        if wanted_type and wanted_type.lower() not in _type_names(node):
            continue
        value: Any = node
        for part in filter(None, field_path.split(".")):
            if isinstance(value, list):
                value = [item.get(part) for item in value if isinstance(item, dict) and part in item]
            elif isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
            if value is None:
                break
        if value is not None:
            return value
    return None
