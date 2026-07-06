from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker

from app.ai.provider import ModelProviderClient, ModelRuntime
from app.database import Base
from app.models.system_setting import SystemSetting
from app.utils.ai_budget import AI_USAGE_BUDGET_KEY, AiBudgetCaps, reserve_ai_token_budget


def _sync_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ai_budget.db'}", future=True, poolclass=NullPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_reserve_ai_budget_persists_daily_and_monthly_usage(tmp_path, monkeypatch):
    session_factory = _sync_session_factory(tmp_path)
    monkeypatch.setattr("app.utils.ai_budget.SessionLocal", session_factory)

    first = reserve_ai_token_budget(40, caps=AiBudgetCaps(daily=100, monthly=150))
    second = reserve_ai_token_budget(50, caps=AiBudgetCaps(daily=100, monthly=150))

    assert first.allowed is True
    assert second.allowed is True
    assert second.daily_used == 90
    assert second.monthly_used == 90

    db = session_factory()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == AI_USAGE_BUDGET_KEY).one()
        assert row.value["daily_used_tokens"] == 90
        assert row.value["monthly_used_tokens"] == 90
    finally:
        db.close()


def test_reserve_ai_budget_rejects_daily_overage_without_increment(tmp_path, monkeypatch):
    session_factory = _sync_session_factory(tmp_path)
    monkeypatch.setattr("app.utils.ai_budget.SessionLocal", session_factory)

    assert reserve_ai_token_budget(80, caps=AiBudgetCaps(daily=100, monthly=0)).allowed is True
    denied = reserve_ai_token_budget(30, caps=AiBudgetCaps(daily=100, monthly=0))

    assert denied.allowed is False
    assert denied.reason == "daily_budget_exceeded"
    assert denied.daily_used == 80

    db = session_factory()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == AI_USAGE_BUDGET_KEY).one()
        assert row.value["daily_used_tokens"] == 80
    finally:
        db.close()


def test_reserve_ai_budget_rejects_monthly_overage(tmp_path, monkeypatch):
    session_factory = _sync_session_factory(tmp_path)
    monkeypatch.setattr("app.utils.ai_budget.SessionLocal", session_factory)

    assert reserve_ai_token_budget(90, caps=AiBudgetCaps(daily=0, monthly=100)).allowed is True
    denied = reserve_ai_token_budget(20, caps=AiBudgetCaps(daily=0, monthly=100))

    assert denied.allowed is False
    assert denied.reason == "monthly_budget_exceeded"
    assert denied.monthly_used == 90


def test_reserve_ai_budget_disabled_does_not_touch_db(monkeypatch):
    def _raise_session():
        raise AssertionError("SessionLocal should not be used when budget is disabled")

    monkeypatch.setattr("app.utils.ai_budget.SessionLocal", _raise_session)

    result = reserve_ai_token_budget(10, caps=AiBudgetCaps(daily=0, monthly=0))

    assert result.allowed is True


@pytest.mark.asyncio
async def test_model_provider_skips_provider_call_when_budget_denied(tmp_path, monkeypatch):
    session_factory = _sync_session_factory(tmp_path)
    monkeypatch.setattr("app.utils.ai_budget.SessionLocal", session_factory)
    monkeypatch.setenv("AI_DAILY_TOKEN_BUDGET", "10")
    monkeypatch.setenv("AI_MONTHLY_TOKEN_BUDGET", "0")

    from app.platform.config.settings import get_settings

    get_settings.cache_clear()
    try:
        client = ModelProviderClient()
        runtime = ModelRuntime(provider="ollama", model="llama", api_base="http://localhost:11434", max_tokens=50)
        with patch("app.ai.provider.ollama_generate_text", new_callable=AsyncMock) as mock_generate:
            result = await client.generate_text(runtime, prompt="x" * 200, max_tokens=50)

        assert result == ""
        mock_generate.assert_not_called()
    finally:
        get_settings.cache_clear()
