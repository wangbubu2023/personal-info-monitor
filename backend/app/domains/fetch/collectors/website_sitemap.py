"""Sitemap discovery helpers for :mod:`website` collector.

The website collector keeps method wrappers for backwards-compatible tests; the
actual sitemap parsing/fetch orchestration lives here so the collector class can
focus on strategy order and article hydration.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree

from app.models import Source
from app.platform.browser.hosts import is_wsj_host

from . import website_helpers as _helpers

RawContent = dict[str, Any]
FetchSitemapXml = Callable[[Source, str], Awaitable[Optional[str]]]
HydratePublicListing = Callable[[Source, list[RawContent], Any, Any], Awaitable[list[RawContent]]]


def default_sitemap_urls(source: Source) -> list[str]:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    configured = metadata.get("sitemap_urls")
    if isinstance(configured, str):
        urls = [configured]
    elif isinstance(configured, list):
        urls = [str(url).strip() for url in configured]
    else:
        urls = []
    urls = [url for url in urls if url]
    if urls:
        return urls

    parsed = urlparse(source.url)
    if not parsed.scheme or not parsed.netloc:
        return []
    root = f"{parsed.scheme}://{parsed.netloc}"
    return [
        f"{root}/sitemap.xml",
        f"{root}/sitemap/news.xml",
        f"{root}/news-sitemap.xml",
    ]


def parse_sitemap_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def url_title(url: str) -> str:
    path = urlparse(url).path.strip("/")
    slug = (path.rsplit("/", 1)[-1] if path else "").strip()
    title = slug.replace("-", " ").replace("_", " ").strip()
    return title[:180] or url


def parse_sitemap_entries(xml_text: str, source: Source) -> tuple[list[RawContent], list[str]]:
    try:
        root = ElementTree.fromstring(xml_text.encode("utf-8"))
    except ElementTree.ParseError:
        return [], []

    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    def _first_descendant_text(node, name: str) -> str | None:
        for child in node.iter():
            if _local(child.tag) == name and child.text:
                return str(child.text).strip()
        return None

    entries: list[RawContent] = []
    nested_sitemaps: list[str] = []
    if _local(root.tag) == "sitemapindex":
        for sitemap in root:
            if _local(sitemap.tag) != "sitemap":
                continue
            loc = next((child.text for child in sitemap if _local(child.tag) == "loc"), None)
            if loc and _helpers.same_site(source.url, loc):
                nested_sitemaps.append(str(loc).strip())
        return [], nested_sitemaps

    if _local(root.tag) != "urlset":
        return [], []

    source_is_wsj = is_wsj_host(urlparse(source.url).hostname)
    for url_node in root:
        if _local(url_node.tag) != "url":
            continue
        loc = next((child.text for child in url_node if _local(child.tag) == "loc"), None)
        url = str(loc or "").strip()
        if not url or not _helpers.same_site(source.url, url):
            continue
        if not _helpers.looks_like_article_url(source.url, url):
            continue
        lastmod = next((child.text for child in url_node if _local(child.tag) == "lastmod"), None)
        publication_date = _first_descendant_text(url_node, "publication_date")
        news_title = _first_descendant_text(url_node, "title")
        # WSJ's generic sitemap contains section/author/topic pages whose URL
        # tails look article-shaped. Only its news sitemap title is a reliable
        # article signal; generating a title from the URL created empty
        # keyword-only Reader entries.
        if source_is_wsj and not news_title:
            continue
        title = news_title or url_title(url)
        entries.append(
            {
                "external_id": url,
                "title": title,
                "content": "",
                "url": url,
                "publish_time": parse_sitemap_time(publication_date or lastmod),
                "metadata": {
                    "discovered_via": "sitemap",
                    "publish_time_estimated": not (publication_date or lastmod),
                    "publish_time_raw": publication_date or lastmod or "",
                },
            }
        )
    return entries, []


async def maybe_fetch_via_sitemap(
    source: Source,
    cookies: Any,
    browser_session: Any,
    *,
    fetch_sitemap_xml: FetchSitemapXml,
    hydrate_public_listing: HydratePublicListing,
) -> Optional[list[RawContent]]:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    if metadata.get("sitemap_discovery") is False:
        return None

    sitemap_urls = default_sitemap_urls(source)
    if not sitemap_urls:
        return None

    max_sitemaps = int(metadata.get("sitemap_max_sitemaps", 3) or 3)
    max_links = int(metadata.get("sitemap_max_links", 30) or 30)
    pending = list(sitemap_urls[:max_sitemaps])
    seen_sitemaps: set[str] = set()
    contents: list[RawContent] = []
    diagnostics = {
        "sitemaps_checked": 0,
        "nested_sitemaps": 0,
        "kept": 0,
        "truncated": 0,
    }

    while pending and len(seen_sitemaps) < max_sitemaps and len(contents) < max_links:
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        xml_text = await fetch_sitemap_xml(source, sitemap_url)
        diagnostics["sitemaps_checked"] += 1
        if not xml_text:
            continue
        parsed_entries, nested = parse_sitemap_entries(xml_text, source)
        diagnostics["nested_sitemaps"] += len(nested)
        for nested_url in nested:
            if nested_url not in seen_sitemaps and len(pending) + len(seen_sitemaps) < max_sitemaps:
                pending.append(nested_url)
        for item in parsed_entries:
            if len(contents) >= max_links:
                diagnostics["truncated"] += 1
                break
            contents.append(item)

    diagnostics["kept"] = len(contents)
    if not contents and not metadata.get("sitemap_urls"):
        return None

    diag_meta = dict(metadata)
    diag_meta["sitemap_diagnostics"] = diagnostics
    source.metadata_ = diag_meta
    if not contents:
        return []
    hydrated = await hydrate_public_listing(source, contents, cookies, browser_session)
    hydrated = [
        item
        for item in hydrated
        if str(item.get("content") or "").strip() or str(item.get("summary") or "").strip()
    ]
    diagnostics["hydrated_kept"] = len(hydrated)
    diagnostics["dropped_unhydrated"] = len(contents) - len(hydrated)
    diag_meta = dict(source.metadata_ if isinstance(source.metadata_, dict) else {})
    diag_meta["sitemap_diagnostics"] = diagnostics
    source.metadata_ = diag_meta
    if hydrated:
        return hydrated
    return [] if metadata.get("sitemap_urls") else None


__all__ = [
    "default_sitemap_urls",
    "maybe_fetch_via_sitemap",
    "parse_sitemap_entries",
    "parse_sitemap_time",
    "url_title",
]
