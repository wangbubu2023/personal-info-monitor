"""Candidate metrics and selection policy for web-clean extraction."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from bs4 import BeautifulSoup

from app.domains.fetch.fulltext_quality import assess_fulltext_quality

METHOD_PRIORITY = {
    "template_selector": 0.12,
    "structured_json_ld": 0.10,
    "structured_next_data": 0.09,
    "structured": 0.09,
    "readability": 0.07,
    "trafilatura": 0.05,
    "beautifulsoup": 0.01,
}


def paragraph_count(text: str) -> int:
    parts = [part.strip() for part in re.split(r"\n{2,}|(?<=[.!?。！？])\s+", text or "") if part.strip()]
    return len([part for part in parts if len(part) >= 40])


def link_density(html: str) -> float:
    soup = BeautifulSoup(html or "", "lxml")
    total = soup.get_text(" ", strip=True)
    linked = " ".join(node.get_text(" ", strip=True) for node in soup.find_all("a"))
    return round(len(linked) / max(1, len(total)), 4)


def title_similarity(title: str | None, text: str) -> float | None:
    if not title:
        return None
    head = (text or "")[: max(500, len(title) * 5)]
    return round(SequenceMatcher(None, title.lower(), head.lower()).quick_ratio(), 4)


def score_candidate(
    *,
    method: str,
    title: str | None,
    html: str,
    text: str,
    url: str,
    schema_confidence: float = 0.0,
) -> tuple[float, str, dict[str, Any], str | None]:
    verdict = assess_fulltext_quality(title=title or "", body=text, url=url)
    density = link_density(html)
    paragraphs = paragraph_count(text)
    title_match = title_similarity(title, text)
    signals: dict[str, Any] = {
        "text_chars": len(text),
        "word_count": len(re.findall(r"\w+", text)),
        "paragraph_count": paragraphs,
        "title_match_score": title_match,
        "link_density": density,
        "boilerplate_ratio": verdict.boilerplate_ratio,
        "blocked_marker_score": 1.0 if verdict.is_blocked() else 0.0,
        "schema_confidence": schema_confidence,
    }
    score = verdict.score * 0.68
    score += min(0.12, len(text) / 20_000)
    score += min(0.08, paragraphs / 100)
    score += METHOD_PRIORITY.get(method, 0.0)
    score += min(0.08, schema_confidence * 0.08)
    score -= max(0.0, density - 0.30) * 0.6
    score -= (verdict.boilerplate_ratio or 0.0) * 0.18
    rejected_reason: str | None = None
    if verdict.is_blocked():
        rejected_reason = verdict.reason
    elif density > 0.45 and len(text) < 1000:
        rejected_reason = "high_link_density"
    elif len(text) < 100:
        rejected_reason = "too_short"
    if rejected_reason:
        score = min(score, 0.15)
    return round(max(0.0, min(1.0, score)), 4), verdict.status, signals, rejected_reason
