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
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError

from app.domains.fetch.failures import (
    FetchFailure,
    FetchFailureCode,
    FetchFailureError,
    make_failure,
)
from app.domains.fetch.collectors.base import BaseCollector
from app.domains.fetch.collectors.rss import RSSCollector
from app.models import Content, Source
from app.platform.persistence.database import SessionLocal
from app.utils.browser import get_browser_context, local_playwright_fetch_prefs
from app.utils.http import permissive_session_kwargs
from app.utils.human_timing import (
    human_inter_request_pause,
    human_scroll_page,
    humanized_wait_ms,
)
from app.utils.logger import get_logger
from app.utils.playwright_stealth import stealth_init_script
from app.utils.text import strip_html_tags
from app.utils.datetime import utcnow_naive
from app.platform.security.ssrf import check_before_fetch, fetch_public_http_text
from app.utils.url import normalize_external_id

from .fetch_profile import diagnose_article_html, get_fetch_profile
from . import website_helpers as _helpers
from . import website_parser as _parser
from . import website_sitemap as _sitemap
from . import bpc_strategies, website_shadow_dom as _shadow_dom

logger = get_logger(__name__)

_STATIC_TO_PLAYWRIGHT_FAILURES = {
    FetchFailureCode.HTTP_403,
    FetchFailureCode.LOGIN_REQUIRED,
    FetchFailureCode.BOT_WALL,
    FetchFailureCode.CAPTCHA,
}
_ARTICLE_HTTP_STATUSES_TO_PLAYWRIGHT = {401, 403, 429, 500, 502, 503}


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

    @staticmethod
    def _known_duplicate_external_id(source: Source, item: Dict[str, Any]) -> bool:
        """Whether this raw item matches the source's latest saved marker.

        Website RSS/listing paths hydrate before the generic pipeline dedupe
        runs. Skipping the already-known latest item avoids a repeated second
        hop on steady-state feeds while still allowing genuinely new entries
        to hydrate.
        """
        marker = normalize_external_id(getattr(source, "last_content_id", None))
        if not marker:
            return False
        candidates = [
            normalize_external_id(item.get("external_id")),
            normalize_external_id(item.get("url")),
        ]
        return marker in {candidate for candidate in candidates if candidate}

    @staticmethod
    def _identity_keys_for_item(item: Dict[str, Any]) -> tuple[set[str], set[str]]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        raw_ids = {
            str(item.get("external_id") or "").strip(),
            str(item.get("url") or "").strip(),
            str(item.get("original_url") or "").strip(),
            str(metadata.get("canonical_url") or "").strip(),
            str(metadata.get("canonical_external_id") or "").strip(),
        }
        identity_keys: set[str] = set()
        url_identities: set[str] = set()
        for raw in raw_ids:
            if not raw:
                continue
            identity_keys.add(raw)
            normalized = normalize_external_id(raw)
            if normalized:
                identity_keys.add(normalized)
            if raw.startswith(("http://", "https://")):
                url_identities.add(raw)
        return identity_keys, url_identities

    def _known_existing_content_indexes(
        self,
        source: Source,
        contents: List[Dict[str, Any]],
    ) -> set[int]:
        """Return indexes already present for this source before hydration.

        ``source.last_content_id`` only catches the latest saved item. Steady
        RSS/listing pages often include many older entries, and hydrating those
        before ingest dedupe wastes a second hop per old item. This batched
        lookup mirrors ingest-side identity matching closely enough to skip
        same-source duplicates before article HTML fetches.
        """
        source_id = getattr(source, "id", None)
        if not isinstance(source_id, str) or not source_id or not contents:
            return set()

        item_identities: list[tuple[set[str], set[str]]] = []
        all_identity_keys: set[str] = set()
        all_url_identities: set[str] = set()
        for item in contents:
            identity_keys, url_identities = self._identity_keys_for_item(item)
            item_identities.append((identity_keys, url_identities))
            all_identity_keys.update(identity_keys)
            all_url_identities.update(url_identities)

        identity_filters = []
        if all_identity_keys:
            identity_list = list(all_identity_keys)
            identity_filters.append(Content.external_id.in_(identity_list))
            identity_filters.append(func.json_extract(Content.metadata_, "$.canonical_external_id").in_(identity_list))
        if all_url_identities:
            url_list = list(all_url_identities)
            identity_filters.append(Content.original_url.in_(url_list))
            identity_filters.append(func.json_extract(Content.metadata_, "$.canonical_url").in_(url_list))
        if not identity_filters:
            return set()

        try:
            with SessionLocal() as db:
                rows = (
                    db.query(Content.external_id, Content.original_url, Content.metadata_)
                    .filter(Content.source_id == source_id, or_(*identity_filters))
                    .all()
                )
        except SQLAlchemyError as exc:
            self.logger.debug("Existing content pre-hydration lookup failed for %s: %s", source.url, exc)
            return set()

        existing_identity_keys: set[str] = set()
        existing_url_identities: set[str] = set()
        for external_id, original_url, metadata in rows:
            row_metadata = metadata if isinstance(metadata, dict) else {}
            row_raw_values = {
                str(external_id or "").strip(),
                str(original_url or "").strip(),
                str(row_metadata.get("canonical_url") or "").strip(),
                str(row_metadata.get("canonical_external_id") or "").strip(),
            }
            for raw in row_raw_values:
                if not raw:
                    continue
                existing_identity_keys.add(raw)
                normalized = normalize_external_id(raw)
                if normalized:
                    existing_identity_keys.add(normalized)
                if raw.startswith(("http://", "https://")):
                    existing_url_identities.add(raw)

        existing_indexes: set[int] = set()
        for idx, (identity_keys, url_identities) in enumerate(item_identities):
            if identity_keys & existing_identity_keys or url_identities & existing_url_identities:
                existing_indexes.add(idx)
        return existing_indexes

    @staticmethod
    def _stamp_session_health(source: Source, *, reason: str, final_url: str | None = None) -> None:
        from app.domains.fetch.session_health import SessionHealth, record_session_health

        action = "none"
        status = "warning"
        if reason in {"login_required", "expired", "http_status_401", "http_status_403"}:
            reason = "login_required" if reason.startswith("http_status") else reason
            action = "relogin"
            status = "error"
        elif reason in {"bot_wall", "wrapper_unresolved"}:
            reason = "bot_wall" if reason == "bot_wall" else reason
            action = "switch_rss_only"
            status = "error"
        elif reason == "captcha":
            action = "relogin"
            status = "error"
        elif reason in {"http_status_429", "playwright_fetch_failed", "http_fetch_failed", "shell_page"}:
            action = "retry_later"

        if action == "none":
            return
        record_session_health(source, SessionHealth(
            status=status,
            reason=reason,
            suggested_action=action,
            validated_at=utcnow_naive().isoformat() + "Z",
            details={"final_url": final_url or source.url, "source": "website_hydration"},
        ))

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
        await _shadow_dom.materialize_shadow_dom(page, logger=self.logger)

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
            try:
                fetched_contents = await fetcher(source)
                hydrated = await self._hydrate_candidate_contents(
                    source,
                    fetched_contents,
                    cookies,
                    browser_session=browser_session,
                )
            except Exception as exc:  # noqa: BLE001 - one direct strategy must not block RSS fallback
                fetcher_name = getattr(fetcher, "__name__", fetcher.__class__.__name__)
                self.logger.warning(
                    "Authenticated %s fetch failed for %s; continuing to next strategy: %s",
                    fetcher_name,
                    source.url,
                    exc,
                )
                continue
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
        direct_contents = self._prefer_direct_article_links(source, contents)
        if not direct_contents:
            return contents

        metadata = source.metadata_ or {}
        rss_limit = int(metadata.get("rss_article_hydrate_limit", 20))
        hydrated_contents, diag = await self._hydrate_direct_articles(
            source,
            direct_contents,
            cookies,
            browser_session=browser_session,
            hydrate_limit_override=rss_limit,
        )
        setattr(source, "_runtime_fetch_diag", diag)
        return hydrated_contents or contents

    async def _maybe_hydrate_public_listing_contents(
        self,
        source: Source,
        contents: List[Dict[str, Any]],
        cookies: Dict[str, str],
        browser_session: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Hydrate public listing-card results when they only contain teasers."""
        if not contents:
            return contents

        metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
        if metadata.get("skip_public_article_hydration"):
            return contents

        direct_contents = self._prefer_direct_article_links(source, contents)
        if not direct_contents:
            return contents

        try:
            min_chars = int(metadata.get("public_article_hydrate_min_chars", 500))
        except (TypeError, ValueError):
            min_chars = 500

        def _body_len(item: Dict[str, Any]) -> int:
            body = item.get("content") or item.get("summary") or ""
            return len(strip_html_tags(str(body)).strip())

        if min_chars > 0 and all(_body_len(item) >= min_chars for item in direct_contents):
            return contents

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

            metadata = metadata if isinstance(metadata, dict) else {}
            prefs = local_playwright_fetch_prefs(metadata)
            ephemeral_context = bool(metadata.get("bpc_ephemeral_context"))
            effective_cookies = {} if ephemeral_context else cookies
            ua_default = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            bpc_headers = bpc_strategies.get_spoofed_headers(metadata, ua_default)
            ua = bpc_headers.pop("User-Agent", ua_default)

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

            if ephemeral_context:
                user_data_dir = None
                storage_state = None

            async with get_browser_context(
                headless=prefs["headless"],
                user_data_dir=user_data_dir,
                user_agent=ua,
                storage_state=storage_state,
                viewport=prefs.get("viewport"),
                locale=prefs.get("locale"),
            ) as context:
                cookie_items = _helpers.cookie_items_for_hosts(hosts, effective_cookies)
                if cookie_items:
                    await context.add_cookies(cookie_items)

                page = await context.new_page()
                extra_headers = prefs.get("extra_http_headers") or {}
                if isinstance(extra_headers, dict):
                    extra_headers = {**extra_headers, **bpc_headers}
                else:
                    extra_headers = bpc_headers
                if extra_headers:
                    await page.set_extra_http_headers(extra_headers)
                if not is_patchright_active():
                    await page.add_init_script(stealth_init_script())

                interceptor = bpc_strategies.get_bpc_playwright_interceptor(metadata)
                if interceptor is not None:
                    await context.route("**/*", interceptor)

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
        """Run Playwright article fetch when a session or browser-only strategy requires it."""
        metadata = metadata if isinstance(metadata, dict) else {}
        bs = browser_session or {}
        storage_ok = bool(_helpers.storage_state_path_for_playwright(bs))
        if not (
            cookies
            or _helpers.browser_session_auth_ready(bs)
            or storage_ok
            or bpc_strategies.requires_bpc_playwright(metadata)
        ):
            return None
        effective_cookies = {} if metadata.get("bpc_ephemeral_context") else cookies
        return await self._fetch_article_html_with_playwright(
            article_url,
            effective_cookies,
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
        metadata = metadata if isinstance(metadata, dict) else {}
        effective_cookies = {} if metadata.get("bpc_ephemeral_context") else cookies
        try:
            await check_before_fetch(
                article_url,
                source_url=source_url,
                cookies=effective_cookies or None,
            )
        except ValueError as exc:
            self.logger.warning("SSRF/cookie check blocked article fetch for %s: %s", article_url, exc)
            return None, None, "ssrf_blocked"

        if _helpers.is_google_news_wrapper(article_url):
            # First try full browser flow directly on wrapper URL.
            result = await self._try_playwright_fetch(
                article_url, effective_cookies, source_url, browser_session=browser_session, metadata=metadata
            )
            if result:
                return result

            # Fallback: resolve wrapper first, then fetch resolved URL.
            resolved_url = await self._resolve_google_wrapper_url_with_playwright(article_url)
            if resolved_url:
                article_url = resolved_url
                attempt = await self._attempt_playwright_article_html(
                    article_url, effective_cookies, source_url, browser_session=browser_session, metadata=metadata
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
                or bpc_strategies.requires_bpc_playwright(metadata)
            ):
                return None, None, "wrapper_unresolved"

        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        bpc_headers = bpc_strategies.get_spoofed_headers(metadata, headers["User-Agent"])
        headers.update(bpc_headers)
        try:
            async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
                response = await fetch_public_http_text(
                    session,
                    article_url,
                    source_url=source_url,
                    validation_cookies=effective_cookies or None,
                    headers=headers,
                    cookies=effective_cookies if effective_cookies else None,
                    timeout=aiohttp.ClientTimeout(total=25),
                )
                if response.status != 200:
                    if response.status in _ARTICLE_HTTP_STATUSES_TO_PLAYWRIGHT:
                        attempt = await self._attempt_playwright_article_html(
                            article_url,
                            effective_cookies,
                            source_url,
                            browser_session=browser_session,
                            metadata=metadata,
                        )
                        if attempt is not None:
                            html, final_url, reason = attempt
                            if html:
                                return html, final_url, None
                            if reason:
                                return None, final_url or article_url, reason
                    return None, None, f"http_status_{response.status}"
                return response.text, response.url, None
        except ValueError as exc:
            self.logger.warning("SSRF/cookie check blocked article fetch for %s: %s", article_url, exc)
            return None, None, "ssrf_blocked"
        except (aiohttp.ClientError, TimeoutError) as exc:
            self.logger.warning("HTTP article fetch failed for %s: %s", article_url, exc)
            attempt = await self._attempt_playwright_article_html(
                article_url, effective_cookies, source_url, browser_session=browser_session, metadata=metadata
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
        *,
        hydrate_limit_override: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not contents:
            return contents, {"attempted": 0, "hydrated": 0, "failures": {}}
        metadata = source.metadata_ or {}
        limit_default = 3 if _helpers.browser_session_auth_ready(browser_session or {}) else 8
        if hydrate_limit_override is not None:
            hydrate_limit = hydrate_limit_override
        else:
            hydrate_limit = int(metadata.get("direct_article_hydrate_limit", limit_default))
        if hydrate_limit <= 0:
            return contents, {"attempted": 0, "hydrated": 0, "failures": {}}

        existing_indexes = await asyncio.to_thread(self._known_existing_content_indexes, source, contents)
        direct_indexes = [
            i for i, item in enumerate(contents)
            if _helpers.looks_like_article_url(source.url, str(item.get("url") or ""))
            and not self._known_duplicate_external_id(source, item)
            and i not in existing_indexes
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
        paced = not meta.get("bpc_ephemeral_context") and _helpers.browser_session_auth_ready(browser_session or {})
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
        vendor_counts: Counter[str] = Counter()
        hydrated_count = 0
        fetch_profile = get_fetch_profile(source)

        for idx, result in zip(direct_indexes, html_results):
            if isinstance(result, Exception) or not result:
                failure_reasons["hydrate_exception"] += 1
                continue
            html, resolved_url, reason = result
            if not html:
                if reason:
                    failure_reasons[reason] += 1
                    self._stamp_session_health(
                        source,
                        reason=reason,
                        final_url=resolved_url or str(contents[idx].get("url") or ""),
                    )
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
            item_metadata = (
                contents[idx].get("metadata")
                if isinstance(contents[idx].get("metadata"), dict)
                else {}
            )
            html_diag = diagnose_article_html(
                html,
                resolved_url or str(contents[idx].get("url") or ""),
                fetch_profile,
            )
            if html_diag:
                item_metadata["fetch_diagnostics"] = html_diag
                for vendor in html_diag.get("paywall_vendors") or []:
                    if isinstance(vendor, dict) and vendor.get("code"):
                        vendor_counts[str(vendor["code"])] += 1
                contents[idx]["metadata"] = item_metadata
            # Let ContentProcessor extractor derive main text from article HTML.
            contents[idx].update({"html": html, "content": "", "hydrated": True})
        diag = {
            "attempted": len(direct_indexes),
            "hydrated": hydrated_count,
            "failures": dict(failure_reasons),
        }
        if vendor_counts:
            diag["paywall_vendors"] = dict(vendor_counts)
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

    @staticmethod
    def _should_retry_static_with_playwright(
        metadata: Dict[str, Any],
        failure: FetchFailure,
    ) -> bool:
        if metadata.get("playwright_auto_fallback") is False:
            return False
        return failure.code in _STATIC_TO_PLAYWRIGHT_FAILURES

    @staticmethod
    def _mark_source_needs_js(source: Source, failure: FetchFailure) -> None:
        metadata = dict(source.metadata_ or {})
        metadata["needs_js"] = True
        metadata["needs_js_reason"] = {
            "code": failure.code.value,
            "message": failure.message,
            "http_status": failure.http_status,
            "source": "static_fetch_auto_fallback",
        }
        source.metadata_ = metadata

    @staticmethod
    def _playwright_failure_message(exc: BaseException) -> str:
        raw = str(exc or "").strip() or exc.__class__.__name__
        lower = raw.lower()
        if "chromium distribution 'chrome' is not found" in lower:
            return (
                "Playwright 浏览器启动失败：当前配置要求 Google Chrome，但系统未找到 "
                "/opt/google/chrome/chrome。默认建议使用 bundled Chromium；请取消 "
                "PIM_PLAYWRIGHT_CHANNEL=chrome，或设置 PIM_PLAYWRIGHT_CHANNEL=none "
                "并重新运行 ./pim setup。原始错误："
                f"{raw}"
            )[:500]
        if "error while loading shared libraries" in lower:
            return (
                "Playwright 浏览器启动失败：Chromium 缺少系统运行库。请重新运行 ./pim setup，"
                "或按部署文档安装 Playwright/Chromium 系统依赖后重试。原始错误："
                f"{raw}"
            )[:500]
        if "no usable sandbox" in lower or "running as root without --no-sandbox" in lower:
            return (
                "Playwright 浏览器启动失败：当前 Linux/容器环境需要禁用 Chromium sandbox。"
                "请保持 PIM_PLAYWRIGHT_NO_SANDBOX=auto，或显式设置为 always 后重试。"
                "原始错误："
                f"{raw}"
            )[:500]
        return f"Playwright 浏览器启动失败：{raw}"[:500]

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

        hydrate_rss = not rss_only

        # Try RSS first.
        if rss_url:
            self.logger.info(f"Using configured RSS feed: {rss_url}")
            original_url = source.url
            rss_source = _helpers.source_with_url(source, rss_url)
            try:
                contents = await self.rss_collector.fetch(rss_source)
                contents = self._filter_unwanted_wsj_items(original_url, contents)
            except FetchFailureError as exc:
                self.logger.warning("Configured RSS fetch failed for %s: %s", rss_url, exc)
                contents = []
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
                try:
                    fallback_contents = await self.rss_collector.fetch(fallback_source)
                    fallback_contents = self._filter_unwanted_wsj_items(original_url, fallback_contents)
                except FetchFailureError as exc:
                    self.logger.warning("WSJ fallback RSS fetch failed for %s: %s", fallback_url, exc)
                    fallback_contents = []
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
            from app.domains.fetch.rss_health import persist_discovered_feed

            persist_discovered_feed(source, feed_url)
            original_url = source.url
            feed_source = _helpers.source_with_url(source, feed_url)
            try:
                contents = await self.rss_collector.fetch(feed_source)
                contents = self._filter_unwanted_wsj_items(original_url, contents)
            except FetchFailureError as exc:
                self.logger.warning("Discovered RSS fetch failed for %s: %s", feed_url, exc)
                contents = []
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

        sitemap_contents = await self._maybe_fetch_via_sitemap(source, cookies, browser_session)
        if sitemap_contents is not None:
            return sitemap_contents

        # Controlled listing-page discovery. Explicit metadata can tune or
        # disable it; otherwise a conservative default probes the source URL.
        # Runs after RSS paths are exhausted, before generic static scraping.
        discovered = await self._maybe_fetch_via_discovery(source, cookies, browser_session)
        if discovered is not None:
            return discovered

        # Check if JS rendering is needed.
        if metadata.get("needs_js", False):
            contents = await self._fetch_with_playwright(source)
            return await self._maybe_hydrate_public_listing_contents(
                source,
                contents,
                cookies,
                browser_session,
            )

        # Fall back to static scraping. For hard access-denied/login/bot-wall
        # failures, try one dynamic render immediately and persist the
        # diagnosis so later scheduled fetches go straight to Playwright.
        try:
            contents = await self._fetch_static(source)
        except FetchFailureError as exc:
            if not self._should_retry_static_with_playwright(metadata, exc.failure):
                raise
            from app.features import playwright_enabled

            if not playwright_enabled():
                raise
            self._mark_source_needs_js(source, exc.failure)
            self.logger.info(
                "Static fetch for %s failed with %s; retrying once with Playwright",
                source.url,
                exc.failure.code.value,
            )
            contents = await self._fetch_with_playwright(source, raise_on_error=True)
            if not contents:
                raise
        return await self._maybe_hydrate_public_listing_contents(
            source,
            contents,
            cookies,
            browser_session,
        )

    async def _fetch_listing_html(self, source: Source, url: str) -> Optional[str]:
        """Fetch a single listing page's raw HTML (SSRF-checked)."""
        metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        headers.update(bpc_strategies.get_spoofed_headers(metadata, headers["User-Agent"]))
        cookies = {} if metadata.get("bpc_ephemeral_context") else self.get_runtime_cookies(source)
        try:
            async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
                response = await fetch_public_http_text(
                    session,
                    url,
                    source_url=source.url,
                    validation_cookies=cookies or None,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    timeout=aiohttp.ClientTimeout(total=30),
                )
                if response.status != 200:
                    from app.domains.fetch.failures import FetchFailureError, classify_http_status

                    self.logger.warning("Discovery listing fetch non-200 (%s) for %s", response.status, url)
                    failure = classify_http_status(response.status, detail=f"Discovery listing fetch failed: {url}")
                    if failure is not None:
                        raise FetchFailureError(failure)
                    return None
                return response.text
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            self.logger.warning("Discovery listing fetch failed for %s: %s", url, exc)
            return None

    def _default_sitemap_urls(self, source: Source) -> list[str]:
        return _sitemap.default_sitemap_urls(source)

    async def _fetch_sitemap_xml(self, source: Source, url: str) -> Optional[str]:
        metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
        }
        headers.update(bpc_strategies.get_spoofed_headers(metadata, headers["User-Agent"]))
        try:
            async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
                response = await fetch_public_http_text(
                    session,
                    url,
                    source_url=source.url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                )
                if response.status != 200:
                    self.logger.debug("Sitemap fetch non-200 (%s) for %s", response.status, url)
                    return None
                return response.text
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            self.logger.debug("Sitemap fetch failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _parse_sitemap_time(value: str | None):
        return _sitemap.parse_sitemap_time(value)

    @staticmethod
    def _url_title(url: str) -> str:
        return _sitemap.url_title(url)

    def _parse_sitemap_entries(self, xml_text: str, source: Source) -> tuple[list[Dict[str, Any]], list[str]]:
        return _sitemap.parse_sitemap_entries(xml_text, source)

    async def _maybe_fetch_via_sitemap(
        self, source: Source, cookies, browser_session
    ) -> Optional[List[Dict[str, Any]]]:
        return await _sitemap.maybe_fetch_via_sitemap(
            source,
            cookies,
            browser_session,
            fetch_sitemap_xml=self._fetch_sitemap_xml,
            hydrate_public_listing=self._maybe_hydrate_public_listing_contents,
        )

    async def _maybe_fetch_via_discovery(
        self, source: Source, cookies, browser_session
    ) -> Optional[List[Dict[str, Any]]]:
        """Run controlled listing-page discovery before generic static fetch.

        Explicit per-source discovery treats an empty result as final. The
        conservative default discovery falls through to static fetch only when
        no candidates were found; if candidates were found and all rejected,
        the discovery verdict is authoritative.
        """
        from app.domains.fetch.discovery import (
            expand_listing_urls,
            filter_candidates,
            record_discovery_diagnostics,
            resolve_discovery_rules,
        )

        rules = resolve_discovery_rules(source.url, source.metadata_ or {})
        if rules is None or not rules.enabled:
            return None

        listing_page_urls = expand_listing_urls(rules)
        self.logger.info(
            "Listing discovery enabled for %s (%d listing urls, %d pages)",
            source.url,
            len(rules.listing_urls),
            len(listing_page_urls),
        )

        # Build a per-source selector override so the HTML parser honours the
        # discovery-specific selectors without mutating the real source.
        selector_overrides = {
            k: v
            for k, v in {
                "article_selector": rules.article_selector,
                "title_selector": rules.title_selector,
                "link_selector": rules.link_selector,
                "content_selector": None,
                "date_selector": rules.date_selector,
            }.items()
            if v
        }

        raw_candidates: List[Dict[str, Any]] = []
        listing_pages_fetched = 0
        for listing_url in listing_page_urls:
            html = await self._fetch_listing_html(source, listing_url)
            if not html:
                continue
            listing_pages_fetched += 1
            listing_source = _helpers.source_with_url(source, listing_url)
            if selector_overrides:
                listing_source.metadata_ = {**(source.metadata_ or {}), **selector_overrides}
            raw_candidates.extend(await asyncio.to_thread(self._parse_html, html, listing_source))

        kept, diagnostics = filter_candidates(raw_candidates, rules, source.url)
        diagnostics["listing_urls_configured"] = len(rules.listing_urls)
        diagnostics["listing_pages_total"] = len(listing_page_urls)
        diagnostics["listing_pages_fetched"] = listing_pages_fetched
        diagnostics["listing_pages_failed"] = len(listing_page_urls) - listing_pages_fetched
        diagnostics["pagination_max_pages"] = rules.pagination_max_pages
        diagnostics = record_discovery_diagnostics(source, diagnostics)
        self.logger.info("Listing discovery for %s: %s", source.url, diagnostics)

        contents: List[Dict[str, Any]] = [
            {
                "external_id": article.url,
                "title": article.title,
                "content": "",
                "url": article.url,
                "publish_time": article.publish_time,
                "metadata": {
                    "publish_time_estimated": article.publish_time is None,
                    "publish_time_raw": "",
                    "discovered_via": "listing",
                },
            }
            for article in kept
        ]
        if not contents:
            if rules.fallback_to_static_on_empty and int(diagnostics.get("total") or 0) == 0:
                return None
            return []
        return await self._maybe_hydrate_public_listing_contents(
            source, contents, cookies, browser_session
        )

    async def _fetch_static(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch static website content using aiohttp."""
        metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        headers.update(bpc_strategies.get_spoofed_headers(metadata, headers["User-Agent"]))
        cookies = {} if metadata.get("bpc_ephemeral_context") else self.get_runtime_cookies(source)

        try:
            async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
                response = await fetch_public_http_text(
                    session,
                    source.url,
                    source_url=source.url,
                    validation_cookies=cookies or None,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    timeout=aiohttp.ClientTimeout(total=30),
                )
                if response.status != 200:
                    from app.domains.fetch.failures import FetchFailureError, classify_http_status

                    self.logger.warning(f"Static fetch non-200 ({response.status}) for {source.url}")
                    failure = classify_http_status(response.status, detail=f"Static fetch failed: {source.url}")
                    if failure is not None:
                        raise FetchFailureError(failure)
                    return []
                html = response.text

            return await asyncio.to_thread(self._parse_html, html, source)

        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            from app.domains.fetch.failures import FetchFailureError, classify_exception

            self.logger.error(f"Error fetching static website: {exc}")
            raise FetchFailureError(classify_exception(exc)) from exc

    async def _fetch_with_playwright(
        self,
        source: Source,
        *,
        raise_on_error: bool = False,
    ) -> List[Dict[str, Any]]:
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
            metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
            prefs = local_playwright_fetch_prefs(metadata)
            ephemeral_context = bool(metadata.get("bpc_ephemeral_context"))
            bpc_headers = bpc_strategies.get_spoofed_headers(metadata, self.user_agents[0])
            ua = bpc_headers.pop("User-Agent", self.user_agents[0])

            runtime_session = self.get_runtime_browser_session(source)
            user_data_dir = (
                str(runtime_session.get("user_data_dir"))
                if _helpers.browser_session_auth_ready(runtime_session)
                else None
            )
            storage_state = _helpers.storage_state_path_for_playwright(runtime_session)
            if ephemeral_context:
                user_data_dir = None
                storage_state = None

            async with get_browser_context(
                headless=prefs["headless"],
                user_data_dir=user_data_dir,
                user_agent=ua,
                storage_state=storage_state,
                viewport=prefs.get("viewport"),
                locale=prefs.get("locale"),
            ) as context:
                cookies = {} if ephemeral_context else self.get_runtime_cookies(source)
                cookie_list = _helpers.build_runtime_cookie_list(source.url, cookies)
                if cookie_list:
                    await context.add_cookies(cookie_list)

                page = await context.new_page()
                extra_headers = prefs.get("extra_http_headers") or {}
                if isinstance(extra_headers, dict):
                    extra_headers = {**extra_headers, **bpc_headers}
                else:
                    extra_headers = bpc_headers
                if extra_headers:
                    await page.set_extra_http_headers(extra_headers)
                # Patchright's patched Chromium already masks the WebDriver/
                # CDP signals this script tries to override, and layering the
                # extra JS overrides on top causes Datadome-class checks to
                # flag the browser as *more* suspicious (plugin count mismatch
                # etc.). Only inject on the vanilla-playwright path.
                if not is_patchright_active():
                    await page.add_init_script(stealth_init_script())
                interceptor = bpc_strategies.get_bpc_playwright_interceptor(metadata)
                if interceptor is not None:
                    await context.route("**/*", interceptor)
                await self._playwright_goto_with_fallback(page, source.url, prefs)
                await self._playwright_after_navigation(page, prefs)

                wait_selector = metadata.get("wait_selector", "article, .post, .entry, main")

                try:
                    await page.wait_for_selector(wait_selector, timeout=10000)
                except _timeout_errs:
                    self.logger.warning(f"Selector '{wait_selector}' not found, continuing anyway")

                html = await page.content()
                return await asyncio.to_thread(self._parse_html, html, source)

        except Exception as exc:  # noqa: BLE001 - broad Playwright surface
            self.logger.error(f"Error fetching with Playwright: {exc}")
            if raise_on_error:
                raise FetchFailureError(
                    make_failure(
                        FetchFailureCode.UNKNOWN,
                        message=self._playwright_failure_message(exc),
                        retryable=False,
                        severity="error",
                    )
                ) from exc
            return []
