from __future__ import annotations

from app.collectors.rss import RSSCollector
from app.collectors.youtube import YouTubeCollector


def test_rss_validate_content_requires_plain_text_body():
    collector = RSSCollector()
    assert collector.validate_content(
        {"title": "T", "url": "https://example.com/a", "content": "x" * 25},
    )
    assert not collector.validate_content(
        {"title": "T", "url": "https://example.com/a", "content": "short"},
    )
    assert not collector.validate_content({"title": "T", "url": "https://example.com/a", "content": ""})


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
