"""Deterministic scoring helpers for PIM selection.

LLMs may provide dimension scores later, but the final score belongs in code so
weights, penalties, and source-star behavior can be tested and versioned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

SCORE_VERSION = "pim-score-v1"

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
        "topic_relevance": 0.25,
        "novelty": 0.20,
        "impact": 0.25,
        "authority": 0.15,
        "actionability": 0.15,
    })
    selected_threshold: float = 75.0
    candidate_threshold: float = 60.0
    minimum_selected_confidence: float = 0.65
    source_stars_bonus: dict[int, float] = field(default_factory=lambda: {1: -5.0, 2: 3.0, 3: 6.0})
    summary_only_penalty: float = 8.0
    title_only_penalty: float = 20.0
    domain_mismatch_min_penalty: float = 5.0
    domain_mismatch_max_penalty: float = 15.0
    high_risk_penalty_max: float = 20.0


def clamp_float(value: Any, *, default: float = 0.0, min_value: float = 0.0, max_value: float = 1.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def normalize_source_stars(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(3, parsed))


def normalize_dimension_score(value: Any) -> float:
    return clamp_float(value, default=0.0, min_value=0.0, max_value=10.0)


def _source_weight(source_metadata: Mapping[str, Any]) -> float:
    return clamp_float(source_metadata.get("source_weight"), default=1.0, min_value=0.5, max_value=1.5)


def compute_domain_match(source_metadata: Mapping[str, Any], text: str) -> float:
    """Lightweight topic/domain match against ``source.metadata.domain_focus``.

    Missing focus means "unknown", not mismatch. In that case we avoid applying
    a penalty until a source has been intentionally configured.
    """

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


def estimate_baseline_dimension_scores(
    *,
    title: str = "",
    summary: str | None = None,
    full_content: str | None = None,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Local fallback dimensions when model scoring has not run yet.

    This is intentionally conservative. It creates a backtestable baseline
    score for sorting and diagnostics without pretending to replace LLM
    judgment.
    """

    content_metadata = content_metadata if isinstance(content_metadata, Mapping) else {}
    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}
    text = " ".join(str(x or "") for x in (title, summary, full_content[:1200] if full_content else ""))
    domain = compute_domain_match(source_metadata, text)
    stars = normalize_source_stars(source_metadata.get("source_stars"))
    status = str(content_metadata.get("fulltext_status") or "summary_only")
    quality = clamp_float(content_metadata.get("content_quality"), default=0.35, min_value=0.0, max_value=1.0)
    body_len = len(str(full_content or ""))
    has_keywords = bool(content_metadata.get("keyword_matches") or content_metadata.get("matched_keywords"))

    if status == "blocked":
        relevance = min(4.0, domain * 5)
    elif domain >= 0.95:
        relevance = 6.0 + (1.0 if has_keywords else 0.0)
    else:
        relevance = 2.0 + domain * 5.5 + (1.0 if has_keywords else 0.0)

    authority = {1: 4.0, 2: 6.5, 3: 8.5}[stars]
    impact = 3.5 + stars * 0.9 + quality * 2.0
    actionability = 3.0 + quality * 3.0 + (1.0 if body_len >= 1000 else 0.0)
    novelty = 5.0
    risk = 2.0
    if status in {"summary_only", "title_only"}:
        risk += 2.0
        impact = min(impact, 5.0)
        actionability = min(actionability, 5.0)
    if status == "blocked":
        risk = 7.0
        impact = min(impact, 4.0)
        actionability = min(actionability, 3.0)
    if domain < 0.5:
        risk += 1.5

    return {
        "topic_relevance": round(min(10.0, relevance), 1),
        "novelty": round(min(10.0, novelty), 1),
        "impact": round(min(10.0, impact), 1),
        "authority": round(min(10.0, authority), 1),
        "actionability": round(min(10.0, actionability), 1),
        "risk": round(min(10.0, risk), 1),
    }


