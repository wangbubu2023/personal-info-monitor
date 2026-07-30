"""Deterministic scoring helpers for PIM selection (pim-score-v2).

Rule-based dimensions are computed in :mod:`score_rules`; event-layer
momentum/corroboration lives in :mod:`score_event`. LLM subjective scoring
is reserved via :mod:`score_subjective` (fixed baseline until enabled).

Fetch completeness is gated by :mod:`app.domains.fetch.acceptance` before scoring runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.domains.score.score_rules import compute_rule_dimension_scores
from app.domains.score.score_subjective import resolve_subjective_score
from app.domains.score.score_vocab_runtime import (
    extract_keyword_vocab_terms,
    extract_matched_keyword_terms,
)
from app.domains.score.score_utils import (
    clamp_float,
    normalize_authority_type,
    normalize_dimension_score,
    normalize_source_stars,
)
from app.domains.score.score_vocab import DIMENSION_LABELS, LANE_LABELS

SCORE_VERSION = "pim-score-v2.3"

FULLTEXT_CONFIDENCE = {
    "full": 0.92,
    "partial": 0.72,
    "summary_only": 0.48,
    "title_only": 0.22,
    "blocked": 0.0,
}

FULLTEXT_STATUS_LABELS = {
    "full": "全文",
    "partial": "部分正文",
    "summary_only": "摘要",
    "title_only": "标题",
    "blocked": "受限页面",
}


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, float] = field(default_factory=lambda: {
        "salience": 0.30,
        "reach": 0.25,
        "authority": 0.25,
        "depth": 0.20,
        "subjective": 0.0,   # disabled until LLM subjective scoring is live
    })
    selected_threshold: float = 70.0
    candidate_threshold: float = 55.0
    minimum_selected_confidence: float = 0.65


def compute_domain_match(source_metadata: Mapping[str, Any], text: str) -> float:
    """Legacy helper retained for diagnostics; not used in pim-score-v2 article_score."""

    raw_focus = source_metadata.get("domain_focus")
    if not isinstance(raw_focus, list) or not raw_focus:
        return 1.0

    normalized = (text or "").lower()
    focus_terms = [str(term).strip().lower() for term in raw_focus if str(term).strip()]
    if not focus_terms:
        return 1.0

    hits = sum(1 for term in focus_terms if term in normalized)
    if hits <= 0:
        return 0.25
    return min(1.0, 0.55 + 0.20 * hits)


def compute_score_confidence(content_metadata: Mapping[str, Any], recommendation_confidence: Any = None) -> float:
    status = str(content_metadata.get("fulltext_status") or "").strip() or "partial"
    evidence_confidence = FULLTEXT_CONFIDENCE.get(status, 0.72)
    quality = clamp_float(content_metadata.get("content_quality"), default=evidence_confidence, min_value=0.0, max_value=1.0)
    if recommendation_confidence is None:
        return round(0.65 * evidence_confidence + 0.35 * quality, 3)
    reason_confidence = clamp_float(recommendation_confidence, default=quality, min_value=0.0, max_value=1.0)
    return round(0.50 * evidence_confidence + 0.30 * quality + 0.20 * reason_confidence, 3)


def build_recommendation_reason(
    dimension_scores: Mapping[str, Any],
    *,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    final_score: float,
    selection_status: str,
    source_stars: int,
    score_confidence: float,
    lane: str = "other",
) -> dict[str, Any]:
    content_metadata = content_metadata if isinstance(content_metadata, Mapping) else {}
    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}
    scores = {str(k): normalize_dimension_score(v) for k, v in dimension_scores.items()}
    status = str(content_metadata.get("fulltext_status") or "").strip() or "partial"
    status_label = FULLTEXT_STATUS_LABELS.get(status, status)
    lane_label = LANE_LABELS.get(lane, lane)

    high_dimensions = [
        DIMENSION_LABELS[key]
        for key in ("salience", "reach", "authority", "depth")
        if scores.get(key, 0.0) >= 7.0 and key in DIMENSION_LABELS
    ]
    if high_dimensions:
        why_matters = f"{'、'.join(high_dimensions[:3])}较高，综合分 {final_score:g}（{lane_label}）。"
    elif final_score >= 60:
        why_matters = f"综合分 {final_score:g}，具备进入候选池的基本价值（{lane_label}）。"
    else:
        why_matters = f"综合分 {final_score:g}，当前优先级较低。"

    why_now = f"本次窗口抓取到新的 {lane_label} 类可评估内容。"

    source_context = f"来自{source_stars}星信源"
    authority_type = normalize_authority_type(source_metadata.get("authority_type"))
    if authority_type:
        source_context += f"，权威类型为 {authority_type}"
    source_context += "。"

    evidence = f"正文状态为{status_label}，评分模型为 {SCORE_VERSION}。"

    if status == "partial":
        caveat = "正文为部分抓取，关键细节建议对照原文核实。"
    else:
        caveat = "暂未发现明显证据短板。"

    suggested_action = {
        "selected": "进入简报重点观察。",
        "candidate": "作为候选保留，等待同类信源补强。",
        "deferred": "等待正文或后续信源验证后再判断。",
        "rejected": "低优先级归档，不主动推送。",
    }.get(selection_status, "保留评分结果供后续排序。")

    reason_confidence = min(score_confidence, 0.85) if status == "partial" else score_confidence

    return {
        "why_now": why_now,
        "why_matters": why_matters,
        "source_context": source_context,
        "evidence": evidence,
        "caveat": caveat,
        "suggested_action": suggested_action,
        "confidence": round(clamp_float(reason_confidence, default=0.0), 3),
        "reason_source": "rule",
        "lane": lane,
    }


def calculate_article_score(
    dimension_scores: Mapping[str, Any],
    *,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    lane: str = "other",
    subjective_meta: Mapping[str, Any] | None = None,
    config: ScoringConfig | None = None,
) -> dict[str, Any]:
    """Calculate deterministic article score (0–100) and selection status."""

    config = config or ScoringConfig()
    content_metadata = content_metadata if isinstance(content_metadata, Mapping) else {}
    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}

    normalized_scores = {
        name: normalize_dimension_score(dimension_scores.get(name))
        for name in config.weights
    }
    base_0_10 = sum(normalized_scores[name] * weight for name, weight in config.weights.items())
    article_score = round(max(0.0, min(100.0, base_0_10 * 10.0)), 2)
    source_stars = normalize_source_stars(source_metadata.get("source_stars"))
    score_confidence = compute_score_confidence(content_metadata)

    if article_score >= config.selected_threshold and score_confidence >= config.minimum_selected_confidence:
        selection_status = "selected"
    elif article_score >= config.candidate_threshold:
        selection_status = "candidate"
    else:
        selection_status = "rejected"

    confidence_limited = (
        article_score >= config.selected_threshold
        and score_confidence < config.minimum_selected_confidence
    )

    subj_meta = dict(subjective_meta or {"source": "fixed_baseline", "score": normalized_scores.get("subjective", 5.0)})

    return {
        "score_version": SCORE_VERSION,
        "lane": lane,
        "dimension_scores": normalized_scores,
        "subjective_meta": subj_meta,
        "source_stars": source_stars,
        "score_confidence": score_confidence,
        "article_score": article_score,
        "final_score": article_score,
        "selection_status": selection_status,
        "confidence_limited_by_fulltext": confidence_limited,
        "recommendation_reason": build_recommendation_reason(
            normalized_scores,
            content_metadata=content_metadata,
            source_metadata=source_metadata,
            final_score=article_score,
            selection_status=selection_status,
            source_stars=source_stars,
            score_confidence=score_confidence,
            lane=lane,
        ),
    }


def calculate_final_score(
    dimension_scores: Mapping[str, Any],
    *,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    domain_match: float | None = None,
    config: ScoringConfig | None = None,
    lane: str = "other",
    subjective_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for :func:`calculate_article_score`."""
    del domain_match  # v1 domain penalties removed in v2
    return calculate_article_score(
        dimension_scores,
        content_metadata=content_metadata,
        source_metadata=source_metadata,
        lane=lane,
        subjective_meta=subjective_meta,
        config=config,
    )


