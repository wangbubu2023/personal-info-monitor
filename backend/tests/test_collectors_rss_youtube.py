from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.collectors.rss import RSSCollector
from app.collectors.youtube import YouTubeCollector
from app.domains.fetch.collectors.podcast import PodcastCollector
from app.utils.http import LARGE_HEADER_LIMIT


def test_rss_validate_content_requires_plain_text_body():
    collector = RSSCollector()
    assert collector.validate_content(
        {"title": "T", "url": "https://example.com/a", "content": "x" * 100},
    )
    assert not collector.validate_content(
        {"title": "T", "url": "https://example.com/a", "content": "x" * 99},
    )
    assert not collector.validate_content({"title": "T", "url": "https://example.com/a", "content": ""})


def test_rss_validate_content_falls_back_to_hydrated_html():
    collector = RSSCollector()
    assert collector.validate_content(
        {
            "title": "T",
            "url": "https://example.com/a",
            "content": "",
            "html": f"<html><body><article>{'article text ' * 12}</article></body></html>",
        },
    )


def test_rss_validate_content_rejects_short_feed_without_hydrated_html():
    collector = RSSCollector()
    assert not collector.validate_content(
        {
            "title": "PromptLayer",
            "url": "https://example.com/promptlayer",
            "content": "Trace AI requests, workflows, and costs in one timeline\n\nDiscussion\n\n|\n\nLink",
        },
    )


def test_rss_validate_content_rejects_embedded_png():
    collector = RSSCollector()
    blob = (b"\x89PNG\r\n\x1a\n" + b"z" * 60).decode("latin-1")
    assert not collector.validate_content(
        {"title": "T", "url": "https://example.com/a", "content": blob},
    )


def test_rss_collector_extracts_meta_description_summary():
    collector = RSSCollector()
    html = """
    <html>
      <head><meta name="description" content="This is a long enough description to use as the article summary for the reader view." /></head>
      <body></body>
    </html>
    """

    summary = collector._extract_summary_from_html(html)
    assert summary is not None
    assert "long enough description" in summary


@pytest.mark.asyncio
async def test_rss_page_html_fetch_uses_permissive_session_kwargs():
    collector = RSSCollector()
    source = MagicMock()
    source.url = "https://deepmind.google/blog/feed/"
    source.metadata_ = {}
    captured_kwargs = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    response = SimpleNamespace(status=200, text="<html><article>body</article></html>")

    with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
         patch.object(collector, "get_runtime_cookies", return_value={}), \
         patch("app.domains.fetch.collectors.rss.check_before_fetch", new=AsyncMock()), \
         patch("app.domains.fetch.collectors.rss.aiohttp.ClientSession", new=FakeSession), \
         patch(
             "app.domains.fetch.collectors.rss.fetch_public_http_text",
             new=AsyncMock(return_value=response),
         ):
        html = await collector._fetch_page_html("https://deepmind.google/blog/post/", source)

    assert html == response.text
    assert captured_kwargs["max_line_size"] == LARGE_HEADER_LIMIT
    assert captured_kwargs["max_field_size"] == LARGE_HEADER_LIMIT


@pytest.mark.asyncio
async def test_rss_discover_feed_url_normalizes_bare_relative_href():
    collector = RSSCollector()
    response = SimpleNamespace(
        status=200,
        text="""
        <html>
          <head>
            <link rel="alternate" type="application/rss+xml" href="rss">
          </head>
          <body></body>
        </html>
        """,
    )

    with patch(
        "app.domains.fetch.collectors.rss.fetch_public_http_text",
        new=AsyncMock(return_value=response),
    ):
        feed_url = await collector.discover_feed_url("https://news.ycombinator.com/")

    assert feed_url == "https://news.ycombinator.com/rss"


def test_youtube_collector_formats_entry_and_normalizes_channel_url():
    collector = YouTubeCollector()
    entry = {
        "id": "abc123",
        "title": "Demo video",
        "description": "Video description",
        "upload_date": "20260331",
        "channel": "Demo Channel",
        "thumbnails": [{"url": "low.jpg"}, {"url": "high.jpg"}],
    }
    parent_info = {"channel": "Fallback Channel"}

    content = collector._format_entry(entry, parent_info)

    assert collector._normalise_channel_url("https://www.youtube.com/@demo/videos") == "https://www.youtube.com/@demo"
    assert content["external_id"] == "abc123"
    assert content["metadata"]["thumbnail"] == "high.jpg"
    assert content["publish_time"].year == 2026


@pytest.mark.asyncio
async def test_youtube_fetch_runs_yt_dlp_in_worker_thread():
    collector = YouTubeCollector()
    source = MagicMock()
    source.url = "https://www.youtube.com/@demo"
    source.metadata_ = {"video_count": 1}

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            raise AssertionError("extract_info should be invoked through asyncio.to_thread")

    info = {
        "entries": [
            {
                "id": "abc123",
                "title": "Demo video",
                "description": "Video description",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
            }
        ],
        "channel": "Demo Channel",
    }

    with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
         patch("app.domains.fetch.collectors.youtube.asyncio.to_thread", new=AsyncMock(return_value=info)) as to_thread, \
         patch("yt_dlp.YoutubeDL", new=lambda opts: FakeYDL(opts)):
        contents = await collector.fetch(source)

    assert len(contents) == 1
    assert contents[0]["external_id"] == "abc123"
    to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_podcast_info_parse_runs_in_worker_thread():
    collector = PodcastCollector()
    parsed = SimpleNamespace(
        bozo=False,
        feed={
            "title": "Demo Podcast",
            "description": "Podcast description",
            "author": "Demo",
            "tags": [{"term": "tech"}],
        },
        entries=[{"title": "ep"}],
    )

    with patch("app.domains.fetch.collectors.podcast.asyncio.to_thread", new=AsyncMock(return_value=parsed)) as to_thread:
        info = await collector.get_podcast_info("https://example.com/feed.xml")

    assert info["title"] == "Demo Podcast"
    assert info["episode_count"] == 1
    to_thread.assert_awaited_once()
