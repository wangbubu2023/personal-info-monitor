"""Website content collector."""

import asyncio
from collections import Counter
from copy import copy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from app.utils.datetime import utcnow_naive
from app.collectors.base import BaseCollector
from app.collectors.rss import RSSCollector
from app.models import Source
from app.pipeline.utils import get_website_content_reject_reason
from app.utils.cookies import cookie_domains_for_host
from app.utils.logger import get_logger
from app.utils.playwright_stealth import stealth_init_script
from app.utils.publish_time import parse_publish_time_text

logger = get_logger(__name__)


class WebsiteCollector(BaseCollector):
    """Collector for websites and blogs."""
    
    def __init__(self):
        super().__init__()
        self.rss_collector = RSSCollector()
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]

    def _wsj_fallback_rss(self, website_url: str) -> Optional[str]:
        """Build a fresh WSJ fallback RSS using Google News site search."""
        host = (urlparse(website_url).hostname or "").lower()
        if "wsj.com" not in host:
            return None
        q = quote("site:wsj.com")
        return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

    def _economist_fallback_rss(self, website_url: str) -> Optional[str]:
        """Build Economist fallback RSS for root/topic URLs that are often challenge-protected."""
        parsed = urlparse(website_url)
        host = (parsed.hostname or "").lower()
        if "economist.com" not in host:
            return None

        path = (parsed.path or "/").strip("/").lower()
        if not path:
            return "https://www.economist.com/international/rss.xml"

        topic_map = {
            "china": "https://www.economist.com/china/rss.xml",
            "business": "https://www.economist.com/business/rss.xml",
            "finance-and-economics": "https://www.economist.com/finance-and-economics/rss.xml",
            "artificial-intelligence": "https://www.economist.com/science-and-technology/rss.xml",
        }
        if path.startswith("topics/"):
            topic = path.split("/", 2)[1] if len(path.split("/", 2)) > 1 else ""
            return topic_map.get(topic, "https://www.economist.com/international/rss.xml")

        section = path.split("/", 1)[0]
        if not section:
            return "https://www.economist.com/international/rss.xml"
        return f"https://www.economist.com/{section}/rss.xml"

    def _filter_unwanted_wsj_items(self, source_url: str, contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop known WSJ fallback noise entries (e.g. print edition listing pages)."""
        host = (urlparse(source_url).hostname or "").lower()
        if "wsj.com" not in host:
            return contents

        blocked_keywords = ("print edition",)
        filtered: List[Dict[str, Any]] = []
        for item in contents:
            title = str(item.get("title") or "").strip().lower()
            if any(keyword in title for keyword in blocked_keywords):
                self.logger.info(f"Skipping non-article WSJ item: {item.get('title', '')}")
                continue
            filtered.append(item)
        return filtered

    def _source_with_url(self, source: Source, url: str) -> Source:
        """Use a shallow copy when routing through alternate feed URLs."""
        cloned = copy(source)
        cloned.url = url
        return cloned

    def _is_stale_rss_content(self, contents: List[Dict[str, Any]], max_age_days: int = 3) -> bool:
        """Whether RSS content is stale by latest publish_time."""
        latest = None
        for item in contents:
            pt = item.get("publish_time")
            if isinstance(pt, datetime):
                if not latest or pt > latest:
                    latest = pt
        if not latest:
            return True
        age = utcnow_naive() - latest
        return age.days >= max_age_days

    def _same_site(self, source_url: str, candidate_url: str) -> bool:
        source_host = (urlparse(source_url).hostname or "").lower().lstrip("www.")
        candidate_host = (urlparse(candidate_url).hostname or "").lower().lstrip("www.")
        if not source_host or not candidate_host:
            return False
        return candidate_host == source_host or candidate_host.endswith("." + source_host)

    def _looks_like_article_url(self, source_url: str, candidate_url: str) -> bool:
        if self._is_google_news_wrapper(candidate_url):
            return True
        if not candidate_url or not self._same_site(source_url, candidate_url):
            return False
        parsed = urlparse(candidate_url)
        path = (parsed.path or "").strip().lower()
        if not path or path == "/":
            return False
        # Skip common non-article paths.
        non_article_prefixes = (
            "/video",
            "/videos",
            "/podcasts",
            "/newsletters",
            "/livecoverage",
            "/live",
            "/search",
            "/topics",
            "/tag",
            "/tags",
            "/authors",
            "/author",
            "/account",
            "/subscribe",
            "/login",
            "/signin",
        )
        if any(path.startswith(prefix) for prefix in non_article_prefixes):
            return False
        non_article_exact = {
            "/news/latest-headlines",
            "/opinion/free-expression",
            "/audio/podcasts",
        }
        if path in non_article_exact:
            return False
        segments = [s for s in path.split("/") if s]
        if len(segments) < 2:
            return False
        tail = segments[-1]
        # Heuristic: section/list pages are often plain words without slug markers.
        if "-" not in tail and "." not in tail and tail.isalpha():
            return False
        return True

    def _prefer_direct_article_links(self, source: Source, contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not contents:
            return []
        direct = [c for c in contents if self._looks_like_article_url(source.url, str(c.get("url") or ""))]
        if not direct and contents:
            self.logger.info(f"No direct article links detected for {source.url}; fallback to RSS/static flow")
        return direct

    @staticmethod
    def _has_browser_session(runtime_session: Dict[str, Any]) -> bool:
        return bool(runtime_session and str(runtime_session.get("user_data_dir") or "").strip())

    @staticmethod
    def _cookie_items_for_hosts(hosts: set[str], cookies: Dict[str, str]) -> List[Dict[str, str]]:
        """Build Playwright cookie payloads for all candidate hosts."""
        cookie_items: List[Dict[str, str]] = []
        for host in hosts:
            for name, value in cookies.items():
                if not name or value is None:
                    continue
                for domain in cookie_domains_for_host(host):
                    cookie_items.append(
                        {
                            "name": str(name),
                            "value": str(value),
                            "domain": domain,
                            "path": "/",
                        }
                    )
        return cookie_items

    @staticmethod
    def _build_runtime_cookie_list(source_url: str, cookies: Dict[str, str]) -> List[Dict[str, str]]:
        host = (urlparse(source_url).hostname or "").lower()
        return WebsiteCollector._cookie_items_for_hosts({host} if host else set(), cookies)

    async def _close_browser_resources(
        self,
        *,
        context,
        browser,
        target_url: str,
        context_label: str,
        browser_label: str,
    ) -> None:
        if context:
            try:
                await context.close()
            except Exception as exc:
                self.logger.warning("Failed to close %s for %s: %s", context_label, target_url, exc)
        if browser:
            try:
                await browser.close()
            except Exception as exc:
                self.logger.warning("Failed to close %s for %s: %s", browser_label, target_url, exc)

    async def _hydrate_candidate_contents(
        self,
        source: Source,
        contents: List[Dict[str, Any]],
        cookies: Dict[str, str],
        browser_session: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        direct_contents = self._prefer_direct_article_links(source, contents)
        if not direct_contents:
            return None

        hydrated_contents, diag = await self._hydrate_direct_articles(
            source,
            direct_contents,
            cookies,
            browser_session=browser_session,
        )
        setattr(source, "_runtime_fetch_diag", diag)
        return hydrated_contents

    async def _fetch_authenticated_direct_articles(
        self,
        source: Source,
        cookies: Dict[str, str],
        browser_session: Optional[Dict[str, Any]],
    ) -> Optional[List[Dict[str, Any]]]:
        self.logger.info(
            f"Auth session detected for {source.url}; prioritizing direct article links "
            f"(cookies={bool(cookies)}, browser_session={self._has_browser_session(browser_session)})"
        )
        for fetcher in (self._fetch_with_playwright, self._fetch_static):
            hydrated = await self._hydrate_candidate_contents(
                source,
                await fetcher(source),
                cookies,
                browser_session=browser_session,
            )
            if hydrated:
                return hydrated
        return None

    async def _maybe_hydrate_rss_contents(
        self,
        source: Source,
        contents: List[Dict[str, Any]],
        cookies: Dict[str, str],
        browser_session: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        hydrated = await self._hydrate_candidate_contents(
            source,
            contents,
            cookies,
            browser_session=browser_session,
        )
        return hydrated or contents

    def _parse_article_candidate(
        self,
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
        publish_time = None
        date_text = ""
        if date_elem:
            datetime_attr = date_elem.get("datetime")
            if datetime_attr:
                try:
                    publish_time = datetime.fromisoformat(datetime_attr.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception as exc:
                    self.logger.warning("Failed to parse article datetime '%s' for %s: %s", datetime_attr, source.url, exc)
            date_text = date_elem.get_text(" ", strip=True) or ""
            if not publish_time and date_text:
                publish_time = parse_publish_time_text(date_text)

        candidate = {"title": title, "content": content, "url": url}
        reject_reason = get_website_content_reject_reason(source.url, candidate)
        if reject_reason:
            self.logger.info(f"Skipping low-signal website item during parse ({reject_reason}): {title}")
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

    def _append_fallback_links(
        self,
        *,
        soup: BeautifulSoup,
        source: Source,
        contents: List[Dict[str, Any]],
    ) -> None:
        if len(contents) >= 5:
            return

        seen = {str(item.get("url") or "") for item in contents}
        for anchor in soup.select("a[href]"):
            if len(contents) >= 20:
                break
            href = (anchor.get("href") or "").strip()
            if not href:
                continue
            url = urljoin(source.url, href)
            title = anchor.get_text(" ", strip=True)
            if not title or len(title) < 8 or url in seen:
                continue
            if not self._looks_like_article_url(source.url, url):
                continue
            seen.add(url)
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

    @staticmethod
    def _is_google_news_wrapper(article_url: str) -> bool:
        try:
            parsed = urlparse(article_url)
            host = (parsed.hostname or "").lower()
            path = parsed.path or ""
            return host == "news.google.com" and "/rss/articles/" in path
        except Exception as exc:
            logger.warning("Failed to inspect Google News wrapper URL %s: %s", article_url, exc)
            return False

    async def _resolve_google_wrapper_url_with_playwright(self, article_url: str) -> Optional[str]:
        """Resolve Google News wrapper URL to publisher URL via browser navigation."""
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            self.logger.warning("Playwright unavailable while resolving wrapper %s: %s", article_url, exc)
            return None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                try:
                    context = await browser.new_context()
                    try:
                        page = await context.new_page()
                        await page.add_init_script(stealth_init_script())
                        await page.goto(article_url, wait_until="networkidle", timeout=60000)
                        return page.url
                    finally:
                        await context.close()
                finally:
                    await browser.close()
        except Exception as exc:
            self.logger.warning("Failed to resolve Google wrapper %s: %s", article_url, exc)
            return None

    async def _fetch_article_html_with_playwright(
        self,
        article_url: str,
        cookies: Dict[str, str],
        source_url: str,
        browser_session: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Browser-based fetch with cookie injection for paywalled pages."""
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            self.logger.warning("Playwright unavailable while hydrating %s: %s", article_url, exc)
            return None, None, "playwright_unavailable"

        hosts = set()
        source_host = (urlparse(source_url).hostname or "").lower()
        article_host = (urlparse(article_url).hostname or "").lower()

        preferred_host = source_host if source_host and source_host != "news.google.com" else ""
        if not preferred_host and article_host and article_host != "news.google.com":
            preferred_host = article_host
        if preferred_host:
            hosts.add(preferred_host)

        try:
            async with async_playwright() as p:
                browser = None
                context = None
                try:
                    if self._has_browser_session(browser_session or {}):
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=str(browser_session.get("user_data_dir")),
                            headless=True,
                            args=["--disable-blink-features=AutomationControlled"],
                            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        )
                    else:
                        browser = await p.chromium.launch(
                            headless=True,
                            args=["--disable-blink-features=AutomationControlled"],
                        )
                        context = await browser.new_context(
                            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        )

                    cookie_items = self._cookie_items_for_hosts(hosts, cookies)
                    if cookie_items:
                        await context.add_cookies(cookie_items)

                    page = await context.new_page()
                    await page.add_init_script(stealth_init_script())
                    await page.goto(article_url, wait_until="networkidle", timeout=60000)
                    await page.wait_for_timeout(3500)
                    html = await page.content()
                    final_url = page.url
                    paragraph_count = await page.locator("article p").count()
                    final_host = (urlparse(final_url).hostname or "").lower()
                    if final_host == "news.google.com":
                        return None, final_url, "wrapper_unresolved"
                    if paragraph_count == 0 and len(html or "") < 8000:
                        return None, final_url, "shell_page"
                    return html, final_url, None
                finally:
                    await self._close_browser_resources(
                        context=context,
                        browser=browser,
                        target_url=article_url,
                        context_label="Playwright context",
                        browser_label="Playwright browser",
                    )
        except Exception as exc:
            self.logger.warning("Playwright fetch failed for %s: %s", article_url, exc)
            return None, None, "playwright_fetch_failed"

    async def _attempt_playwright_article_html(
        self,
        article_url: str,
        cookies: Dict[str, str],
        source_url: str,
        browser_session: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
        """Run Playwright article fetch when cookies or browser session exist; else None (skipped)."""
        if not (cookies or self._has_browser_session(browser_session or {})):
            return None
        return await self._fetch_article_html_with_playwright(
            article_url,
            cookies,
            source_url,
            browser_session=browser_session,
        )

    async def _try_playwright_fetch(
        self,
        url: str,
        cookies: Dict[str, str],
        source_url: str,
        browser_session: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[str, str, None]]:
        """Try fetching with Playwright. Returns (html, url, None) on success, None on failure or skip."""
        attempt = await self._attempt_playwright_article_html(
            url, cookies, source_url, browser_session=browser_session
        )
        if attempt is None:
            return None
        html, final_url, _reason = attempt
        if html:
            return html, final_url, None
        return None

    async def _fetch_article_html(
        self,
        article_url: str,
        cookies: Dict[str, str],
        source_url: str,
        browser_session: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        import random

        if self._is_google_news_wrapper(article_url):
            # First try full browser flow directly on wrapper URL.
            result = await self._try_playwright_fetch(
                article_url, cookies, source_url, browser_session=browser_session
            )
            if result:
                return result

            # Fallback: resolve wrapper first, then fetch resolved URL.
            resolved_url = await self._resolve_google_wrapper_url_with_playwright(article_url)
            if resolved_url:
                article_url = resolved_url
                attempt = await self._attempt_playwright_article_html(
                    article_url, cookies, source_url, browser_session=browser_session
                )
                if attempt is not None:
                    html, final_url, reason = attempt
                    if html:
                        return html, final_url, None
                    if reason:
                        return None, final_url or article_url, reason

            if cookies or self._has_browser_session(browser_session or {}):
                return None, None, "wrapper_unresolved"

        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    article_url,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    timeout=aiohttp.ClientTimeout(total=25),
                    allow_redirects=True,
                ) as response:
                    if response.status != 200:
                        attempt = await self._attempt_playwright_article_html(
                            article_url, cookies, source_url, browser_session=browser_session
                        )
                        if attempt is not None:
                            html, final_url, reason = attempt
                            if html:
                                return html, final_url, None
                            if reason:
                                return None, final_url or article_url, reason
                        return None, None, f"http_status_{response.status}"
                    return await response.text(), str(response.url), None
        except Exception as exc:
            self.logger.warning("HTTP article fetch failed for %s: %s", article_url, exc)
            attempt = await self._attempt_playwright_article_html(
                article_url, cookies, source_url, browser_session=browser_session
            )
            if attempt is not None:
                html, final_url, reason = attempt
                if html:
                    return html, final_url, None
                if reason:
                    return None, final_url or article_url, reason
            return None, None, "http_fetch_failed"

    async def _hydrate_direct_articles(
        self,
        source: Source,
        contents: List[Dict[str, Any]],
        cookies: Dict[str, str],
        browser_session: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not contents:
            return contents, {"attempted": 0, "hydrated": 0, "failures": {}}
        metadata = source.metadata_ or {}
        hydrate_limit = int(metadata.get("direct_article_hydrate_limit", 8))
        if hydrate_limit <= 0:
            return contents, {"attempted": 0, "hydrated": 0, "failures": {}}

        direct_indexes = [
            i for i, item in enumerate(contents)
            if self._looks_like_article_url(source.url, str(item.get("url") or ""))
        ][:hydrate_limit]
        if not direct_indexes:
            return contents, {"attempted": 0, "hydrated": 0, "failures": {}}

        tasks = [
            self._fetch_article_html(
                str(contents[i].get("url")),
                cookies,
                source.url,
                browser_session=browser_session,
            )
            for i in direct_indexes
        ]
        html_results = await asyncio.gather(*tasks, return_exceptions=True)
        failure_reasons: Counter[str] = Counter()
        hydrated_count = 0

        for idx, result in zip(direct_indexes, html_results):
            if isinstance(result, Exception) or not result:
                failure_reasons["hydrate_exception"] += 1
                continue
            html, resolved_url, reason = result
            if not html:
                if reason:
                    failure_reasons[reason] += 1
                continue
            hydrated_count += 1
            if resolved_url and resolved_url != str(contents[idx].get("url") or ""):
                metadata = contents[idx].get("metadata") if isinstance(contents[idx].get("metadata"), dict) else {}
                metadata["google_wrapper_url"] = str(contents[idx].get("url") or "")
                metadata["resolved_original_url"] = resolved_url
                contents[idx]["metadata"] = metadata
                contents[idx]["url"] = resolved_url
            # Let ContentProcessor extractor derive main text from article HTML.
            contents[idx]["html"] = html
            contents[idx]["content"] = ""
        diag = {
            "attempted": len(direct_indexes),
            "hydrated": hydrated_count,
            "failures": dict(failure_reasons),
        }
        return contents, diag
    
    async def fetch(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch content from a website."""
        await self._check_ssrf(source.url)
        self.logger.info(f"Fetching website: {source.url}")
        
        metadata = source.metadata_ or {}
        auth = self.get_runtime_auth(source)
        cookies = self.get_runtime_cookies(source)
        browser_session = self.get_runtime_browser_session(source)
        has_cookies = bool(cookies)
        has_browser_session = self._has_browser_session(browser_session)
        if auth and auth.get("auth_type") == "password" and not has_cookies:
            self.logger.info("Password auth configured without cookies; RSS-only mode may still miss paywalled content")

        if has_cookies or has_browser_session:
            direct_contents = await self._fetch_authenticated_direct_articles(source, cookies, browser_session)
            if direct_contents:
                return direct_contents

        # Check if source has RSS feed configured
        rss_map = metadata.get("rss_urls") if isinstance(metadata.get("rss_urls"), dict) else {}
        rss_url = rss_map.get(source.url) or metadata.get("rss_url")
        if not rss_url:
            rss_url = self._economist_fallback_rss(source.url)
            if rss_url:
                self.logger.info(f"Using Economist fallback RSS feed: {rss_url}")
        
        # Try RSS first
        if rss_url:
            self.logger.info(f"Using configured RSS feed: {rss_url}")
            original_url = source.url
            rss_source = self._source_with_url(source, rss_url)
            contents = await self.rss_collector.fetch(rss_source)
            contents = self._filter_unwanted_wsj_items(original_url, contents)
            if contents and not self._is_stale_rss_content(contents):
                if has_cookies or has_browser_session:
                    return await self._maybe_hydrate_rss_contents(source, contents, cookies, browser_session)
                return contents
            # WSJ feed endpoints often become stale; use a fresh fallback feed.
            fallback_url = self._wsj_fallback_rss(original_url)
            if fallback_url:
                self.logger.warning(f"Configured RSS appears stale for {original_url}; trying WSJ fallback feed")
                fallback_source = self._source_with_url(source, fallback_url)
                fallback_contents = await self.rss_collector.fetch(fallback_source)
                fallback_contents = self._filter_unwanted_wsj_items(original_url, fallback_contents)
                if fallback_contents:
                    if has_cookies or has_browser_session:
                        return await self._maybe_hydrate_rss_contents(source, fallback_contents, cookies, browser_session)
                    return fallback_contents
        
        # Try to discover RSS feed
        feed_url = await self.rss_collector.discover_feed_url(source.url)
        if feed_url:
            self.logger.info(f"Discovered RSS feed: {feed_url}")
            original_url = source.url
            feed_source = self._source_with_url(source, feed_url)
            contents = await self.rss_collector.fetch(feed_source)
            contents = self._filter_unwanted_wsj_items(original_url, contents)
            if contents:
                if has_cookies or has_browser_session:
                    return await self._maybe_hydrate_rss_contents(source, contents, cookies, browser_session)
                return contents
        
        # Check if JS rendering is needed
        if metadata.get("needs_js", False):
            return await self._fetch_with_playwright(source)
        
        # Fall back to static scraping
        return await self._fetch_static(source)
    
    async def _fetch_static(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch static website content using aiohttp."""
        import random
        
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        cookies = self.get_runtime_cookies(source)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    source.url,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        self.logger.warning(f"Static fetch non-200 ({response.status}) for {source.url}")
                        return []
                    html = await response.text()
            
            return self._parse_html(html, source)
            
        except Exception as e:
            self.logger.error(f"Error fetching static website: {e}")
            return []
    
    async def _fetch_with_playwright(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch dynamic website content using Playwright."""
        try:
            from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
            
            async with async_playwright() as p:
                browser = None
                context = None
                try:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    context = await browser.new_context(user_agent=self.user_agents[0])
                    runtime_session = self.get_runtime_browser_session(source)
                    if self._has_browser_session(runtime_session):
                        await context.close()
                        context = None
                        await browser.close()
                        browser = None
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=str(runtime_session.get("user_data_dir")),
                            headless=True,
                            args=["--disable-blink-features=AutomationControlled"],
                            user_agent=self.user_agents[0],
                        )

                    cookies = self.get_runtime_cookies(source)
                    cookie_list = self._build_runtime_cookie_list(source.url, cookies)
                    if cookie_list:
                        await context.add_cookies(cookie_list)

                    page = await context.new_page()
                    await page.add_init_script(stealth_init_script())
                    await page.goto(source.url, wait_until="networkidle")
                    
                    # Wait for content to load
                    metadata = source.metadata_ or {}
                    wait_selector = metadata.get("wait_selector", "article, .post, .entry, main")
                    
                    try:
                        await page.wait_for_selector(wait_selector, timeout=10000)
                    except PlaywrightTimeoutError:
                        self.logger.warning(f"Selector '{wait_selector}' not found, continuing anyway")
                    
                    html = await page.content()
                    return self._parse_html(html, source)
                finally:
                    await self._close_browser_resources(
                        context=context,
                        browser=browser,
                        target_url=source.url,
                        context_label="website Playwright context",
                        browser_label="website Playwright browser",
                    )
                
        except Exception as e:
            self.logger.error(f"Error fetching with Playwright: {e}")
            return []
    
    def _parse_html(self, html: str, source: Source) -> List[Dict[str, Any]]:
        """Parse HTML content and extract articles."""
        soup = BeautifulSoup(html, "lxml")
        metadata = source.metadata_ or {}
        
        # Get selectors from metadata or use defaults (expanded for Chinese sites)
        article_selector = metadata.get(
            "article_selector",
            "article, .post, .entry, [class*='news'], [class*='article'], [class*='story'], [class*='item'], [class*='card']"
        )
        title_selector = metadata.get("title_selector", "h1, h2, h3, .title, .post-title, a")
        link_selector = metadata.get("link_selector", "a")
        content_selector = metadata.get("content_selector", "p, .summary, .excerpt, .desc, .description")
        date_selector = metadata.get("date_selector", "time, .date, .published, .time, span[class*='time'], span[class*='date']")
        
        contents = []
        articles = soup.select(article_selector)[:20]  # Limit to 20 articles
        
        for article in articles:
            try:
                candidate = self._parse_article_candidate(
                    article,
                    source=source,
                    title_selector=title_selector,
                    link_selector=link_selector,
                    content_selector=content_selector,
                    date_selector=date_selector,
                )
                if candidate:
                    contents.append(candidate)
            except Exception as e:
                self.logger.error(f"Error parsing article: {e}")
                continue

        self._append_fallback_links(soup=soup, source=source, contents=contents)

        self.logger.info(f"Extracted {len(contents)} articles from website")
        return contents
