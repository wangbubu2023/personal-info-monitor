"""Rule-based dimension scoring for pim-score-v2."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from app.domains.score.score_subjective import SubjectiveScoreResult
from app.domains.score.score_vocab import (
    AUTHORITY_TYPE_BONUS,
    CASUALTY_TERMS,
    COMMERCE_SIGNALS,
    DISASTER_TERMS,
    EVENT_PATTERNS,
    IMPACT_CAPS,
    LANE_KEYWORDS,
    MARKET_OFFERING_EXEMPT,
    NARROW_SCOPE_SIGNALS,
    REACH_KEYWORDS,
    REACH_SCORES,
    SOURCE_STARS_AUTHORITY,
)
from app.domains.score.score_vocab_runtime import RuntimeScoringVocab
from app.domains.score.score_utils import normalize_authority_type, normalize_source_stars


def _corpus(title: str, summary: str | None, full_content: str | None, *, limit: int = 800) -> str:
    body = (full_content or "")[:limit]
    return f"{title or ''} {summary or ''} {body}".lower()


def _headline_corpus(title: str, summary: str | None, *, limit: int = 600) -> str:
    """Title + summary only — used for salience/reach to avoid body incidental hits."""
    return f"{title or ''} {summary or ''}"[:limit].lower()


def detect_impact_cap_scope(title: str, summary: str | None) -> str | None:
    """Return cap bucket for low-impact commerce / product-scoped stories."""
    title_l = (title or "").lower()
    headline = _headline_corpus(title, summary)

    if any(ex.lower() in headline for ex in MARKET_OFFERING_EXEMPT):
        return None

    if any(sig.lower() in title_l for sig in COMMERCE_SIGNALS):
        return "commerce"
    if any(sig.lower() in headline for sig in COMMERCE_SIGNALS):
        return "commerce"
    if any(sig.lower() in title_l for sig in NARROW_SCOPE_SIGNALS):
        return "narrow"
    if any(sig.lower() in headline for sig in NARROW_SCOPE_SIGNALS):
        return "narrow"
    return None


def apply_disaster_salience_floor(title: str, summary: str | None, salience: float) -> float:
    """Raise salience for disasters, especially casualties named in the headline."""
    headline = _headline_corpus(title, summary)
    title_l = (title or "").lower()
    has_disaster = any(term.lower() in headline for term in DISASTER_TERMS)
    has_casualty = any(term.lower() in headline for term in CASUALTY_TERMS)
    title_disaster = any(term.lower() in title_l for term in DISASTER_TERMS)
    title_casualty = any(term.lower() in title_l for term in CASUALTY_TERMS)
    if title_disaster and title_casualty:
        return max(salience, 9.0)
    if has_disaster and has_casualty:
        return max(salience, 8.5)
    if has_disaster:
        return max(salience, 7.5)
    return salience


def apply_impact_caps(dimensions: dict[str, float], scope: str | None) -> dict[str, float]:
    if not scope or scope not in IMPACT_CAPS:
        return dimensions
    caps = IMPACT_CAPS[scope]
    out = dict(dimensions)
    for key, ceiling in caps.items():
        if key in out:
            out[key] = round(min(out[key], ceiling), 1)
    return out


def scoring_title(content: Any | None, *, title: str = "") -> str:
    """Headline used for rule scoring (original language only)."""
    if title:
        return title.strip()
    if content is None:
        return ""
    return (getattr(content, "title", None) or "").strip()


def classify_lane(title: str, summary: str | None, full_content: str | None) -> str:
    title_l = (title or "").lower()
    corpus = _corpus(title, summary, full_content)
    best_lane = "other"
    best_score = 0.0
    for lane, keywords in LANE_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            kw_l = kw.lower()
            if kw_l in title_l:
                score += 2.0
            elif kw_l in corpus:
                score += 1.0
        if score > best_score:
            best_score = score
            best_lane = lane
    return best_lane if best_score >= 1.0 else "other"


def score_salience(
    title: str,
    summary: str | None,
    full_content: str | None,
    *,
    runtime_vocab: RuntimeScoringVocab | None = None,
) -> float:
    runtime_vocab = runtime_vocab or RuntimeScoringVocab.build()
    headline = _headline_corpus(title, summary)
    base = runtime_vocab.entity_tier_score(headline)
    bonus = 0.0
    for _key, (add, keywords) in EVENT_PATTERNS.items():
        if any(kw.lower() in headline for kw in keywords):
            bonus = max(bonus, add)
    raw = base + bonus
    raw = runtime_vocab.salience_with_user_match_floor(raw, _corpus(title, summary, full_content, limit=2000))
    raw = apply_disaster_salience_floor(title, summary, raw)
    return round(min(10.0, raw), 1)


def score_reach(
    title: str,
    summary: str | None,
    full_content: str | None,
    *,
    runtime_vocab: "RuntimeScoringVocab | None" = None,
) -> float:
    del full_content  # reach is headline-scoped; body mentions are often incidental
    corpus = _headline_corpus(title, summary)
    title_l = (title or "").lower()
    has_disaster = any(term.lower() in corpus for term in DISASTER_TERMS)
    if has_disaster and any(k in title_l for k in ("多地", "多个省份", "数个省份", "跨省")):
        if any(term.lower() in title_l for term in CASUALTY_TERMS):
            return REACH_SCORES["systemic"]
        return REACH_SCORES["sector"]
    for level in ("systemic", "sector", "local"):
        if any(kw.lower() in corpus for kw in REACH_KEYWORDS[level]):
            return REACH_SCORES[level]
    # S-tier entity in headline → major_entity reach (between entity and sector)
    if runtime_vocab is not None:
        from app.domains.score.score_vocab import ENTITY_TIER_S
        if any(term.lower() in corpus for term in ENTITY_TIER_S):
            return REACH_SCORES["major_entity"]
    return REACH_SCORES["entity"]


def score_authority(source_metadata: Mapping[str, Any] | None) -> float:
    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}
    stars = normalize_source_stars(source_metadata.get("source_stars"))
    base = SOURCE_STARS_AUTHORITY.get(stars, 4.0)
    auth_type = normalize_authority_type(source_metadata.get("authority_type"))
    bonus = AUTHORITY_TYPE_BONUS.get(auth_type, 0.0)
    return round(min(10.0, base + bonus), 1)


def _paragraph_count(text: str) -> int:
    if not text:
        return 0
    parts = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?。！？])\s+", text) if p.strip()]
    return len([p for p in parts if len(p) >= 40]) or (1 if len(text) >= 80 else 0)


def score_depth(
    *,
    title: str = "",
    summary: str | None = None,
    full_content: str | None = None,
    content_metadata: Mapping[str, Any] | None = None,
    content_type: str = "",
    content: Any | None = None,
) -> float:
    content_metadata = content_metadata if isinstance(content_metadata, Mapping) else {}
    body = (full_content or "").strip()
    status = str(content_metadata.get("fulltext_status") or "partial").strip()
    ctype = (content_type or "").strip().lower()

    paragraphs = _paragraph_count(body)
    structure = min(4.0, paragraphs * 0.8)
    digit_count = len(re.findall(r"\d", body))
    quote_markers = body.count('"') + body.count('"') + body.count("'") + body.count("「")
    fact_density = min(4.0, digit_count * 0.15 + quote_markers * 0.4)

    type_adjust = 0.0
    if ctype == "x":
        from app.domains.fetch.acceptance import is_x_long_article

        if content is not None and is_x_long_article(content, content_metadata):
            type_adjust = 1.0
        else:
            type_adjust = 2.0
    elif status == "full":
        type_adjust = 1.0

    return round(min(10.0, structure + fact_density + type_adjust), 1)


def compute_rule_dimension_scores(
    *,
    title: str = "",
    summary: str | None = None,
    full_content: str | None = None,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    content_type: str = "",
    content: Any | None = None,
    subjective: SubjectiveScoreResult | None = None,
    user_keyword_terms: Sequence[str] | None = None,
    matched_user_terms: Sequence[str] | None = None,
) -> tuple[str, dict[str, float], RuntimeScoringVocab]:
    runtime_vocab = RuntimeScoringVocab.build(user_keyword_terms, matched_user_terms)
    resolved_title = scoring_title(content, title=title)
    lane = classify_lane(resolved_title, summary, full_content)
    subj = subjective or SubjectiveScoreResult(score=5.0, source="fixed_baseline")
    dimensions = {
        "salience": score_salience(resolved_title, summary, full_content, runtime_vocab=runtime_vocab),
        "reach": score_reach(resolved_title, summary, full_content, runtime_vocab=runtime_vocab),
        "authority": score_authority(source_metadata),
        "depth": score_depth(
            title=resolved_title,
            summary=summary,
            full_content=full_content,
            content_metadata=content_metadata,
            content_type=content_type,
            content=content,
        ),
        "subjective": round(max(0.0, min(10.0, float(subj.score))), 1),
    }
    dimensions = apply_impact_caps(dimensions, detect_impact_cap_scope(resolved_title, summary))
    return lane, dimensions, runtime_vocab
