"""Website content collector.

The public API lives on :class:`WebsiteCollector`. Pure helpers have been
extracted into sibling modules so this file can focus on the
fetch → hydrate → parse state machine and stay readable:

* :mod:`app.domains.fetch.collectors.website_helpers` — URL/RSS rules,
  cookie shaping, browser-session introspection (all side-effect free).
* :mod:`app.domains.fetch.collectors.website_parser` — HTML → content dict
  parsing.

Tests still poke at ``WebsiteCollector._xxx`` names, so the original
underscore-prefixed method surface is preserved as thin delegating wrappers
over the module-level helpers.
"""

import asyncio
import random
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from app.domains.fetch.collectors.base import BaseCollector
from app.domains.fetch.collectors.rss import RSSCollector
from app.models import Source
from app.utils.browser import get_browser_context, local_playwright_fetch_prefs
from app.utils.http import permissive_session_kwargs
from app.utils.human_timing import (
    human_inter_request_pause,
    human_scroll_page,
    humanized_wait_ms,
)
from app.utils.logger import get_logger
from app.utils.playwright_stealth import stealth_init_script
from app.platform.security.ssrf import check_before_fetch

from . import website_helpers as _helpers
from . import website_parser as _parser

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

    # ------------------------------------------------------------------
    # URL / RSS heuristics — thin wrappers around :mod:`website_helpers`.
    # Kept as methods so existing tests that call
    # ``WebsiteCollector._is_google_news_wrapper(...)`` continue to work.
    # ------------------------------------------------------------------

    @staticmethod
    def _wsj_fallback_rss(website_url: str) -> Optional[str]:
        return _helpers.wsj_fallback_rss(website_url)

    @staticmethod
    def _economist_fallback_rss(website_url: str) -> Optional[str]:
        return _helpers.economist_fallback_rss(website_url)

    @staticmethod
    def _source_with_url(source: Source, url: str) -> Source:
        return _helpers.source_with_url(source, url)

    @staticmethod
    def _is_stale_rss_content(contents: List[Dict[str, Any]], max_age_days: int = 3) -> bool:
        return _helpers.is_stale_rss_content(contents, max_age_days=max_age_days)

    @staticmethod
    def _same_site(source_url: str, candidate_url: str) -> bool:
        return _helpers.same_site(source_url, candidate_url)

    @staticmethod
    def _is_google_news_wrapper(article_url: str) -> bool:
        return _helpers.is_google_news_wrapper(article_url)

    @staticmethod
    def _looks_like_article_url(source_url: str, candidate_url: str) -> bool:
        return _helpers.looks_like_article_url(source_url, candidate_url)

    @staticmethod
    def _has_browser_session(runtime_session: Optional[Dict[str, Any]]) -> bool:
        return _helpers.has_browser_session(runtime_session)

    @staticmethod
    def _browser_session_auth_ready(runtime_session: Optional[Dict[str, Any]]) -> bool:
        return _helpers.browser_session_auth_ready(runtime_session)

    @staticmethod
    def _storage_state_path_for_playwright(browser_session: Optional[Dict[str, Any]]) -> Optional[str]:
        return _helpers.storage_state_path_for_playwright(browser_session)

    @staticmethod
    def _cookie_items_for_hosts(hosts: set[str], cookies: Dict[str, str]) -> List[Dict[str, str]]:
        return _helpers.cookie_items_for_hosts(hosts, cookies)

    @staticmethod
    def _build_runtime_cookie_list(source_url: str, cookies: Dict[str, str]) -> List[Dict[str, str]]:
        return _helpers.build_runtime_cookie_list(source_url, cookies)

    # ------------------------------------------------------------------
    # Item filtering / direct-link selection.
    # ------------------------------------------------------------------

    def _filter_unwanted_wsj_items(
        self, source_url: str, contents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
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

    def _prefer_direct_article_links(
        self, source: Source, contents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not contents:
            return []
        direct = [
            c for c in contents
            if _helpers.looks_like_article_url(source.url, str(c.get("url") or ""))
        ]
        if not direct and contents:
            self.logger.info(f"No direct article links detected for {source.url}; fallback to RSS/static flow")
        return direct

    # ------------------------------------------------------------------
    # Playwright navigation helpers (need ``self.logger`` — keep on class).
    # ------------------------------------------------------------------

    async def _playwright_goto_with_fallback(self, page, url: str, prefs: Dict[str, Any]) -> None:
        from app.utils.playwright_runtime import timeout_error_types

        timeout = int(prefs.get("goto_timeout_ms") or 60000)
        primary = prefs.get("wait_until") or "networkidle"
        fallback = prefs.get("fallback_wait_until") or "domcontentloaded"
        try:
            await page.goto(url, wait_until=primary, timeout=timeout)
        except timeout_error_types():
            self.logger.info(
                "Playwright goto timed out (%s); retrying with %s for %s",
                primary,
                fallback,
                url,
            )
            await page.goto(url, wait_until=fallback, timeout=min(timeout, 45_000))

    async def _playwright_after_navigation(self, page, prefs: Dict[str, Any]) -> None:
        # Paywall detectors fingerprint fixed-duration waits ("exactly 1500ms
        # after goto" across every fetch is a tell). Humanize the settle
        # window around the configured base so repeated hits look varied.
        post = int(prefs.get("post_goto_wait_ms") or 0)
        if post > 0:
            await page.wait_for_timeout(humanized_wait_ms(post, jitter_pct=0.3))
        if prefs.get("scroll_lazy"):
            try:
                # Multi-step scroll with random pauses, instead of one
                # ``scrollTo(scrollHeight)`` — the latter is a textbook
                # bot signature even when other fingerprints look clean.
                await human_scroll_page(page)
            except Exception as exc:  # noqa: BLE001 - Playwright surfaces many eval error types
                self.logger.debug("playwright_scroll_lazy skipped: %s", exc)

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
            except Exception as exc:  # noqa: BLE001 - teardown should never raise
                self.logger.warning("Failed to close %s for %s: %s", context_label, target_url, exc)
        if browser:
            try:
                await browser.close()
            except Exception as exc:  # noqa: BLE001 - teardown should never raise
                self.logger.warning("Failed to close %s for %s: %s", browser_label, target_url, exc)

    # ------------------------------------------------------------------
    # Hydration orchestration.
    # ------------------------------------------------------------------

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
            f"(cookies={bool(cookies)}, browser_session={_helpers.browser_session_auth_ready(browser_session)})"
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

    # ------------------------------------------------------------------
    # Article HTML fetching.
    # ------------------------------------------------------------------

    async def _resolve_google_wrapper_url_with_playwright(self, article_url: str) -> Optional[str]:
        """Resolve Google News wrapper URL to publisher URL via browser navigation."""
        from app.features import playwright_enabled

        if not playwright_enabled():
            return None
        from app.utils.playwright_runtime import is_patchright_active

        prefs = local_playwright_fetch_prefs({})
        try:
            async with get_browser_context(headless=prefs["headless"]) as context:
                page = await context.new_page()
                if not is_patchright_active():
                    await page.add_init_script(stealth_init_script())
                await self._playwright_goto_with_fallback(page, article_url, prefs)
                await self._playwright_after_navigation(page, prefs)
                return page.url
        except Exception as exc:  # noqa: BLE001 - broad Playwright/runtime surface
            self.logger.warning("Failed to resolve Google wrapper %s: %s", article_url, exc)
            return None

    async def _fetch_article_html_with_playwright(
        self,
        article_url: str,
        cookies: Dict[str, str],
        source_url: str,
        browser_session: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Browser-based fetch with cookie injection for paywalled pages."""
        from app.features import playwright_enabled

        if not playwright_enabled():
            return None, None, "playwright_disabled"
        try:
            from app.utils.playwright_runtime import is_patchright_active

            prefs = local_playwright_fetch_prefs(metadata)
            ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

            hosts: set[str] = set()
            source_host = (urlparse(source_url).hostname or "").lower()
            article_host = (urlparse(article_url).hostname or "").lower()

            preferred_host = source_host if source_host and source_host != "news.google.com" else ""
            if not preferred_host and article_host and article_host != "news.google.com":
                preferred_host = article_host
            if preferred_host:
                hosts.add(preferred_host)

            user_data_dir = (
                str(browser_session.get("user_data_dir"))
                if _helpers.browser_session_auth_ready(browser_session or {})
                else None
            )
            storage_state = _helpers.storage_state_path_for_playwright(browser_session)

            async with get_browser_context(
                headless=prefs["headless"],
                user_data_dir=user_data_dir,
                user_agent=ua,
                storage_state=storage_state,
                viewport=prefs.get("viewport"),
                locale=prefs.get("locale"),
            ) as context:
                cookie_items = _helpers.cookie_items_for_hosts(hosts, cookies)
                if cookie_items:
                    await context.add_cookies(cookie_items)

                page = await context.new_page()
                extra_headers = prefs.get("extra_http_headers")
                if isinstance(extra_headers, dict) and extra_headers:
                    await page.set_extra_http_headers(extra_headers)
                if not is_patchright_active():
                    await page.add_init_script(stealth_init_script())

                # Paywall sites (NYT, WSJ, Bloomberg…) treat cold hits on
                # article URLs as bot traffic and serve a shell/subscribe
                # page even when the persistent profile is logged in. The
                # browser-session validation path solves this by first
                # visiting the homepage and letting the session cookies
                # settle; mirror that here when a browser session is bound,
                # otherwise the profile's cookies go unused.
                if _helpers.browser_session_auth_ready(browser_session or {}) and preferred_host:
                    warmup_url = f"https://{preferred_host}/"
                    if warmup_url.rstrip("/") != article_url.rstrip("/"):
                        try:
                            await page.goto(
                                warmup_url,
                                wait_until="domcontentloaded",
                                timeout=20000,
                            )
                            # Humanize the "user lands on homepage" dwell so
                            # paywalls don't see identical 1500ms gaps on every
                            # session-backed fetch.
                            await page.wait_for_timeout(
                                humanized_wait_ms(1800, jitter_pct=0.35, floor_ms=900)
                            )
                        except Exception as warmup_exc:  # noqa: BLE001 - warm-up is best-effort
                            self.logger.debug(
                                "Homepage warm-up for %s failed: %s; proceeding with cold article hit",
                                warmup_url,
                                warmup_exc,
                            )

                await self._playwright_goto_with_fallback(page, article_url, prefs)
                await self._playwright_after_navigation(page, prefs)
                html = await page.content()
                final_url = page.url
                paragraph_count = await page.locator("article p").count()
                final_host = (urlparse(final_url).hostname or "").lower()
                if final_host == "news.google.com":
                    return None, final_url, "wrapper_unresolved"
                if paragraph_count == 0 and len(html or "") < 8000:
                    return None, final_url, "shell_page"
                return html, final_url, None
        except Exception as exc:  # noqa: BLE001 - broad Playwright/runtime surface
            self.logger.warning("Playwright fetch failed for %s: %s", article_url, exc)
            return None, None, "playwright_fetch_failed"

    async def _attempt_playwright_article_html(
        self,
        article_url: str,
        cookies: Dict[str, str],
        source_url: str,
        browser_session: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
        """Run Playwright article fetch when cookies or browser session exist; else None (skipped)."""
        bs = browser_session or {}
        storage_ok = bool(_helpers.storage_state_path_for_playwright(bs))
        if not (cookies or _helpers.browser_session_auth_ready(bs) or storage_ok):
            return None
        return await self._fetch_article_html_with_playwright(
            article_url,
            cookies,
            source_url,
            browser_session=browser_session,
            metadata=metadata,
        )

    async def _try_playwright_fetch(
        self,
        url: str,
        cookies: Dict[str, str],
        source_url: str,
        browser_session: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[str, str, None]]:
        """Try fetching with Playwright. Returns (html, url, None) on success, None on failure or skip."""
        attempt = await self._attempt_playwright_article_html(
            url, cookies, source_url, browser_session=browser_session, metadata=metadata
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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        try:
            await check_before_fetch(
                article_url,
                source_url=source_url,
                cookies=cookies or None,
            )
        except ValueError as exc:
            self.logger.warning("SSRF/cookie check blocked article fetch for %s: %s", article_url, exc)
            return None, None, "ssrf_blocked"

        if _helpers.is_google_news_wrapper(article_url):
            # First try full browser flow directly on wrapper URL.
            result = await self._try_playwright_fetch(
                article_url, cookies, source_url, browser_session=browser_session, metadata=metadata
            )
            if result:
                return result

            # Fallback: resolve wrapper first, then fetch resolved URL.
            resolved_url = await self._resolve_google_wrapper_url_with_playwright(article_url)
            if resolved_url:
                article_url = resolved_url
                attempt = await self._attempt_playwright_article_html(
                    article_url, cookies, source_url, browser_session=browser_session, metadata=metadata
                )
                if attempt is not None:
                    html, final_url, reason = attempt
                    if html:
                        return html, final_url, None
                    if reason:
                        return None, final_url or article_url, reason

            if (
                cookies
                or _helpers.browser_session_auth_ready(browser_session or {})
                or _helpers.storage_state_path_for_playwright(browser_session or {})
            ):
                return None, None, "wrapper_unresolved"

        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        try:
            async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
                async with session.get(
                    article_url,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    timeout=aiohttp.ClientTimeout(total=25),
                    allow_redirects=True,
                ) as response:
                    if response.status != 200:
                        attempt = await self._attempt_playwright_article_html(
                            article_url, cookies, source_url, browser_session=browser_session, metadata=metadata
                        )
                        if attempt is not None:
                            html, final_url, reason = attempt
                            if html:
                                return html, final_url, None
                            if reason:
                                return None, final_url or article_url, reason
                        return None, None, f"http_status_{response.status}"
                    return await response.text(), str(response.url), None
        except (aiohttp.ClientError, TimeoutError) as exc:
            self.logger.warning("HTTP article fetch failed for %s: %s", article_url, exc)
            attempt = await self._attempt_playwright_article_html(
                article_url, cookies, source_url, browser_session=browser_session, metadata=metadata
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
        limit_default = 3 if _helpers.browser_session_auth_ready(browser_session or {}) else 8
        hydrate_limit = int(metadata.get("direct_article_hydrate_limit", limit_default))
        if hydrate_limit <= 0:
            return contents, {"attempted": 0, "hydrated": 0, "failures": {}}

        direct_indexes = [
            i for i, item in enumerate(contents)
            if _helpers.looks_like_article_url(source.url, str(item.get("url") or ""))
        ][:hydrate_limit]
        if not direct_indexes:
            return contents, {"attempted": 0, "hydrated": 0, "failures": {}}

        meta = source.metadata_ if isinstance(source.metadata_, dict) else {}

        # Paywall sites fingerprint bursts of parallel same-host fetches as
        # bot traffic — 8 simultaneous article hits in <1s is the classic
        # crawler signature. When the source is backed by a logged-in
        # browser session we deliberately pace hydration: serialize, then
        # sleep a small random interval between hits so the server sees
        # click-like cadence instead of a gather() burst. Public sites
        # without an auth session keep the fast parallel path for throughput.
        paced = _helpers.browser_session_auth_ready(browser_session or {})
        html_results: List[Any]
        if paced:
            html_results = []
            for offset, i in enumerate(direct_indexes):
                if offset > 0:
                    await human_inter_request_pause(min_ms=900, max_ms=2800)
                try:
                    html_results.append(
                        await self._fetch_article_html(
                            str(contents[i].get("url")),
                            cookies,
                            source.url,
                            browser_session=browser_session,
                            metadata=meta,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - mirror gather(return_exceptions=True)
                    html_results.append(exc)
        else:
            tasks = [
                self._fetch_article_html(
                    str(contents[i].get("url")),
                    cookies,
                    source.url,
                    browser_session=browser_session,
                    metadata=meta,
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
                item_metadata = (
                    contents[idx].get("metadata")
                    if isinstance(contents[idx].get("metadata"), dict)
                    else {}
                )
                item_metadata["google_wrapper_url"] = str(contents[idx].get("url") or "")
                item_metadata["resolved_original_url"] = resolved_url
                contents[idx]["metadata"] = item_metadata
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

    # ------------------------------------------------------------------
    # Listing-page parsing.
    # ------------------------------------------------------------------

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
        return _parser.parse_article_candidate(
            article,
            source=source,
            title_selector=title_selector,
            link_selector=link_selector,
            content_selector=content_selector,
            date_selector=date_selector,
        )

    def _append_fallback_links(
        self,
        *,
        soup: BeautifulSoup,
        source: Source,
        contents: List[Dict[str, Any]],
    ) -> None:
        _parser.append_fallback_links(soup=soup, source=source, contents=contents)

    def _parse_html(self, html: str, source: Source) -> List[Dict[str, Any]]:
        return _parser.parse_html_content(html=html, source=source, item_logger=self.logger)

    # ------------------------------------------------------------------
    # Top-level orchestration.
    # ------------------------------------------------------------------

    async def fetch(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch content from a website."""
        await self._check_ssrf(source.url)
        self.logger.info(f"Fetching website: {source.url}")

        metadata = source.metadata_ or {}
        # Opt-in "仅 RSS 摘要" mode. When the operator flips this flag on a
        # source (typically because DataDome / Cloudflare bot-walls have
        # invalidated the Playwright hydration path), we skip all browser-based
        # article fetches and return the RSS summaries as-is. AI
        # summarization/translation still run downstream — we just don't
        # pretend we can pull full bodies.
        rss_only = bool(metadata.get("rss_only"))

        auth = self.get_runtime_auth(source)
        cookies = self.get_runtime_cookies(source)
        browser_session = self.get_runtime_browser_session(source)
        has_cookies = bool(cookies)
        has_browser_session = _helpers.browser_session_auth_ready(browser_session)
        has_storage_export = bool(_helpers.storage_state_path_for_playwright(browser_session))
        if auth and auth.get("auth_type") == "password" and not has_cookies:
            self.logger.info(
                "Password auth configured without cookies; RSS-only mode may still miss paywalled content"
            )

        if rss_only:
            self.logger.info(
                "rss_only=true for %s; skipping Playwright hydration, returning RSS summaries only",
                source.url,
            )

        if not rss_only and (has_cookies or has_browser_session or has_storage_export):
            direct_contents = await self._fetch_authenticated_direct_articles(
                source, cookies, browser_session
            )
            if direct_contents:
                return direct_contents

        # Check if source has RSS feed configured.
        rss_map = metadata.get("rss_urls") if isinstance(metadata.get("rss_urls"), dict) else {}
        rss_url = rss_map.get(source.url) or metadata.get("rss_url")
        if not rss_url:
            rss_url = _helpers.economist_fallback_rss(source.url)
            if rss_url:
                self.logger.info(f"Using Economist fallback RSS feed: {rss_url}")

        hydrate_rss = (
            not rss_only and (has_cookies or has_browser_session or has_storage_export)
        )

        # Try RSS first.
        if rss_url:
            self.logger.info(f"Using configured RSS feed: {rss_url}")
            original_url = source.url
            rss_source = _helpers.source_with_url(source, rss_url)
            contents = await self.rss_collector.fetch(rss_source)
            contents = self._filter_unwanted_wsj_items(original_url, contents)
            if contents and not _helpers.is_stale_rss_content(contents):
                if hydrate_rss:
                    return await self._maybe_hydrate_rss_contents(
                        source, contents, cookies, browser_session
                    )
                return contents
            # WSJ feed endpoints often become stale; use a fresh fallback feed.
            fallback_url = _helpers.wsj_fallback_rss(original_url)
            if fallback_url:
                self.logger.warning(f"Configured RSS appears stale for {original_url}; trying WSJ fallback feed")
                fallback_source = _helpers.source_with_url(source, fallback_url)
                fallback_contents = await self.rss_collector.fetch(fallback_source)
                fallback_contents = self._filter_unwanted_wsj_items(original_url, fallback_contents)
                if fallback_contents:
                    if hydrate_rss:
                        return await self._maybe_hydrate_rss_contents(
                            source, fallback_contents, cookies, browser_session
                        )
                    return fallback_contents

        # Try to discover RSS feed.
        feed_url = await self.rss_collector.discover_feed_url(source.url)
        if feed_url:
            self.logger.info(f"Discovered RSS feed: {feed_url}")
            original_url = source.url
            feed_source = _helpers.source_with_url(source, feed_url)
            contents = await self.rss_collector.fetch(feed_source)
            contents = self._filter_unwanted_wsj_items(original_url, contents)
            if contents:
                if hydrate_rss:
                    return await self._maybe_hydrate_rss_contents(
                        source, contents, cookies, browser_session
                    )
                return contents

        # rss_only: once we've exhausted all RSS options, bail out instead of
        # falling back to Playwright/static scraping. The operator explicitly
        # opted into RSS-only behavior; returning [] here just means "no new
        # items this cycle" rather than triggering a browser-walled fetch.
        if rss_only:
            self.logger.info(
                "rss_only=true and no RSS feed yielded content for %s; skipping HTML fallback",
                source.url,
            )
            return []

        # Check if JS rendering is needed.
        if metadata.get("needs_js", False):
            return await self._fetch_with_playwright(source)

        # Fall back to static scraping.
        return await self._fetch_static(source)

    async def _fetch_static(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch static website content using aiohttp."""
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        cookies = self.get_runtime_cookies(source)

        try:
            async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
                async with session.get(
                    source.url,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        self.logger.warning(f"Static fetch non-200 ({response.status}) for {source.url}")
                        return []
                    html = await response.text()

            return self._parse_html(html, source)

        except (aiohttp.ClientError, TimeoutError) as exc:
            self.logger.error(f"Error fetching static website: {exc}")
            return []

    async def _fetch_with_playwright(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch dynamic website content using Playwright."""
        from app.features import playwright_enabled

        if not playwright_enabled():
            # Master switch off (audit 2026-04-20 S5). Fall back silently so
            # that disabling Playwright does not spam logs on every scheduled
            # fetch; callers (the pipeline) already know to try static/RSS.
            self.logger.debug(
                "Skipping dynamic fetch for %s: PIM_FEATURE_PLAYWRIGHT is off", source.url
            )
            return []

        try:
            from app.utils.playwright_runtime import (
                is_patchright_active,
                timeout_error_types,
            )

            _timeout_errs = timeout_error_types()
            metadata = source.metadata_ or {}
            prefs = local_playwright_fetch_prefs(metadata)

            runtime_session = self.get_runtime_browser_session(source)
            user_data_dir = (
                str(runtime_session.get("user_data_dir"))
                if _helpers.browser_session_auth_ready(runtime_session)
                else None
            )
            storage_state = _helpers.storage_state_path_for_playwright(runtime_session)

            async with get_browser_context(
                headless=prefs["headless"],
                user_data_dir=user_data_dir,
                user_agent=self.user_agents[0],
                storage_state=storage_state,
                viewport=prefs.get("viewport"),
                locale=prefs.get("locale"),
            ) as context:
                cookies = self.get_runtime_cookies(source)
                cookie_list = _helpers.build_runtime_cookie_list(source.url, cookies)
                if cookie_list:
                    await context.add_cookies(cookie_list)

                page = await context.new_page()
                extra_headers = prefs.get("extra_http_headers")
                if isinstance(extra_headers, dict) and extra_headers:
                    await page.set_extra_http_headers(extra_headers)
                # Patchright's patched Chromium already masks the WebDriver/
                # CDP signals this script tries to override, and layering the
                # extra JS overrides on top causes Datadome-class checks to
                # flag the browser as *more* suspicious (plugin count mismatch
                # etc.). Only inject on the vanilla-playwright path.
                if not is_patchright_active():
                    await page.add_init_script(stealth_init_script())
                await self._playwright_goto_with_fallback(page, source.url, prefs)
                await self._playwright_after_navigation(page, prefs)

                wait_selector = metadata.get("wait_selector", "article, .post, .entry, main")

                try:
                    await page.wait_for_selector(wait_selector, timeout=10000)
                except _timeout_errs:
                    self.logger.warning(f"Selector '{wait_selector}' not found, continuing anyway")

                html = await page.content()
                return self._parse_html(html, source)

        except Exception as exc:  # noqa: BLE001 - broad Playwright surface
            self.logger.error(f"Error fetching with Playwright: {exc}")
            return []
