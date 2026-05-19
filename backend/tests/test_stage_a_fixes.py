import pytest

from app.processors.summarizer import Summarizer
from app.processors import translator as translator_module
from app.processors.translator import Translator


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeAsyncCompletions:
    async def create(self, **kwargs):
        model = kwargs.get("model", "")
        return _FakeResponse(f"ok:{model}")


class _FakeAsyncChat:
    def __init__(self):
        self.completions = _FakeAsyncCompletions()


class _FakeAsyncClient:
    def __init__(self):
        self.chat = _FakeAsyncChat()


@pytest.mark.asyncio
async def test_summarizer_openai_path_uses_async_client(monkeypatch):
    s = Summarizer(api_key="k")

    monkeypatch.setattr(s, "_get_client", lambda **kwargs: (_ for _ in ()).throw(AssertionError("sync client should not be used")))
    monkeypatch.setattr(s, "_get_async_client", lambda **kwargs: _FakeAsyncClient())

    result = await s._summarize_with_openai(
        text="a" * 200,
        max_length=120,
        language="zh-CN",
        model="gpt-4.1-mini",
        api_key="k",
        api_base=None,
    )
    assert result == "ok:gpt-4.1-mini"


@pytest.mark.asyncio
async def test_translator_openai_provider_no_duplicate_fallback(monkeypatch):
    t = Translator()
    calls = {"openai": 0}

    monkeypatch.setattr(translator_module, "get_translation_settings", lambda: {"provider": "openai"})
    monkeypatch.setattr(translator_module, "is_translation_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(translator_module, "get_translation_fallback_model_settings", lambda: {})
    monkeypatch.setattr(
        translator_module,
        "get_translation_cloud_fallback_openai_settings",
        lambda: {"provider": "openai", "model": "fallback-model", "api_key": "k"},
    )

    async def _fake_openai(text, target, trans_settings=None):
        calls["openai"] += 1
        if trans_settings and trans_settings.get("model") == "fallback-model":
            return "fallback-ok"
        return None

    monkeypatch.setattr(t, "_translate_with_openai", _fake_openai)

    result = await t.translate("This is a test sentence for translation.", "zh-CN")
    assert result == "fallback-ok"
    assert calls["openai"] == 2


@pytest.mark.asyncio
async def test_translator_openai_path_uses_async_client(monkeypatch):
    t = Translator()
    t.settings.openai_api_key = "k"
    monkeypatch.setattr(t, "_get_async_openai_client", lambda api_key, api_base: _FakeAsyncClient())

    result = await t._translate_with_openai("hello world", "zh-CN")
    assert result == "ok:gpt-4o-mini"
