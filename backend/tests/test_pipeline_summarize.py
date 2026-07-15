"""Tests for enrich pipeline summarize stage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.enrich.content.summarize import apply_pipeline_summary


@pytest.mark.asyncio
async def test_apply_pipeline_summary_skipped_when_auto_disabled():
    content = MagicMock()
    content.full_content = "x" * 200
    with patch("app.domains.enrich.content.summarize.pipeline_summary_enabled", return_value=False):
        assert await apply_pipeline_summary(content) is False


@pytest.mark.asyncio
async def test_apply_pipeline_summary_writes_llm_summary():
    content = MagicMock()
    content.id = "cid-1"
    content.full_content = "OpenAI is preparing for an IPO according to sources. " * 10
    content.metadata_ = {}

    with patch("app.domains.enrich.content.summarize.pipeline_summary_enabled", return_value=True), patch(
        "app.platform.llm.policy.resolve_auto_summary_state",
        new_callable=AsyncMock,
        return_value=MagicMock(effective=True),
    ):
        with patch(
            "app.platform.llm.summarizer.Summarizer.summarize",
            new_callable=AsyncMock,
            return_value="OpenAI is reportedly preparing to file for an IPO in the near term.",
        ):
            assert await apply_pipeline_summary(content) is True

    assert "IPO" in content.summary
    assert content.metadata_.get("summary_source") == "llm"
