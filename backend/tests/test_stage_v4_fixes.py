import sys
import types
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.collectors.website import WebsiteCollector
from app.domains.ingest.content_processor import ContentProcessor
from app.tasks import fetch_auth_helpers
from app.utils.model_catalog import load_model_providers


class _SourceStub:
    def __init__(self, url: str, source_type: str = "website"):
        self.id = uuid4()
        self.url = url
        self.type = source_type
        self.metadata_ = {}


class _AuthConfigStub:
    def __init__(self):
        self.auth_type = "password"
        self.login_url = None
        self.login_selectors = {}


class _SourceWithAuthStub(_SourceStub):
    def __init__(self, url: str):
        super().__init__(url)
        self.auth_config = _AuthConfigStub()


@pytest.mark.asyncio
async def test_login_and_capture_cookies_closes_context_and_browser_on_failure(monkeypatch):
    calls = {"context_closed": False, "browser_closed": False}

    class _FakePage:
        async def goto(self, *args, **kwargs):
            raise RuntimeError("goto failed")

    class _FakeContext:
        async def new_page(self):
            return _FakePage()

        async def close(self):
            calls["context_closed"] = True

    class _FakeBrowser:
        async def new_context(self):
            return _FakeContext()

        async def close(self):
            calls["browser_closed"] = True

    class _FakeChromium:
        async def launch(self, **kwargs):
            return _FakeBrowser()

    class _FakePlaywright:
        chromium = _FakeChromium()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    # _login_and_capture_cookies routes through the playwright_runtime shim
    # so patchright / playwright can be swapped at runtime. Phase 5 step 7
    # relocated the shim to ``app.platform.browser.playwright_runtime``;
    # the caller (``app.platform.browser.login_capture._login_and_capture_cookies``)
    # imports ``async_playwright`` from the canonical module, so the
    # monkey-patch must target the canonical module — patching the
    # ``app.utils.playwright_runtime`` re-export is a no-op for the
    # caller's binding lookup.
    from app.platform.browser import playwright_runtime

    monkeypatch.setattr(playwright_runtime, "async_playwright", lambda: _FakePlaywright())

    with pytest.raises(RuntimeError, match="goto failed"):
        await fetch_auth_helpers._login_and_capture_cookies(
            site_url="https://example.com",
            login_url="https://example.com/login",
            username="u",
            password="p",
        )

    assert calls["context_closed"] is True
    assert calls["browser_closed"] is True


@pytest.mark.asyncio
async def test_maybe_refresh_auth_cookies_manual_mode_returns_stale_cookie_warning(monkeypatch):
    source = _SourceWithAuthStub("https://example.com/article")
    creds = {"cookie_mode": "manual", "cookies": {"sid": "abc"}}

    async def _fake_cookies_appear_valid(site_url, cookies):
        return False

    monkeypatch.setattr(
        "app.domains.fetch.auth.refresh.cookies_appear_valid",
        _fake_cookies_appear_valid,
    )

    updated, warning = await fetch_auth_helpers.maybe_refresh_auth_cookies(db=object(), source=source, creds=creds)

    assert updated == creds
    assert warning == "手动 Cookie 可能已失效，请更新后重试"


@pytest.mark.asyncio
async def test_maybe_refresh_auth_cookies_respects_global_auto_login_disable(monkeypatch):
    from app.config import get_settings

    source = _SourceWithAuthStub("https://example.com/login")
    creds = {"username": "u", "password": "p"}
    monkeypatch.setenv("PIM_DISABLE_PASSWORD_AUTO_LOGIN", "true")
    get_settings.cache_clear()

    login_mock = AsyncMock(return_value={"sid": "new"})
    monkeypatch.setattr(
        "app.domains.fetch.auth.refresh.login_and_capture_cookies",
        login_mock,
    )

    try:
        updated, warning = await fetch_auth_helpers.maybe_refresh_auth_cookies(
            db=object(),
            source=source,
            creds=creds,
        )
    finally:
        get_settings.cache_clear()

    assert updated == creds
    assert warning == "密码自动登录已被 PIM_DISABLE_PASSWORD_AUTO_LOGIN 禁用"
    login_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_refresh_auth_cookies_rolls_back_failed_persist(monkeypatch):
    source = _SourceWithAuthStub("https://example.com/login")
    source.auth_config.credentials = "old"
    creds = {"username": "u", "password": "p"}
    calls = {"rollback": False, "refresh": False}

    class _DB:
        def commit(self):
            raise RuntimeError("commit failed")

        def rollback(self):
            calls["rollback"] = True

        def refresh(self, obj):
            calls["refresh"] = obj is source.auth_config
            obj.credentials = "old"

    async def _fake_login_and_capture_cookies(**kwargs):
        return {"sid": "new"}

    monkeypatch.setattr(
        "app.domains.fetch.auth.refresh.login_and_capture_cookies",
        _fake_login_and_capture_cookies,
    )
    monkeypatch.setattr(
        "app.platform.security.encryption.encrypt_data",
        lambda payload: "encrypted-new",
    )

    updated, warning = await fetch_auth_helpers.maybe_refresh_auth_cookies(
        db=_DB(),
        source=source,
        creds=creds,
    )

    assert updated == creds
    assert "持久化 cookies 失败" in warning
    assert source.auth_config.credentials == "old"
    assert calls == {"rollback": True, "refresh": True}


@pytest.mark.asyncio
async def test_cookie_precheck_timeout_is_not_treated_as_invalid(monkeypatch):
    async def _timeout(*args, **kwargs):
        raise TimeoutError("slow precheck")

    monkeypatch.setattr(
        "app.platform.auth.cookies.fetch_public_http_text",
        _timeout,
    )

    from app.platform.auth.cookies import cookies_appear_valid

    assert await cookies_appear_valid("https://x.com", {"auth_token": "abc"}) is True


