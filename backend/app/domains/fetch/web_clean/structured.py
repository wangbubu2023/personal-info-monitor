"""Structured article metadata adapter for JSON-LD, meta and hydration data."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.utils.publish_time import parse_publish_time_text
from app.utils.structured_article import extract_article_page_metadata, extract_structured_article

ARTICLE_TYPES = {
    "article", "newsarticle", "blogposting", "scholarlyarticle",
    "reportagenewsarticle", "socialmediaposting",
}


def _iter_nodes(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nodes(child)


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
            payload[mapping[key]] = urljoin(page_url, value) if mapping[key] in {"image", "canonical_url"} else value
    canonical = soup.select_one('link[rel~="canonical"]')
    if canonical and canonical.get("href"):
        payload["canonical_url"] = urljoin(page_url, str(canonical["href"]))

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for node in _iter_nodes(data):
            if not isinstance(node, dict) or not (_type_names(node) & ARTICLE_TYPES):
                continue
            payload["schema_nodes"].append(node)
            payload.setdefault("title", node.get("headline") or node.get("name"))
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
                payload["image"] = urljoin(page_url, str(image))
            raw_date = node.get("datePublished") or node.get("dateModified")
            if raw_date and not payload.get("published_time"):
                payload["published_time"] = parse_publish_time_text(str(raw_date))
                payload["published_time_raw"] = str(raw_date)

    structured_body = extract_structured_article(html, min_chars=120)
    if structured_body:
        payload["article_text"] = structured_body.text
        payload["article_method"] = structured_body.method
        payload["article_signals"] = structured_body.signals
        payload.setdefault("title", structured_body.title)
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
