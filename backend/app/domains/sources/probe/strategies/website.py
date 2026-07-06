"""Website probe strategy (standalone, no mixin)."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from app.domains.sources.probe.strategies.result import ProbeResult
from app.domains.sources.probe.strategies.rss import _UNFETCHABLE, _USE_SCRAPING
from app.utils.logger import get_logger

logger = get_logger(__name__)


class WebsiteProbeStrategy:
    """Probe a generic website URL (RSS discovery → scraping fallback)."""

    def __init__(self, helpers: Any):
        self.helpers = helpers

    async def probe(self, url: str) -> ProbeResult:
        known = self.helpers._check_known_feeds(url)
        if known is not None:
            if known == _UNFETCHABLE:
                if "facebook.com" in url:
                    msg = "Facebook 个人页面不支持 RSS 或网页抓取"
                elif "theinformation.com" in url:
                    msg = "The Information 为付费订阅站，Feed 需要认证，暂不支持免费抓取"
                else:
                    msg = "该平台不支持自动抓取"
                return ProbeResult(status="error", strategy="none", message=msg)
            if known == _USE_SCRAPING:
                scrape_result = await self.helpers._test_scrape(url)
                if scrape_result.sample_count > 0:
                    return scrape_result
            else:
                result = await self.helpers._test_rss_feed(known)
                if result.status == "ok":
                    return result

        rss_url = await self.helpers._discover_rss(url)
        if rss_url:
            result = await self.helpers._test_rss_feed(rss_url)
            if result.status == "ok":
                return result

        rss_url = await self.helpers._try_common_rss_paths(url)
        if rss_url:
            result = await self.helpers._test_rss_feed(rss_url)
            if result.status == "ok":
                return result

        scrape_result = await self.helpers._test_scrape(url)
        if scrape_result.status == "ok":
            return scrape_result

        return ProbeResult(
            status="error", strategy="none",
            message="无法通过 RSS 或网页抓取获取内容，可能需要 JS 渲染或该站有反爬保护",
        )

    async def test_scrape(self, url: str) -> ProbeResult:
        try:
            html = await self.helpers._http_get(url)
            if not html:
                return ProbeResult(
                    status="error", strategy="scrape", message="网页无法访问",
                )
            soup = BeautifulSoup(html, "html.parser")
            selectors = [
                "article", ".post", ".entry", "main article",
                "[class*='article']", "[class*='post']", "[class*='story']",
                "[class*='news']", "[class*='item']", "[class*='card']",
                ".list-item", ".feed-item", ".content-item",
                "li[class]>a[href]",
            ]
            articles = []
            for sel in selectors:
                try:
                    articles = soup.select(sel)
                except (ValueError, TypeError) as exc:
                    logger.debug("BS4 select failed: %s", exc)
                    continue
                if len(articles) >= 3:
                    break

            if not articles:
                links = soup.select("a[href]")
                article_links = [
                    a for a in links
                    if a.get_text(strip=True)
                    and len(a.get_text(strip=True)) > 20
                    and a.get("href", "").startswith(("http", "/"))
                ]
                if len(article_links) >= 3:
                    return ProbeResult(
                        status="warning",
                        strategy="scrape",
                        message=f"未找到标准文章结构，但发现 {len(article_links)} 个链接可供提取",
                        sample_count=len(article_links),
                    )
                return ProbeResult(
                    status="error", strategy="scrape",
                    message="网页可访问但未找到可提取的文章内容，可能需要 JS 渲染",
                )

            return ProbeResult(
                status="ok" if len(articles) >= 3 else "warning",
                strategy="scrape",
                message=f"网页抓取可用，发现 {len(articles)} 篇文章",
                sample_count=len(articles),
            )
        except Exception as exc:  # noqa: BLE001 - BeautifulSoup / aiohttp raise mixed types
            return ProbeResult(
                status="error", strategy="scrape",
                message=f"网页抓取测试失败: {exc}",
            )
