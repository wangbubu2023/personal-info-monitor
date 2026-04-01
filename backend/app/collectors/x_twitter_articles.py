"""Article hydration helpers for X collector."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class XCollectorArticleMixin:
    """x.com/i/article helpers and Playwright hydration."""

    async def _enrich_article_content(self, contents: List[Dict[str, Any]], source) -> List[Dict[str, Any]]:
        if not contents:
            return contents

        metadata = source.metadata_ or {}
        if metadata.get("fetch_x_articles", True) is False:
            return contents

        article_limit = int(metadata.get("x_article_fetch_limit", 8))
        if article_limit <= 0:
            return contents

        article_map: Dict[str, List[int]] = {}
        for idx, item in enumerate(contents):
            item_meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            url_texts: List[str] = [
                str(item.get("title") or ""),
                str(item.get("content") or ""),
                str(item.get("url") or ""),
            ]
            for u in item_meta.get("urls") or []:
                if isinstance(u, dict):
                    url_texts.extend(
                        [
                            str(u.get("expanded_url") or ""),
                            str(u.get("display_url") or ""),
                            str(u.get("short_url") or ""),
                        ]
                    )
                elif isinstance(u, str):
                    url_texts.append(u)

            for article_url in self._extract_article_urls(" ".join(url_texts)):
                article_map.setdefault(article_url, []).append(idx)

        if not article_map:
            return contents

        target_urls = list(article_map.keys())[:article_limit]
        text_map = await self._fetch_article_texts_with_playwright(target_urls, self.get_runtime_cookies(source))

        for article_url, indexes in article_map.items():
            article_text = text_map.get(article_url)
            for idx in indexes:
                item = contents[idx]
                item_meta = item.get("metadata") or {}
                item_meta["article_url"] = article_url
                item_meta["article_fulltext"] = bool(article_text)
                item["metadata"] = item_meta
                if not article_text:
                    continue

                item_meta["article_text_chars"] = len(article_text)
                item["content"] = article_text
                item["url"] = article_url
                title = str(item.get("title") or "")
                if self._title_looks_like_url(title):
                    item["title"] = self._build_title_from_text(article_text)
        return contents

    def _extract_article_urls(self, text: str) -> List[str]:
        if not text:
            return []
        seen = set()
        urls = []
        for match in self.ARTICLE_URL_RE.finditer(text):
            candidate = (match.group(0) or "").strip()
            if not candidate:
                continue
            if not candidate.startswith("http://") and not candidate.startswith("https://"):
                candidate = f"https://{candidate}"
            if candidate.startswith("http://"):
                candidate = "https://" + candidate[len("http://"):]
            if candidate in seen:
                continue
            seen.add(candidate)
            urls.append(candidate)
        return urls

    async def _fetch_article_texts_with_playwright(
        self, article_urls: List[str], cookies: Dict[str, str]
    ) -> Dict[str, str]:
        if not article_urls:
            return {}

        try:
            from playwright.async_api import async_playwright
        except Exception as e:
            self.logger.warning(f"Playwright unavailable for X article hydration: {e}")
            return {}

        text_map: Dict[str, str] = {}
        try:
            browser, context = await self._get_shared_browser_context(p_module=None, cookies=cookies)
            try:
                for article_url in article_urls:
                    page = await context.new_page()
                    try:
                        await page.goto(article_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(4000)
                        raw = await page.evaluate(
                            """() => {
                                const articleNode = document.querySelector('article');
                                const mainNode = document.querySelector('main');
                                const articleText = articleNode && articleNode.innerText ? articleNode.innerText : '';
                                const mainText = mainNode && mainNode.innerText ? mainNode.innerText : '';
                                const bodyText = document.body && document.body.innerText ? document.body.innerText : '';
                                const candidates = [articleText, mainText, bodyText]
                                  .map((t) => (t || '').trim())
                                  .filter((t) => t.length > 0)
                                  .sort((a, b) => b.length - a.length);
                                return candidates[0] || '';
                            }"""
                        )
                        cleaned = self._clean_article_text(raw)
                        if cleaned:
                            text_map[article_url] = cleaned
                            self.logger.info(f"Hydrated X article text: {article_url} ({len(cleaned)} chars)")
                        else:
                            self.logger.info(f"X article text unavailable (likely auth-gated): {article_url}")
                    except Exception as e:
                        self.logger.warning(f"Failed to hydrate X article {article_url}: {e}")
                    finally:
                        await page.close()
            finally:
                await self._release_shared_browser()
        except Exception as e:
            self.logger.warning(f"Playwright article hydration failed: {e}")
        return text_map

    def _build_x_cookie_items(self, cookies: Dict[str, str]) -> List[Dict[str, Any]]:
        if not cookies:
            return []
        cookie_items = []
        for name, value in cookies.items():
            if not name or value is None:
                continue
            for domain in ("x.com", ".x.com"):
                cookie_items.append(
                    {
                        "name": str(name),
                        "value": str(value),
                        "domain": domain,
                        "path": "/",
                    }
                )
        return cookie_items

    _shared_browser = None
    _shared_context = None
    _shared_pw = None

    async def _get_shared_browser_context(self, p_module, cookies):
        if self._shared_browser is None:
            from playwright.async_api import async_playwright

            self.__class__._shared_pw = await async_playwright().__aenter__()
            self.__class__._shared_browser = await self._shared_pw.chromium.launch(headless=True)
            self.__class__._shared_context = await self._shared_browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            )
            cookie_items = self._build_x_cookie_items(cookies)
            if cookie_items:
                await self._shared_context.add_cookies(cookie_items)
        return self._shared_browser, self._shared_context

    async def _release_shared_browser(self):
        if self._shared_context:
            try:
                await self._shared_context.close()
            except Exception as exc:
                self.logger.debug("Failed to close shared Playwright context: %s", exc)
            self.__class__._shared_context = None
        if self._shared_browser:
            try:
                await self._shared_browser.close()
            except Exception as exc:
                self.logger.debug("Failed to close shared Playwright browser: %s", exc)
            self.__class__._shared_browser = None
        if self._shared_pw:
            try:
                await self._shared_pw.__aexit__(None, None, None)
            except Exception as exc:
                self.logger.debug("Failed to exit shared Playwright runtime: %s", exc)
            self.__class__._shared_pw = None

    def _clean_article_text(self, text: str) -> Optional[str]:
        if not text:
            return None

        cleaned = re.sub(r"\r\n?", "\n", text).strip()
        if not cleaned:
            return None

        deny_markers = [
            "This page is not supported.",
            "Something went wrong. Try reloading.",
            "People on X are the first to know.",
            "New to X?",
        ]
        if any(marker in cleaned for marker in deny_markers):
            return None

        lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
        if not lines:
            return None

        skip_exact = {
            "Log in",
            "Sign up",
            "Retry",
            "Posts",
            "Replies",
            "Highlights",
            "Articles",
            "Media",
            "Terms of Service",
            "Privacy Policy",
            "Cookie Policy",
            "Accessibility",
            "Ads info",
            "More",
            "查看键盘快捷键",
            "要查看键盘快捷键，按下问号",
            "键盘快捷键",
            "键盘快捷方式",
            "文章",
            "加入",
            "注册",
            "探索",
            "通知",
            "消息",
        }
        filtered = []
        for line in lines:
            if line in skip_exact or line.startswith("@"):
                continue
            if re.fullmatch(r"[·•\-\s]+", line):
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿|k|K|m|M|千)?", line):
                continue
            if re.fullmatch(r"\d+\s*(?:秒|分钟|小时|天|周|月|年)", line):
                continue
            if re.fullmatch(r"\d+月\d+日", line):
                continue
            if line.startswith("© ") and "X Corp" in line:
                continue
            filtered.append(line)

        result = "\n".join(filtered).strip()
        return result if len(result) >= 280 else None

    def _title_looks_like_url(self, title: str) -> bool:
        if not title:
            return True
        title = title.strip().lower()
        return title.startswith("http://") or title.startswith("https://")

    def _build_title_from_text(self, text: str) -> str:
        if not text:
            return "X 长文"
        for raw in text.splitlines():
            first_line = (raw or "").strip()
            if not first_line or first_line.startswith("@"):
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿|k|K|m|M|千)?", first_line):
                continue
            if len(first_line) < 8:
                continue
            return first_line[:80] + ("..." if len(first_line) > 80 else "")
        fallback = text.strip()[:80]
        return fallback + ("..." if len(text.strip()) > 80 else "")
