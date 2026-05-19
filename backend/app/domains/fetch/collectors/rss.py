"""RSS feed collector."""

from datetime import datetime, timezone
from calendar import timegm
from typing import Any, Dict, List, Optional
import hashlib
import re
import asyncio
from urllib.parse import urlparse

import feedparser
import aiohttp
from bs4 import BeautifulSoup

from app.domains.fetch.collectors.base import BaseCollector
from app.models import Source
from app.utils.logger import get_logger
from app.utils.ssrf import check_before_fetch
from app.utils.text import strip_html_tags, text_looks_like_embedded_binary

logger = get_logger(__name__)


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
            
            if feed.bozo and not feed.entries:
                self.logger.error(f"Failed to parse RSS feed: {feed.bozo_exception}")
                return []
            
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
            self.logger.error(f"Error fetching RSS feed: {e}")
            return []

    def validate_content(self, content: Dict[str, Any]) -> bool:
        """Require title/url plus meaningful description (filters channel hub rows with empty body)."""
        if not super().validate_content(content):
            return False
        blob = str(content.get("content") or "")
        if text_looks_like_embedded_binary(blob):
            self.logger.debug("Skipping RSS entry with embedded binary in body: %s", (content.get("title") or "")[:60])
            return False
        plain = strip_html_tags(blob).strip()
        if len(plain) < 20:
            self.logger.debug(
                "Skipping RSS entry with insufficient plain text (%s chars): %s",
                len(plain),
                (content.get("title") or "")[:80],
            )
            return False
        return True

    async def _parse_entry_with_summary(self, entry, source: Source) -> Dict[str, Any]:
        """Parse a single feed entry and fetch summary if needed."""
        content = self._parse_entry(entry)
        
        # 如果摘要为空或太短，尝试从原始页面获取
        summary = content.get("content", "")
        url = content.get("url", "")
        
        if url and not self._is_google_news_article_link(url) and (not summary or len(strip_html_tags(summary)) < 50):
            self.logger.info(f"Summary too short, fetching from page: {url}")
            async with self._entry_hydrate_sem:
                page_summary = await self._fetch_page_summary(url, source)
            if page_summary:
                content["content"] = page_summary
                self.logger.info(f"Got page summary: {page_summary[:100]}...")
        
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
    
    async def _fetch_page_summary(self, url: str, source: Source) -> Optional[str]:
        """Fetch summary/description from the original page."""
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
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    timeout=aiohttp.ClientTimeout(total=15),
                    allow_redirects=True
                ) as response:
                    if response.status != 200:
                        self.logger.warning(f"Failed to fetch page: {response.status}")
                        return None
                    html = await response.text()
            
            return self._extract_summary_from_html(html)
            
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout fetching page: {url}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching page summary: {e}")
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
            "metadata": {
                "author": entry.get("author"),
                "tags": [tag.term for tag in entry.get("tags", [])],
                "media": media,
                "enclosures": enclosures,
            }
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
                async with session.get(website_url, allow_redirects=True) as response:
                    html = await response.text()
            
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
                    # Handle relative URLs
                    if href.startswith("/"):
                        from urllib.parse import urljoin
                        href = urljoin(website_url, href)
                    return href
            
            # Try common feed URLs
            common_paths = [
                "/feed", "/feed/", "/rss", "/rss/",
                "/feed.xml", "/rss.xml", "/atom.xml",
                "/index.xml", "/feeds/posts/default"
            ]
            
            from urllib.parse import urljoin
            
            async with aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as session:
                for path in common_paths:
                    feed_url = urljoin(website_url, path)
                    try:
                        async with session.head(feed_url, timeout=5, allow_redirects=True) as response:
                            if response.status == 200:
                                return feed_url
                    except Exception as e:
                        self.logger.debug(f"RSS path probe failed for {feed_url}: {e}")
                        continue
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error discovering feed URL: {e}")
            return None
