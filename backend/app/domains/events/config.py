"""Central Event v1 configuration and guarded release switches."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class EventEngineConfig:
    cluster_version: str = "event-v1.0-rules"
    signature_version: str = "event-signature-v1"
    classifier_version: str = "event-pair-v1"
    snapshot_version: str = "snapshot-rules-v1"
    candidate_limit: int = 50
    auto_attach_threshold: float = 0.72
    review_threshold: float = 0.56
    duplicate_bonus: float = 0.18
    alias_bonus: float = 0.12
    cooling_penalty: float = 0.06
    closed_penalty: float = 0.18
    size_penalty_step: float = 0.015
    max_size_penalty: float = 0.15
    max_dispersion_penalty: float = 0.18
    active_ttl_hours: dict[str, int] = field(
        default_factory=lambda: {
            "breaking": 72,
            "product": 14 * 24,
            "policy": 30 * 24,
            "legal": 30 * 24,
            "default": 7 * 24,
        }
    )
    source_weights: dict[str, float] = field(
        default_factory=lambda: {
            "official": 1.0,
            "original": 1.0,
            "wire": 1.0,
            "commentary": 0.6,
            "reprint": 0.0,
            "aggregator": 0.2,
            "unknown": 0.4,
        }
    )


def event_config() -> EventEngineConfig:
    base = EventEngineConfig()
    return EventEngineConfig(candidate_limit=_int("EVENT_CANDIDATE_LIMIT", base.candidate_limit, minimum=5))


def event_v1_enabled() -> bool:
    return _bool("EVENT_V1_ENABLED", True)


def event_v1_assignment_enabled() -> bool:
    return event_v1_enabled() and _bool("EVENT_V1_ASSIGNMENT", True)


def event_v1_today_read_enabled() -> bool:
    # Fail closed. This may be enabled only after the external M2 release gate
    # and seven-day production shadow have been approved.
    return (
        event_v1_enabled()
        and _bool("EVENT_V1_TODAY_READ", False)
        and _bool("EVENT_V1_READ_GATE_APPROVED", False)
    )


def event_rebalance_enabled() -> bool:
    return event_v1_enabled() and _bool("EVENT_REBALANCE_ENABLED", True)


def event_debug_explain_enabled() -> bool:
    return _bool("EVENT_DEBUG_EXPLAIN_ENABLED", False)


def assignment_mode() -> str:
    value = os.environ.get("EVENT_ASSIGNMENT_MODE", "rules").strip().lower()
    return value if value in {"rules", "hybrid", "embedding_shadow", "embedding"} else "rules"


def assignment_log_retention_days() -> int:
    return _int("EVENT_ASSIGNMENT_LOG_RETENTION_DAYS", 30, minimum=7)


def export_event_config() -> dict:
    config = asdict(event_config())
    config["flags"] = {
        "EVENT_V1_ENABLED": event_v1_enabled(),
        "EVENT_V1_ASSIGNMENT": event_v1_assignment_enabled(),
        "EVENT_V1_TODAY_READ": event_v1_today_read_enabled(),
        "EVENT_V1_READ_GATE_APPROVED": _bool("EVENT_V1_READ_GATE_APPROVED", False),
        "EVENT_REBALANCE_ENABLED": event_rebalance_enabled(),
        "EVENT_AUTO_MERGE_ENABLED": _bool("EVENT_AUTO_MERGE_ENABLED", False),
        "EVENT_AUTO_SPLIT_ENABLED": _bool("EVENT_AUTO_SPLIT_ENABLED", False),
        "EVENT_LLM_JUDGE_ENABLED": _bool("EVENT_LLM_JUDGE_ENABLED", False),
        "EVENT_SIGNATURE_LLM_ENABLED": _bool("EVENT_SIGNATURE_LLM_ENABLED", False),
        "EVENT_CROSSLINGUAL_ENABLED": _bool("EVENT_CROSSLINGUAL_ENABLED", False),
        "EVENT_STORYLINE_ENABLED": _bool("EVENT_STORYLINE_ENABLED", False),
        "EVENT_DEBUG_EXPLAIN_ENABLED": event_debug_explain_enabled(),
        "EVENT_ASSIGNMENT_LOG_RETENTION_DAYS": assignment_log_retention_days(),
    }
    config["assignment_mode"] = assignment_mode()
    return json.loads(json.dumps(config, sort_keys=True))


__all__ = [
    "EventEngineConfig",
    "assignment_mode",
    "assignment_log_retention_days",
    "event_config",
    "event_debug_explain_enabled",
    "event_rebalance_enabled",
    "event_v1_assignment_enabled",
    "event_v1_enabled",
    "event_v1_today_read_enabled",
    "export_event_config",
]