def merge_scoring_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    dimension_scores: Mapping[str, Any],
    source_metadata: Mapping[str, Any] | None = None,
    lane: str = "other",
    subjective_meta: Mapping[str, Any] | None = None,
    config: ScoringConfig | None = None,
    domain_match: float | None = None,
) -> dict[str, Any]:
    del domain_match
    merged = dict(metadata or {})
    result = calculate_article_score(
        dimension_scores,
        content_metadata=merged,
        source_metadata=source_metadata,
        lane=lane,
        subjective_meta=subjective_meta,
        config=config,
    )
    merged.update(result)
    return merged


def merge_rule_scoring_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    title: str = "",
    summary: str | None = None,
    full_content: str | None = None,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    content_type: str = "",
    content: Any | None = None,
    scored_at: datetime | None = None,
    user_keyword_terms: Sequence[str] | None = None,
    matched_user_terms: Sequence[str] | None = None,
    keyword_objects: Sequence[Any] | None = None,
    keyword_matches: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute pim-score-v2 rule dimensions and stamp metadata."""

    merged = dict(metadata or {})
    if merged.get("fetch_acceptance") == "incomplete":
        return merged
    if merged.get("score_version") == SCORE_VERSION and isinstance(merged.get("dimension_scores"), Mapping):
        return merged

    if keyword_objects is not None:
        user_keyword_terms = extract_keyword_vocab_terms(keyword_objects)
    if keyword_matches is not None:
        matched_user_terms = extract_matched_keyword_terms(keyword_matches)

    content_metadata = merged if content_metadata is None else {**merged, **dict(content_metadata or {})}
    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}

    subjective = resolve_subjective_score(content, lane="other")
    lane, dimensions, runtime_vocab = compute_rule_dimension_scores(
        title=title,
        summary=summary,
        full_content=full_content,
        content_metadata=content_metadata,
        source_metadata=source_metadata,
        content_type=content_type,
        content=content,
        subjective=subjective,
        user_keyword_terms=user_keyword_terms,
        matched_user_terms=matched_user_terms,
    )
    merged = merge_scoring_metadata(
        merged,
        dimension_scores=dimensions,
        source_metadata=source_metadata,
        lane=lane,
        subjective_meta=subjective.to_metadata(),
    )
    merged["scoring_method"] = "rule"
    merged["score_vocab_user_terms"] = list(runtime_vocab.user_keyword_terms)
    merged["score_vocab_matched_user_terms"] = list(runtime_vocab.matched_user_terms)
    merged["scored_at"] = (scored_at or datetime.utcnow()).isoformat()
    return merged


async def merge_rule_scoring_metadata_async(
    metadata: Mapping[str, Any] | None,
    *,
    content: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Async scoring entry — shadow-records LLM subjective scoring when policy allows it."""
    from app.domains.score.score_subjective import score_subjective_async

    result = merge_rule_scoring_metadata(metadata, content=content, **kwargs)

    lane = result.get("lane", "other")
    subj = await score_subjective_async(content, lane=lane)
    if subj.source == "llm":
        # Phase 1 is shadow-only: persist subjective_meta, but keep the
        # subjective dimension weight/effective article_score unchanged.
        result["subjective_meta"] = subj.to_metadata()
        result["scoring_method"] = "rule+llm-shadow"

    return result


