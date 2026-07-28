"""Content-quality metadata stamping for already-kept Content rows.

This is the *positive* counterpart of :mod:`app.domains.ingest.quality`:

* :mod:`quality` — decides whether to **reject** a raw item (boolean filter).
* :mod:`quality_metadata` — decides what **quality signals** to stamp into
  ``contents.metadata`` for items we keep (so downstream scoring / digests
  can reason about evidence quality).

Moved out of ``app.services.content_quality_service`` as part of Phase 3
step 4 of the module-refactor blueprint. The old service path remains as a
re-export shim through Phase 7 so consumers that haven't been migrated
yet (``processors/content_processor.py``, ``tasks/process_tasks.py``) and
the existing test file (``tests/test_content_quality_scoring.py``)
continue to resolve their imports.

The ingest domain is the natural home: the fetch path must stay
model-free, these helpers only look at already-available
title/summary/body text + lightweight fetch metadata, and the result is
written straight to ``Content.metadata_`` by :func:`build_raw_content_objects`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.utils.text import strip_html_tags

from app.domains.contracts.content_quality import (
    FULLTEXT_STATUS_BLOCKED,
    FULLTEXT_STATUS_FULL,
    FULLTEXT_STATUS_PARTIAL,
    FULLTEXT_STATUS_SUMMARY_ONLY,
    FULLTEXT_STATUS_TITLE_ONLY,
)

_BLOCKED_FLAGS = (
    "blocked",
    "paywall_detected",
    "auth_required_but_missing",
    "cookie_fulltext_required",
)
_BLOCKED_STATUS_CODES = {401, 402, 403, 451}


@dataclass(frozen=True)
class ContentQuality:
    fulltext_status: str
    content_quality: float
    score_basis: str
    signals: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "fulltext_status": self.fulltext_status,
            "content_quality": self.content_quality,
            "score_basis": self.score_basis,
            "content_quality_signals": self.signals,
        }


def _clean(text: Any) -> str:
    return strip_html_tags(str(text or "")).strip()


def effective_listing_summary(
    summary: str | None,
    translated_summary: str | None = None,
) -> str:
    """Pick the longer cleaned listing summary (translation may be shorter than source)."""
    candidates = [_clean(translated_summary), _clean(summary)]
    candidates = [text for text in candidates if text]
    if not candidates:
        return ""
    return max(candidates, key=len)


def _paragraph_count(text: str) -> int:
    if not text:
        return 0
    parts = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?。！？])\s+", text) if p.strip()]
    meaningful = [p for p in parts if len(p) >= 40]
    if meaningful:
        return len(meaningful)
    return 1 if len(text) >= 80 else 0


def _looks_blocked(metadata: Mapping[str, Any], *, body_len: int, summary_len: int) -> bool:
    for key in _BLOCKED_FLAGS:
        value = metadata.get(key)
        if value is True:
            if key == "cookie_fulltext_required":
                return not metadata.get("cookie_fulltext_obtained") and body_len < 120
            return True

    status_code = metadata.get("http_status") or metadata.get("status_code")
    try:
        if int(status_code) in _BLOCKED_STATUS_CODES:
            return True
    except (TypeError, ValueError):
        pass

    outcome = metadata.get("last_fetch_outcome")
    if isinstance(outcome, Mapping):
        code = str(outcome.get("code") or "").lower()
        severity = str(outcome.get("severity") or "").lower()
        if severity == "error" and any(token in code for token in ("auth", "paywall", "forbidden", "blocked")):
            return True

    fetch_diag = metadata.get("fetch_diagnostics")
    if isinstance(fetch_diag, Mapping) and fetch_diag.get("shell_like"):
        return body_len < 120 and summary_len < 120

    warning = " ".join(
        str(metadata.get(key) or "")
        for key in ("warning", "last_warning", "error", "last_error")
    ).lower()
    if any(token in warning for token in ("paywall", "forbidden", "login required", "403", "captcha")):
        return body_len < 120 and summary_len < 120
    return False


def assess_content_quality(
    *,
    title: str = "",
    full_content: str | None = None,
    summary: str | None = None,
    translated_summary: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ContentQuality:
    """Classify text availability and evidence quality for downstream scoring."""

    metadata = metadata if isinstance(metadata, Mapping) else {}
    title_text = _clean(title)
    body = _clean(full_content)
    summary_text = effective_listing_summary(summary, translated_summary)

    body_len = len(body)
    summary_len = len(summary_text)
    title_len = len(title_text)
    paragraphs = _paragraph_count(body)
    blocked = _looks_blocked(metadata, body_len=body_len, summary_len=summary_len)
    trusted_structured_short = (
        str(metadata.get("article_extract_method") or "") == "structured:cls_next_data"
        and body_len >= 20
        and bool(title_text)
        and title_text in body
    )

    if blocked:
        status = FULLTEXT_STATUS_BLOCKED
        basis = "blocked"
    elif trusted_structured_short:
        status = FULLTEXT_STATUS_FULL
        basis = "trusted_structured_fulltext"
    elif body_len >= 1200 and paragraphs >= 3:
        status = FULLTEXT_STATUS_FULL
        basis = "full_content"
    elif body_len >= 400 or (body_len >= 220 and paragraphs >= 2):
        status = FULLTEXT_STATUS_PARTIAL
        basis = "full_content"
    elif summary_len >= 50:
        status = FULLTEXT_STATUS_SUMMARY_ONLY
        basis = "summary"
    elif title_len > 0:
        status = FULLTEXT_STATUS_TITLE_ONLY
        basis = "title"
    else:
        status = FULLTEXT_STATUS_BLOCKED
        basis = "blocked"

    length_score = min(1.0, body_len / 1600.0)
    paragraph_score = min(1.0, paragraphs / 5.0)
    summary_score = min(1.0, summary_len / 300.0) * 0.45
    if status == FULLTEXT_STATUS_FULL:
        quality = max(0.78, 0.65 * length_score + 0.35 * paragraph_score)
    elif status == FULLTEXT_STATUS_PARTIAL:
        quality = max(0.45, min(0.74, 0.55 * length_score + 0.35 * paragraph_score + 0.10 * summary_score))
    elif status == FULLTEXT_STATUS_SUMMARY_ONLY:
        quality = max(0.24, min(0.48, summary_score))
    elif status == FULLTEXT_STATUS_TITLE_ONLY:
        quality = 0.12
    else:
        quality = 0.0

    signals = {
        "body_length": body_len,
        "summary_length": summary_len,
        "title_length": title_len,
        "paragraph_count": paragraphs,
        "blocked": blocked,
        "trusted_structured_short": trusted_structured_short,
    }
    return ContentQuality(
        fulltext_status=status,
        content_quality=round(float(quality), 3),
        score_basis=basis,
        signals=signals,
    )


def merge_content_quality_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    title: str = "",
    full_content: str | None = None,
    summary: str | None = None,
    translated_summary: str | None = None,
) -> dict[str, Any]:
    """Return a metadata dict stamped with the latest content-quality fields."""

    merged = dict(metadata or {})
    quality = assess_content_quality(
        title=title,
        full_content=full_content,
        summary=summary,
        translated_summary=translated_summary,
        metadata=merged,
    )
    merged.update(quality.to_metadata())
    return merged


__all__ = [
    "FULLTEXT_STATUS_FULL",
    "FULLTEXT_STATUS_PARTIAL",
    "FULLTEXT_STATUS_SUMMARY_ONLY",
    "FULLTEXT_STATUS_TITLE_ONLY",
    "FULLTEXT_STATUS_BLOCKED",
    "ContentQuality",
    "assess_content_quality",
    "merge_content_quality_metadata",
]
