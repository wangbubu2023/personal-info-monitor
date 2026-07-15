from unittest.mock import AsyncMock

import pytest

from app.platform.llm import translator as translator_module
from app.platform.llm.policy import AiFeatureState
from app.platform.llm.translator import Translator


@pytest.mark.asyncio
async def test_translator_ollama_cloud_fallback_uses_runtime_openai_settings(monkeypatch):
    captured = {}

    async def _fake_ollama(*args, **kwargs):
        return None

    async def _fake_openai(text, target_language, trans_settings=None):
        captured["settings"] = trans_settings
        return "ok"

    monkeypatch.setattr(translator_module, "get_translation_settings", lambda: {"provider": "ollama"})
    monkeypatch.setattr(
        "app.platform.llm.policy.resolve_translation_state",
        AsyncMock(
            return_value=AiFeatureState(
                enabled=True,
                runtime_ready=True,
                effective=True,
                reason="ready",
            )
        ),
    )
    monkeypatch.setattr(translator_module, "is_translation_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(translator_module, "get_translation_fallback_model_settings", lambda: {})
    monkeypatch.setattr(
        translator_module,
        "get_translation_cloud_fallback_openai_settings",
        lambda: {
            "provider": "openai",
            "model": "deepseek-chat",
            "api_base": "https://api.deepseek.com/v1",
            "api_key": "k",
        },
    )

    t = Translator()
    monkeypatch.setattr(t, "_translate_with_ollama", _fake_ollama)
    monkeypatch.setattr(t, "_translate_with_openai", _fake_openai)

    result = await t.translate("This is a sample text for translation.", "zh-CN", source_language="en")
    assert result == "ok"
    assert captured["settings"]["model"] == "deepseek-chat"
    assert captured["settings"]["api_base"] == "https://api.deepseek.com/v1"


@pytest.mark.asyncio
async def test_translate_with_openai_respects_openai_compatible_settings(monkeypatch):
    t = Translator()
    captured = {}

    class _FakeCompletions:
        async def create(self, **kwargs):
            captured["model"] = kwargs["model"]
            return type("Resp", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "ok"})()})()]})()

    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": _FakeCompletions()})()})()

    def _fake_get_client(api_key, api_base):
        captured["api_key"] = api_key
        captured["api_base"] = api_base
        return fake_client

    monkeypatch.setattr(t, "_get_async_openai_client", _fake_get_client)

    result = await t._translate_with_openai(
        "hello world",
        "zh-CN",
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_base": "https://api.deepseek.com/v1",
            "api_key": "deepseek-key",
        },
    )
    assert result == "ok"
    assert captured["model"] == "deepseek-chat"
    assert captured["api_base"] == "https://api.deepseek.com/v1"
    assert captured["api_key"] == "deepseek-key"


@pytest.mark.asyncio
async def test_translate_with_openai_strips_reasoning_block(monkeypatch):
    t = Translator()

    class _FakeCompletions:
        async def create(self, **kwargs):
            content = "<think>用户要求我将这段内容翻译成简体中文。</think>\n真正的译文"
            return type("Resp", (), {"choices": [type("C", (), {"message": type("M", (), {"content": content})()})()]})()

    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": _FakeCompletions()})()})()
    monkeypatch.setattr(t, "_get_async_openai_client", lambda api_key, api_base: fake_client)

    result = await t._translate_with_openai(
        "hello world",
        "zh-CN",
        {"provider": "minimax", "model": "MiniMax-M2.7", "api_base": "https://api.minimaxi.com/v1", "api_key": "k"},
    )

    assert result == "真正的译文"


@pytest.mark.asyncio
async def test_translate_with_openai_discards_truncated_reasoning(monkeypatch):
    t = Translator()

    class _FakeCompletions:
        async def create(self, **kwargs):
            content = "<think>用户要求我将这段内容翻译成简体中文。"
            return type("Resp", (), {"choices": [type("C", (), {"message": type("M", (), {"content": content})()})()]})()

    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": _FakeCompletions()})()})()
    monkeypatch.setattr(t, "_get_async_openai_client", lambda api_key, api_base: fake_client)

    result = await t._translate_with_openai(
        "hello world",
        "zh-CN",
        {"provider": "minimax", "model": "MiniMax-M2.7", "api_base": "https://api.minimaxi.com/v1", "api_key": "k"},
    )

    assert result is None
