"""Stable data contracts shared by web fetch, ingest, Reader and export."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CleanInput:
    url: str
    raw_html: str
    source_id: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    hydrated: bool = False


@dataclass(frozen=True)
class CleanCandidate:
    method: str
    article_html: str
    article_text: str
    article_markdown: str
    score: float
    quality_status: str
    signals: dict[str, Any] = field(default_factory=dict)
    rejected_reason: str | None = None

    def trace_payload(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "score": round(float(self.score), 4),
            "quality_status": self.quality_status,
            "text_chars": len(self.article_text),
            "rejected_reason": self.rejected_reason,
            "signals": self.signals,
        }


@dataclass(frozen=True)
class CleanTrace:
    version: str = "v1"
    duration_ms: float = 0.0
    standardizer: dict[str, Any] = field(default_factory=dict)
    candidates: tuple[dict[str, Any], ...] = ()
    selected_method: str | None = None
    template_validation_errors: tuple[str, ...] = ()
    shadow_materialized_count: int = 0
    shadow_timeout: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    triggers: tuple[str, ...] = ()
    article_html: str | None = None
    title: str | None = None
    author: str | None = None
    published: str | None = None
    remove_html: tuple[str, ...] = ()
    markdown_filters: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class CleanResult:
    url: str
    title: str | None
    author: str | None
    published_time: datetime | None
    canonical_url: str | None
    site_name: str | None
    language: str | None
    article_html: str
    article_text: str
    article_markdown: str
    clean_full_html: str | None
    extraction_method: str
    template_id: str | None
    quality_status: str
    quality_score: float
    trace: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self, *, include_trace: bool = True) -> dict[str, Any]:
        signals = self.metadata.get("quality_signals", {})
        payload: dict[str, Any] = {
            "version": "v1",
            "extraction_method": self.extraction_method,
            "template_id": self.template_id,
            "quality_status": self.quality_status,
            "quality_score": round(float(self.quality_score), 4),
            "text_chars": len(self.article_text),
            "paragraph_count": signals.get("paragraph_count", 0),
            "title_match_score": signals.get("title_match_score"),
            "boilerplate_ratio": signals.get("boilerplate_ratio"),
            "link_density": signals.get("link_density"),
            "canonical_url": self.canonical_url,
            "published_time_raw": self.metadata.get("published_time_raw"),
            "shadow": bool(self.metadata.get("shadow")),
        }
        if include_trace:
            payload["trace"] = self.trace
        return {key: value for key, value in payload.items() if value is not None}
