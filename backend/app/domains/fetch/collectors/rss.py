"""RSS feed collector."""

from datetime import datetime, timezone
from calendar import timegm
from typing import Any, Dict, List, Optional
import hashlib
import re
import asyncio
from urllib.parse import urljoin, urlparse

import feedparser
import aiohttp
from bs4 import BeautifulSoup

from app.domains.fetch.collectors.base import BaseCollector
from app.models import Source
from app.utils.logger import get_logger
from app.platform.security.ssrf import check_before_fetch, fetch_public_http_text
from app.utils.http import permissive_session_kwargs
from app.utils.text import strip_html_tags, text_looks_like_embedded_binary

logger = get_logger(__name__)


MIN_RSS_PLAIN_TEXT_CHARS = 100


class RSSCollector(BaseCollector):
    """Collector for RSS/Atom feeds."""
    
    def __init__(self):
        super().__init__()
        # Cap parallel per-entry page fetches (summary hydration) per feed
        self._entry_hydrate_sem = asyncio.Semaphore(6)
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
    
    async def fetch(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch content from an RSS feed."""
        await self._check_ssrf(source.url)
        self.logger.info(f"Fetching RSS feed: {source.url}")
        
        try:
            cookies = self.get_runtime_cookies(source)
            request_headers = None
            if cookies:
                cookie_header = "; ".join([f"{k}={v}" for k, v in cookies.items() if k and v])
                if cookie_header:
                    request_headers = {"Cookie": cookie_header}
            feed = await asyncio.to_thread(feedparser.parse, source.url, request_headers=request_headers)

            self._record_feed_health(source, feed)

            status = int(getattr(feed, "status", 0) or 0)
            if status >= 400:
                from app.domains.fetch.failures import FetchFailureError, classify_http_status

                failure = classify_http_status(status, detail=f"RSS feed request failed: {source.url}")
                if failure is not None:
                    raise FetchFailureError(failure)

            if feed.bozo and not feed.entries:
                from app.domains.fetch.failures import FetchFailureCode, FetchFailureError, make_failure

                self.logger.error(f"Failed to parse RSS feed: {feed.bozo_exception}")
                raise FetchFailureError(
                    make_failure(FetchFailureCode.RSS_PARSE_ERROR, detail=str(feed.bozo_exception))
                )
            
            contents = []
            # 并行获取所有条目的摘要
            tasks = []
            for entry in feed.entries[:20]:  # 限制为最多20条
                tasks.append(self._parse_entry_with_summary(entry, source))
            
            parsed_entries = await asyncio.gather(*tasks, return_exceptions=True)
            
            for content in parsed_entries:
                if isinstance(content, Exception):
                    self.logger.error(f"Error parsing entry: {content}")
                    continue
                if self.validate_content(content):
                    contents.append(content)
            
            self.logger.info(f"Fetched {len(contents)} items from RSS feed")
            return contents
            
        except Exception as e:
            from app.domains.fetch.failures import FetchFailureError

            if isinstance(e, FetchFailureError):
                raise
            self.logger.error(f"Error fetching RSS feed: {e}")
            return []

    def _record_feed_health(self, source: Source, feed: Any) -> None:
        """Stamp feed health into source metadata (best-effort, never fatal)."""
        try:
            from app.domains.fetch.rss_health import assess_parsed_feed_health, record_feed_health

            health = assess_parsed_feed_health(feed)
            record_feed_health(source, health, feed_url=source.url)
        except Exception as exc:  # noqa: BLE001 — health bookkeeping is non-critical
            self.logger.debug("Failed to record RSS feed health for %s: %s", source.url, exc)

    def validate_content(self, content: Dict[str, Any]) -> bool:
        """Require title/url plus meaningful text from RSS body or hydrated HTML."""
        if not super().validate_content(content):
            return False
        blob = str(content.get("content") or "")
        if text_looks_like_embedded_binary(blob):
            self.logger.debug("Skipping RSS entry with embedded binary in body: %s", (content.get("title") or "")[:60])
            return False
        plain = strip_html_tags(blob).strip()
        if len(plain) < MIN_RSS_PLAIN_TEXT_CHARS:
            html_blob = str(content.get("html") or "")
            if html_blob:
                plain = strip_html_tags(html_blob).strip()
        if len(plain) < MIN_RSS_PLAIN_TEXT_CHARS:
            self.logger.debug(
                "Skipping RSS entry with insufficient plain text (%s chars): %s",
                len(plain),
                (content.get("title") or "")[:80],
            )
            return False
        return True

    async def _parse_entry_with_summary(self, entry, source: Source) -> Dict[str, Any]:
        """Parse a feed entry and best-effort load article HTML for local storage."""
        content = self._parse_entry(entry)
        url = content.get("url", "")

        if url and not self._is_google_news_article_link(url):
            self.logger.info("Fetching article HTML for RSS entry: %s", url)
            async with self._entry_hydrate_sem:
                page_html = await self._fetch_page_html(url, source)
            if page_html:
                content["html"] = page_html
                content["content"] = ""
            else:
                summary = content.get("content", "")
                if not summary or len(strip_html_tags(summary)) < 50:
                    self.logger.info("Article HTML unavailable; fetching page summary: %s", url)
                    async with self._entry_hydrate_sem:
                        page_summary = await self._fetch_page_summary(url, source)
                    if page_summary:
                        content["content"] = page_summary

        return content

    @staticmethod
    def _is_google_news_article_link(url: str) -> bool:
        """Google News RSS article links are redirect wrappers and expensive to hydrate."""
        try:
            parsed = urlparse(url)
            return parsed.hostname == "news.google.com" and "/rss/articles/" in (parsed.path or "")
        except Exception as exc:
            logger.debug("Failed to inspect Google News article link '%s': %s", url, exc)
            return False

    @staticmethod
    def _stable_google_news_external_id(entry, publish_time: Optional[datetime]) -> str:
        """Build a stable external_id for Google News wrapper links."""
        title = str(entry.get("title") or "").strip().lower()
        title = re.sub(r"\s+", " ", title)
        source_title = ""
        source_obj = entry.get("source")
        if isinstance(source_obj, dict):
            source_title = str(source_obj.get("title") or source_obj.get("href") or "").strip().lower()
        publish_key = publish_time.isoformat() if isinstance(publish_time, datetime) else ""
        raw = f"{title}|{publish_key}|{source_title}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return f"gnews:{digest}"
    
    async def _fetch_page_html(self, url: str, source: Source) -> Optional[str]:
        """Fetch article page HTML (for full-text extraction downstream)."""
        import random

        try:
            cookies = self.get_runtime_cookies(source)
            await check_before_fetch(url, source_url=source.url, cookies=cookies or None)
        except ValueError as exc:
            self.logger.warning("SSRF/cookie check blocked page fetch for %s: %s", url, exc)
            return None

        try:
            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
                response = await fetch_public_http_text(
                    session,
                    url,
                    source_url=source.url,
                    validation_cookies=cookies or None,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    timeout=aiohttp.ClientTimeout(total=25),
                )
                if response.status != 200:
                    self.logger.warning("Failed to fetch article page: %s", response.status)
                    return None
                return response.text
        except asyncio.TimeoutError:
            self.logger.warning("Timeout fetching article page: %s", url)
            return None
        except Exception as exc:  # noqa: BLE001 - network/HTML fetch may raise anything
            self.logger.error("Error fetching article page %s: %s", url, exc)
            return None

    async def _fetch_page_summary(self, url: str, source: Source) -> Optional[str]:
        """Fetch summary/description from the original page."""
        html = await self._fetch_page_html(url, source)
        if not html:
            return None
        try:
            return self._extract_summary_from_html(html)
        except Exception as exc:  # noqa: BLE001 - BeautifulSoup parse may fail
            self.logger.error("Error extracting page summary from %s: %s", url, exc)
            return None
    
    def _extract_summary_from_html(self, html: str) -> Optional[str]:
        """Extract summary from HTML page (meta description, og:description, or first paragraph)."""
        try:
            soup = BeautifulSoup(html, "lxml")
            
            # 1. 尝试获取 meta description
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                desc = strip_html_tags(meta_desc["content"])
                if len(desc) >= 50:
                    return desc
            
            # 2. 尝试获取 og:description
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            if og_desc and og_desc.get("content"):
                desc = strip_html_tags(og_desc["content"])
                if len(desc) >= 50:
                    return desc
            
            # 3. 尝试获取 twitter:description
            twitter_desc = soup.find("meta", attrs={"name": "twitter:description"})
            if twitter_desc and twitter_desc.get("content"):
                desc = strip_html_tags(twitter_desc["content"])
                if len(desc) >= 50:
                    return desc
            
            # 4. 尝试从文章内容中提取
            # 查找常见的文章内容容器
            article_selectors = [
                "article p",
                ".article-content p",
                ".post-content p",
                ".entry-content p",
                ".content p",
                "main p",
                "#content p"
            ]
            
            for selector in article_selectors:
                paragraphs = soup.select(selector)
                if paragraphs:
                    # 获取前几个段落
                    text_parts = []
                    for p in paragraphs[:3]:
                        text = strip_html_tags(p.get_text())
                        if text and len(text) > 30:
                            text_parts.append(text)
                    
                    if text_parts:
                        combined = " ".join(text_parts)
                        # 限制长度
                        if len(combined) > 500:
                            combined = combined[:500] + "..."
                        return combined
            
            # 5. 最后尝试获取任何段落
            all_paragraphs = soup.find_all("p")
            for p in all_paragraphs:
                text = strip_html_tags(p.get_text())
                if text and len(text) >= 100:
                    return text[:500] + "..." if len(text) > 500 else text
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error extracting summary from HTML: {e}")
            return None
    
    def _parse_entry(self, entry) -> Dict[str, Any]:
        """Parse a single feed entry."""
        # Get publish time
        publish_time = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            # feedparser returns UTC-like struct_time; use timegm to avoid local timezone skew
            publish_time = datetime.fromtimestamp(timegm(entry.published_parsed), tz=timezone.utc).replace(tzinfo=None)
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            publish_time = datetime.fromtimestamp(timegm(entry.updated_parsed), tz=timezone.utc).replace(tzinfo=None)
        
        # Get content - 尝试多个字段
        content = ""
        
        # 优先使用 content 字段（通常是完整内容）
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].value
        
        # 如果 content 为空或太短，尝试 summary
        if not content or len(strip_html_tags(content)) < 50:
            if hasattr(entry, "summary") and entry.summary:
                summary_text = strip_html_tags(entry.summary)
                if len(summary_text) > len(strip_html_tags(content)):
                    content = entry.summary
        
        # 如果还是空或太短，尝试 description
        if not content or len(strip_html_tags(content)) < 50:
            if hasattr(entry, "description") and entry.description:
                desc_text = strip_html_tags(entry.description)
                if len(desc_text) > len(strip_html_tags(content)):
                    content = entry.description
        
        # Get external ID
        link = entry.get("link", "")
        external_id = entry.get("id") or link
        if self._is_google_news_article_link(link):
            external_id = self._stable_google_news_external_id(entry, publish_time)
        
        # Extract media/images
        media = []
        if hasattr(entry, "media_content"):
            for m in entry.media_content:
                media.append({
                    "url": m.get("url"),
                    "type": m.get("type"),
                })
        
        # Extract enclosures (for podcasts)
        enclosures = []
        if hasattr(entry, "enclosures"):
            for enc in entry.enclosures:
                enclosures.append({
                    "url": enc.get("href") or enc.get("url"),
                    "type": enc.get("type"),
                    "length": enc.get("length"),
                })
        
        return {
            "external_id": external_id,
            "title": entry.get("title", "Untitled"),
            "content": content,
            "url": link,
            "publish_time": publish_time,
            "ingest_channel": "rss",
            "metadata": {
                "author": entry.get("author"),
                "tags": [tag.term for tag in entry.get("tags", [])],
                "media": media,
                "enclosures": enclosures,
                "ingest_channel": "rss",
            },
        }
    
    async def discover_feed_url(self, website_url: str) -> Optional[str]:
        """Try to discover RSS feed URL from a website."""
        try:
            import random

            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            async with aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as session:
                response = await fetch_public_http_text(session, website_url)
                html = response.text
            
            soup = BeautifulSoup(html, "lxml")
            
            # Look for RSS/Atom feed links
            feed_links = soup.find_all("link", type=[
                "application/rss+xml",
                "application/atom+xml",
                "application/feed+json"
            ])
            
            if feed_links:
                href = feed_links[0].get("href")
                if href:
                    # Handle absolute, root-relative, and bare relative feed links.
                    return urljoin(website_url, href)
            
            # Try common feed URLs
            common_paths = [
                "/feed", "/feed/", "/rss", "/rss/",
                "/feed.xml", "/rss.xml", "/atom.xml",
                "/index.xml", "/feeds/posts/default"
            ]
            
            async with aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as session:
                for path in common_paths:
                    feed_url = urljoin(website_url, path)
                    try:
                        response = await fetch_public_http_text(
                            session,
                            feed_url,
                            method="HEAD",
                            timeout=5,
                            read_body=False,
                        )
                        if response.status == 200:
                            return feed_url
                    except Exception as e:
                        self.logger.debug(f"RSS path probe failed for {feed_url}: {e}")
                        continue
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error discovering feed URL: {e}")
            return None