def compute_score_confidence(content_metadata: Mapping[str, Any], recommendation_confidence: Any = None) -> float:
    status = str(content_metadata.get("fulltext_status") or "").strip() or "summary_only"
    evidence_confidence = FULLTEXT_CONFIDENCE.get(status, 0.42)
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
) -> dict[str, Any]:
    """Build a structured, non-LLM explanation for the score.

    Model scoring can replace this later with richer reason atoms, but keeping
    the same shape from day one makes ranking/debug UI deterministic.
    """

    content_metadata = content_metadata if isinstance(content_metadata, Mapping) else {}
    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}
    scores = {str(k): normalize_dimension_score(v) for k, v in dimension_scores.items()}
    status = str(content_metadata.get("fulltext_status") or "").strip() or "summary_only"
    status_label = FULLTEXT_STATUS_LABELS.get(status, status)
    score_basis = str(content_metadata.get("score_basis") or status_label).strip()
    focus = source_metadata.get("domain_focus")
    focus_terms = [str(x).strip() for x in focus if str(x).strip()] if isinstance(focus, list) else []

    high_dimensions = [
        label
        for key, label in (
            ("topic_relevance", "主题相关"),
            ("impact", "潜在影响"),
            ("authority", "信源权威"),
            ("actionability", "可跟进行动"),
            ("novelty", "新鲜度"),
        )
        if scores.get(key, 0.0) >= 7.0
    ]
    if high_dimensions:
        why_matters = f"{'、'.join(high_dimensions[:3])}评分较高，综合分 {final_score:g}。"
    elif final_score >= 60:
        why_matters = f"综合分 {final_score:g}，具备进入候选池的基本价值。"
    else:
        why_matters = f"综合分 {final_score:g}，当前优先级较低。"

    if focus_terms:
        why_now = f"本次窗口抓取到与 {'、'.join(focus_terms[:4])} 相关的新内容。"
    else:
        why_now = "本次窗口抓取到新的可评估内容。"

    source_context = f"来自{source_stars}星信源"
    authority_type = str(source_metadata.get("authority_type") or "").strip()
    if authority_type:
        source_context += f"，权威类型为 {authority_type}"
    source_context += "。"

    evidence = f"评分依据为{score_basis}，正文状态为{status_label}。"

    risk = scores.get("risk", 0.0)
    if status == "blocked":
        caveat = "页面受限或未取得正文，暂不应作为高置信结论。"
    elif status in {"summary_only", "title_only"}:
        caveat = "证据主要来自标题或摘要，完整事实链仍需正文验证。"
    elif risk >= 6:
        caveat = "风险维度偏高，建议在采用前交叉验证。"
    else:
        caveat = "暂未发现明显证据短板。"

    suggested_action = {
        "selected": "进入简报重点观察。",
        "candidate": "作为候选保留，等待同类信源补强。",
        "deferred": "等待正文或后续信源验证后再判断。",
        "rejected": "低优先级归档，不主动推送。",
    }.get(selection_status, "保留评分结果供后续排序。")

    reason_confidence = score_confidence
    if status in {"summary_only", "title_only", "blocked"}:
        reason_confidence = min(reason_confidence, 0.6 if status != "blocked" else 0.35)

    return {
        "why_now": why_now,
        "why_matters": why_matters,
        "source_context": source_context,
        "evidence": evidence,
        "caveat": caveat,
        "suggested_action": suggested_action,
        "confidence": round(clamp_float(reason_confidence, default=0.0), 3),
        "reason_source": "baseline",
    }


