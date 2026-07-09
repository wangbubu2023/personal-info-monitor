"""HTML → content dict parsing for :mod:`app.domains.fetch.collectors.website`.

Functions here take a raw ``BeautifulSoup`` tree or element and produce the
canonical collector content dicts. They're kept free of self/state so they
can be exercised directly via fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.models import Source
from app.domains.ingest.quality import get_non_article_format_reject_reason
from app.utils.logger import get_logger
from app.utils.publish_time import parse_publish_time_text

from .website_helpers import looks_like_article_url

logger = get_logger(__name__)


def _parse_datetime_attr(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_article_candidate(
    article,
    *,
    source: Source,
    title_selector: str,
    link_selector: str,
    content_selector: str,
    date_selector: str,
) -> Optional[Dict[str, Any]]:
    title_elem = article.select_one(title_selector)
    title = title_elem.get_text(strip=True) if title_elem else None

    link_elem = article.select_one(link_selector)
    url = None
    if link_elem and link_elem.has_attr("href"):
        url = str(link_elem["href"])
        if url.startswith("/"):
            url = urljoin(source.url, url)
    if not title or not url:
        return None

    content_elem = article.select_one(content_selector)
    content = content_elem.get_text(strip=True) if content_elem else ""
    date_elem = article.select_one(date_selector)
    publish_time: Optional[datetime] = None
    date_text = ""
    if date_elem:
        datetime_attr = date_elem.get("datetime")
        if datetime_attr:
            try:
                publish_time = _parse_datetime_attr(str(datetime_attr))
            except ValueError as exc:
                publish_time = parse_publish_time_text(str(datetime_attr))
                if not publish_time:
                    logger.warning("Failed to parse article datetime '%s' for %s: %s", datetime_attr, source.url, exc)
        date_text = date_elem.get_text(" ", strip=True) or ""
        if not publish_time and date_text:
            publish_time = parse_publish_time_text(date_text)

    candidate = {"title": title, "content": content, "url": url}
    reject_reason = get_non_article_format_reject_reason(source.url, candidate)
    if reject_reason:
        logger.info("Skipping non-article website item during parse (%s): %s", reject_reason, title)
        return None
    return {
        "external_id": url,
        "title": title,
        "content": content,
        "url": url,
        "publish_time": publish_time,
        "metadata": {
            "publish_time_estimated": publish_time is None,
            "publish_time_raw": date_text,
        },
    }


def append_fallback_links(
    *,
    soup: BeautifulSoup,
    source: Source,
    contents: List[Dict[str, Any]],
) -> None:
    """Add anchor-based fallback candidates when primary selectors yield few hits."""
    seen = {str(item.get("url") or "") for item in contents}
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    try:
        max_links = int(metadata.get("fallback_link_max", 50))
    except (TypeError, ValueError):
        max_links = 50
    max_links = max(0, min(max_links, 100))
    article_link_count = sum(
        1 for item in contents
        if looks_like_article_url(source.url, str(item.get("url") or ""))
    )
    if article_link_count >= max_links:
        return

    for anchor in soup.select("a[href]"):
        if article_link_count >= max_links:
            break
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(source.url, href)
        title = anchor.get_text(" ", strip=True)

        # Toughened criteria:
        #   1. Length >= 12 to avoid simple nav links like 'Read More'.
        #   2. Must look like an article URL.
        #   3. Must not trigger the generic content reject reason.
        if not title or len(title) < 12 or url in seen:
            continue
        if not looks_like_article_url(source.url, url):
            continue

        candidate_check = {"title": title, "url": url, "content": ""}
        if get_non_article_format_reject_reason(source.url, candidate_check):
            continue

        seen.add(url)
        article_link_count += 1
        contents.append(
            {
                "external_id": url,
                "title": title,
                "content": "",
                "url": url,
                "publish_time": None,
                "metadata": {
                    "publish_time_estimated": True,
                    "publish_time_raw": "",
                },
            }
        )


def parse_html_content(
    *,
    html: str,
    source: Source,
    item_logger=None,
) -> List[Dict[str, Any]]:
    """Parse HTML into canonical content dicts using configured selectors."""
    log = item_logger or logger
    soup = BeautifulSoup(html, "lxml")
    metadata = source.metadata_ or {}

    # Default selectors cover English + Chinese listing pages.
    article_selector = metadata.get(
        "article_selector",
        "article, .post, .entry, [class*='news'], [class*='article'], [class*='story'], [class*='item'], [class*='card']",
    )
    title_selector = metadata.get("title_selector", "h1, h2, h3, .title, .post-title, a")
    link_selector = metadata.get("link_selector", "a")
    content_selector = metadata.get("content_selector", "p, .summary, .excerpt, .desc, .description")
    date_selector = metadata.get(
        "date_selector",
        "time, .date, .published, .time, span[class*='time'], span[class*='date']",
    )

    contents: List[Dict[str, Any]] = []
    articles = soup.select(article_selector)[:20]

    for article in articles:
        try:
            candidate = parse_article_candidate(
                article,
                source=source,
                title_selector=title_selector,
                link_selector=link_selector,
                content_selector=content_selector,
                date_selector=date_selector,
            )
            if candidate:
                contents.append(candidate)
        except Exception as exc:  # noqa: BLE001 - per-article parse errors shouldn't abort the page
            log.error("Error parsing article: %s", exc)
            continue

    append_fallback_links(soup=soup, source=source, contents=contents)
    log.info("Extracted %d articles from website", len(contents))
    return contents
