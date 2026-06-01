"""Tests for app.collectors.website — WebsiteCollector helpers."""

from __future__ import annotations

from copy import copy
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.collectors.website import WebsiteCollector
from app.utils.datetime import utcnow_naive


def _make_source(**overrides) -> MagicMock:
    source = MagicMock()
    source.url = overrides.get("url", "https://example.com")
    source.name = overrides.get("name", "Test Source")
    source.metadata_ = overrides.get("metadata_", {})
    source._runtime_auth = overrides.get("_runtime_auth", None)
    return source


# ---------------------------------------------------------------------------
# _is_google_news_wrapper
# ---------------------------------------------------------------------------

class TestIsGoogleNewsWrapper:

    def test_google_news_rss_article(self):
        url = "https://news.google.com/rss/articles/CBMiZmh0..."
        assert WebsiteCollector._is_google_news_wrapper(url) is True

    def test_normal_url(self):
        assert WebsiteCollector._is_google_news_wrapper("https://example.com/article/1") is False

    def test_google_news_non_article(self):
        assert WebsiteCollector._is_google_news_wrapper("https://news.google.com/home") is False

    def test_empty_string(self):
        assert WebsiteCollector._is_google_news_wrapper("") is False

    def test_malformed_url(self):
        assert WebsiteCollector._is_google_news_wrapper("not a url at all") is False


# ---------------------------------------------------------------------------
# _has_browser_session
# ---------------------------------------------------------------------------

class TestHasBrowserSession:

    def test_with_user_data_dir(self):
        assert WebsiteCollector._has_browser_session({"user_data_dir": "/tmp/profile"}) is True

    def test_empty_user_data_dir(self):
        assert WebsiteCollector._has_browser_session({"user_data_dir": ""}) is False

    def test_whitespace_only(self):
        assert WebsiteCollector._has_browser_session({"user_data_dir": "   "}) is False

    def test_none_dict(self):
        assert WebsiteCollector._has_browser_session(None) is False

    def test_empty_dict(self):
        assert WebsiteCollector._has_browser_session({}) is False

    def test_missing_key(self):
        assert WebsiteCollector._has_browser_session({"other": "value"}) is False


class TestBrowserSessionAuthReady:

    def test_legacy_payload_without_auth_ready_is_usable(self):
        assert WebsiteCollector._browser_session_auth_ready({"user_data_dir": "/tmp/profile"}) is True

    def test_explicit_stale_session_is_not_usable(self):
        assert WebsiteCollector._browser_session_auth_ready(
            {"user_data_dir": "/tmp/profile", "auth_ready": False}
        ) is False


# ---------------------------------------------------------------------------
# _storage_state_path_for_playwright
# ---------------------------------------------------------------------------


class TestStorageStatePathForPlaywright:

    def test_none_session(self):
        assert WebsiteCollector._storage_state_path_for_playwright(None) is None

    def test_skipped_when_persistent_profile(self, tmp_path):
        f = tmp_path / "state.json"
        f.write_text("{}")
        assert (
            WebsiteCollector._storage_state_path_for_playwright(
                {"user_data_dir": str(tmp_path / "prof"), "storage_state_path": str(f)}
            )
            is None
        )

    def test_returns_resolved_path_when_file_exists(self, tmp_path):
        f = tmp_path / "storage_state.json"
        f.write_text("{}")
        out = WebsiteCollector._storage_state_path_for_playwright({"storage_state_path": str(f)})
        assert out == str(f.resolve())

    def test_missing_file(self, tmp_path):
        assert WebsiteCollector._storage_state_path_for_playwright(
            {"storage_state_path": str(tmp_path / "nope.json")}
        ) is None

    def test_skipped_when_auth_not_ready(self, tmp_path):
        f = tmp_path / "storage_state.json"
        f.write_text("{}")
        assert WebsiteCollector._storage_state_path_for_playwright(
            {"storage_state_path": str(f), "auth_ready": False}
        ) is None


# ---------------------------------------------------------------------------
# _same_site
# ---------------------------------------------------------------------------

class TestSameSite:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_same_domain(self):
        assert self.collector._same_site("https://example.com", "https://example.com/page") is True

    def test_subdomain_match(self):
        assert self.collector._same_site("https://example.com", "https://blog.example.com/post") is True

    def test_different_domain(self):
        assert self.collector._same_site("https://example.com", "https://other.com/page") is False

    def test_www_prefix_stripped(self):
        assert self.collector._same_site("https://www.example.com", "https://example.com/page") is True

    def test_empty_source_url(self):
        assert self.collector._same_site("", "https://example.com/page") is False

    def test_empty_candidate_url(self):
        assert self.collector._same_site("https://example.com", "") is False


# ---------------------------------------------------------------------------
# _looks_like_article_url
# ---------------------------------------------------------------------------

