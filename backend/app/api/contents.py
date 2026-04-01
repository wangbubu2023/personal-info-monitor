"""Content API router aggregator and compatibility exports."""

from app.api.content_shared import (
    _build_clean_reader_html,
    _clean_x_reader_body,
    _derive_title_from_body,
    _extract_x_article_url,
    _is_valid_title_translation,
    _is_valid_translation_text,
    _looks_like_translation_refusal,
    _reader_body_hash,
    _serialize_content,
    _split_for_reader,
    _title_looks_like_url,
)
from app.api.contents_cleanup import _build_low_signal_cleanup_report, router as cleanup_router
from app.api.contents_crud import MAX_CONTENTS_PAGE_SIZE, router as crud_router
from app.api.contents_reader import (
    _ensure_reader_body,
    _ensure_translated_title,
    _fetch_reader_fulltext,
    _fetch_x_article_fulltext,
    _load_source_cookies_for_reader,
    _translate_reader_text,
    router as reader_router,
)
from fastapi import APIRouter

router = APIRouter()
router.include_router(cleanup_router)
router.include_router(reader_router)
# crud_router defines GET "" (list). FastAPI rejects include_router(..., prefix="") when any route path is empty.
router.routes.extend(crud_router.routes)

__all__ = [
    "MAX_CONTENTS_PAGE_SIZE",
    "_build_clean_reader_html",
    "_build_low_signal_cleanup_report",
    "_clean_x_reader_body",
    "_derive_title_from_body",
    "_ensure_reader_body",
    "_ensure_translated_title",
    "_extract_x_article_url",
    "_fetch_reader_fulltext",
    "_fetch_x_article_fulltext",
    "_is_valid_title_translation",
    "_is_valid_translation_text",
    "_load_source_cookies_for_reader",
    "_looks_like_translation_refusal",
    "_reader_body_hash",
    "_serialize_content",
    "_split_for_reader",
    "_title_looks_like_url",
    "_translate_reader_text",
    "router",
]
