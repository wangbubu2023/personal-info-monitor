"""Explain pim-score-v2 results for debugging and the score lab UI."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.domains.score.score_rules import (
    apply_impact_caps,
    classify_lane,
    detect_impact_cap_scope,
    score_authority,
    score_depth,
    score_reach,
    score_salience,
    scoring_title,
    _corpus,
    _headline_corpus,
)
from app.domains.score.score_subjective import SubjectiveScoreResult, resolve_subjective_score
from app.domains.score.score_vocab import (
    COMMERCE_SIGNALS,
    DIMENSION_LABELS,
    EVENT_PATTERNS,
    IMPACT_CAPS,
    LANE_KEYWORDS,
    LANE_LABELS,
    MARKET_OFFERING_EXEMPT,
    NARROW_SCOPE_SIGNALS,
    REACH_KEYWORDS,
)
from app.domains.score.score_vocab_runtime import RuntimeScoringVocab, extract_keyword_vocab_terms, extract_matched_keyword_terms
from app.domains.score.scoring import ScoringConfig, calculate_article_score


def _match_terms(corpus: str, terms: Sequence[str], *, limit: int = 12) -> list[str]:
    corpus_l = (corpus or "").lower()
    hits: list[str] = []
    for term in terms:
        token = str(term).strip()
        if not token:
            continue
        if token.lower() in corpus_l:
            hits.append(token)
        if len(hits) >= limit:
            break
    return hits


def compute_lane_scores(title: str, summary: str | None, full_content: str | None) -> dict[str, float]:
    title_l = (title or "").lower()
    corpus = _corpus(title, summary, full_content)
    scores: dict[str, float] = {}
    for lane, keywords in LANE_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            kw_l = kw.lower()
            if kw_l in title_l:
                score += 2.0
            elif kw_l in corpus:
                score += 1.0
        if score > 0:
            scores[lane] = round(score, 1)
    return scores


def _entity_hits(vocab: RuntimeScoringVocab, corpus: str) -> list[dict[str, Any]]:
    from app.domains.score.score_vocab import ENTITY_TIER_SCORES

    corpus_l = (corpus or "").lower()
    hits: list[dict[str, Any]] = []
    for tier, terms in (
        ("S", vocab.entity_tier_s),
        ("A", vocab.entity_tier_a),
        ("B", vocab.entity_tier_b),
    ):
        for term in terms:
            if term.lower() in corpus_l:
                hits.append(
                    {
                        "term": term,
                        "tier": tier,
                        "score": ENTITY_TIER_SCORES[tier],
                        "user_keyword": term in vocab.user_keyword_terms,
                    }
                )
    return hits[:20]


def _event_pattern_hits(headline: str) -> list[dict[str, Any]]:
    headline_l = (headline or "").lower()
    hits: list[dict[str, Any]] = []
    for key, (bonus, keywords) in EVENT_PATTERNS.items():
        matched = [kw for kw in keywords if kw.lower() in headline_l]
        if matched:
            hits.append({"pattern": key, "bonus": bonus, "matched": matched[:5]})
    return hits


def _reach_level(title: str, summary: str | None) -> str:
    from app.domains.score.score_vocab import CASUALTY_TERMS, DISASTER_TERMS

    corpus = _headline_corpus(title, summary)
    title_l = (title or "").lower()
    has_disaster = any(term.lower() in corpus for term in DISASTER_TERMS)
    if has_disaster and any(k in title_l for k in ("多地", "多个省份", "数个省份", "跨省")):
        if any(term.lower() in title_l for term in CASUALTY_TERMS):
            return "systemic"
        return "sector"
    for level in ("systemic", "sector", "local"):
        if any(kw.lower() in corpus for kw in REACH_KEYWORDS[level]):
            return level
    return "entity"


def _weight_breakdown(dimension_scores: Mapping[str, Any], config: ScoringConfig | None = None) -> list[dict[str, Any]]:
    config = config or ScoringConfig()
    rows: list[dict[str, Any]] = []
    for name, weight in config.weights.items():
        score = float(dimension_scores.get(name) or 0.0)
        rows.append(
            {
                "dimension": name,
                "label": DIMENSION_LABELS.get(name, name),
                "weight": weight,
                "score": score,
                "weighted": round(score * weight, 3),
            }
        )
    return rows


def explain_content_score(
    *,
    title: str = "",
    summary: str | None = None,
    full_content: str | None = None,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    content_type: str = "",
    content: Any | None = None,
    user_keyword_terms: Sequence[str] | None = None,
    matched_user_terms: Sequence[str] | None = None,
    stored_metadata: Mapping[str, Any] | None = None,
    config: ScoringConfig | None = None,
) -> dict[str, Any]:
    """Recompute score and return a structured explanation payload."""

    config = config or ScoringConfig()
    content_metadata = dict(content_metadata or {})
    source_metadata = dict(source_metadata or {})
    stored_metadata = dict(stored_metadata or {})

    resolved_title = scoring_title(content, title=title)
    headline = _headline_corpus(resolved_title, summary)
    depth_corpus = _corpus(resolved_title, summary, full_content, limit=800)

    runtime_vocab = RuntimeScoringVocab.build(user_keyword_terms, matched_user_terms)
    subjective = resolve_subjective_score(content, lane="other")

    dimensions_before_cap = {
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
        "subjective": round(max(0.0, min(10.0, float(subjective.score))), 1),
    }
    impact_cap_scope = detect_impact_cap_scope(resolved_title, summary)
    dimensions_after_cap = apply_impact_caps(dict(dimensions_before_cap), impact_cap_scope)

    lane_scores = compute_lane_scores(resolved_title, summary, full_content)
    lane = classify_lane(resolved_title, summary, full_content)

    result = calculate_article_score(
        dimensions_after_cap,
        content_metadata=content_metadata,
        source_metadata=source_metadata,
        lane=lane,
        subjective_meta=subjective.to_metadata(),
        config=config,
    )

    caps_applied: dict[str, float] = {}
    if impact_cap_scope and impact_cap_scope in IMPACT_CAPS:
        for key, ceiling in IMPACT_CAPS[impact_cap_scope].items():
            before = dimensions_before_cap.get(key)
            after = dimensions_after_cap.get(key)
            if before is not None and after is not None and after < before:
                caps_applied[key] = ceiling

    stored_score = stored_metadata.get("article_score", stored_metadata.get("final_score"))
    recomputed_score = result["article_score"]
    score_delta = None
    if stored_score is not None:
        try:
            score_delta = round(float(recomputed_score) - float(stored_score), 2)
        except (TypeError, ValueError):
            score_delta = None

    return {
        "score_version": result["score_version"],
        "lane": lane,
        "lane_label": LANE_LABELS.get(lane, lane),
        "lane_scores": lane_scores,
        "scoring_title": resolved_title,
        "corpus": {
            "headline": headline[:600],
            "depth_prefix": depth_corpus[:800],
        },
        "impact_cap_scope": impact_cap_scope,
        "impact_caps_applied": caps_applied,
        "matched_signals": {
            "commerce": _match_terms(headline, COMMERCE_SIGNALS),
            "narrow": _match_terms(headline, NARROW_SCOPE_SIGNALS),
            "market_offering_exempt": _match_terms(headline, MARKET_OFFERING_EXEMPT),
        },
        "entity_hits": _entity_hits(runtime_vocab, headline),
        "event_pattern_hits": _event_pattern_hits(headline),
        "reach_level": _reach_level(resolved_title, summary),
        "user_keywords": {
            "configured": list(runtime_vocab.user_keyword_terms),
            "matched": list(runtime_vocab.matched_user_terms),
        },
        "dimension_scores_before_cap": dimensions_before_cap,
        "dimension_scores": dimensions_after_cap,
        "weight_breakdown": _weight_breakdown(dimensions_after_cap, config),
        "weighted_sum_0_10": round(sum(row["weighted"] for row in _weight_breakdown(dimensions_after_cap, config)), 3),
        "thresholds": {
            "selected": config.selected_threshold,
            "candidate": config.candidate_threshold,
            "minimum_selected_confidence": config.minimum_selected_confidence,
        },
        "recomputed": result,
        "stored": {
            "article_score": stored_score,
            "final_score": stored_metadata.get("final_score"),
            "selection_status": stored_metadata.get("selection_status"),
            "dimension_scores": stored_metadata.get("dimension_scores"),
            "score_version": stored_metadata.get("score_version"),
            "fetch_acceptance": stored_metadata.get("fetch_acceptance"),
            "fulltext_status": stored_metadata.get("fulltext_status"),
            "score_confidence": stored_metadata.get("score_confidence"),
        },
        "score_delta": score_delta,
        "fetch_acceptance": content_metadata.get("fetch_acceptance"),
        "fulltext_status": content_metadata.get("fulltext_status"),
    }


def explain_content_row(content: Any, *, keyword_objects: Sequence[Any] | None = None) -> dict[str, Any]:
    """Build explain payload from a Content ORM row."""

    meta = dict(getattr(content, "metadata_", None) or {})
    source = getattr(content, "source", None)
    source_meta = dict(getattr(source, "metadata_", None) or {}) if source else {}
    keyword_objects = keyword_objects or []
    keyword_matches = getattr(content, "keyword_matches", None) or []

    payload = explain_content_score(
        title=getattr(content, "title", "") or "",
        summary=getattr(content, "summary", None),
        full_content=getattr(content, "full_content", None),
        content_metadata=meta,
        source_metadata=source_meta,
        content_type=getattr(content, "content_type", "") or "",
        content=content,
        user_keyword_terms=extract_keyword_vocab_terms(keyword_objects) if keyword_objects else None,
        matched_user_terms=extract_matched_keyword_terms(keyword_matches) if keyword_matches else None,
        stored_metadata=meta,
    )
    payload["content"] = {
        "id": str(getattr(content, "id", "")),
        "title": getattr(content, "title", "") or "",
        "summary": getattr(content, "summary", None),
        "original_url": getattr(content, "original_url", "") or "",
        "content_type": getattr(content, "content_type", "") or "",
        "publish_time": getattr(content, "publish_time", None),
        "fetched_at": getattr(content, "fetched_at", None),
        "source_name": getattr(source, "name", None) if source else None,
    }
    return payload