class TestLooksLikeArticleUrl:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_article_slug(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/news/2024/big-story-here"
        ) is True

    def test_root_url_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/"
        ) is False

    def test_video_path_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/video/123"
        ) is False

    def test_login_path_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/login"
        ) is False

    def test_subscribe_path_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/subscribe"
        ) is False

    def test_different_domain_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://other.com/news/article-slug"
        ) is False

    def test_google_news_wrapper_accepted(self):
        with patch.object(self.collector, "_is_google_news_wrapper", return_value=True):
            assert self.collector._looks_like_article_url(
                "https://example.com", "https://news.google.com/rss/articles/xxx"
            ) is True

    def test_single_segment_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/about"
        ) is False

    def test_plain_word_tail_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/section/subsection"
        ) is False

    def test_slug_with_dash_accepted(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/blog/my-great-post"
        ) is True

    def test_topics_path_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/topics/tech"
        ) is False

    def test_bbc_zhongwen_simp_accepted(self):
        assert self.collector._looks_like_article_url(
            "https://www.bbc.com/zhongwen/simp",
            "https://www.bbc.com/zhongwen/articles/c0jz3ej8d3do/simp",
        ) is True

    def test_bbc_zhongwen_trad_accepted(self):
        assert self.collector._looks_like_article_url(
            "https://www.bbc.com/zhongwen/trad",
            "https://www.bbc.com/zhongwen/articles/c0jz3ej8d3do/trad",
        ) is True

    def test_article_hub_without_locale_tail_accepted(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/articles/story-123"
        ) is True

    def test_article_hub_section_page_rejected(self):
        assert self.collector._looks_like_article_url(
            "https://example.com", "https://example.com/articles/latest"
        ) is False


# ---------------------------------------------------------------------------
# _cookie_items_for_hosts
# ---------------------------------------------------------------------------

class TestCookieItemsForHosts:

    def test_single_host(self):
        items = WebsiteCollector._cookie_items_for_hosts({"example.com"}, {"session": "abc"})
        assert len(items) >= 1
        assert all(item["name"] == "session" for item in items)
        assert all(item["value"] == "abc" for item in items)

    def test_empty_cookies(self):
        items = WebsiteCollector._cookie_items_for_hosts({"example.com"}, {})
        assert items == []

    def test_empty_hosts(self):
        items = WebsiteCollector._cookie_items_for_hosts(set(), {"session": "abc"})
        assert items == []

    def test_none_value_skipped(self):
        items = WebsiteCollector._cookie_items_for_hosts({"example.com"}, {"a": None, "b": "val"})
        assert all(item["name"] != "a" for item in items)

    def test_empty_name_skipped(self):
        items = WebsiteCollector._cookie_items_for_hosts({"example.com"}, {"": "val", "b": "val"})
        assert all(item["name"] != "" for item in items)


# ---------------------------------------------------------------------------
# _build_runtime_cookie_list
# ---------------------------------------------------------------------------

class TestBuildRuntimeCookieList:

    def test_builds_cookies_for_source_host(self):
        items = WebsiteCollector._build_runtime_cookie_list(
            "https://example.com/page", {"sid": "xyz"}
        )
        assert len(items) >= 1
        assert items[0]["name"] == "sid"

    def test_empty_url(self):
        items = WebsiteCollector._build_runtime_cookie_list("", {"sid": "xyz"})
        assert items == []


# ---------------------------------------------------------------------------
# _wsj_fallback_rss
# ---------------------------------------------------------------------------

class TestWsjFallbackRss:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_wsj_url(self):
        result = self.collector._wsj_fallback_rss("https://www.wsj.com/news")
        assert result is not None
        assert "news.google.com" in result

    def test_non_wsj_url(self):
        result = self.collector._wsj_fallback_rss("https://www.nytimes.com")
        assert result is None


# ---------------------------------------------------------------------------
# _economist_fallback_rss
# ---------------------------------------------------------------------------

class TestEconomistFallbackRss:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_root_url(self):
        result = self.collector._economist_fallback_rss("https://www.economist.com")
        assert result is not None
        assert "international" in result

    def test_china_section(self):
        result = self.collector._economist_fallback_rss("https://www.economist.com/china")
        assert result is not None
        assert "china" in result

    def test_business_section(self):
        result = self.collector._economist_fallback_rss("https://www.economist.com/business")
        assert result is not None
        assert "business" in result

    def test_non_economist_url(self):
        result = self.collector._economist_fallback_rss("https://www.bbc.com")
        assert result is None

    def test_topics_path(self):
        result = self.collector._economist_fallback_rss("https://www.economist.com/topics/china")
        assert result is not None


# ---------------------------------------------------------------------------
# _filter_unwanted_wsj_items
# ---------------------------------------------------------------------------

class TestFilterUnwantedWsjItems:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_non_wsj_returns_unchanged(self):
        items = [{"title": "Print Edition: May"}]
        result = self.collector._filter_unwanted_wsj_items("https://nytimes.com", items)
        assert result == items

    def test_wsj_filters_print_edition(self):
        items = [
            {"title": "Print Edition: Weekly"},
            {"title": "Markets Rally on Tech Gains"},
        ]
        result = self.collector._filter_unwanted_wsj_items("https://www.wsj.com", items)
        assert len(result) == 1
        assert result[0]["title"] == "Markets Rally on Tech Gains"

    def test_empty_list(self):
        assert self.collector._filter_unwanted_wsj_items("https://www.wsj.com", []) == []


