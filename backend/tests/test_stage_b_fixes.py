import pytest

from app.processors.summarizer import Summarizer
from app.processors.translator import Translator
from app.services.probe_service import ProbeService
from app.utils.cookies import cookie_domains_for_host


def test_probe_known_feed_matches_host_not_substring():
    service = ProbeService()
    assert service._check_known_feeds("https://www.bloomberg.com/markets") == "https://feeds.bloomberg.com/markets/news.rss"
    assert service._check_known_feeds("https://bloomberg.com.fake-site.com/news") is None


def test_cookie_domains_for_host_shared_utility():
    domains = cookie_domains_for_host("www.wsj.com")
    assert "www.wsj.com" in domains
    assert ".www.wsj.com" in domains
    assert "wsj.com" in domains
    assert ".wsj.com" in domains


@pytest.mark.asyncio
async def test_translator_openai_uses_runtime_model(monkeypatch):
    t = Translator()
    captured = {}

    class _FakeCompletions:
        async def create(self, **kwargs):
            captured["model"] = kwargs["model"]
            return type("Resp", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "ok"})()})()]})()

    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": _FakeCompletions()})()})()
    monkeypatch.setattr(t, "_get_async_openai_client", lambda api_key, api_base: fake_client)

    result = await t._translate_with_openai(
        "hello",
        "zh-CN",
        {"provider": "openai", "model": "gpt-4.1-mini", "api_key": "k"},
    )
    assert result == "ok"
    assert captured["model"] == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_summarizer_extract_keywords_uses_runtime_model(monkeypatch):
    s = Summarizer(api_key="k")
    captured = {}

    class _FakeCompletions:
        async def create(self, **kwargs):
            captured["model"] = kwargs["model"]
            return type("Resp", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "a,b"})()})()]})()

    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": _FakeCompletions()})()})()
    monkeypatch.setattr(
        s,
        "_get_runtime_settings",
        lambda: {"ai_model": {"provider": "openai", "model": "gpt-4.1-mini", "api_key": "k"}},
    )
    monkeypatch.setattr(s, "_get_async_client", lambda **kwargs: fake_client)

    keywords = await s.extract_keywords("text " * 30, max_keywords=5)
    assert keywords == ["a", "b"]
    assert captured["model"] == "gpt-4.1-mini"

