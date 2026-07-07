"""HTTP serialization helpers + backwards-compatible reader-helper facade.

Reader-shared helpers (paragraph split, X-body clean, title heuristics,
translation-validity gates, X article URL extraction, reader-body hash,
clean reader HTML builder) moved to
:mod:`app.domains.enrich.reader.shared` in Phase 4 step 1 of the
module-refactor blueprint, which eliminates the
``app.services.reader.* → app.api.content_shared`` reverse dependency
the audit flagged.

The remaining HTTP-layer concern is :func:`_serialize_content`, which
maps a ``Content`` ORM instance onto the API response dict
``app.api.contents_crud`` returns. That stays here because it shapes
HTTP responses, not domain logic.

All previously exported reader-helper names are re-exported below so
existing imports (``from app.interfaces.http.content_shared import _split_for_reader``,
``from app.interfaces.http.contents import _split_for_reader``, plus the routes in
``app.api.contents_reader``) keep resolving through Phase 7.
"""

from __future__ import annotations

from app.domains.enrich.reader.shared import (  # noqa: F401 — re-exported for backwards compatibility
    _build_clean_reader_html,
    _build_reader_blocks,
    _clean_x_reader_body,
    _derive_title_from_body,
    _extract_x_article_url,
    _is_valid_title_translation,
    _is_valid_translation_text,
    _looks_like_translation_refusal,
    _reader_body_hash,
    _split_for_reader,
    _title_looks_like_url,
)
from app.models import Content


def _serialize_content(content: Content) -> dict:
    """Serialize a Content ORM instance to a response dict."""
    return {
        "id": content.id,
        "source_id": content.source_id,
        "external_id": content.external_id,
        "title": content.title,
        "translated_title": content.translated_title,
        "summary": content.summary,
        "translated_summary": content.translated_summary,
        "original_url": content.original_url,
        "full_content": content.full_content,
        "content_type": content.content_type,
        "publish_time": content.publish_time,
        "read_status": content.read_status,
        "favorited": content.favorited,
        "archived": content.archived,
        "is_user_edited": bool(getattr(content, "is_user_edited", False)),
        "keyword_matches": content.keyword_matches or [],
        "metadata": content.metadata_ or {},
        "fetched_at": content.fetched_at,
        "created_at": content.created_at,
        "updated_at": content.updated_at,
        "source_name": content.source.name if content.source else None,
    }


__all__ = [
    "_serialize_content",
    "_title_looks_like_url",
    "_looks_like_translation_refusal",
    "_reader_body_hash",
    "_extract_x_article_url",
    "_is_valid_translation_text",
    "_is_valid_title_translation",
    "_split_for_reader",
    "_build_reader_blocks",
    "_derive_title_from_body",
    "_clean_x_reader_body",
    "_build_clean_reader_html",
]
