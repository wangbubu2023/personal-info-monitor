"""Extended tests for app.services.probe_service — complements test_probe_service_security.py."""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.probe_service import (
    KNOWN_RSS_FEEDS,
    ProbeResult,
    ProbeService,
    _UNFETCHABLE,
    _USE_SCRAPING,
)


# ---------------------------------------------------------------------------
# ProbeResult
# ---------------------------------------------------------------------------

class TestProbeResult:

    def test_defaults(self):
        r = ProbeResult()
        assert r.status == "unknown"
        assert r.strategy == "none"
        assert r.rss_url is None
        assert r.message == ""
        assert r.sample_count == 0

    def test_custom_values(self):
        r = ProbeResult(status="ok", strategy="rss", rss_url="http://feed.xml", message="ok", sample_count=10)
        assert r.status == "ok"
        assert r.strategy == "rss"
        assert r.rss_url == "http://feed.xml"
        assert r.sample_count == 10

    def test_to_dict(self):
        r = ProbeResult(status="ok", strategy="rss", rss_url="http://feed.xml", message="good", sample_count=5)
        d = r.to_dict()
        assert d["status"] == "ok"
        assert d["strategy"] == "rss"
        assert d["rss_url"] == "http://feed.xml"
        assert d["sample_count"] == 5
        assert "probed_at" in d


# ---------------------------------------------------------------------------
# _extract_x_username
# ---------------------------------------------------------------------------

class TestExtractXUsername:

    def setup_method(self):
        self.service = ProbeService()

    def test_at_prefix(self):
        assert self.service._extract_x_username("@elonmusk") == "elonmusk"

    def test_twitter_url(self):
        assert self.service._extract_x_username("https://twitter.com/elonmusk") == "elonmusk"

    def test_x_url(self):
        assert self.service._extract_x_username("https://x.com/elonmusk") == "elonmusk"

    def test_x_url_with_at(self):
        assert self.service._extract_x_username("https://x.com/@elonmusk") == "elonmusk"

    def test_plain_username(self):
        assert self.service._extract_x_username("elonmusk") == "elonmusk"

    def test_invalid_url(self):
        assert self.service._extract_x_username("https://example.com/page") is None

    def test_empty_string(self):
        assert self.service._extract_x_username("") is None

    def test_special_chars(self):
        assert self.service._extract_x_username("not a valid username!") is None


# ---------------------------------------------------------------------------
# _check_known_feeds
# ---------------------------------------------------------------------------

class TestCheckKnownFeeds:

    def setup_method(self):
        self.service = ProbeService()

    def test_bloomberg(self):
        result = self.service._check_known_feeds("https://www.bloomberg.com/news")
        assert result is not None
        assert "bloomberg" in result

    def test_facebook_unfetchable(self):
        result = self.service._check_known_feeds("https://www.facebook.com/user")
        assert result == _UNFETCHABLE

    def test_reuters_scraping(self):
        result = self.service._check_known_feeds("https://www.reuters.com/business")
        assert result == _USE_SCRAPING

    def test_unknown_site(self):
        result = self.service._check_known_feeds("https://myunknownblog.com")
        assert result is None

    def test_theinformation_unfetchable(self):
        result = self.service._check_known_feeds("https://www.theinformation.com")
        assert result == _UNFETCHABLE


# ---------------------------------------------------------------------------
# _extract_youtube_channel_id
# ---------------------------------------------------------------------------

class TestExtractYoutubeChannelId:

    def setup_method(self):
        self.service = ProbeService()

    def test_channel_url(self):
        result = self.service._extract_youtube_channel_id("https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx")
        assert result == "UCxxxxxxxxxxxxxxxxxxxxxx"

    def test_non_channel_url(self):
        result = self.service._extract_youtube_channel_id("https://www.youtube.com/@username")
        assert result is None


# ---------------------------------------------------------------------------
# _extract_youtube_playlist_id
# ---------------------------------------------------------------------------