# ---------------------------------------------------------------------------
# _is_stale_rss_content
# ---------------------------------------------------------------------------

class TestIsStaleRssContent:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_fresh_content(self):
        items = [{"publish_time": utcnow_naive()}]
        assert self.collector._is_stale_rss_content(items) is False

    def test_stale_content(self):
        old = utcnow_naive() - timedelta(days=5)
        items = [{"publish_time": old}]
        assert self.collector._is_stale_rss_content(items) is True

    def test_no_publish_times(self):
        items = [{"title": "No time"}]
        assert self.collector._is_stale_rss_content(items) is True

    def test_empty_list(self):
        assert self.collector._is_stale_rss_content([]) is True

    def test_mixed_times(self):
        items = [
            {"publish_time": utcnow_naive() - timedelta(days=5)},
            {"publish_time": utcnow_naive()},
        ]
        assert self.collector._is_stale_rss_content(items) is False


# ---------------------------------------------------------------------------
# _source_with_url
# ---------------------------------------------------------------------------

class TestSourceWithUrl:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_returns_copy_with_new_url(self):
        source = _make_source(url="https://old.com")
        cloned = self.collector._source_with_url(source, "https://new.com/feed")
        assert cloned.url == "https://new.com/feed"
        assert source.url == "https://old.com"


# ---------------------------------------------------------------------------
# _prefer_direct_article_links
# ---------------------------------------------------------------------------

class TestPreferDirectArticleLinks:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_filters_non_article_links(self):
        source = _make_source(url="https://example.com")
        contents = [
            {"url": "https://example.com/news/article-slug"},
            {"url": "https://example.com/"},
            {"url": "https://other.com/page"},
        ]
        with patch.object(self.collector, "_looks_like_article_url", side_effect=[True, False, False]):
            result = self.collector._prefer_direct_article_links(source, contents)
            assert len(result) == 1

    def test_empty_contents(self):
        source = _make_source()
        assert self.collector._prefer_direct_article_links(source, []) == []


# ---------------------------------------------------------------------------
# _append_fallback_links
# ---------------------------------------------------------------------------