def merge_baseline_scoring_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    title: str = "",
    summary: str | None = None,
    full_content: str | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    content_type: str = "",
    content: Any | None = None,
    scored_at: datetime | None = None,
    keyword_objects: Sequence[Any] | None = None,
    keyword_matches: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Stamp rule-based pim-score-v2 metadata (sync, used by ingest finish)."""

    return merge_rule_scoring_metadata(
        metadata,
        title=title,
        summary=summary,
        full_content=full_content,
        source_metadata=source_metadata,
        content_type=content_type,
        content=content,
        scored_at=scored_at,
        keyword_objects=keyword_objects,
        keyword_matches=keyword_matches,
    )


def estimate_baseline_dimension_scores(
    *,
    title: str = "",
    summary: str | None = None,
    full_content: str | None = None,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Legacy name — returns v2 rule dimensions without subjective metadata."""

    _lane, dimensions, _vocab = compute_rule_dimension_scores(
        title=title,
        summary=summary,
        full_content=full_content,
        content_metadata=content_metadata,
        source_metadata=source_metadata,
    )
    return dimensions


__all__ = [
    "SCORE_VERSION",
    "FULLTEXT_CONFIDENCE",
    "FULLTEXT_STATUS_LABELS",
    "ScoringConfig",
    "clamp_float",
    "normalize_source_stars",
    "normalize_dimension_score",
    "compute_domain_match",
    "estimate_baseline_dimension_scores",
    "compute_score_confidence",
    "build_recommendation_reason",
    "calculate_article_score",
    "calculate_final_score",
    "merge_scoring_metadata",
    "merge_rule_scoring_metadata",
    "merge_baseline_scoring_metadata",
]