def calculate_final_score(
    dimension_scores: Mapping[str, Any],
    *,
    content_metadata: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    domain_match: float | None = None,
    config: ScoringConfig | None = None,
) -> dict[str, Any]:
    """Calculate deterministic final score and selection status."""

    config = config or ScoringConfig()
    content_metadata = content_metadata if isinstance(content_metadata, Mapping) else {}
    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}

    normalized_scores = {
        name: normalize_dimension_score(dimension_scores.get(name))
        for name in config.weights
    }
    risk = normalize_dimension_score(dimension_scores.get("risk"))
    base_0_10 = sum(normalized_scores[name] * weight for name, weight in config.weights.items())
    score = base_0_10 * 10.0 * _source_weight(source_metadata)

    source_stars = normalize_source_stars(source_metadata.get("source_stars"))
    domain = clamp_float(domain_match if domain_match is not None else content_metadata.get("domain_match"), default=1.0)
    stars_bonus = config.source_stars_bonus.get(source_stars, 0.0)
    if domain < 0.5 and stars_bonus > 0:
        stars_bonus *= domain
    score += stars_bonus

    if domain < 0.5:
        severity = (0.5 - domain) / 0.5
        score -= config.domain_mismatch_min_penalty + severity * (
            config.domain_mismatch_max_penalty - config.domain_mismatch_min_penalty
        )

    fulltext_status = str(content_metadata.get("fulltext_status") or "")
    if fulltext_status == "summary_only":
        score -= config.summary_only_penalty
    elif fulltext_status == "title_only":
        score -= config.title_only_penalty
    elif fulltext_status == "blocked":
        score = min(score, config.candidate_threshold - 1)

    if risk > 5:
        score -= ((risk - 5) / 5.0) * config.high_risk_penalty_max

    final_score = round(max(0.0, min(100.0, score)), 2)
    score_confidence = compute_score_confidence(content_metadata)

    if fulltext_status == "blocked":
        selection_status = "deferred" if source_stars >= 2 else "rejected"
    elif final_score >= config.selected_threshold and score_confidence >= config.minimum_selected_confidence:
        selection_status = "selected"
    elif final_score >= config.candidate_threshold:
        selection_status = "candidate"
    else:
        selection_status = "rejected"

    return {
        "score_version": SCORE_VERSION,
        "dimension_scores": {**normalized_scores, "risk": risk},
        "source_stars": source_stars,
        "domain_match": round(domain, 3),
        "score_confidence": score_confidence,
        "final_score": final_score,
        "selection_status": selection_status,
        "recommendation_reason": build_recommendation_reason(
            {**normalized_scores, "risk": risk},
            content_metadata=content_metadata,
            source_metadata=source_metadata,
            final_score=final_score,
            selection_status=selection_status,
            source_stars=source_stars,
            score_confidence=score_confidence,
        ),
    }


def merge_scoring_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    dimension_scores: Mapping[str, Any],
    source_metadata: Mapping[str, Any] | None = None,
    domain_match: float | None = None,
    config: ScoringConfig | None = None,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    result = calculate_final_score(
        dimension_scores,
        content_metadata=merged,
        source_metadata=source_metadata,
        domain_match=domain_match,
        config=config,
    )
    merged.update(result)
    return merged


def merge_baseline_scoring_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    title: str = "",
    summary: str | None = None,
    full_content: str | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    scored_at: datetime | None = None,
) -> dict[str, Any]:
    """Stamp baseline dimensions/final score if model dimensions are absent."""

    merged = dict(metadata or {})
    if isinstance(merged.get("dimension_scores"), Mapping) and merged.get("score_version"):
        return merged

    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}
    text = " ".join(str(x or "") for x in (title, summary, full_content[:1200] if full_content else ""))
    domain_match = compute_domain_match(source_metadata, text)
    dimensions = estimate_baseline_dimension_scores(
        title=title,
        summary=summary,
        full_content=full_content,
        content_metadata=merged,
        source_metadata=source_metadata,
    )
    merged = merge_scoring_metadata(
        merged,
        dimension_scores=dimensions,
        source_metadata=source_metadata,
        domain_match=domain_match,
    )
    merged["scoring_method"] = "baseline"
    merged["scored_at"] = (scored_at or datetime.utcnow()).isoformat()
    return merged
