"""Online Event v1 assignment: recall, classify, attach/create, and snapshot."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.domains.events.config import assignment_mode, event_config, event_v1_assignment_enabled
from app.domains.events.signature import extract_event_signature, signature_facts
from app.domains.events.source_independence import canonical_report, independence_summary, source_role
from app.domains.score.ranking import _jaccard, _tokenize
from app.models import (
    Content,
    ContentEvent,
    ContentEventMembership,
    ContentEventSnapshot,
    EventAlias,
    EventAssignmentLog,
    EventMembershipV1,
    EventSignature,
)
from app.platform.observability.metrics import event_metrics, reliability_metrics
from app.utils.datetime import utcnow_naive


@dataclass(frozen=True)
class AssignmentResult:
    content_id: str
    event_id: str | None
    decision: str
    relation: str
    candidate_count: int
    created: bool = False
    snapshot_created: bool = False
    skipped_reason: str | None = None


def uuid7_hex(now: datetime | None = None) -> str:
    """Return a compact RFC-9562-shaped UUIDv7 without external dependencies."""

    current = now or datetime.now(timezone.utc)
    millis = int(current.timestamp() * 1000) & ((1 << 48) - 1)
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (millis << 80) | (0x7 << 76) | (random_a << 64) | (0b10 << 62) | random_b
    return f"{value:032x}"


def _signature_payload(row: EventSignature | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    return {
        "signature_version": row.signature_version,
        "normalized_entities": row.normalized_entities or [],
        "actors": row.actors or [],
        "trigger_action": row.trigger_action or {},
        "object": row.object_ or {},
        "location": row.location or {},
        "event_time_start": row.event_time_start,
        "event_time_end": row.event_time_end,
        "event_time_precision": row.event_time_precision,
        "quantities": row.quantities or [],
        "identifiers": row.identifiers or [],
        "outcomes": row.outcomes or [],
        "modality": row.modality,
        "source_claim_type": row.source_claim_type,
        "language": row.language,
        "source_text": row.source_text or {},
        "confidence": row.confidence,
        "extraction_method": row.extraction_method,
        "model_version": row.model_version,
        "evidence_spans": row.evidence_spans or [],
        "fingerprint": row.fingerprint,
    }


def _save_signature(db: Session, content: Content, payload: dict[str, Any]) -> EventSignature:
    config = event_config()
    row = (
        db.query(EventSignature)
        .filter(
            EventSignature.content_id == str(content.id),
            EventSignature.signature_version == config.signature_version,
        )
        .first()
    )
    values = {
        "normalized_entities": payload["normalized_entities"],
        "actors": payload["actors"],
        "trigger_action": payload["trigger_action"],
        "object_": payload["object"],
        "location": payload["location"],
        "event_time_start": payload["event_time_start"],
        "event_time_end": payload["event_time_end"],
        "event_time_precision": payload["event_time_precision"],
        "quantities": payload["quantities"],
        "identifiers": payload["identifiers"],
        "outcomes": payload["outcomes"],
        "modality": payload["modality"],
        "source_claim_type": payload["source_claim_type"],
        "language": payload["language"],
        "source_text": payload["source_text"],
        "confidence": payload["confidence"],
        "extraction_method": payload["extraction_method"],
        "model_version": payload["model_version"],
        "evidence_spans": payload["evidence_spans"],
        "fingerprint": payload["fingerprint"],
        "updated_at": utcnow_naive(),
    }
    if row is None:
        row = EventSignature(
            content_id=str(content.id),
            signature_version=config.signature_version,
            created_at=utcnow_naive(),
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _values(rows: list[dict[str, Any]], key: str = "value") -> set[str]:
    return {str(row.get(key) or "").lower() for row in rows if row.get(key)}


def _event_signature(event: ContentEvent) -> dict[str, Any]:
    centroid = event.centroid if isinstance(event.centroid, dict) else {}
    signature = centroid.get("signature")
    if isinstance(signature, dict):
        return signature
    metadata = event.metadata_ if isinstance(event.metadata_, dict) else {}
    return metadata.get("event_signature") if isinstance(metadata.get("event_signature"), dict) else {}


def _event_tokens(event: ContentEvent) -> set[str]:
    centroid = event.centroid if isinstance(event.centroid, dict) else {}
    tokens = centroid.get("tokens")
    if isinstance(tokens, list):
        return {str(token) for token in tokens}
    return _tokenize(f"{event.title or ''} {event.summary or ''}")


def _hard_conflicts(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    left_ids = {(row.get("type"), str(row.get("value") or "").lower()) for row in left.get("identifiers") or []}
    right_ids = {(row.get("type"), str(row.get("value") or "").lower()) for row in right.get("identifiers") or []}
    for kind in {"version", "canonical_identifier"}:
        lvalues = {value for row_kind, value in left_ids if row_kind == kind}
        rvalues = {value for row_kind, value in right_ids if row_kind == kind}
        if lvalues and rvalues and not (lvalues & rvalues):
            conflicts.append(f"different_{kind}")
    left_location = (left.get("location") or {}).get("canonical_id")
    right_location = (right.get("location") or {}).get("canonical_id")
    if left_location and right_location and left_location != right_location:
        conflicts.append("different_location")
    left_date = left.get("event_time_start")
    right_date = right.get("event_time_start")
    if isinstance(left_date, str):
        try:
            left_date = datetime.fromisoformat(left_date)
        except ValueError:
            left_date = None
    if isinstance(right_date, str):
        try:
            right_date = datetime.fromisoformat(right_date)
        except ValueError:
            right_date = None
    if left_date and right_date and abs((left_date - right_date).total_seconds()) > 45 * 86400:
        conflicts.append("incompatible_time")
    left_action = left.get("trigger_action") or {}
    right_action = right.get("trigger_action") or {}
    if (
        left_action.get("lemma")
        and right_action.get("lemma")
        and {left_action.get("polarity"), right_action.get("polarity")} == {"positive", "negative"}
        and left_action.get("lemma") != right_action.get("lemma")
    ):
        conflicts.append("opposite_action")
    return conflicts


def _temporal_similarity(left: datetime | None, right: datetime | None, *, tau_days: float = 7.0) -> float:
    if not left or not right:
        return 0.5
    if isinstance(left, str):
        try:
            left = datetime.fromisoformat(left)
        except ValueError:
            return 0.5
    if isinstance(right, str):
        try:
            right = datetime.fromisoformat(right)
        except ValueError:
            return 0.5
    delta_days = abs((left - right).total_seconds()) / 86400
    return math.exp(-delta_days / tau_days)


def _effective_threshold(event: ContentEvent, *, duplicate: bool = False, alias: bool = False) -> float:
    config = event_config()
    metadata = event.metadata_ if isinstance(event.metadata_, dict) else {}
    size = int(metadata.get("active_member_count") or 0)
    threshold = config.auto_attach_threshold
    threshold += min(config.max_size_penalty, max(0, size - 5) * config.size_penalty_step)
    threshold += min(config.max_dispersion_penalty, max(0.0, float(event.dispersion or 0.0)) * 0.2)
    if event.status == "cooling":
        threshold += config.cooling_penalty
    elif event.status in {"closed", "archived"}:
        threshold += config.closed_penalty
    if duplicate:
        threshold -= config.duplicate_bonus
    if alias:
        threshold -= config.alias_bonus
    return round(max(0.45, min(0.95, threshold)), 3)


def _classify(
    signature: dict[str, Any],
    content: Content,
    event: ContentEvent,
    *,
    duplicate: bool,
    alias: bool,
    recall_reasons: list[str],
) -> dict[str, Any]:
    candidate_signature = _event_signature(event)
    left_entities = _values(signature.get("normalized_entities") or [], "canonical_id")
    right_entities = _values(candidate_signature.get("normalized_entities") or [], "canonical_id")
    entity_overlap = len(left_entities & right_entities) / max(1, len(left_entities | right_entities))
    left_action = signature.get("trigger_action") or {}
    right_action = candidate_signature.get("trigger_action") or {}
    action_match = 1.0 if left_action.get("lemma") and left_action.get("lemma") == right_action.get("lemma") else 0.0
    left_object = str((signature.get("object") or {}).get("canonical_id") or "")
    right_object = str((candidate_signature.get("object") or {}).get("canonical_id") or "")
    object_match = 1.0 if left_object and left_object == right_object else 0.0
    structure = 0.65 * entity_overlap + 0.25 * action_match + 0.10 * object_match
    left_ids = _values(signature.get("identifiers") or [])
    right_ids = _values(candidate_signature.get("identifiers") or [])
    identifier_match = 1.0 if left_ids and right_ids and left_ids & right_ids else 0.0
    lexical = _jaccard(
        _tokenize(f"{content.title or ''} {content.summary or ''}"),
        _event_tokens(event),
    )
    temporal = _temporal_similarity(signature.get("event_time_start"), candidate_signature.get("event_time_start"))
    duplicate_score = 1.0 if duplicate else 0.0
    metadata_score = 1.0 if alias else 0.0
    conflicts = _hard_conflicts(signature, candidate_signature)
    contradiction_penalty = min(0.8, len(conflicts) * 0.4)
    semantic = max(lexical, 0.65 * entity_overlap + 0.35 * identifier_match)
    score = (
        0.45 * semantic
        + 0.25 * structure
        + 0.15 * temporal
        + 0.10 * duplicate_score
        + 0.05 * metadata_score
        - contradiction_penalty
    )
    threshold = _effective_threshold(event, duplicate=duplicate, alias=alias)
    modality_changed = (
        signature.get("modality")
        and candidate_signature.get("modality")
        and signature.get("modality") != candidate_signature.get("modality")
    )
    if conflicts:
        relation = "unrelated"
    elif source_role(content) == "commentary":
        relation = "commentary"
    elif duplicate:
        relation = "duplicate"
    elif modality_changed:
        relation = "event_update"
    elif score >= threshold:
        relation = "same_event"
    elif score >= event_config().review_threshold:
        relation = "related_context"
    else:
        relation = "unrelated"
    return {
        "event": event,
        "score": round(max(0.0, min(1.0, score)), 4),
        "relation": relation,
        "component_scores": {
            "semantic_similarity": round(semantic, 4),
            "actor_trigger_object_similarity": round(structure, 4),
            "entity_overlap": round(entity_overlap, 4),
            "action_match": action_match,
            "identifier_match": identifier_match,
            "temporal_similarity": round(temporal, 4),
            "lexical_similarity": round(lexical, 4),
            "duplicate_or_syndication_evidence": duplicate_score,
            "metadata_similarity": metadata_score,
            "contradiction_penalty": contradiction_penalty,
        },
        "hard_conflicts": conflicts,
        "effective_threshold": threshold,
        "recall_reasons": sorted(set(recall_reasons)),
    }


def _duplicate_event_ids(db: Session, content: Content) -> set[str]:
    meta = content.metadata_ if isinstance(content.metadata_, dict) else {}
    duplicate_group = str(meta.get("duplicate_group_id") or "").strip()
    related_ids = {str(content.duplicate_of)} if content.duplicate_of else set()
    if duplicate_group:
        rows = db.query(Content.id).filter(Content.metadata_["duplicate_group_id"].as_string() == duplicate_group).limit(100).all()
        related_ids.update(str(row[0]) for row in rows)
    if not related_ids:
        return set()
    rows = (
        db.query(EventMembershipV1.event_id)
        .filter(EventMembershipV1.content_id.in_(related_ids), EventMembershipV1.active.is_(True))
        .all()
    )
    return {str(row[0]) for row in rows}


def recall_candidates(db: Session, content: Content, signature: dict[str, Any]) -> list[dict[str, Any]]:
    """Recall at most 50 candidates without LLM calls."""

    config = event_config()
    duplicate_ids = _duplicate_event_ids(db, content)
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    alias_values = {
        str(value).strip()
        for value in (metadata.get("event_id"), metadata.get("event_key"), metadata.get("thread_id"))
        if value
    }
    alias_ids = {
        str(row[0])
        for row in (
            db.query(EventAlias.canonical_event_id)
            .filter(EventAlias.alias_value.in_(alias_values), EventAlias.redirect_enabled.is_(True))
            .all()
        )
    } if alias_values else set()
    events = (
        db.query(ContentEvent)
        .filter(ContentEvent.cluster_version == config.cluster_version)
        .filter(ContentEvent.status.in_(["active", "cooling", "reopened", "closed"]))
        .order_by(ContentEvent.last_material_update_at.desc(), ContentEvent.event_id)
        .limit(1500)
        .all()
    )
    left_entities = _values(signature.get("normalized_entities") or [], "canonical_id")
    left_ids = _values(signature.get("identifiers") or [])
    left_action = (signature.get("trigger_action") or {}).get("lemma")
    left_tokens = _tokenize(f"{content.title or ''} {content.summary or ''}")
    recalled: list[dict[str, Any]] = []
    for event in events:
        event_sig = _event_signature(event)
        reasons: list[str] = []
        duplicate = event.event_id in duplicate_ids
        alias = event.event_id in alias_ids
        if duplicate:
            reasons.append("duplicate_propagation")
        if alias:
            reasons.append("explicit_alias")
        event_entities = _values(event_sig.get("normalized_entities") or [], "canonical_id")
        if left_entities & event_entities:
            reasons.append("entity_time")
        event_ids = _values(event_sig.get("identifiers") or [])
        if left_ids & event_ids:
            reasons.append("canonical_identifier")
        if left_action and left_action == (event_sig.get("trigger_action") or {}).get("lemma"):
            reasons.append("trigger_action")
        lexical = _jaccard(left_tokens, _event_tokens(event))
        if lexical >= 0.12:
            reasons.append("lexical")
        if not reasons:
            continue
        if event.status in {"closed", "archived"} and not (
            duplicate or alias or "canonical_identifier" in reasons
        ):
            continue
        recalled.append(
            {
                "event": event,
                "duplicate": duplicate,
                "alias": alias,
                "recall_reasons": reasons,
                "pre_score": (
                    (1.0 if duplicate else 0.0)
                    + (1.0 if alias else 0.0)
                    + (1.0 if "canonical_identifier" in reasons else 0.0)
                    + (0.5 if "entity_time" in reasons else 0.0)
                    + lexical
                ),
            }
        )
    recalled.sort(
        key=lambda row: (
            float(row["pre_score"]),
            row["event"].last_material_update_at or row["event"].updated_at or datetime.min,
            row["event"].event_id,
        ),
        reverse=True,
    )
    return recalled[: config.candidate_limit]


def _safe_title(content: Content, signature: dict[str, Any]) -> str:
    title = str(content.translated_title or content.title or "未命名事件").strip()
    modality = signature.get("modality")
    markers = {
        "planned": ("计划", "拟", "将", "plan", "planned"),
        "reported": ("据", "消息", "reported", "reportedly", "sources"),
        "alleged": ("被指", "涉嫌", "alleged", "accused"),
        "question": ("?", "？", "是否", "will", "could"),
        "denied": ("否认", "驳斥", "deny", "denied"),
    }
    if modality in markers and not any(marker.lower() in title.lower() for marker in markers[modality]):
        prefix = {
            "planned": "计划：",
            "reported": "据报：",
            "alleged": "被指：",
            "question": "待确认：",
            "denied": "相关方否认：",
        }[modality]
        title = f"{prefix}{title}"
    return title[:500]


def _facts_fingerprint(facts: list[dict[str, Any]]) -> str:
    payload = {"facts": facts}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _change_type(previous: ContentEventSnapshot | None, signature: dict[str, Any]) -> str:
    modality = str(signature.get("modality") or "")
    if modality == "denied":
        return "disputed_fact"
    if (signature.get("trigger_action") or {}).get("lemma") == "retract":
        return "retracted_fact"
    if modality == "confirmed" and previous is not None:
        return "confirmed_fact"
    return "added_fact" if previous is None or modality != "confirmed" else "confirmed_fact"


def _active_event_contents(db: Session, event_id: str) -> list[Content]:
    membership_ids = [
        str(row[0])
        for row in (
            db.query(EventMembershipV1.content_id)
            .filter(EventMembershipV1.event_id == event_id, EventMembershipV1.active.is_(True))
            .all()
        )
    ]
    if not membership_ids:
        return []
    return (
        db.query(Content)
        .options(joinedload(Content.source))
        .filter(Content.id.in_(membership_ids))
        .all()
    )


def _refresh_event_and_snapshot(
    db: Session,
    event: ContentEvent,
    content: Content,
    signature: dict[str, Any],
) -> bool:
    contents = _active_event_contents(db, event.event_id)
    if all(str(row.id) != str(content.id) for row in contents):
        contents.append(content)
    canonical, canonical_reason = canonical_report(contents)
    canonical = canonical or content
    independence = independence_summary(contents)
    title = _safe_title(canonical, signature)
    summary = str(canonical.translated_summary or canonical.summary or "").strip() or None
    facts = signature_facts(signature)
    fingerprint = _facts_fingerprint(facts)
    latest = (
        db.query(ContentEventSnapshot)
        .filter(ContentEventSnapshot.event_id == event.event_id)
        .order_by(ContentEventSnapshot.version.desc())
        .first()
    )
    canonical_id = str(canonical.id)
    source_ids = sorted({str(row.id) for row in contents})
    explanation = {
        "selection_reason": "权威或独立来源与事件结构信号达到展示条件。",
        "factual_consequence": None,
        "evidence": [{"content_id": cid} for cid in source_ids],
        "uncertainty": [] if signature.get("modality") == "confirmed" else [f"modality={signature.get('modality')}"],
        "personal_relevance": None,
        "what_changed_since_last_read": "出现实质事实、确认状态或可信代表材料变化。",
        "why_now": "最近材料触发在线 Event assignment。",
        "generator_version": event_config().snapshot_version,
    }
    created = latest is None or latest.change_fingerprint != fingerprint
    if created:
        version = int(latest.version or 0) + 1 if latest else 1
        change = _change_type(latest, signature)
        db.add(
            ContentEventSnapshot(
                event_id=event.event_id,
                version=version,
                title=title,
                summary=summary,
                what_changed=explanation["what_changed_since_last_read"],
                why_matters=explanation["selection_reason"],
                source_content_ids=source_ids,
                change_type=change,
                change_fingerprint=fingerprint,
                facts=facts,
                evidence_refs=explanation["evidence"],
                uncertainty=explanation["uncertainty"],
                canonical_content_id=canonical_id,
                generator_version=event_config().snapshot_version,
                explanation=explanation,
                metadata_={"canonical_selection": canonical_reason, "source_independence": independence},
                created_at=utcnow_naive(),
            )
        )
        event.latest_snapshot_version = version
        event.last_material_update_at = utcnow_naive()
        reliability_metrics.record(f"event_snapshot:{change}")
        event_metrics.increment("pim_event_snapshot_total", labels={"reason": change})
    event.title = title
    event.summary = summary
    event.canonical_content_id = canonical_id
    event.independent_source_count = int(independence["effective_independent_source_count"])
    event.source_names = sorted({row.source.name for row in contents if row.source})
    scores = [
        float(row.article_score if row.article_score is not None else row.final_score or 0.0)
        for row in contents
    ]
    event.importance_score = max(scores, default=0.0)
    event.confidence_score = float(signature.get("confidence") or 0.0) * 100
    low_value_roles = set(independence["source_roles"]) <= {"aggregator", "reprint", "unknown"}
    event.event_state = (
        "need_to_know"
        if independence["effective_independent_source_weight"] >= 1.8
        or signature.get("source_claim_type") == "official"
        or canonical_reason.get("source_role") == "official"
        else (
            "noise"
            if low_value_roles and event.importance_score < 20
            else ("developing" if len(contents) > 1 else "watch")
        )
    )
    tokens: set[str] = set()
    for row in contents:
        tokens.update(_tokenize(f"{row.title or ''} {row.summary or ''}"))
    event.centroid = {
        "tokens": sorted(tokens)[:500],
        "signature": {
            **signature,
            "event_time_start": signature.get("event_time_start").isoformat()
            if isinstance(signature.get("event_time_start"), datetime)
            else signature.get("event_time_start"),
            "event_time_end": signature.get("event_time_end").isoformat()
            if isinstance(signature.get("event_time_end"), datetime)
            else signature.get("event_time_end"),
        },
        "representative_content_ids": [canonical_id],
        "source_independence": independence,
        "centroid_version": event_config().cluster_version,
    }
    content_token_sets = [_tokenize(f"{row.title or ''} {row.summary or ''}") for row in contents]
    pair_distances = [
        1.0 - _jaccard(left, right)
        for left, right in combinations(content_token_sets, 2)
    ]
    event.dispersion = round(sum(pair_distances) / len(pair_distances), 3) if pair_distances else 0.0
    event.last_seen_at = max(
        [row.publish_time or row.fetched_at or utcnow_naive() for row in contents],
        default=utcnow_naive(),
    )
    event.updated_at = utcnow_naive()
    event.metadata_ = {
        **(event.metadata_ if isinstance(event.metadata_, dict) else {}),
        "active_member_count": len(contents),
        "canonical_selection": canonical_reason,
        "source_independence": independence,
        "event_signature": event.centroid["signature"],
        "snapshot_truth_source": True,
    }
    return created


def _create_event(db: Session, content: Content, signature: dict[str, Any]) -> ContentEvent:
    event_id = uuid7_hex()
    event_key = f"evt-{signature['fingerprint'][:12]}-{event_id[-6:]}"
    now = utcnow_naive()
    event = ContentEvent(
        event_id=event_id,
        event_key=event_key,
        title=_safe_title(content, signature),
        summary=content.translated_summary or content.summary,
        status="active",
        first_seen_at=content.publish_time or content.fetched_at or now,
        last_seen_at=content.publish_time or content.fetched_at or now,
        anchor_signature=signature["fingerprint"],
        cluster_version=event_config().cluster_version,
        latest_snapshot_version=0,
        event_state="watch",
        canonical_content_id=str(content.id),
        last_material_update_at=now,
        metadata_={"created_by": "event_assign", "snapshot_truth_source": True},
        created_at=now,
        updated_at=now,
    )
    db.add(event)
    db.flush()
    db.add(
        EventAlias(
            canonical_event_id=event_id,
            alias_type="event_key",
            alias_value=event_key,
            redirect_enabled=True,
            created_at=now,
            valid_from=now,
        )
    )
    reliability_metrics.record("event_created")
    event_metrics.increment("pim_event_created_total")
    return event


def assign_content(db: Session, content_id: str, *, shadow_only: bool = True) -> AssignmentResult:
    """Idempotently assign one post-processed Content row to Event v1."""

    if not event_v1_assignment_enabled():
        return AssignmentResult(content_id=str(content_id), event_id=None, decision="skipped", relation="unrelated", candidate_count=0, skipped_reason="feature_disabled")
    started = time.perf_counter()
    config = event_config()
    existing = (
        db.query(EventMembershipV1)
        .filter(
            EventMembershipV1.content_id == str(content_id),
            EventMembershipV1.assignment_version == config.cluster_version,
            EventMembershipV1.active.is_(True),
        )
        .first()
    )
    if existing is not None:
        return AssignmentResult(
            content_id=str(content_id),
            event_id=existing.event_id,
            decision="idempotent",
            relation=existing.relation,
            candidate_count=len((existing.explanation or {}).get("candidates") or []),
        )
    content = (
        db.query(Content)
        .options(joinedload(Content.source))
        .filter(Content.id == str(content_id))
        .first()
    )
    if content is None:
        raise LookupError(f"Content not found: {content_id}")
    signature = extract_event_signature(
        title=content.title,
        summary=content.summary,
        publish_time=content.publish_time or content.fetched_at,
        metadata=content.metadata_ if isinstance(content.metadata_, dict) else {},
    )
    _save_signature(db, content, signature)
    recalled = recall_candidates(db, content, signature)
    classified = [
        _classify(
            signature,
            content,
            row["event"],
            duplicate=bool(row["duplicate"]),
            alias=bool(row["alias"]),
            recall_reasons=row["recall_reasons"],
        )
        for row in recalled
    ]
    classified.sort(key=lambda row: (row["score"], row["event"].event_id), reverse=True)
    best = classified[0] if classified else None
    auto_attach = bool(
        best
        and not best["hard_conflicts"]
        and best["relation"] in {"same_event", "event_update", "duplicate"}
        and best["score"] >= best["effective_threshold"]
    )
    created = False
    if auto_attach:
        event = best["event"]
        decision = "attach"
        relation = best["relation"]
    else:
        event = _create_event(db, content, signature)
        created = True
        decision = "review_new" if best and best["score"] >= config.review_threshold else "new"
        relation = "related_context" if decision == "review_new" else "same_event"
    db.query(EventMembershipV1).filter(
        EventMembershipV1.content_id == str(content.id),
        EventMembershipV1.assignment_version == config.cluster_version,
        EventMembershipV1.active.is_(True),
    ).update({"active": False, "updated_at": utcnow_naive()}, synchronize_session=False)
    candidate_payload = [
        {
            "event_id": row["event"].event_id,
            "rank": index,
            "score": row["score"],
            "relation": row["relation"],
            "recall_reasons": row["recall_reasons"],
            "component_scores": row["component_scores"],
            "hard_conflicts": row["hard_conflicts"],
            "effective_threshold": row["effective_threshold"],
        }
        for index, row in enumerate(classified, start=1)
    ]
    method = "duplicate_propagation" if best and best["relation"] == "duplicate" and auto_attach else assignment_mode()
    explanation = {
        "candidates": candidate_payload,
        "selected_event_id": event.event_id,
        "decision": decision,
        "relation": relation,
        "classifier_version": config.classifier_version,
        "signature_version": config.signature_version,
        "actual_threshold": best["effective_threshold"] if auto_attach and best else config.auto_attach_threshold,
        "shadow_only": shadow_only,
    }
    db.add(
        EventMembershipV1(
            event_id=event.event_id,
            content_id=str(content.id),
            assignment_version=config.cluster_version,
            role="primary" if created else ("duplicate" if relation == "duplicate" else "supporting"),
            confidence=best["score"] if auto_attach and best else 1.0,
            explanation=explanation,
            shadow_only=shadow_only,
            active=True,
            assignment_method=method,
            relation=relation,
            effective_threshold=best["effective_threshold"] if auto_attach and best else config.auto_attach_threshold,
            created_at=utcnow_naive(),
            updated_at=utcnow_naive(),
        )
    )
    db.flush()
    snapshot_created = _refresh_event_and_snapshot(db, event, content, signature)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    db.add(
        EventAssignmentLog(
            content_id=str(content.id),
            assignment_version=config.cluster_version,
            selected_event_id=event.event_id,
            decision=decision,
            relation=relation,
            assignment_method=method,
            candidate_count=len(candidate_payload),
            candidates=candidate_payload,
            component_scores=(best or {}).get("component_scores") or {},
            hard_conflicts=(best or {}).get("hard_conflicts") or [],
            explain_reasons=(best or {}).get("recall_reasons") or ["stable_event_created"],
            effective_threshold=(best or {}).get("effective_threshold") or config.auto_attach_threshold,
            latency_ms=latency_ms,
            shadow_only=shadow_only,
            created_at=utcnow_naive(),
        )
    )
    from app.platform.persistence.lineage import add_lineage_edge

    add_lineage_edge(
        from_type="content",
        from_id=str(content.id),
        to_type="event",
        to_id=event.event_id,
        relation="assigned_to",
        pipeline_version=config.cluster_version,
        metadata={"relation": relation, "shadow_only": shadow_only},
        session=db,
    )
    if snapshot_created:
        add_lineage_edge(
            from_type="event",
            from_id=event.event_id,
            to_type="event_snapshot",
            to_id=f"{event.event_id}:v{event.latest_snapshot_version}",
            relation="snapshotted_as",
            pipeline_version=config.snapshot_version,
            session=db,
        )
    reliability_metrics.record(f"event_assignment:{method}:{decision}")
    reliability_metrics.record("event_assignment_latency_ms", latency_ms)
    reliability_metrics.record("event_candidate_count", len(candidate_payload))
    event_metrics.increment(
        "pim_event_assignment_total",
        labels={"method": method, "decision": decision, "version": config.cluster_version},
    )
    event_metrics.observe(
        "pim_event_assignment_latency_seconds",
        latency_ms / 1000,
        labels={"stage": "total"},
    )
    event_metrics.observe("pim_event_candidate_count", len(candidate_payload))
    event_metrics.gauge("pim_event_cluster_size_bucket", int((event.metadata_ or {}).get("active_member_count") or 1))
    event_metrics.gauge("pim_event_cluster_dispersion", float(event.dispersion or 0.0))
    if method == "duplicate_propagation":
        event_metrics.increment("pim_event_duplicate_propagation_ratio", labels={"kind": "assignment"})
    return AssignmentResult(
        content_id=str(content.id),
        event_id=event.event_id,
        decision=decision,
        relation=relation,
        candidate_count=len(candidate_payload),
        created=created,
        snapshot_created=snapshot_created,
    )


def assign_content_sync(content_id: str, *, shadow_only: bool = True) -> AssignmentResult:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = assign_content(db, str(content_id), shadow_only=shadow_only)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def backfill_event_v1(
    db: Session,
    *,
    cursor: str | None = None,
    batch_size: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    query = db.query(Content).order_by(Content.created_at, Content.id)
    if cursor:
        try:
            cursor_time_raw, cursor_id = cursor.split("|", 1)
            cursor_time = datetime.fromisoformat(cursor_time_raw)
            query = query.filter(
                or_(
                    Content.created_at > cursor_time,
                    (Content.created_at == cursor_time) & (Content.id > cursor_id),
                )
            )
        except (TypeError, ValueError):
            query = query.filter(Content.id > cursor)
    rows = query.limit(max(1, min(1000, int(batch_size)))).all()
    results: list[dict[str, Any]] = []
    for row in rows:
        if dry_run:
            signature = extract_event_signature(
                title=row.title,
                summary=row.summary,
                publish_time=row.publish_time or row.fetched_at,
                metadata=row.metadata_ if isinstance(row.metadata_, dict) else {},
            )
            results.append({"content_id": str(row.id), "signature_fingerprint": signature["fingerprint"]})
        else:
            result = assign_content(db, str(row.id), shadow_only=True)
            results.append(result.__dict__)
    normalized = [
        (str(row.get("content_id")), str(row.get("event_id") or row.get("signature_fingerprint") or ""))
        for row in results
    ]
    checksum = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "input_count": len(rows),
        "results": results,
        "last_cursor": (
            f"{rows[-1].created_at.isoformat()}|{rows[-1].id}"
            if rows and rows[-1].created_at
            else (str(rows[-1].id) if rows else cursor)
        ),
        "checksum": checksum,
        "assignment_version": event_config().cluster_version,
        "dry_run": dry_run,
    }


__all__ = [
    "AssignmentResult",
    "assign_content",
    "assign_content_sync",
    "backfill_event_v1",
    "recall_candidates",
    "uuid7_hex",
]
