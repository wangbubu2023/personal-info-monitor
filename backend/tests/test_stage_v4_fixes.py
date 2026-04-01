import sys
import types
from uuid import uuid4

import pytest

from app.collectors.website import WebsiteCollector
from app.processors.content_processor import ContentProcessor
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

    fake_module = types.SimpleNamespace(async_playwright=lambda: _FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_module)

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

    monkeypatch.setattr(fetch_auth_helpers, "cookies_appear_valid", _fake_cookies_appear_valid)

    updated, warning = await fetch_auth_helpers.maybe_refresh_auth_cookies(db=object(), source=source, creds=creds)

    assert updated == creds
    assert warning == "手动 Cookie 可能已失效，请更新后重试"


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
async def test_content_processor_cookie_fulltext_path_sets_metadata(monkeypatch):
    processor = ContentProcessor()
    source = _SourceStub("https://example.com/article")
    source._runtime_auth = {"credentials": {"cookies": {"sid": "abc"}}}

    long_text = "A" * 900
    async def _fake_fetch_full_text(url, cookies):
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
