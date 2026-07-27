"""Web Clean Pipeline v1 orchestration and extractor candidate selection."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any, Mapping

from bs4 import BeautifulSoup

from app.utils.text import html_to_text_preserving_blocks, normalize_article_text

from .contracts import CleanCandidate, CleanInput, CleanResult, CleanTrace
from .html_standardizer import standardize_html
from .filters import apply_filters
from .markdown import html_to_markdown
from .quality import score_candidate
from .structured import extract_structured_document
from .templates import (
    TemplateValidationError,
    render_template,
    template_from_metadata,
    template_matches,
)


def _main_node_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    node = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=lambda value: value and "content" in " ".join(value if isinstance(value, list) else [value]).lower())
        or soup.body
    )
    return str(node or "")


def _text_from_html(html: str) -> str:
    return normalize_article_text(html_to_text_preserving_blocks(html or "")).strip()


def _candidate(
    *,
    method: str,
    article_html: str,
    article_text: str | None,
    title: str | None,
    url: str,
    schema_confidence: float = 0.0,
) -> CleanCandidate | None:
    text = normalize_article_text(article_text or _text_from_html(article_html)).strip()
    if not text:
        return None
    markdown = html_to_markdown(article_html, base_url=url, standardize=False) if article_html else text
    score, status, signals, rejected = score_candidate(
        method=method,
        title=title,
        html=article_html,
        text=text,
        url=url,
        schema_confidence=schema_confidence,
    )
    return CleanCandidate(
        method=method,
        article_html=article_html,
        article_text=text,
        article_markdown=markdown or text,
        score=score,
        quality_status=status,
        signals=signals,
        rejected_reason=rejected,
    )


class WebDocumentExtractor:
    """Generate, score and explain candidates without bypassing access controls."""

    async def extract(
        self,
        clean_input: CleanInput,
        *,
        max_html_bytes: int = 3_000_000,
    ) -> CleanResult:
        return await asyncio.to_thread(self.extract_sync, clean_input, max_html_bytes=max_html_bytes)

    def extract_sync(
        self,
        clean_input: CleanInput,
        *,
        max_html_bytes: int = 3_000_000,
    ) -> CleanResult:
        started = time.perf_counter()
        template = None
        validation_errors: tuple[str, ...] = ()
        try:
            template = template_from_metadata(clean_input.source_metadata)
        except TemplateValidationError as exc:
            validation_errors = exc.errors

        raw_structured = extract_structured_document(clean_input.raw_html, page_url=clean_input.url)
        if template and not template_matches(template, url=clean_input.url, structured=raw_structured):
            template = None
        standardized = standardize_html(
            clean_input.raw_html,
            base_url=clean_input.url,
            remove_selectors=template.remove_html if template else (),
            max_html_bytes=max_html_bytes,
        )
        normalized_structured = extract_structured_document(standardized.html, page_url=clean_input.url)
        # Scripts are intentionally removed by the standardizer, so preserve
        # same-page JSON-LD/hydration evidence parsed from the raw response.
        structured = dict(raw_structured)
        structured.update(
            {
                key: value
                for key, value in normalized_structured.items()
                if value not in (None, "", [], {})
            }
        )
        candidates: list[CleanCandidate] = []
        template_fields: dict[str, Any] = {}

        if template:
            try:
                template_fields = render_template(
                    template,
                    html=standardized.html,
                    url=clean_input.url,
                    structured=structured,
                )
                article_html = template_fields.get("article_html")
                if isinstance(article_html, list):
                    article_html = "\n".join(str(item) for item in article_html)
                if article_html:
                    filtered_article = (
                        apply_filters(article_html, template.markdown_filters, base_url=clean_input.url)
                        if template.markdown_filters
                        else article_html
                    )
                    has_markdown_filter = any(
                        item.strip().split(":", 1)[0].split("(", 1)[0] == "markdown"
                        for item in template.markdown_filters
                    )
                    item = _candidate(
                        method="template_selector",
                        article_html=str(article_html) if has_markdown_filter else str(filtered_article),
                        article_text=None if not has_markdown_filter else _text_from_html(str(article_html)),
                        title=str(template_fields.get("title") or structured.get("title") or "") or None,
                        url=clean_input.url,
                    )
                    if item:
                        if has_markdown_filter:
                            item = replace(item, article_markdown=str(filtered_article))
                        candidates.append(item)
            except (TemplateValidationError, ValueError, TypeError) as exc:
                validation_errors = (*validation_errors, str(exc))

        structured_text = structured.get("article_text")
        if structured_text:
            method = f"structured_{structured.get('article_method') or 'data'}"
            item = _candidate(
                method=method,
                article_html="",
                article_text=str(structured_text),
                title=str(structured.get("title") or "") or None,
                url=clean_input.url,
                schema_confidence=1.0,
            )
            if item:
                candidates.append(item)

        readability_html = self._readability_html(standardized.html)
        if readability_html:
            item = _candidate(
                method="readability",
                article_html=readability_html,
                article_text=None,
                title=str(structured.get("title") or "") or None,
                url=clean_input.url,
            )
            if item:
                candidates.append(item)

        trafilatura_text = self._trafilatura_text(standardized.html, clean_input.url)
        if trafilatura_text:
            item = _candidate(
                method="trafilatura",
                article_html="",
                article_text=trafilatura_text,
                title=str(structured.get("title") or "") or None,
                url=clean_input.url,
            )
            if item:
                candidates.append(item)

        fallback_html = _main_node_html(standardized.html)
        fallback = _candidate(
            method="beautifulsoup",
            article_html=fallback_html,
            article_text=None,
            title=str(structured.get("title") or "") or None,
            url=clean_input.url,
        )
        if fallback:
            candidates.append(fallback)

        accepted = [candidate for candidate in candidates if not candidate.rejected_reason]
        pool = accepted or candidates
        if pool:
            best = max(pool, key=lambda candidate: (candidate.score, len(candidate.article_text)))
        else:
            best = CleanCandidate(
                method="beautifulsoup",
                article_html="",
                article_text="",
                article_markdown="",
                score=0.0,
                quality_status="empty",
                signals={"paragraph_count": 0, "link_density": 0.0},
                rejected_reason="empty",
            )

        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        trace = CleanTrace(
            duration_ms=duration_ms,
            standardizer=standardized.trace,
            candidates=tuple(candidate.trace_payload() for candidate in candidates),
            selected_method=best.method,
            template_validation_errors=validation_errors,
            shadow_materialized_count=int(standardized.trace.get("shadow_materialized_count") or 0),
        ).to_dict()
        published = structured.get("published_time")
        return CleanResult(
            url=clean_input.url,
            title=str(template_fields.get("title") or structured.get("title") or "").strip() or None,
            author=str(template_fields.get("author") or structured.get("author") or "").strip() or None,
            published_time=published if hasattr(published, "isoformat") else None,
            canonical_url=str(structured.get("canonical_url") or "").strip() or None,
            site_name=str(structured.get("site_name") or "").strip() or None,
            language=str(structured.get("language") or "").strip() or None,
            article_html=best.article_html,
            article_text=best.article_text,
            article_markdown=best.article_markdown,
            clean_full_html=standardized.html,
            extraction_method=best.method,
            template_id=template.id if template else None,
            quality_status=best.quality_status,
            quality_score=best.score,
            trace=trace,
            metadata={
                "published_time_raw": structured.get("published_time_raw"),
                "image": structured.get("image"),
                "quality_signals": best.signals,
                "shadow": bool(standardized.trace.get("shadow")),
            },
        )

    @staticmethod
    def _readability_html(html: str) -> str:
        try:
            from readability import Document

            summary = Document(html).summary()
            return summary if summary and len(summary) >= 100 else ""
        except (ImportError, ValueError, TypeError, AttributeError):
            return ""

    @staticmethod
    def _trafilatura_text(html: str, url: str) -> str:
        try:
            import trafilatura

            return str(
                trafilatura.extract(
                    html,
                    url=url,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False,
                )
                or ""
            )
        except (ImportError, ValueError, TypeError, AttributeError):
            return ""
