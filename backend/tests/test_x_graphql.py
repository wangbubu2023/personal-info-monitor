import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from app.collectors.x_twitter import XCollector
from app.models.source import Source


# ==============================================================================
#  Mock Models
# ==============================================================================

class MockUser:
    def __init__(self, user_id="12345", screen_name="hello"):
        self.id = user_id
        self.screen_name = screen_name


class MockMedia:
    def __init__(self, media_type="photo", url="http://img.test"):
        self.type = media_type
        self.url = url
        self.media_url_https = url


class MockTweet:
    def __init__(
        self,
        tweet_id,
        text="",
        full_text="",
        created_at="Wed Oct 10 20:19:24 +0000 2018",
        media=None,
        urls=None,
        likes=10,
        retweets=5,
        views=100,
        is_retweet=False,
    ):
        self.id = tweet_id
        self.text = text
        self.full_text = full_text
        self.created_at = created_at
        self.created_at_datetime = datetime(2018, 10, 10, 20, 19, 24)
        self.media = media or []
        self.urls = urls or []
        self.favorite_count = likes
        self.retweet_count = retweets
        self.view_count = views
        self.reply_count = 1
        self.lang = "en"
        self.hashtags = []
        
        if is_retweet:
            rt_user = MockUser(screen_name="original_author")
            rt_tweet = MagicMock()
            rt_tweet.user = rt_user
            rt_tweet.full_text = "This is the original tweet"
            self.retweeted_tweet = rt_tweet
        else:
            self.retweeted_tweet = None


# ==============================================================================
#  Tests
# ==============================================================================

@pytest.fixture
def collector():
    c = XCollector()
    c._twikit_available = True  # Mock availability
    return c


@pytest.fixture
def source_w_cookies():
    s = Source(id=1, name="Test", url="https://x.com/test", type="x")
    s.metadata_ = {
        "strategy": "graphql",
        "auth_token": "abc_auth",
        "ct0": "def_ct0",
    }
    return s


def test_format_tweet_graphql(collector):
    # 1. Normal short tweet
    t1 = MockTweet(101, text="Short tweet", full_text="Short tweet full")
    res1 = collector._format_tweet_graphql(t1, "hello")
    assert res1["external_id"] == "101"
    assert res1["content"] == "Short tweet full"
    assert res1["title"] == "Short tweet full"
    assert res1["url"] == "https://x.com/hello/status/101"
    assert res1["publish_time"] == datetime(2018, 10, 10, 20, 19, 24)
    assert res1["metadata"]["metrics"]["likes"] == 10
    assert res1["metadata"]["content_type"] == "tweet"

    # 2. Article tweet
    t2 = MockTweet(102, full_text="Here is a long article https://x.com/i/article/1234")
    res2 = collector._format_tweet_graphql(t2, "hello")
    assert res2["metadata"]["content_type"] == "article"

    # 3. Retweet
    t3 = MockTweet(103, is_retweet=True)
    res3 = collector._format_tweet_graphql(t3, "hello")
    assert res3["title"].startswith("RT @original_author:")
    assert res3["metadata"]["is_retweet"] is True


def test_extract_article_urls_from_bare_and_http_links(collector):
    text = "read x.com/i/article/2038460528033492992 and http://x.com/i/article/999"
    urls = collector._extract_article_urls(text)
    assert "https://x.com/i/article/2038460528033492992" in urls
    assert "https://x.com/i/article/999" in urls


def test_clean_article_text_filters_ui_noise(collector):
    long_body = "这是一段有效正文，长度足够长，用于确保清洗后内容能被保留。"
    raw = (
        "要查看键盘快捷键，按下问号\n"
        "查看键盘快捷键\n"
        "@Khazix0918\n"
        "3小时\n"
        "分享6个我觉得应该必装的Skills。\n"
        f"{long_body}\n{long_body}\n{long_body}\n{long_body}\n{long_body}\n"
        f"{long_body}\n{long_body}\n{long_body}\n{long_body}\n{long_body}\n"
        f"{long_body}\n{long_body}\n{long_body}\n{long_body}\n{long_body}\n"
        "45\n"
        "2.7万\n"
    )
    cleaned = collector._clean_article_text(raw)
    assert cleaned is not None
    assert "查看键盘快捷键" not in cleaned
    assert "@Khazix0918" not in cleaned
    assert "分享6个我觉得应该必装的Skills。" in cleaned


@pytest.mark.asyncio
async def test_enrich_article_content_uses_metadata_urls(collector):
    source = Source(id=1, name="X", url="https://x.com/test", type="x")
    source.metadata_ = {"fetch_x_articles": True, "x_article_fetch_limit": 8}
    items = [
        {
            "external_id": "1",
            "title": "https://t.co/demo",
            "content": "",
            "url": "https://x.com/test/status/1",
            "metadata": {
                "urls": [
                    {"expanded_url": "http://x.com/i/article/2038460528033492992"},
                ]
            },
        }
    ]

    with patch.object(
        collector,
        "_fetch_article_texts_with_playwright",
        new=AsyncMock(return_value={"https://x.com/i/article/2038460528033492992": "A" * 600}),
    ):
        enriched = await collector._enrich_article_content(items, source)

    assert enriched[0]["url"] == "https://x.com/i/article/2038460528033492992"
    assert len(enriched[0]["content"]) == 600
    assert enriched[0]["metadata"]["article_fulltext"] is True


@pytest.mark.asyncio
async def test_fetch_via_graphql_success(collector, source_w_cookies):
    # Mock TwikitClient
    mock_client = AsyncMock()
    mock_client.get_user_by_screen_name.return_value = MockUser()
    mock_client.get_user_tweets.return_value = [
        MockTweet(1, full_text="Tweet 1"),
        MockTweet(2, full_text="Tweet 2"),
        MockTweet(2, full_text="Tweet 2"),  # Duplicate
    ]

    with patch.object(collector, "_get_twikit_client", return_value=mock_client) as mock_get:
        res = await collector._fetch_via_graphql("hello", source_w_cookies)
        
        mock_get.assert_called_once()
        mock_client.get_user_by_screen_name.assert_called_with("hello")
        mock_client.get_user_tweets.assert_called_with("12345", "Tweets", count=50)
        
        assert len(res) == 2  # Deduplicated from 3
        assert res[0]["external_id"] in ("1", "2")
        assert res[1]["external_id"] in ("1", "2")


@pytest.mark.asyncio
async def test_fetch_via_graphql_no_cookies(collector):
    # No cookies -> should skip silently
    source = Source(id=1, name="Test", url="https://x.com/test", type="x")
    source.metadata_ = {"strategy": "graphql"}
    
    with patch.object(collector, "x_auth_token", return_value=None), \
         patch.object(collector, "x_ct0_token", return_value=None):
        res = await collector._fetch_via_graphql("hello", source)
        assert res == []


@pytest.mark.asyncio
async def test_probe_x_graphql_success():
    from app.services.probe_service import ProbeService
    probe = ProbeService()
    
    # Mock config
    with patch("app.config.get_settings") as mock_settings:
        settings = mock_settings.return_value
        settings.x_auth_token = "auth"
        settings.x_ct0_token = "ct0"
        
        # Mock TwikitClient
        mock_client = AsyncMock()
        mock_client.set_cookies = MagicMock()
        mock_client.get_user_by_screen_name.return_value = MockUser("123")
        
        with patch("twikit.Client", return_value=mock_client):
            res = await probe._probe_x("https://x.com/hello")
            
            assert res.status == "ok"
            assert res.strategy == "graphql"
            assert "已验证 (user_id=123)" in res.message
