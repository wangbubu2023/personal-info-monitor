"""Pipeline summarize stage — LLM canonical summary before scoring.

Runs synchronously inside ingest finish when fetch acceptance passed.
Falls back to the existing extractive ``summary`` when LLM is disabled or fails.
"""

from __future__ import annotations

from typing import Any

from app.utils.logger import get_logger
from app.utils.text import strip_html_tags

logger = get_logger(__name__)

_MIN_BODY_CHARS = 120


def pipeline_summary_enabled() -> bool:
    from app.platform.llm.policy import product_ai_flag_enabled

    return product_ai_flag_enabled("auto_summary_enabled", True)


async def apply_pipeline_summary(content: Any) -> bool:
    """Overwrite ``content.summary`` with an LLM summary when enabled.

    Returns True when a new LLM summary was written.
    """
    if not pipeline_summary_enabled():
        return False

    from app.platform.llm.policy import resolve_auto_summary_state

    state = await resolve_auto_summary_state()
    if not state.effective:
        logger.debug(
            "Pipeline summary skipped for %s: %s",
            getattr(content, "id", ""),
            state.reason,
        )
        return False

    body = strip_html_tags(getattr(content, "full_content", None) or "").strip()
    if len(body) < _MIN_BODY_CHARS:
        return False

    from app.platform.llm.summarizer import Summarizer

    summarizer = Summarizer()
    try:
        generated = await summarizer.summarize(body, max_length=500, language="en")
    except Exception as exc:  # noqa: BLE001 - fall back to extractive summary
        logger.debug("Pipeline summarize failed for %s: %s", getattr(content, "id", ""), exc)
        return False

    generated = strip_html_tags(generated or "").strip()
    if len(generated) < 50:
        return False

    content.summary = generated
    merged = dict(getattr(content, "metadata_", None) or {})
    merged["summary_source"] = "llm"
    content.metadata_ = merged
    logger.info(
        "Pipeline LLM summary for %s (%d chars)",
        getattr(content, "id", ""),
        len(generated),
    )
    return True


__all__ = ["apply_pipeline_summary", "pipeline_summary_enabled"]
