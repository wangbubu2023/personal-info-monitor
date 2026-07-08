"""Single-user preference adjustments for local PIM scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from sqlalchemy.exc import SQLAlchemyError

from app.domains.score.scoring import ScoringConfig
from app.domains.score.score_utils import clamp_float
from app.models import Content, ScoreFeedback

PERSONALIZATION_VERSION = "pim-personal-v1"
DEFAULT_FEEDBACK_LIMIT = 240
MAX_TOTAL_ADJUSTMENT = 8.0
MAX_SOURCE_ADJUSTMENT = 6.0
MAX_LANE_ADJUSTMENT = 4.0
MAX_TYPE_ADJUSTMENT = 2.5


@dataclass
class ScopeSignal:
    score: float = 0.0
    count: int = 0

    def add(self, value: float) -> None:
        self.score += value
        self.count += 1


@dataclass
class PersonalPreferenceProfile:
    source: dict[str, ScopeSignal] = field(default_factory=dict)
    lane: dict[str, ScopeSignal] = field(default_factory=dict)
    content_type: dict[str, ScopeSignal] = field(default_factory=dict)
    total_signals: int = 0

    @property
    def has_signals(self) -> bool:
        return self.total_signals > 0


def _key(value: Any) -> str:
    return str(value or "").strip()


def _snapshot(feedback: ScoreFeedback) -> Mapping[str, Any]:
    value = getattr(feedback, "snapshot", None)
    return value if isinstance(value, Mapping) else {}


def _content_meta(content: Content | None) -> Mapping[str, Any]:
    value = getattr(content, "metadata_", None) if content is not None else None
    return value if isinstance(value, Mapping) else {}


def _event_weight(feedback: ScoreFeedback) -> float:
    event_type = _key(getattr(feedback, "event_type", None))
    direction = _key(getattr(feedback, "direction", None))
    event_value = getattr(feedback, "event_value", None)

    if event_type == "score_calibration":
        calibration = _key(event_value) or direction
        if calibration == "too_low":
            return 2.8
        if calibration == "too_high":
            return -2.8
        if calibration == "ok":
            return 0.4
        return 0.0

    if event_type == "star":
        return 1.8 if event_value is True else -0.8
    if event_type == "hide":
        return -3.0 if event_value is True else 0.6
    if event_type == "open":
        return 0.25 if event_value is True else 0.0
    return 0.0


def _add_signal(bucket: dict[str, ScopeSignal], key: str, value: float) -> None:
    if not key or value == 0:
        return
    bucket.setdefault(key, ScopeSignal()).add(value)


def build_personal_preference_profile(db: Any, *, limit: int = DEFAULT_FEEDBACK_LIMIT) -> PersonalPreferenceProfile:
    """Build a local, single-user preference profile from recent feedback."""

    profile = PersonalPreferenceProfile()
    try:
        rows = (
            db.query(ScoreFeedback, Content)
            .join(Content, Content.id == ScoreFeedback.content_id)
            .order_by(ScoreFeedback.created_at.desc())
            .limit(max(1, limit))
            .all()
        )
    except (AttributeError, TypeError, SQLAlchemyError):
        return profile

    if not isinstance(rows, list):
        return profile

    for row in rows:
        try:
            feedback, content = row
        except (TypeError, ValueError):
            continue

        weight = _event_weight(feedback)
        if weight == 0:
            continue

        snap = _snapshot(feedback)
        meta = _content_meta(content)
        source_id = _key(snap.get("source_id") or getattr(content, "source_id", None))
        lane = _key(snap.get("lane") or meta.get("lane") or getattr(content, "lane", None))
        content_type = _key(snap.get("content_type") or getattr(content, "content_type", None))

        _add_signal(profile.source, source_id, weight)
        _add_signal(profile.lane, lane, weight * 0.65)
        _add_signal(profile.content_type, content_type, weight * 0.35)
        profile.total_signals += 1

    return profile


def _scope_adjustment(
    signals: Mapping[str, ScopeSignal],
    key: str,
    *,
    cap: float,
    scope: str,
) -> tuple[float, dict[str, Any] | None]:
    if not key:
        return 0.0, None
    signal = signals.get(key)
    if not signal:
        return 0.0, None
    adjustment = round(clamp_float(signal.score, default=0.0, min_value=-cap, max_value=cap), 2)
    return adjustment, {
        "scope": scope,
        "key": key,
        "count": signal.count,
        "raw": round(signal.score, 2),
        "adjustment": adjustment,
    }


def _selection_status(final_score: float, score_confidence: float, config: ScoringConfig) -> str:
    if final_score >= config.selected_threshold and score_confidence >= config.minimum_selected_confidence:
        return "selected"
    if final_score >= config.candidate_threshold:
        return "candidate"
    return "rejected"


def apply_personal_preference_adjustment(
    metadata: Mapping[str, Any] | None,
    profile: PersonalPreferenceProfile | None,
    *,
    content: Any | None = None,
    config: ScoringConfig | None = None,
) -> dict[str, Any]:
    """Apply local feedback-derived adjustment to ``final_score`` only."""

    merged = dict(metadata or {})
    if not profile or not profile.has_signals:
        return merged

    base_score = clamp_float(merged.get("article_score", merged.get("final_score")), default=0.0, min_value=0.0, max_value=100.0)
    lane = _key(merged.get("lane") or getattr(content, "lane", None))
    content_type = _key(getattr(content, "content_type", None) or merged.get("content_type"))
    source_id = _key(getattr(content, "source_id", None))
    if not source_id:
        source = getattr(content, "source", None)
        source_id = _key(getattr(source, "id", None))

    contributions: list[dict[str, Any]] = []
    adjustment = 0.0
    for amount, detail in (
        _scope_adjustment(profile.source, source_id, cap=MAX_SOURCE_ADJUSTMENT, scope="source"),
        _scope_adjustment(profile.lane, lane, cap=MAX_LANE_ADJUSTMENT, scope="lane"),
        _scope_adjustment(profile.content_type, content_type, cap=MAX_TYPE_ADJUSTMENT, scope="content_type"),
    ):
        adjustment += amount
        if detail and amount != 0:
            contributions.append(detail)

    adjustment = round(clamp_float(adjustment, default=0.0, min_value=-MAX_TOTAL_ADJUSTMENT, max_value=MAX_TOTAL_ADJUSTMENT), 2)
    if adjustment == 0:
        return merged

    config = config or ScoringConfig()
    final_score = round(clamp_float(base_score + adjustment, default=base_score, min_value=0.0, max_value=100.0), 2)
    score_confidence = clamp_float(merged.get("score_confidence"), default=0.0, min_value=0.0, max_value=1.0)

    merged["final_score"] = final_score
    merged["selection_status"] = _selection_status(final_score, score_confidence, config)
    merged["confidence_limited_by_fulltext"] = (
        final_score >= config.selected_threshold
        and score_confidence < config.minimum_selected_confidence
    )
    merged["personalization"] = {
        "version": PERSONALIZATION_VERSION,
        "base_score": base_score,
        "adjustment": adjustment,
        "final_score": final_score,
        "signals_considered": profile.total_signals,
        "contributions": contributions,
    }

    reason = merged.get("recommendation_reason")
    if isinstance(reason, dict):
        reason = dict(reason)
        reason["personalization_adjustment"] = adjustment
        reason["personalization"] = f"个人反馈修正 {adjustment:+g}，最终分 {final_score:g}。"
        merged["recommendation_reason"] = reason

    return merged


__all__ = [
    "PERSONALIZATION_VERSION",
    "PersonalPreferenceProfile",
    "ScopeSignal",
    "apply_personal_preference_adjustment",
    "build_personal_preference_profile",
]
