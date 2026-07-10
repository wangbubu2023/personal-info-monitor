from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from feedparser.util import FeedParserDict

from app.collectors.rss import RSSCollector
from app.collectors.youtube import YouTubeCollector
from app.domains.fetch.failures import FetchFailureError
from app.domains.fetch.collectors.podcast import PodcastCollector


def test_rss_validate_content_accepts_short_text_body():
    collector = RSSCollector()
    assert collector.validate_content(
        {"title": "T", "url": "https://example.com/a", "content": "x" * 100},
    )
    assert collector.validate_content(
        {"title": "T", "url": "https://example.com/a", "content": "x" * 99},
    )
    assert collector.validate_content({"title": "T", "url": "https://example.com/a", "content": ""})


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


def test_rss_validate_content_allows_short_feed_without_hydrated_html():
    collector = RSSCollector()
    assert collector.validate_content(
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


@pytest.mark.asyncio
async def test_rss_fetch_issues_no_page_requests_before_dedupe():
    """RSS fetch is a listing pass only: no per-entry article page HTTP.

    Body hydration happens after dedupe in ingest finalization. This test
    locks the invariant at the network boundary (any page fetch would go
    through ``fetch_public_http_text``), which is stronger than patching a
    private hydration helper.
    """
    collector = RSSCollector()
    source = MagicMock()
    source.url = "https://example.com/feed.xml"
    source.metadata_ = {}
    parsed = SimpleNamespace(
        status=200,
        bozo=False,
        entries=[
            FeedParserDict(
                {
                    "id": "entry-1",
                    "title": "Short feed item",
                    "link": "https://example.com/post",
                    "summary": "Short summary",
                    "tags": [],
                }
            )
        ],
    )

    with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
         patch.object(collector, "_record_feed_health"), \
         patch(
             "app.domains.fetch.collectors.rss.fetch_public_http_text",
             new=AsyncMock(
                 return_value=SimpleNamespace(
                     status=200,
                     text="<rss />",
                     body=b"<rss />",
                     headers={"Content-Type": "application/rss+xml; charset=utf-8"},
                     url=source.url,
                 )
             ),
         ) as feed_fetch, \
         patch("app.domains.fetch.collectors.rss.feedparser.parse", return_value=parsed):
        contents = await collector.fetch(source)

    assert len(contents) == 1
    assert contents[0]["external_id"] == "entry-1"
    feed_fetch.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type",
    ["text/xml", "text/xml; charset=windows-1252"],
)
async def test_rss_fetch_preserves_utf8_title_from_raw_bytes(content_type):
    collector = RSSCollector()
    source = MagicMock()
    source.url = "https://www.ithome.com/rss/"
    source.metadata_ = {}
    raw_feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>IT之家</title>
        <item>
          <guid>ithome-1</guid>
          <title>小米卢伟冰爆料 REDMI Note 17 标准版手机</title>
          <link>https://www.ithome.com/0/001/001.htm</link>
          <description>&#x5c0f;&#x7c73;</description>
        </item>
      </channel>
    </rss>
    """.encode("utf-8")
    mojibake_text = raw_feed.decode("latin-1")

    with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
         patch.object(collector, "_record_feed_health"), \
         patch(
             "app.domains.fetch.collectors.rss.fetch_public_http_text",
             new=AsyncMock(
                 return_value=SimpleNamespace(
                     status=200,
                     text=mojibake_text,
                     body=raw_feed,
                     headers={"Content-Type": content_type},
                     url=source.url,
                 )
             ),
         ):
        contents = await collector.fetch(source)

    assert len(contents) == 1
    assert contents[0]["title"] == "小米卢伟冰爆料 REDMI Note 17 标准版手机"
    assert contents[0]["content"] == "小米"


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
async def test_youtube_fetch_prefers_rss_from_channel_marker():
    collector = YouTubeCollector()
    source = MagicMock()
    source.url = "https://www.youtube.com/c/lexfridman"
    source.metadata_ = {"video_count": 2}
    source.last_content_id = "UCSHZKyawb77ixDdsGog4iWA"
    feed = SimpleNamespace(
        bozo=False,
        status=200,
        feed={"title": "Lex Fridman"},
        entries=[
            FeedParserDict(
                {
                    "id": "yt:video:pv1TUJSEM2k",
                    "yt_videoid": "pv1TUJSEM2k",
                    "title": "Roman Empire",
                    "link": "https://www.youtube.com/watch?v=pv1TUJSEM2k",
                    "summary": "Video description",
                    "published_parsed": (2026, 6, 30, 21, 16, 13, 1, 181, 0),
                }
            )
        ],
    )

    with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
         patch("app.domains.fetch.collectors.youtube.feedparser.parse", return_value=feed) as parse_feed:
        contents = await collector.fetch(source)

    assert len(contents) == 1
    assert contents[0]["external_id"] == "pv1TUJSEM2k"
    assert contents[0]["metadata"]["source_strategy"] == "youtube_rss"
    parse_feed.assert_called_once_with(
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCSHZKyawb77ixDdsGog4iWA"
    )


def test_youtube_collector_extracts_inline_vtt_transcript():
    collector = YouTubeCollector()
    entry = {
        "id": "abc123",
        "title": "Demo video",
        "description": "Video description",
        "upload_date": "20260331",
        "subtitles": {
            "en": [
                {
                    "ext": "vtt",
                    "data": """WEBVTT

