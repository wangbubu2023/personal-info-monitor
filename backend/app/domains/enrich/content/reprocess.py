"""Manual reprocess — regenerate summary / re-translate an existing Content row.

Extracted from ``ContentProcessor.reprocess_content`` as part of Phase
4 step 4 of the module-refactor blueprint. The canonical method on
:class:`app.domains.ingest.content_processor.ContentProcessor` is kept
as a thin wrapper delegating here so existing callers keep working.

Why a standalone function instead of a method?

The "reprocess on user click" path doesn't need the rest of
``ContentProcessor`` state (extractor, keyword matcher); it only needs
the Summariser and Translator. Pulling it out makes the dependency
explicit and lets the enrich domain own this operation without
reaching into the legacy processors package.

The summariser/translator live under ``platform.llm``; legacy
``app.processors.*`` paths remain only as compatibility shims.
"""

from __future__ import annotations

from app.domains.ingest.quality_metadata import merge_content_quality_metadata
from app.models import Content
from app.platform.llm.summarizer import Summarizer
from app.platform.llm.translator import Translator
from app.utils.datetime import utcnow_naive


async def reprocess_content(
    content: Content,
    *,
    regenerate_summary: bool = False,
    retranslate: bool = False,
    summarizer: Summarizer | None = None,
    translator: Translator | None = None,
) -> Content:
    """Reprocess an existing content item.

    Args:
        content: ORM-bound :class:`Content` row to mutate in place.
        regenerate_summary: When true, run the summariser over
            ``full_content`` and overwrite ``content.summary``.
        retranslate: When true, translate title + summary into Chinese
            if the originals are not already Chinese, populating
            ``translated_title`` / ``translated_summary``.
        summarizer: Optional summariser instance (a fresh
            :class:`Summarizer` is constructed when omitted).
        translator: Optional translator instance (a fresh
            :class:`Translator` is constructed when omitted).

    Returns:
        The mutated ``content`` instance (also stamps quality metadata
        and bumps ``updated_at``).
    """
    if regenerate_summary and content.full_content:
        active_summarizer = summarizer or Summarizer()
        content.summary = await active_summarizer.summarize(content.full_content)

    if retranslate:
        active_translator = translator or Translator()
        if content.title and not active_translator.is_chinese(content.title):
            content.translated_title = await active_translator.translate(
                content.title, "zh-CN"
            )
        if content.summary and not active_translator.is_chinese(content.summary):
            content.translated_summary = await active_translator.translate(
                content.summary, "zh-CN"
            )

    content.metadata_ = merge_content_quality_metadata(
        content.metadata_ or {},
        title=content.title or "",
        full_content=content.full_content,
        summary=content.summary,
        translated_summary=content.translated_summary,
    )
    content.updated_at = utcnow_naive()
    return content


__all__ = ["reprocess_content"]
