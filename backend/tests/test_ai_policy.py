import pytest

from app.platform.llm import policy


@pytest.mark.asyncio
async def test_auto_summary_disabled_by_product_switch(monkeypatch):
    monkeypatch.setattr(policy, "ai_hard_disabled", lambda: False)
    settings = {
        "ai_processing_paused": False,
        "auto_summary_enabled": False,
        "ai_model": {"provider": "ollama", "model": "llama3"},
    }

    state = await policy.resolve_auto_summary_state(settings)

    assert state.enabled is False
    assert state.effective is False
    assert state.reason == "disabled"


@pytest.mark.asyncio
async def test_auto_translation_waits_for_runtime(monkeypatch):
    monkeypatch.setattr(policy, "ai_hard_disabled", lambda: False)
    policy.invalidate_ai_policy_cache()
    settings = {
        "ai_processing_paused": False,
        "auto_listing_translation_enabled": True,
        "translation_model": {"provider": "ollama", "model": "missing"},
    }

    async def fake_runtime(**kwargs):
        return None

    monkeypatch.setattr(policy, "get_runtime_from_system_settings", fake_runtime)

    state = await policy.resolve_translation_state(automatic=True, settings=settings)

    assert state.enabled is True
    assert state.runtime_ready is False
    assert state.effective is False
    assert state.reason == "model_unavailable"


@pytest.mark.asyncio
async def test_reader_translation_ignores_auto_translation_switch(monkeypatch):
    monkeypatch.setattr(policy, "ai_hard_disabled", lambda: False)
    policy.invalidate_ai_policy_cache()
    settings = {
        "ai_processing_paused": False,
        "auto_listing_translation_enabled": False,
        "translation_model": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"},
    }

    class Runtime:
        pass

    async def fake_runtime(**kwargs):
        return Runtime()

    monkeypatch.setattr(policy, "get_runtime_from_system_settings", fake_runtime)

    state = await policy.resolve_translation_state(automatic=False, settings=settings)

    assert state.enabled is True
    assert state.runtime_ready is True
    assert state.effective is True
    assert state.reason == "ready"


@pytest.mark.asyncio
async def test_translation_fallback_keeps_feature_ready(monkeypatch):
    monkeypatch.setattr(policy, "ai_hard_disabled", lambda: False)
    policy.invalidate_ai_policy_cache()
    settings = {
        "ai_processing_paused": False,
        "auto_listing_translation_enabled": True,
        "translation_fallback_enabled": True,
        "translation_model": {"provider": "ollama", "model": "missing"},
        "translation_fallback": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"},
    }
    calls = []

    async def fake_runtime(**kwargs):
        calls.append(kwargs["setting_key"])
        return object() if kwargs["setting_key"] == "translation_fallback" else None

    monkeypatch.setattr(policy, "get_runtime_from_system_settings", fake_runtime)

    state = await policy.resolve_translation_state(automatic=True, settings=settings)

    assert calls == ["translation_model", "translation_fallback"]
    assert state.runtime_ready is True
    assert state.effective is True
    assert state.reason == "ready"


@pytest.mark.asyncio
async def test_summary_fallback_keeps_feature_ready(monkeypatch):
    monkeypatch.setattr(policy, "ai_hard_disabled", lambda: False)
    policy.invalidate_ai_policy_cache()
    settings = {
        "ai_processing_paused": False,
        "auto_summary_enabled": True,
        "summarization_fallback_enabled": True,
        "ai_model": {"provider": "ollama", "model": "missing"},
        "summarization_fallback": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"},
    }

    async def fake_runtime(**kwargs):
        return object() if kwargs["setting_key"] == "summarization_fallback" else None

    monkeypatch.setattr(policy, "get_runtime_from_system_settings", fake_runtime)

    state = await policy.resolve_auto_summary_state(settings)

    assert state.runtime_ready is True
    assert state.effective is True
    assert state.reason == "ready"


@pytest.mark.asyncio
async def test_global_pause_blocks_effective_state(monkeypatch):
    monkeypatch.setattr(policy, "ai_hard_disabled", lambda: False)
    settings = {
        "ai_processing_paused": True,
        "auto_summary_enabled": True,
        "ai_model": {"provider": "ollama", "model": "llama3"},
    }

    state = await policy.resolve_auto_summary_state(settings)

    assert state.enabled is True
    assert state.effective is False
    assert state.reason == "paused"
