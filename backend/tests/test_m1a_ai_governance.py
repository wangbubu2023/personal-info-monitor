from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.provider import ModelRuntime
from app.database import Base
from app.domains.score.score_subjective import (
    LlmSubjectiveScorer,
    SUBJECTIVE_MAX_BODY_CHARS,
    build_subjective_input,
)
from app.models.ai_governance import AiPolicyMigrationState, AiSubjectiveScoreCache
from app.models.system_setting import SystemSetting
from app.platform.config import system_settings


def _session_factory(tmp_path, name: str = "m1a.db"):
    engine = create_engine(f"sqlite:///{tmp_path / name}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _content(
    *,
    content_id: str = "content-1",
    title: str = "A material product update",
    summary: str = "Short verified summary.",
    body: str = "Evidence " * 300,
    acceptance: str = "accepted",
    fulltext_status: str = "full",
):
    return SimpleNamespace(
        id=content_id,
        title=title,
        translated_title=None,
        summary=summary,
        translated_summary=None,
        full_content=body,
        metadata_={
            "fetch_acceptance": acceptance,
            "fulltext_status": fulltext_status,
        },
    )


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (_content(acceptance="incomplete"), "fetch_not_accepted"),
        (_content(fulltext_status="title_only"), "title_only"),
        (_content(fulltext_status="blocked"), "blocked"),
        (_content(title="https://example.com/article"), "url_title"),
    ],
)
def test_subjective_input_rejects_ineligible_content(content, reason):
    prepared, blocked_reason = build_subjective_input(content)
    assert prepared is None
    assert blocked_reason == reason


def test_subjective_input_bounds_body_to_800_characters():
    prepared, reason = build_subjective_input(_content(body="x" * 5000))
    assert reason is None
    assert prepared is not None
    body = prepared.prompt.split("正文补充：", 1)[1]
    assert len(body) == SUBJECTIVE_MAX_BODY_CHARS
    assert "x" * (SUBJECTIVE_MAX_BODY_CHARS + 1) not in prepared.prompt


@pytest.mark.asyncio
async def test_same_subjective_cache_key_replayed_ten_times_calls_provider_once(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path)
    monkeypatch.setattr("app.platform.persistence.database.SessionLocal", factory)
    runtime = ModelRuntime(provider="ollama", model="qwen-test", api_base="http://localhost:11434")

    async def runtime_resolver(**kwargs):
        return runtime

    monkeypatch.setattr("app.ai.provider.get_runtime_from_system_settings", runtime_resolver)
    calls = 0
    scorer = LlmSubjectiveScorer()

    async def fake_call(prompt, selected_runtime):
        nonlocal calls
        calls += 1
        assert selected_runtime is runtime
        assert len(prompt.split("正文补充：", 1)[1]) <= SUBJECTIVE_MAX_BODY_CHARS
        return "score: 8\nrationale: evidence is material"

    monkeypatch.setattr(scorer, "_call_llm", fake_call)
    results = [await scorer.score(_content(), lane="other") for _ in range(10)]

    assert calls == 1
    assert sum(result.cache_hit for result in results) == 9
    db = factory()
    try:
        rows = db.query(AiSubjectiveScoreCache).all()
        assert len(rows) == 1
        assert rows[0].hit_count == 9
        assert rows[0].prompt_version
        assert rows[0].model_version == "ollama:qwen-test"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_subjective_provider_concurrency_never_exceeds_two(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path, "concurrency.db")
    monkeypatch.setattr("app.platform.persistence.database.SessionLocal", factory)
    runtime = ModelRuntime(provider="ollama", model="qwen-concurrency", api_base="http://localhost:11434")

    async def runtime_resolver(**kwargs):
        return runtime

    monkeypatch.setattr("app.ai.provider.get_runtime_from_system_settings", runtime_resolver)
    active = 0
    peak = 0
    guard = asyncio.Lock()
    scorer = LlmSubjectiveScorer()

    async def fake_call(prompt, selected_runtime):
        nonlocal active, peak
        del prompt, selected_runtime
        async with guard:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.02)
        async with guard:
            active -= 1
        return "score: 7\nrationale: useful"

    monkeypatch.setattr(scorer, "_call_llm", fake_call)
    await asyncio.gather(
        *(
            scorer.score(
                _content(content_id=f"c-{index}", title=f"title {index}"),
                lane="other",
            )
            for index in range(6)
        )
    )
    assert peak == 2


def test_legacy_policy_env_is_persisted_once_and_env_changes_do_not_reapply(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path, "migration.db")
    monkeypatch.setattr(system_settings, "SessionLocal", factory)
    monkeypatch.setenv("AI_PROCESSING_ENABLED", "true")
    monkeypatch.setenv("ENRICH_AUTO_ON_INGEST", "true")
    monkeypatch.setenv("ENRICH_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("ENRICH_TRANSLATE_ENABLED", "false")
    monkeypatch.setenv("PIM_SCORE_LLM_SUBJECTIVE", "true")
    system_settings.invalidate_system_settings_cache()

    first = system_settings.get_system_settings_sync(force_refresh=True)
    assert first["auto_summary_enabled"] is True
    assert first["auto_listing_translation_enabled"] is False
    assert first["ai_subjective_scoring_enabled"] is True

    monkeypatch.setenv("AI_PROCESSING_ENABLED", "false")
    monkeypatch.setenv("ENRICH_TRANSLATE_ENABLED", "true")
    monkeypatch.setenv("PIM_SCORE_LLM_SUBJECTIVE", "false")
    system_settings.invalidate_system_settings_cache()
    second = system_settings.get_system_settings_sync(force_refresh=True)

    assert second["auto_summary_enabled"] is True
    assert second["auto_listing_translation_enabled"] is False
    assert second["ai_subjective_scoring_enabled"] is True
    assert all(
        key not in second
        for key in ("translation_enabled", "title_translation_enabled", "summarization_enabled")
    )

    db = factory()
    try:
        assert db.query(AiPolicyMigrationState).count() == 1
        stored = db.query(SystemSetting).filter(SystemSetting.key == "global").one().value
        assert stored["ai_policy_migration_version"] == 1
        assert "translation_enabled" not in stored
    finally:
        db.close()