00:00:00.000 --> 00:00:02.000
First caption line

00:00:02.000 --> 00:00:04.000
Second caption line
""",
                }
            ]
        },
    }

    content = collector._format_entry(entry, {})

    assert "Transcript:" in content["content"]
    assert "First caption line Second caption line" in content["content"]
    assert content["metadata"]["youtube_transcript_status"] == "inline"
    assert content["metadata"]["youtube_transcript_source"] == "subtitles"
    assert content["metadata"]["youtube_transcript_language"] == "en"
    assert content["metadata"]["article_fulltext"] is True
    assert content["metadata"]["fulltext_status"] == "full"


def test_youtube_collector_extracts_fragment_transcript():
    collector = YouTubeCollector()
    entry = {
        "id": "abc123",
        "title": "Demo video",
        "automatic_captions": {
            "en": [
                {
                    "fragments": [
                        {"text": "Hello"},
                        {"text": "world"},
                    ]
                }
            ]
        },
    }

    content = collector._format_entry(entry, {})

    assert content["content"] == "Hello world"
    assert content["metadata"]["youtube_transcript_status"] == "inline"
    assert content["metadata"]["youtube_transcript_source"] == "automatic_captions"


@pytest.mark.asyncio
async def test_youtube_fetch_skips_channel_tab_entries_from_yt_dlp():
    collector = YouTubeCollector()
    source = MagicMock()
    source.url = "https://www.youtube.com/@demo"
    source.metadata_ = {"video_count": 2}
    source.last_content_id = None

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
                "id": "UCSHZKyawb77ixDdsGog4iWA",
                "title": "Demo - Videos",
                "url": "https://www.youtube.com/@demo/videos",
            },
            {
                "id": "abc123def45",
                "title": "Demo video",
                "description": "Video description",
                "webpage_url": "https://www.youtube.com/watch?v=abc123def45",
            },
        ],
        "channel": "Demo Channel",
    }

    with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
         patch("app.domains.fetch.collectors.youtube.asyncio.to_thread", new=AsyncMock(return_value=info)), \
         patch("yt_dlp.YoutubeDL", new=lambda opts: FakeYDL(opts)):
        contents = await collector.fetch(source)

    assert [item["external_id"] for item in contents] == ["abc123def45"]


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
async def test_youtube_fetch_raises_classified_failure_on_yt_dlp_error():
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
            return {}

    with patch.object(collector, "_check_ssrf", new_callable=AsyncMock), \
         patch("app.domains.fetch.collectors.youtube.asyncio.to_thread", new=AsyncMock(side_effect=TimeoutError("slow"))), \
         patch("yt_dlp.YoutubeDL", new=lambda opts: FakeYDL(opts)):
        with pytest.raises(FetchFailureError) as err:
            await collector.fetch(source)

    assert err.value.failure.code.value == "timeout"


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


def test_podcast_enhancement_parses_audio_duration():
    collector = PodcastCollector()

    content = collector._enhance_podcast_content(
        {
            "title": "Episode",
            "metadata": {
                "itunes_duration": "01:02:03",
                "enclosures": [{"url": "https://cdn.example.com/ep.mp3", "type": "audio/mpeg", "length": "123"}],
            },
        }
    )

    assert content["metadata"]["audio_url"] == "https://cdn.example.com/ep.mp3"
    assert content["metadata"]["audio_size"] == "123"
    assert content["metadata"]["audio_duration"] == 3723


def test_podcast_duration_parser_accepts_common_formats():
    assert PodcastCollector._parse_duration_seconds("42:05") == 2525
    assert PodcastCollector._parse_duration_seconds("3600") == 3600
    assert PodcastCollector._parse_duration_seconds(90) == 90
    assert PodcastCollector._parse_duration_seconds("not a duration") is None