def test_website_collector_prefers_direct_article_links_and_wrappers():
    collector = WebsiteCollector()
    source = _SourceStub("https://www.wsj.com")

    contents = [
        {"url": "https://www.wsj.com/business/economy/article-title-12345"},
        {"url": "https://www.wsj.com/topics/business"},
        {"url": "https://example.org/other"},
        {"url": "https://news.google.com/rss/articles/abc123"},
    ]

    result = collector._prefer_direct_article_links(source, contents)
    urls = [item["url"] for item in result]

    assert "https://www.wsj.com/business/economy/article-title-12345" in urls
    assert "https://news.google.com/rss/articles/abc123" in urls
    assert "https://www.wsj.com/topics/business" not in urls
    assert "https://example.org/other" not in urls


@pytest.mark.asyncio
async def test_website_hydration_skips_known_latest_external_id(monkeypatch):
    collector = WebsiteCollector()
    source = _SourceStub("https://example.com")
    source.last_content_id = "https://example.com/article:123456"
    contents = [
        {
            "external_id": "https://example.com/articles/123456/story",
            "url": "https://example.com/articles/123456/story",
            "title": "Already saved",
            "content": "teaser",
        }
    ]
    fetch_mock = AsyncMock(return_value=("<html>body</html>", contents[0]["url"], None))
    monkeypatch.setattr(collector, "_fetch_article_html", fetch_mock)

    hydrated, diag = await collector._hydrate_direct_articles(source, contents, {})

    assert hydrated == contents
    assert diag == {"attempted": 0, "hydrated": 0, "failures": {}}
    fetch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_website_hydration_stamps_session_health(monkeypatch):
    collector = WebsiteCollector()
    source = _SourceStub("https://example.com")
    contents = [
        {
            "external_id": "https://example.com/articles/123456/story",
            "url": "https://example.com/articles/123456/story",
            "title": "Needs login",
            "content": "teaser",
        }
    ]
    monkeypatch.setattr(
        collector,
        "_fetch_article_html",
        AsyncMock(return_value=(None, contents[0]["url"], "login_required")),
    )

    _hydrated, diag = await collector._hydrate_direct_articles(source, contents, {})

    assert diag["failures"] == {"login_required": 1}
    assert source.metadata_["session_health"]["reason"] == "login_required"
    assert source.metadata_["session_health"]["suggested_action"] == "relogin"


@pytest.mark.asyncio
async def test_website_discovered_feed_is_persisted(monkeypatch):
    collector = WebsiteCollector()
    source = _SourceStub("https://example.com")
    feed_items = [
        {
            "external_id": "https://example.com/news/123456/story",
            "url": "https://example.com/news/123456/story",
            "title": "Feed item",
            "content": "teaser",
        }
    ]
    monkeypatch.setattr(collector, "_fetch_authenticated_direct_articles", AsyncMock(return_value=None))
    monkeypatch.setattr(collector.rss_collector, "discover_feed_url", AsyncMock(return_value="https://example.com/feed.xml"))
    monkeypatch.setattr(collector.rss_collector, "fetch", AsyncMock(return_value=feed_items))
    monkeypatch.setattr(collector, "_maybe_hydrate_rss_contents", AsyncMock(return_value=feed_items))

    result = await collector.fetch(source)

    assert result == feed_items
    assert source.metadata_["rss_url"] == "https://example.com/feed.xml"


@pytest.mark.asyncio
async def test_content_processor_cookie_fulltext_path_sets_metadata(monkeypatch):
    processor = ContentProcessor()
    source = _SourceStub("https://example.com/article")
    source._runtime_auth = {"credentials": {"cookies": {"sid": "abc"}}}

    long_text = "A" * 900
    async def _fake_fetch_full_text(url, cookies, source_url=None):
        return long_text

    monkeypatch.setattr(processor, "_fetch_full_text_with_cookies", _fake_fetch_full_text)

    content = await processor.process(
        raw_content={
            "title": "Example Title",
            "url": "https://example.com/article",
            "content": "short",
            "publish_time": "2026-02-27T00:00:00Z",
        },
        source=source,
        keywords=[],
        generate_summary=False,
        translate=False,
    )

    assert content.metadata_["cookie_fulltext_required"] is True
    assert content.metadata_["cookie_fulltext_obtained"] is True
    assert content.metadata_["cookie_fulltext_length"] == len(long_text)
    assert content.full_content == long_text


def test_model_provider_catalog_loads_from_json_file(monkeypatch, tmp_path):
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        '{"providers":[{"id":"openai","name":"OpenAI","models":[{"id":"x","name":"x"}],"requires_api_key":true}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_PROVIDERS_CONFIG_PATH", str(config_path))

    providers = load_model_providers()

    assert len(providers) == 1
    assert providers[0]["id"] == "openai"
    assert providers[0]["models"][0]["id"] == "x"


def test_default_model_provider_catalog_includes_domestic_openai_compatible_vendors(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDERS_CONFIG_PATH", raising=False)

    providers = load_model_providers()
    provider_ids = {provider["id"] for provider in providers}

    assert "qwen" in provider_ids
    assert "volcengine" in provider_ids
    assert "hunyuan" in provider_ids
    assert "minimax" in provider_ids
    assert "zhipu" in provider_ids
    assert "moonshot" in provider_ids
    assert "deepseek" in provider_ids
    assert "openai_compatible" in provider_ids