class TestAppendFallbackLinks:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_does_not_add_if_enough_content(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        contents = [{"url": f"https://example.com/a{i}"} for i in range(5)]
        soup = BeautifulSoup("<html><a href='/extra-page'>Extra Article Link Here</a></html>", "html.parser")
        self.collector._append_fallback_links(soup=soup, source=source, contents=contents)
        assert len(contents) == 5

    def test_adds_fallback_links(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        contents = []
        links = "".join(
            f'<a href="/news/article-{i}">This is article number {i} title</a>' for i in range(3)
        )
        soup = BeautifulSoup(f"<html>{links}</html>", "html.parser")
        with patch.object(self.collector, "_looks_like_article_url", return_value=True):
            self.collector._append_fallback_links(soup=soup, source=source, contents=contents)
            assert len(contents) >= 1

    def test_skips_short_titles(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        contents = []
        soup = BeautifulSoup('<html><a href="/page">Hi</a></html>', "html.parser")
        self.collector._append_fallback_links(soup=soup, source=source, contents=contents)
        assert len(contents) == 0

    def test_deduplicates_urls(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        contents = [{"url": "https://example.com/news/article-0"}]
        links = '<a href="/news/article-0">This is article number 0 title</a>'
        soup = BeautifulSoup(f"<html>{links}</html>", "html.parser")
        with patch.object(self.collector, "_looks_like_article_url", return_value=True):
            self.collector._append_fallback_links(soup=soup, source=source, contents=contents)
            urls = [c.get("url") for c in contents]
            assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# _close_browser_resources
# ---------------------------------------------------------------------------

class TestCloseBrowserResources:

    @pytest.mark.asyncio
    async def test_close_both(self):
        collector = WebsiteCollector()
        context = AsyncMock()
        browser = AsyncMock()
        await collector._close_browser_resources(
            context=context, browser=browser,
            target_url="https://example.com",
            context_label="ctx", browser_label="brw",
        )
        context.close.assert_called_once()
        browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_close_exceptions(self):
        collector = WebsiteCollector()
        context = AsyncMock()
        context.close = AsyncMock(side_effect=Exception("close error"))
        browser = AsyncMock()
        browser.close = AsyncMock(side_effect=Exception("close error"))
        await collector._close_browser_resources(
            context=context, browser=browser,
            target_url="https://example.com",
            context_label="ctx", browser_label="brw",
        )

    @pytest.mark.asyncio
    async def test_none_context_and_browser(self):
        collector = WebsiteCollector()
        await collector._close_browser_resources(
            context=None, browser=None,
            target_url="https://example.com",
            context_label="ctx", browser_label="brw",
        )


# ---------------------------------------------------------------------------
# _try_playwright_fetch
# ---------------------------------------------------------------------------

class TestTryPlaywrightFetch:

    @pytest.mark.asyncio
    async def test_skipped_when_no_auth(self):
        collector = WebsiteCollector()
        with patch.object(collector, "_attempt_playwright_article_html", new_callable=AsyncMock, return_value=None):
            result = await collector._try_playwright_fetch(
                "https://example.com/page", {}, "https://example.com"
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_html_on_success(self):
        collector = WebsiteCollector()
        with patch.object(
            collector, "_attempt_playwright_article_html",
            new_callable=AsyncMock,
            return_value=("<html>content</html>", "https://example.com/page", None),
        ):
            result = await collector._try_playwright_fetch(
                "https://example.com/page", {"session": "abc"}, "https://example.com"
            )
            assert result is not None
            assert result[0] == "<html>content</html>"

    @pytest.mark.asyncio
    async def test_returns_none_on_html_none(self):
        collector = WebsiteCollector()
        with patch.object(
            collector, "_attempt_playwright_article_html",
            new_callable=AsyncMock,
            return_value=(None, "https://example.com/page", "shell_page"),
        ):
            result = await collector._try_playwright_fetch(
                "https://example.com/page", {"session": "abc"}, "https://example.com"
            )
            assert result is None


# ---------------------------------------------------------------------------
# _parse_html
# ---------------------------------------------------------------------------

class TestParseHtml:

    def test_extracts_articles(self):
        collector = WebsiteCollector()
        source = _make_source(url="https://example.com")
        html = """<html><body>
        <article>
            <h2><a href="/news/story-one">Big Story One Here</a></h2>
            <p>Summary text for article one</p>
        </article>
        <article>
            <h2><a href="/news/story-two">Big Story Two Here</a></h2>
            <p>Summary text for article two</p>
        </article>
        </body></html>"""
        with patch("app.domains.fetch.collectors.website_parser.get_website_content_reject_reason", return_value=None):
            results = collector._parse_html(html, source)
            assert len(results) >= 1

    def test_empty_html_returns_empty(self):
        collector = WebsiteCollector()
        source = _make_source(url="https://example.com")
        results = collector._parse_html("<html><body></body></html>", source)
        assert results == []

    def test_custom_selectors_from_metadata(self):
        collector = WebsiteCollector()
        source = _make_source(
            url="https://example.com",
            metadata_={"article_selector": ".custom-article"},
        )
        html = """<html><body>
        <div class="custom-article">
            <h2><a href="/custom/article-slug">Custom Article Title Here</a></h2>
            <p>Custom content</p>
        </div>
        </body></html>"""
        with patch("app.domains.fetch.collectors.website_parser.get_website_content_reject_reason", return_value=None):
            results = collector._parse_html(html, source)
            assert len(results) >= 1


# ---------------------------------------------------------------------------
# _parse_article_candidate
# ---------------------------------------------------------------------------

class TestParseArticleCandidate:

    def setup_method(self):
        self.collector = WebsiteCollector()

    def test_valid_article(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        html = '<div><h2><a href="/news/slug">Title</a></h2><p>Content</p></div>'
        article = BeautifulSoup(html, "html.parser").div
        with patch("app.domains.fetch.collectors.website_parser.get_website_content_reject_reason", return_value=None):
            result = self.collector._parse_article_candidate(
                article, source=source,
                title_selector="h2", link_selector="a",
                content_selector="p", date_selector="time",
            )
            assert result is not None
            assert result["title"] == "Title"
            assert "example.com" in result["url"]

    def test_missing_title_returns_none(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        html = '<div><a href="/news/slug">link</a><p>Content</p></div>'
        article = BeautifulSoup(html, "html.parser").div
        result = self.collector._parse_article_candidate(
            article, source=source,
            title_selector="h2", link_selector="a",
            content_selector="p", date_selector="time",
        )
        assert result is None

    def test_missing_link_returns_none(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        html = '<div><h2>Title</h2><p>Content</p></div>'
        article = BeautifulSoup(html, "html.parser").div
        result = self.collector._parse_article_candidate(
            article, source=source,
            title_selector="h2", link_selector="a",
            content_selector="p", date_selector="time",
        )
        assert result is None

    def test_relative_url_resolved(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        html = '<div><h2><a href="/post/my-article">Title</a></h2></div>'
        article = BeautifulSoup(html, "html.parser").div
        with patch("app.domains.fetch.collectors.website_parser.get_website_content_reject_reason", return_value=None):
            result = self.collector._parse_article_candidate(
                article, source=source,
                title_selector="h2", link_selector="a",
                content_selector="p", date_selector="time",
            )
            assert result["url"].startswith("https://example.com")

    def test_rejected_content_returns_none(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        html = '<div><h2><a href="/news/slug">Title</a></h2><p>Content</p></div>'
        article = BeautifulSoup(html, "html.parser").div
        with patch("app.domains.fetch.collectors.website_parser.get_website_content_reject_reason", return_value="too_short"):
            result = self.collector._parse_article_candidate(
                article, source=source,
                title_selector="h2", link_selector="a",
                content_selector="p", date_selector="time",
            )
            assert result is None

    def test_datetime_attr_parsed(self):
        from bs4 import BeautifulSoup
        source = _make_source(url="https://example.com")
        html = '<div><h2><a href="/news/slug">Title</a></h2><time datetime="2025-01-15T10:00:00Z">Jan 15</time></div>'
        article = BeautifulSoup(html, "html.parser").div
        with patch("app.domains.fetch.collectors.website_parser.get_website_content_reject_reason", return_value=None):
            result = self.collector._parse_article_candidate(
                article, source=source,
                title_selector="h2", link_selector="a",
                content_selector="p", date_selector="time",
            )
            assert result is not None
            assert result["publish_time"] is not None


# ---------------------------------------------------------------------------
# _attempt_playwright_article_html
# ---------------------------------------------------------------------------

class TestAttemptPlaywrightArticleHtml:

    @pytest.mark.asyncio
    async def test_skipped_without_auth(self):
        collector = WebsiteCollector()
        result = await collector._attempt_playwright_article_html(
            "https://example.com/page", {}, "https://example.com", browser_session={}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_runs_with_cookies(self):
        collector = WebsiteCollector()
        with patch.object(
            collector, "_fetch_article_html_with_playwright",
            new_callable=AsyncMock,
            return_value=("<html>ok</html>", "https://example.com/page", None),
        ):
            result = await collector._attempt_playwright_article_html(
                "https://example.com/page", {"session": "abc"}, "https://example.com"
            )
            assert result is not None
            assert result[0] == "<html>ok</html>"

    @pytest.mark.asyncio
    async def test_runs_with_browser_session(self):
        collector = WebsiteCollector()
        with patch.object(
            collector, "_fetch_article_html_with_playwright",
            new_callable=AsyncMock,
            return_value=("<html>ok</html>", "https://example.com/page", None),
        ):
            result = await collector._attempt_playwright_article_html(
                "https://example.com/page", {}, "https://example.com",
                browser_session={"user_data_dir": "/tmp/profile"},
            )
            assert result is not None

    @pytest.mark.asyncio
    async def test_skips_stale_browser_session_without_cookies(self):
        collector = WebsiteCollector()
        fetch_mock = AsyncMock(return_value=("<html>ok</html>", "https://example.com/page", None))
        with patch.object(
            collector,
            "_fetch_article_html_with_playwright",
            fetch_mock,
        ):
            result = await collector._attempt_playwright_article_html(
                "https://example.com/page", {}, "https://example.com",
                browser_session={"user_data_dir": "/tmp/profile", "auth_ready": False},
            )
        assert result is None
        fetch_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# _hydrate_direct_articles — paced vs parallel dispatch
# ---------------------------------------------------------------------------

class TestHydrateDirectArticlesPacing:
    """The hydration loop must serialize + insert anti-bot pauses when a
    browser session is present (paywall case), but stay fast/parallel when
    it isn't (public sites). Verifies the burst-suppression heuristic that
    lets logged-in fetches survive NYT/WSJ bot detectors."""

    def _build_contents(self, n: int = 3) -> List[Dict[str, Any]]:
        return [
            {"url": f"https://example.com/article-{i}", "title": f"A{i}"}
            for i in range(n)
        ]

    @pytest.mark.asyncio
    async def test_browser_session_paces_articles_sequentially(self):
        collector = WebsiteCollector()
        source = _make_source(metadata_={"direct_article_hydrate_limit": 5})
        contents = self._build_contents(3)

        call_order: List[str] = []
        pause_calls: List[tuple[int, int]] = []

        async def fake_fetch(url, *args, **kwargs):
            call_order.append(f"start:{url}")
            # Give the event loop a chance — if two fetches were running
            # truly in parallel this interleave would produce
            # start,start,end,end instead of start,end,start,end.
            import asyncio
            await asyncio.sleep(0)
            call_order.append(f"end:{url}")
            return ("<html>ok</html>", url, None)

        async def fake_pause(*, min_ms: int, max_ms: int) -> None:
            pause_calls.append((min_ms, max_ms))

        with patch.object(collector, "_fetch_article_html", side_effect=fake_fetch), \
             patch.object(
                 collector.__module__ and
                 __import__("app.domains.fetch.collectors.website", fromlist=["_helpers"])._helpers,
                 "looks_like_article_url",
                 return_value=True,
             ), \
             patch("app.domains.fetch.collectors.website.human_inter_request_pause", side_effect=fake_pause):
            hydrated, diag = await collector._hydrate_direct_articles(
                source,
                contents,
                cookies={},
                browser_session={"user_data_dir": "/tmp/profile", "id": "x"},
            )

        assert diag["attempted"] == 3
        assert diag["hydrated"] == 3
        # Strictly serial: each article's end occurs before the next start.
        for i in range(len(contents)):
            assert call_order[i * 2] == f"start:https://example.com/article-{i}"
            assert call_order[i * 2 + 1] == f"end:https://example.com/article-{i}"
        # n-1 pauses between n articles.
        assert len(pause_calls) == len(contents) - 1
        for lo, hi in pause_calls:
            assert lo >= 500 and hi <= 5000 and lo < hi

    @pytest.mark.asyncio
    async def test_browser_session_default_hydrate_limit_is_three(self):
        collector = WebsiteCollector()
        source = _make_source(metadata_={})
        contents = self._build_contents(5)

        async def fake_fetch(url, *args, **kwargs):
            return ("<html>ok</html>", url, None)

        with patch.object(collector, "_fetch_article_html", side_effect=fake_fetch), \
             patch.object(
                 __import__("app.domains.fetch.collectors.website", fromlist=["_helpers"])._helpers,
                 "looks_like_article_url",
                 return_value=True,
             ), \
             patch("app.domains.fetch.collectors.website.human_inter_request_pause", new_callable=AsyncMock):
            _hydrated, diag = await collector._hydrate_direct_articles(
                source,
                contents,
                cookies={},
                browser_session={"user_data_dir": "/tmp/profile", "auth_ready": True},
            )

        assert diag["attempted"] == 3

    @pytest.mark.asyncio
    async def test_stale_browser_session_keeps_parallel_dispatch(self):
        """A profile with auth_ready=false is treated like no usable auth
        session, so stale paywall profiles do not put the collector on the
        slow persistent-Chrome pacing path."""
        collector = WebsiteCollector()
        source = _make_source(metadata_={"direct_article_hydrate_limit": 5})
        contents = self._build_contents(3)

        active = {"count": 0, "max_concurrent": 0}

        async def fake_fetch(url, *args, **kwargs):
            import asyncio
            active["count"] += 1
            active["max_concurrent"] = max(active["max_concurrent"], active["count"])
            await asyncio.sleep(0.01)
            active["count"] -= 1
            return ("<html>ok</html>", url, None)

        with patch.object(collector, "_fetch_article_html", side_effect=fake_fetch), \
             patch.object(
                 __import__("app.domains.fetch.collectors.website", fromlist=["_helpers"])._helpers,
                 "looks_like_article_url",
                 return_value=True,
             ), \
             patch("app.domains.fetch.collectors.website.human_inter_request_pause", new_callable=AsyncMock) as pause_mock:
            _hydrated, diag = await collector._hydrate_direct_articles(
                source,
                contents,
                cookies={},
                browser_session={"user_data_dir": "/tmp/profile", "auth_ready": False},
            )

        assert diag["hydrated"] == 3
        assert active["max_concurrent"] >= 2
        pause_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_browser_session_keeps_parallel_dispatch(self):
        """Public sources (no auth session) should keep the fast
        asyncio.gather path to preserve throughput; adding paced-sleep
        here would regress fetch latency for the 90% common case."""
        collector = WebsiteCollector()
        source = _make_source(metadata_={"direct_article_hydrate_limit": 5})
        contents = self._build_contents(3)

        active = {"count": 0, "max_concurrent": 0}

        async def fake_fetch(url, *args, **kwargs):
            import asyncio
            active["count"] += 1
            active["max_concurrent"] = max(active["max_concurrent"], active["count"])
            await asyncio.sleep(0.01)
            active["count"] -= 1
            return ("<html>ok</html>", url, None)

        pause_calls: List[tuple] = []

        async def fake_pause(**_kw) -> None:
            pause_calls.append(("pause",))

        with patch.object(collector, "_fetch_article_html", side_effect=fake_fetch), \
             patch.object(
                 __import__("app.domains.fetch.collectors.website", fromlist=["_helpers"])._helpers,
                 "looks_like_article_url",
                 return_value=True,
             ), \
             patch("app.domains.fetch.collectors.website.human_inter_request_pause", side_effect=fake_pause):
            hydrated, diag = await collector._hydrate_direct_articles(
                source,
                contents,
                cookies={},
                browser_session=None,
            )

        assert diag["hydrated"] == 3
        # Parallel gather lets at least 2 fetches overlap.
        assert active["max_concurrent"] >= 2
        # Non-paced branch must not call inter-request pause.
        assert not pause_calls

    @pytest.mark.asyncio
    async def test_hydrated_articles_record_fetch_diagnostics(self):
        collector = WebsiteCollector()
        source = _make_source(
            url="https://www.reuters.com",
            metadata_={"direct_article_hydrate_limit": 1},
        )
        contents = [{"url": "https://www.reuters.com/world/story-1", "title": "Story"}]

        html = '<html><script src="https://www.reuters.com/arc/subs/p.min.js"></script><article><p>Body</p></article></html>'

        async def fake_fetch(url, *args, **kwargs):  # noqa: ARG001
            return (html, url, None)

        with patch.object(collector, "_fetch_article_html", side_effect=fake_fetch), \
             patch.object(
                 __import__("app.domains.fetch.collectors.website", fromlist=["_helpers"])._helpers,
                 "looks_like_article_url",
                 return_value=True,
             ):
            hydrated, diag = await collector._hydrate_direct_articles(
                source,
                contents,
                cookies={},
                browser_session=None,
            )

        item_diag = hydrated[0]["metadata"]["fetch_diagnostics"]
        assert item_diag["paywall_vendors"] == [{"code": "arcxp", "label": "Arc XP subscriptions"}]
        assert item_diag["profile_known_paywall_vendors"] == ["arcxp"]
        assert diag["paywall_vendors"] == {"arcxp": 1}


# ---------------------------------------------------------------------------
# rss_only metadata flag — skip Playwright hydration, return RSS summaries
# ---------------------------------------------------------------------------


class TestRssOnlyMode:
    """``source.metadata.rss_only = True`` tells the collector to give up on
    full-text hydration and just surface whatever the RSS feed yields. This
    is the operator's escape hatch when DataDome/Cloudflare permanently block
    Playwright for a given domain."""

    def _rss_items(self) -> List[Dict[str, Any]]:
        # ``publish_time`` must be recent — ``is_stale_rss_content`` treats
        # any feed whose newest item is >3 days old (or missing) as stale and
        # the collector then falls through to the wsj/fallback/discovery
        # branches, masking the behavior we want to verify.
        now = utcnow_naive()
        return [
            {"url": "https://example.com/a", "title": "A", "content": "summary A", "publish_time": now},
            {"url": "https://example.com/b", "title": "B", "content": "summary B", "publish_time": now},
        ]

    @pytest.mark.asyncio
    async def test_rss_only_skips_direct_article_hydration(self):
        """Even with cookies + a browser session on the source, rss_only must
        short-circuit the authenticated direct-article path and take the RSS
        branch instead. Protects users who explicitly opted out of Playwright
        hydration from having their choice silently overridden."""
        collector = WebsiteCollector()
        source = _make_source(
            url="https://paywalled.example.com",
            metadata_={"rss_only": True, "rss_url": "https://paywalled.example.com/feed"},
        )
        items = self._rss_items()

        direct_mock = AsyncMock(return_value=[{"url": "hydrated"}])
        rss_mock = AsyncMock(return_value=list(items))
        hydrate_rss_mock = AsyncMock(return_value=[{"url": "would-be-hydrated"}])

        with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
             patch.object(collector, "get_runtime_auth", return_value=None), \
             patch.object(collector, "get_runtime_cookies", return_value={"session": "abc"}), \
             patch.object(
                 collector, "get_runtime_browser_session",
                 return_value={"user_data_dir": "/tmp/profile", "id": "x"},
             ), \
             patch.object(
                 collector, "_fetch_authenticated_direct_articles",
                 new=direct_mock,
             ), \
             patch.object(collector.rss_collector, "fetch", new=rss_mock), \
             patch.object(
                 collector, "_maybe_hydrate_rss_contents",
                 new=hydrate_rss_mock,
             ):
            result = await collector.fetch(source)

        # RSS items are returned verbatim, no hydration passes ran.
        assert [c["url"] for c in result] == ["https://example.com/a", "https://example.com/b"]
        direct_mock.assert_not_awaited()
        hydrate_rss_mock.assert_not_awaited()
        rss_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rss_hydrates_without_auth_when_rss_only_off(self):
        """RSS batches should hydrate article HTML even without cookies/session."""
        collector = WebsiteCollector()
        source = _make_source(
            url="https://open.example.com",
            metadata_={"rss_url": "https://open.example.com/feed"},
        )
        items = self._rss_items()

        rss_mock = AsyncMock(return_value=list(items))
        hydrate_rss_mock = AsyncMock(return_value=[{"url": "hydrated", "content": "full"}])

        with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
             patch.object(collector, "get_runtime_auth", return_value=None), \
             patch.object(collector, "get_runtime_cookies", return_value={}), \
             patch.object(collector, "get_runtime_browser_session", return_value=None), \
             patch.object(
                 collector, "_fetch_authenticated_direct_articles",
                 new=AsyncMock(return_value=None),
             ), \
             patch.object(collector.rss_collector, "fetch", new=rss_mock), \
             patch.object(
                 collector, "_maybe_hydrate_rss_contents",
                 new=hydrate_rss_mock,
             ):
            result = await collector.fetch(source)

        hydrate_rss_mock.assert_awaited_once()
        assert result == [{"url": "hydrated", "content": "full"}]

    @pytest.mark.asyncio
    async def test_rss_only_off_still_hydrates_when_auth_present(self):
        """Regression guard: with rss_only unset, the legacy hydration path
        still runs. If this test breaks, we've accidentally disabled full-text
        extraction for every website source."""
        collector = WebsiteCollector()
        source = _make_source(
            url="https://paywalled.example.com",
            metadata_={"rss_url": "https://paywalled.example.com/feed"},
        )
        items = self._rss_items()

        direct_mock = AsyncMock(return_value=[])  # direct path has nothing to offer
        rss_mock = AsyncMock(return_value=list(items))
        hydrate_rss_mock = AsyncMock(
            return_value=[{"url": "hydrated", "content": "full"}]
        )

        with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
             patch.object(collector, "get_runtime_auth", return_value=None), \
             patch.object(collector, "get_runtime_cookies", return_value={"session": "abc"}), \
             patch.object(
                 collector, "get_runtime_browser_session",
                 return_value={"user_data_dir": "/tmp/profile", "id": "x"},
             ), \
             patch.object(
                 collector, "_fetch_authenticated_direct_articles",
                 new=direct_mock,
             ), \
             patch.object(collector.rss_collector, "fetch", new=rss_mock), \
             patch.object(
                 collector, "_maybe_hydrate_rss_contents",
                 new=hydrate_rss_mock,
             ):
            result = await collector.fetch(source)

        # Hydration ran exactly once and we returned its output.
        direct_mock.assert_awaited_once()
        hydrate_rss_mock.assert_awaited_once()
        assert result == [{"url": "hydrated", "content": "full"}]

    @pytest.mark.asyncio
    async def test_rss_only_returns_empty_when_no_feed_configured(self):
        """If no RSS feed is configured or discoverable, rss_only must NOT
        silently fall back to ``_fetch_with_playwright`` or ``_fetch_static``.
        The operator explicitly opted out of HTML fetches; returning [] tells
        the pipeline "no new items" without crossing the line the user drew."""
        collector = WebsiteCollector()
        source = _make_source(
            url="https://paywalled.example.com",
            metadata_={"rss_only": True},  # no rss_url
        )

        rss_fetch_mock = AsyncMock(return_value=[])
        discover_mock = AsyncMock(return_value=None)
        static_mock = AsyncMock(return_value=[{"url": "static-result"}])
        playwright_mock = AsyncMock(return_value=[{"url": "playwright-result"}])

        with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
             patch.object(collector, "get_runtime_auth", return_value=None), \
             patch.object(collector, "get_runtime_cookies", return_value={}), \
             patch.object(collector, "get_runtime_browser_session", return_value=None), \
             patch.object(collector.rss_collector, "fetch", new=rss_fetch_mock), \
             patch.object(
                 collector.rss_collector, "discover_feed_url", new=discover_mock,
             ), \
             patch.object(collector, "_fetch_static", new=static_mock), \
             patch.object(collector, "_fetch_with_playwright", new=playwright_mock):
            result = await collector.fetch(source)

        assert result == []
        static_mock.assert_not_awaited()
        playwright_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_public_static_listing_hydrates_short_article_cards(self):
        """Public listing pages should hydrate direct article URLs even without auth."""
        collector = WebsiteCollector()
        source = _make_source(url="https://open.example.com/news")
        listing_items = [
            {
                "url": "https://open.example.com/articles/story-123",
                "title": "Story 123",
                "content": "Short teaser",
            },
        ]
        hydrated_items = [
            {
                "url": "https://open.example.com/articles/story-123",
                "title": "Story 123",
                "content": "Full article body",
            },
        ]

        static_mock = AsyncMock(return_value=list(listing_items))
        hydrate_mock = AsyncMock(return_value=hydrated_items)

        with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
             patch.object(collector, "get_runtime_auth", return_value=None), \
             patch.object(collector, "get_runtime_cookies", return_value={}), \
             patch.object(collector, "get_runtime_browser_session", return_value=None), \
             patch.object(collector.rss_collector, "discover_feed_url", new=AsyncMock(return_value=None)), \
             patch.object(collector, "_fetch_static", new=static_mock), \
             patch.object(collector, "_hydrate_candidate_contents", new=hydrate_mock):
            result = await collector.fetch(source)

        assert result == hydrated_items
        static_mock.assert_awaited_once()
        hydrate_mock.assert_awaited_once_with(
            source,
            listing_items,
            {},
            browser_session=None,
        )

    @pytest.mark.asyncio
    async def test_public_static_listing_skips_hydration_when_body_is_already_long(self):
        collector = WebsiteCollector()
        source = _make_source(url="https://open.example.com/news")
        listing_items = [
            {
                "url": "https://open.example.com/articles/story-123",
                "title": "Story 123",
                "content": "Full paragraph. " * 60,
            },
        ]

        static_mock = AsyncMock(return_value=list(listing_items))
        hydrate_mock = AsyncMock(return_value=[])

        with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
             patch.object(collector, "get_runtime_auth", return_value=None), \
             patch.object(collector, "get_runtime_cookies", return_value={}), \
             patch.object(collector, "get_runtime_browser_session", return_value=None), \
             patch.object(collector.rss_collector, "discover_feed_url", new=AsyncMock(return_value=None)), \
             patch.object(collector, "_fetch_static", new=static_mock), \
             patch.object(collector, "_hydrate_candidate_contents", new=hydrate_mock):
            result = await collector.fetch(source)

        assert result == listing_items
        hydrate_mock.assert_not_awaited()