class TestExtractYoutubePlaylistId:

    def setup_method(self):
        self.service = ProbeService()

    def test_playlist_url(self):
        result = self.service._extract_youtube_playlist_id(
            "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        )
        assert result == "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"

    def test_non_playlist_url(self):
        result = self.service._extract_youtube_playlist_id("https://www.youtube.com/@username")
        assert result is None

    def test_non_youtube_url(self):
        result = self.service._extract_youtube_playlist_id("https://example.com/?list=xyz")
        assert result is None


# ---------------------------------------------------------------------------
# _extract_youtube_feed_username
# ---------------------------------------------------------------------------

class TestExtractYoutubeFeedUsername:

    def setup_method(self):
        self.service = ProbeService()

    def test_c_url(self):
        assert self.service._extract_youtube_feed_username("https://www.youtube.com/c/TechChannel") == "TechChannel"

    def test_user_url(self):
        assert self.service._extract_youtube_feed_username("https://www.youtube.com/user/OldUser") == "OldUser"

    def test_handle_url_returns_none(self):
        assert self.service._extract_youtube_feed_username("https://www.youtube.com/@handle") is None


# ---------------------------------------------------------------------------
# _extract_youtube_channel_hint
# ---------------------------------------------------------------------------

class TestExtractYoutubeChannelHint:

    def setup_method(self):
        self.service = ProbeService()

    def test_handle_url(self):
        assert self.service._extract_youtube_channel_hint("https://www.youtube.com/@TechGuy") == "TechGuy"

    def test_c_url(self):
        assert self.service._extract_youtube_channel_hint("https://www.youtube.com/c/TechChannel") == "TechChannel"

    def test_no_hint(self):
        assert self.service._extract_youtube_channel_hint("https://www.youtube.com/watch?v=123") is None


# ---------------------------------------------------------------------------
# _youtube_channel_page_candidates
# ---------------------------------------------------------------------------

class TestYoutubeChannelPageCandidates:

    def setup_method(self):
        self.service = ProbeService()

    def test_handle_url(self):
        candidates = self.service._youtube_channel_page_candidates("https://www.youtube.com/@handle")
        assert "https://www.youtube.com/@handle" in candidates

    def test_legacy_url_adds_handle_candidate(self):
        candidates = self.service._youtube_channel_page_candidates("https://www.youtube.com/c/SomeChannel")
        assert any("@SomeChannel" in c for c in candidates)

    def test_strips_videos_suffix(self):
        candidates = self.service._youtube_channel_page_candidates("https://www.youtube.com/@handle/videos")
        assert all("/videos" not in c or "/videos" in c.replace("/videos", "", 1) for c in candidates)

    def test_deduplication(self):
        candidates = self.service._youtube_channel_page_candidates("https://www.youtube.com/@handle")
        assert len(candidates) == len(set(candidates))


# ---------------------------------------------------------------------------
# probe() dispatch
# ---------------------------------------------------------------------------

class TestProbeDispatch:

    @pytest.mark.asyncio
    async def test_unknown_source_type(self):
        service = ProbeService()
        result = await service.probe("https://example.com", source_type="unknown_type")
        assert result.status == "error"
        assert "Unknown source type" in result.message

    @pytest.mark.asyncio
    async def test_website_type_dispatches(self):
        service = ProbeService()
        with patch.object(service, "_probe_website", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = ProbeResult(status="ok", strategy="rss")
            result = await service.probe("https://example.com", source_type="website")
            mock_probe.assert_called_once_with("https://example.com")
            assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_rss_type_dispatches_to_website(self):
        service = ProbeService()
        with patch.object(service, "_probe_website", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = ProbeResult(status="ok", strategy="rss")
            result = await service.probe("https://example.com/feed", source_type="rss")
            mock_probe.assert_called_once()

    @pytest.mark.asyncio
    async def test_x_type_dispatches(self):
        service = ProbeService()
        with patch.object(service, "_probe_x", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = ProbeResult(status="ok", strategy="rsshub")
            result = await service.probe("https://x.com/user", source_type="x")
            mock_probe.assert_called_once_with("https://x.com/user")

    @pytest.mark.asyncio
    async def test_youtube_type_dispatches(self):
        service = ProbeService()
        with patch.object(service, "_probe_youtube", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = ProbeResult(status="ok", strategy="rss")
            result = await service.probe("https://youtube.com/@ch", source_type="youtube")
            mock_probe.assert_called_once()

    @pytest.mark.asyncio
    async def test_podcast_type_dispatches(self):
        service = ProbeService()
        with patch.object(service, "_probe_podcast", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = ProbeResult(status="ok", strategy="rss")
            result = await service.probe("https://feed.example.com/rss", source_type="podcast")
            mock_probe.assert_called_once()


# ---------------------------------------------------------------------------
# _test_rss_feed
# ---------------------------------------------------------------------------

class TestTestRssFeed:

    @pytest.mark.asyncio
    async def test_empty_response(self):
        service = ProbeService()
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=None):
            result = await service._test_rss_feed("https://example.com/feed")
            assert result.status == "warning"
            assert "返回为空" in result.message

    @pytest.mark.asyncio
    async def test_valid_feed(self):
        service = ProbeService()
        rss_text = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Test</title>
            <item><title>Entry 1</title></item>
            <item><title>Entry 2</title></item>
          </channel>
        </rss>"""
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=rss_text):
            result = await service._test_rss_feed("https://example.com/feed")
            assert result.status == "ok"
            assert result.sample_count == 2

    @pytest.mark.asyncio
    async def test_empty_feed_no_entries(self):
        service = ProbeService()
        rss_text = """<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>"""
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=rss_text):
            result = await service._test_rss_feed("https://example.com/feed")
            assert result.status == "warning"
            assert "为空" in result.message

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        service = ProbeService()
        with patch.object(service, "_http_get", new_callable=AsyncMock, side_effect=Exception("network error")):
            result = await service._test_rss_feed("https://example.com/feed")
            assert result.status == "error"
            assert "测试失败" in result.message


# ---------------------------------------------------------------------------
# _test_scrape
# ---------------------------------------------------------------------------

class TestTestScrape:

    @pytest.mark.asyncio
    async def test_unreachable_page(self):
        service = ProbeService()
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=None):
            result = await service._test_scrape("https://example.com")
            assert result.status == "error"
            assert "无法访问" in result.message

    @pytest.mark.asyncio
    async def test_page_with_articles(self):
        service = ProbeService()
        html = """<html><body>
        <article><h2>Article 1</h2></article>
        <article><h2>Article 2</h2></article>
        <article><h2>Article 3</h2></article>
        </body></html>"""
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=html):
            result = await service._test_scrape("https://example.com")
            assert result.status == "ok"
            assert result.sample_count >= 3

    @pytest.mark.asyncio
    async def test_page_with_links_only(self):
        service = ProbeService()
        links = "\n".join(
            f'<a href="http://example.com/article/{i}">This is article number {i} with a long title</a>'
            for i in range(5)
        )
        html = f"<html><body>{links}</body></html>"
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=html):
            result = await service._test_scrape("https://example.com")
            assert result.status == "warning"
            assert result.sample_count >= 3

    @pytest.mark.asyncio
    async def test_page_no_content(self):
        service = ProbeService()
        html = "<html><body><p>Just some text</p></body></html>"
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=html):
            result = await service._test_scrape("https://example.com")
            assert result.status == "error"
            assert "JS 渲染" in result.message

    @pytest.mark.asyncio
    async def test_exception_during_scrape(self):
        service = ProbeService()
        with patch.object(service, "_http_get", new_callable=AsyncMock, side_effect=Exception("parse error")):
            result = await service._test_scrape("https://example.com")
            assert result.status == "error"
            assert "测试失败" in result.message


# ---------------------------------------------------------------------------
# _discover_rss
# ---------------------------------------------------------------------------

class TestDiscoverRss:

    @pytest.mark.asyncio
    async def test_discovers_link_tag(self):
        service = ProbeService()
        html = '<html><head><link type="application/rss+xml" href="/feed.xml"></head></html>'
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=html):
            result = await service._discover_rss("https://example.com")
            assert result is not None
            assert "feed.xml" in result

    @pytest.mark.asyncio
    async def test_relative_href_resolved(self):
        service = ProbeService()
        html = '<html><head><link type="application/rss+xml" href="/blog/feed"></head></html>'
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=html):
            result = await service._discover_rss("https://example.com")
            assert result.startswith("https://example.com")

    @pytest.mark.asyncio
    async def test_no_feed_link(self):
        service = ProbeService()
        html = "<html><head><title>No Feed</title></head></html>"
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=html):
            result = await service._discover_rss("https://example.com")
            assert result is None

    @pytest.mark.asyncio
    async def test_empty_response(self):
        service = ProbeService()
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=None):
            result = await service._discover_rss("https://example.com")
            assert result is None


# ---------------------------------------------------------------------------
# _try_common_rss_paths
# ---------------------------------------------------------------------------

class TestTryCommonRssPaths:

    @pytest.mark.asyncio
    async def test_finds_feed_path(self):
        service = ProbeService()

        async def mock_get(url, timeout=15):
            if "/feed" in url:
                return '<rss version="2.0"><channel><item></item></channel></rss>'
            return None

        with patch.object(service, "_http_get", side_effect=mock_get):
            result = await service._try_common_rss_paths("https://example.com")
            assert result is not None
            assert "/feed" in result

    @pytest.mark.asyncio
    async def test_no_common_path_works(self):
        service = ProbeService()
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=None):
            result = await service._try_common_rss_paths("https://example.com")
            assert result is None


# ---------------------------------------------------------------------------
# _probe_website (integration-ish with mocked network)
# ---------------------------------------------------------------------------

class TestProbeWebsite:

    @pytest.mark.asyncio
    async def test_known_feed_unfetchable(self):
        service = ProbeService()
        result = await service._probe_website("https://facebook.com/user")
        assert result.status == "error"
        assert result.strategy == "none"

    @pytest.mark.asyncio
    async def test_known_rss_works(self):
        service = ProbeService()
        rss_text = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item><title>Entry</title></item></channel></rss>"""
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=rss_text):
            result = await service._probe_website("https://bloomberg.com/news")
            assert result.status == "ok"
            assert result.strategy == "rss"

    @pytest.mark.asyncio
    async def test_scraping_fallback_for_known_scraping_sites(self):
        service = ProbeService()
        html = "<html><body>" + "".join(f"<article>Article {i}</article>" for i in range(5)) + "</body></html>"
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=html):
            result = await service._probe_website("https://reuters.com/business")
            assert result.status == "ok"
            assert result.strategy == "scrape"

    @pytest.mark.asyncio
    async def test_nothing_works_returns_error(self):
        service = ProbeService()
        with patch.object(service, "_check_known_feeds", return_value=None):
            with patch.object(service, "_discover_rss", new_callable=AsyncMock, return_value=None):
                with patch.object(service, "_try_common_rss_paths", new_callable=AsyncMock, return_value=None):
                    with patch.object(service, "_test_scrape", new_callable=AsyncMock) as mock_scrape:
                        mock_scrape.return_value = ProbeResult(status="error", strategy="scrape", message="no content")
                        result = await service._probe_website("https://example.com")
                        assert result.status == "error"


# ---------------------------------------------------------------------------
# _probe_x
# ---------------------------------------------------------------------------

class TestProbeX:

    @pytest.mark.asyncio
    async def test_invalid_username(self):
        service = ProbeService()
        result = await service._probe_x("https://example.com/not-a-x-url")
        assert result.status == "error"
        assert "无法从 URL 中提取用户名" in result.message

    @pytest.mark.asyncio
    async def test_rsshub_available(self):
        service = ProbeService()
        rss_text = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item><title>Tweet</title></item></channel></rss>"""
        with patch("app.services.probe_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.x_auth_token = None
            settings.x_ct0_token = None
            settings.rsshub_url = "https://rsshub.app"
            settings.nitter_instances = ""
            settings.x_bearer_token = None
            mock_settings.return_value = settings
            with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=rss_text):
                result = await service._probe_x("https://x.com/testuser")
                assert result.status == "ok"
                assert result.strategy == "rsshub"

    @pytest.mark.asyncio
    async def test_no_strategy_available(self):
        service = ProbeService()
        with patch("app.services.probe_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.x_auth_token = None
            settings.x_ct0_token = None
            settings.rsshub_url = "https://rsshub.app"
            settings.nitter_instances = ""
            settings.x_bearer_token = None
            mock_settings.return_value = settings
            with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=None):
                result = await service._probe_x("https://x.com/testuser")
                assert result.status == "error"
                assert "未配置" in result.message


# ---------------------------------------------------------------------------
# _probe_podcast
# ---------------------------------------------------------------------------

class TestProbePodcast:

    @pytest.mark.asyncio
    async def test_spotify_rejected(self):
        service = ProbeService()
        result = await service._probe_podcast("https://open.spotify.com/show/123")
        assert result.status == "error"
        assert "Spotify" in result.message

    @pytest.mark.asyncio
    async def test_direct_rss_valid(self):
        service = ProbeService()
        with patch.object(service, "_test_rss_feed", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = ProbeResult(status="ok", strategy="rss", sample_count=10)
            result = await service._probe_podcast("https://feeds.example.com/podcast.xml")
            assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_direct_rss_invalid(self):
        service = ProbeService()
        with patch.object(service, "_test_rss_feed", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = ProbeResult(status="error", message="failed")
            result = await service._probe_podcast("https://feeds.example.com/bad")
            assert result.status == "error"
            assert "无法解析播客" in result.message

    @pytest.mark.asyncio
    async def test_apple_podcast_extraction(self):
        service = ProbeService()
        with patch.object(service, "_extract_apple_podcast_rss", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = "https://feeds.example.com/podcast.xml"
            with patch.object(service, "_test_rss_feed", new_callable=AsyncMock) as mock_test:
                mock_test.return_value = ProbeResult(status="ok", strategy="rss", sample_count=5)
                result = await service._probe_podcast("https://podcasts.apple.com/podcast/id12345")
                assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_apple_podcast_extraction_fails(self):
        service = ProbeService()
        with patch.object(service, "_extract_apple_podcast_rss", new_callable=AsyncMock, return_value=None):
            result = await service._probe_podcast("https://podcasts.apple.com/podcast/id12345")
            assert result.status == "warning"
            assert "Apple Podcasts" in result.message


# ---------------------------------------------------------------------------
# _extract_apple_podcast_rss
# ---------------------------------------------------------------------------

class TestExtractApplePodcastRss:

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        service = ProbeService()
        api_response = '{"resultCount":1,"results":[{"feedUrl":"https://feeds.example.com/pod.xml"}]}'
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value=api_response):
            result = await service._extract_apple_podcast_rss("https://podcasts.apple.com/us/podcast/id12345")
            assert result == "https://feeds.example.com/pod.xml"

    @pytest.mark.asyncio
    async def test_no_id_in_url(self):
        service = ProbeService()
        result = await service._extract_apple_podcast_rss("https://podcasts.apple.com/podcast")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_returns_empty(self):
        service = ProbeService()
        with patch.object(service, "_http_get", new_callable=AsyncMock, return_value='{"resultCount":0,"results":[]}'):
            result = await service._extract_apple_podcast_rss("https://podcasts.apple.com/us/podcast/id12345")
            assert result is None


# ---------------------------------------------------------------------------
# _http_get
# ---------------------------------------------------------------------------

class TestHttpGet:

    @pytest.mark.asyncio
    async def test_ssrf_block(self):
        service = ProbeService()
        async def _fake_resolve(hostname, port):
            return ["127.0.0.1"]
        with patch("app.utils.ssrf._resolve_host_addresses", _fake_resolve):
            result = await service._http_get("http://localhost/admin")
            assert result is None

    @pytest.mark.asyncio
    async def test_redirect_limit(self):
        service = ProbeService()

        class _FakeResp:
            def __init__(self, status, headers=None, url="http://a.com"):
                self.status = status
                self.headers = headers or {}
                self.url = url
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def text(self):
                return ""

        call_count = 0

        class _FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            def get(self, url, **kw):
                nonlocal call_count
                call_count += 1
                return _FakeResp(302, headers={"Location": "http://public.example.com/redir"}, url=url)

        with patch("app.services.probe_service.aiohttp.ClientSession", lambda: _FakeSession()):
            async def _fake_resolve(hostname, port):
                return ["93.184.216.34"]
            with patch("app.utils.ssrf._resolve_host_addresses", _fake_resolve):
                result = await service._http_get("http://public.example.com/start")
                assert result is None


# ---------------------------------------------------------------------------
# probe_all (batch)
# ---------------------------------------------------------------------------

class TestProbeAll:

    @pytest.mark.asyncio
    async def test_batch_probe(self):
        service = ProbeService()
        sources = [
            {"id": "1", "url": "https://example.com", "type": "website"},
            {"id": "2", "url": "https://x.com/user", "type": "x"},
        ]
        with patch.object(service, "probe", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = ProbeResult(status="ok")
            results = await service.probe_all(sources)
            assert "1" in results
            assert "2" in results
            assert results["1"].status == "ok"

    @pytest.mark.asyncio
    async def test_batch_probe_exception_handling(self):
        service = ProbeService()
        sources = [{"id": "1", "url": "https://example.com", "type": "website"}]
        with patch.object(service, "probe", new_callable=AsyncMock, side_effect=Exception("boom")):
            results = await service.probe_all(sources)
            assert results["1"].status == "error"
            assert "boom" in results["1"].message


# ---------------------------------------------------------------------------
# _is_private_address static proxy
# ---------------------------------------------------------------------------

class TestIsPrivateAddress:

    def test_private(self):
        assert ProbeService._is_private_address("127.0.0.1") is True

    def test_public(self):
        assert ProbeService._is_private_address("93.184.216.34") is False
