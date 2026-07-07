"""Fixture-based tests for :mod:`app.collectors.website_parser`."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from bs4 import BeautifulSoup

from app.collectors.website_parser import (
    append_fallback_links,
    parse_article_candidate,
    parse_html_content,
)


def _make_source(url: str = "https://example.com/news", metadata: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(url=url, metadata_=metadata or {}, name="fixture")


# ---------------------------------------------------------------------------
# parse_article_candidate
# ---------------------------------------------------------------------------


class TestParseArticleCandidate:
    def _parse(self, html: str, source: SimpleNamespace | None = None):
        soup = BeautifulSoup(html, "lxml")
        article = soup.select_one("article")
        assert article is not None
        return parse_article_candidate(
            article,
            source=source or _make_source(),
            title_selector="h2, h3",
            link_selector="a",
            content_selector="p",
            date_selector="time",
        )

    def test_returns_none_without_title(self):
        html = """
        <article>
            <a href='/post/1'>link</a>
            <p>body</p>
        </article>
        """
        result = self._parse(html)
        assert result is None

    def test_returns_none_without_url(self):
        html = """
        <article>
            <h2>Headline that is plainly long enough</h2>
            <p>body text</p>
        </article>
        """
        result = self._parse(html)
        assert result is None

    def test_relative_url_resolves_against_source(self):
        html = """
        <article>
            <h2>Breaking news about widget factories</h2>
            <a href='/world/widgets-2026-04-20'>widgets story</a>
            <p>Some body sentence that reads naturally and is long enough.</p>
            <time datetime='2026-04-20T10:00:00Z'>Apr 20</time>
        </article>
        """
        result = self._parse(html, _make_source("https://example.com/news"))
        assert result is not None
        assert result["url"].endswith("/world/widgets-2026-04-20")
        assert result["publish_time"] == datetime(2026, 4, 20, 10, 0)
        assert result["metadata"]["publish_time_estimated"] is False

    def test_datetime_attr_with_offset_normalises_to_utc_naive(self):
        html = """
        <article>
            <h2>Breaking news about timezone handling</h2>
            <a href='/world/timezone-2026-07-07'>timezone story</a>
            <p>Some body sentence that reads naturally and is long enough.</p>
            <time datetime='2026-07-07T11:39:44+08:00'>Jul 7</time>
        </article>
        """
        result = self._parse(html, _make_source("https://example.com/news"))
        assert result is not None
        assert result["publish_time"] == datetime(2026, 7, 7, 3, 39, 44)
        assert result["publish_time"].tzinfo is None

    def test_date_text_captured_in_metadata(self):
        html = """
        <article>
            <h2>Another long headline for parsing</h2>
            <a href='https://example.com/story/abc-123'>link</a>
            <p>Body paragraph that stands alone easily.</p>
            <time>April 20, 2026</time>
        </article>
        """
        result = self._parse(html)
        assert result is not None
        assert result["metadata"]["publish_time_raw"] == "April 20, 2026"

    def test_invalid_datetime_attr_falls_through(self):
        html = """
        <article>
            <h2>Title covering enough characters to pass</h2>
            <a href='https://example.com/story/abc-123'>link</a>
            <p>Body sentence that is substantial enough.</p>
            <time datetime='not-a-date'>not-a-date</time>
        </article>
        """
        result = self._parse(html)
        assert result is not None
        assert result["metadata"]["publish_time_estimated"] is True


# ---------------------------------------------------------------------------
# append_fallback_links
# ---------------------------------------------------------------------------


class TestAppendFallbackLinks:
    def test_skips_when_enough_content(self):
        html = "<html><a href='/post'>Another article link here</a></html>"
        soup = BeautifulSoup(html, "lxml")
        source = _make_source("https://example.com")
        contents = [{"url": f"https://example.com/p{i}", "title": f"t{i}"} for i in range(5)]
        append_fallback_links(soup=soup, source=source, contents=contents)
        assert len(contents) == 5

    def test_adds_fallback_anchors_that_look_like_articles(self):
        html = """
        <html>
            <a href='https://example.com/2026/04/20/article-about-widgets'>
                A very legitimate looking article title
            </a>
            <a href='https://example.com/2026/04/20/another-long-article-title'>
                Another absolutely long article title to include
            </a>
            <a href='/short'>too short</a>
            <a href='/topics/newsletter'>Topic hub page — excluded</a>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        source = _make_source("https://example.com")
        contents: list = []
        append_fallback_links(soup=soup, source=source, contents=contents)
        assert len(contents) == 2
        assert all(c["metadata"]["publish_time_estimated"] for c in contents)

    def test_dedupes_against_existing_urls(self):
        html = """
        <html>
            <a href='https://example.com/2026/04/20/widgets-story'>Widgets story article title long enough</a>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        source = _make_source("https://example.com")
        contents = [
            {
                "url": "https://example.com/2026/04/20/widgets-story",
                "title": "Widgets story already present",
            }
        ]
        append_fallback_links(soup=soup, source=source, contents=contents)
        assert len(contents) == 1


# ---------------------------------------------------------------------------
# parse_html_content
# ---------------------------------------------------------------------------


class TestParseHtmlContent:
    def test_empty_html_returns_empty_list(self):
        source = _make_source()
        assert parse_html_content(html="", source=source) == []

    def test_extracts_article_elements(self):
        html = """
        <html>
          <body>
            <article>
              <h2>Alpha article with a meaningful long headline</h2>
              <a href='/alpha-2026-04-20'>alpha</a>
              <p>Alpha body content that reads well.</p>
              <time datetime='2026-04-20T00:00:00Z'>Apr 20</time>
            </article>
            <article>
              <h2>Beta article — another proper headline length</h2>
              <a href='/beta-2026-04-20'>beta</a>
              <p>Beta body content long enough.</p>
              <time datetime='2026-04-19T00:00:00Z'>Apr 19</time>
            </article>
          </body>
        </html>
        """
        source = _make_source("https://example.com")
        result = parse_html_content(html=html, source=source)
        assert len(result) >= 2
        urls = {item["url"] for item in result}
        assert "https://example.com/alpha-2026-04-20" in urls
        assert "https://example.com/beta-2026-04-20" in urls

    def test_honors_metadata_selectors(self):
        html = """
        <html><body>
          <div class='card'>
            <span class='card-title'>Carded headline sufficiently lengthy</span>
            <a class='card-link' href='https://example.com/custom-2026-04-20/slug-id'>link</a>
            <span class='card-date' datetime='2026-04-20T00:00:00Z'>Apr 20</span>
            <div class='card-body'>Card body sentence present.</div>
          </div>
        </body></html>
        """
        source = _make_source(
            "https://example.com",
            metadata={
                "article_selector": ".card",
                "title_selector": ".card-title",
                "link_selector": ".card-link",
                "content_selector": ".card-body",
                "date_selector": ".card-date",
            },
        )
        result = parse_html_content(html=html, source=source)
        assert len(result) == 1
        assert result[0]["url"].endswith("/custom-2026-04-20/slug-id")
