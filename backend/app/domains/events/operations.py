"""Audited Event resolve/merge/split/close/reopen/revert commands."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.domains.events.config import event_config
from app.domains.events.engine import uuid7_hex
from app.models import (
    ContentEvent,
    ContentEventSnapshot,
    Content,
    EventAlias,
    EventMembershipV1,
    EventOperation,
    PersonalItemState,
    UserRule,
    EventSignature,
)
from app.platform.observability.metrics import event_metrics
from app.utils.datetime import utcnow_naive


def resolve_event(db: Session, event_ref: str) -> dict[str, Any] | None:
    direct = db.get(ContentEvent, str(event_ref))
    if direct is not None and direct.status not in {"merged", "split"}:
        return {"kind": "canonical", "event_id": direct.event_id}
    alias = (
        db.query(EventAlias)
        .filter(EventAlias.alias_value == str(event_ref), EventAlias.redirect_enabled.is_(True))
        .first()
    )
    if alias is not None:
        target = db.get(ContentEvent, alias.canonical_event_id)
        if target is not None and target.status != "split":
            return {"kind": "redirect", "event_id": target.event_id, "from": str(event_ref)}
    event = direct
    if event is None:
        return None
    metadata = event.metadata_ if isinstance(event.metadata_, dict) else {}
    if event.status == "merged":
        return {"kind": "redirect", "event_id": metadata.get("redirect_event_id"), "from": event.event_id}
    if event.status == "split":
        return {"kind": "split", "event_id": event.event_id, "mapping": metadata.get("split_mapping") or {}}
    return {"kind": "canonical", "event_id": event.event_id}


def _copy_personal_state(db: Session, source_id: str, target_id: str) -> None:
    source = (
        db.query(PersonalItemState)
        .filter(PersonalItemState.target_type == "event", PersonalItemState.target_id == source_id)
        .first()
    )
    if source is None:
        return
    target = (
        db.query(PersonalItemState)
        .filter(PersonalItemState.target_type == "event", PersonalItemState.target_id == target_id)
        .first()
    )
    if target is None:
        target = PersonalItemState(target_type="event", target_id=target_id, created_at=utcnow_naive())
        db.add(target)
    target.last_seen_version = max(int(target.last_seen_version or 0), int(source.last_seen_version or 0))
    target.saved = bool(target.saved or source.saved)
    target.read_later = bool(target.read_later or source.read_later)
    target.hidden = bool(target.hidden and source.hidden)
    target.read_at = max(filter(None, [target.read_at, source.read_at]), default=None)
    target.updated_at = utcnow_naive()
    for rule in db.query(UserRule).filter(UserRule.scope_type == "event", UserRule.scope_key == source_id).all():
        exists = (
            db.query(UserRule)
            .filter(
                UserRule.scope_type == "event",
                UserRule.scope_key == target_id,
                UserRule.rule == rule.rule,
                UserRule.status == rule.status,
            )
            .first()
        )
        if exists is None:
            db.add(
                UserRule(
                    scope_type="event",
                    scope_key=target_id,
                    rule=rule.rule,
                    status=rule.status,
                    created_by="event_merge",
                    evidence_summary=f"Migrated from Event {source_id}",
                    metadata_={"source_event_id": source_id, "source_rule_id": str(rule.id)},
                    created_at=utcnow_naive(),
                    updated_at=utcnow_naive(),
                )
            )


def merge_events(
    db: Session,
    *,
    canonical_event_id: str,
    source_event_ids: list[str],
    actor: str,
    reason: str,
) -> EventOperation:
    canonical = db.get(ContentEvent, canonical_event_id)
    if canonical is None:
        raise LookupError("canonical event not found")
    sources = []
    for source_id in sorted(set(source_event_ids) - {canonical_event_id}):
        row = db.get(ContentEvent, source_id)
        if row is None:
            raise LookupError(f"source event not found: {source_id}")
        if row.status in {"merged", "split"}:
            raise ValueError(f"source event is already terminal: {source_id}")
        sources.append(row)
    if not sources:
        raise ValueError("merge requires at least one distinct source event")
    before = {
        row.event_id: {"status": row.status, "metadata": row.metadata_ or {}}
        for row in [canonical, *sources]
    }
    for source in sources:
        memberships = (
            db.query(EventMembershipV1)
            .filter(EventMembershipV1.event_id == source.event_id, EventMembershipV1.active.is_(True))
            .all()
        )
        for membership in memberships:
            membership.active = False
            membership.updated_at = utcnow_naive()
            target = (
                db.query(EventMembershipV1)
                .filter(
                    EventMembershipV1.event_id == canonical.event_id,
                    EventMembershipV1.content_id == membership.content_id,
                    EventMembershipV1.assignment_version == membership.assignment_version,
                )
                .first()
            )
            if target is None:
                db.add(
                    EventMembershipV1(
                        event_id=canonical.event_id,
                        content_id=membership.content_id,
                        assignment_version=membership.assignment_version,
                        role=membership.role,
                        confidence=membership.confidence,
                        explanation={
                            **(membership.explanation or {}),
                            "operation": "merge",
                            "source_event_id": source.event_id,
                        },
                        shadow_only=membership.shadow_only,
                        active=True,
                        assignment_method="manual_merge",
                        relation="same_event",
                        effective_threshold=membership.effective_threshold,
                        created_at=utcnow_naive(),
                        updated_at=utcnow_naive(),
                    )
                )
            else:
                target.active = True
                target.updated_at = utcnow_naive()
        source.status = "merged"
        source.metadata_ = {**(source.metadata_ or {}), "redirect_event_id": canonical.event_id}
        source.updated_at = utcnow_naive()
        alias_exists = (
            db.query(EventAlias)
            .filter(EventAlias.alias_type == "legacy_event_id", EventAlias.alias_value == source.event_id)
            .first()
        )
        if alias_exists is None:
            db.add(
                EventAlias(
                    canonical_event_id=canonical.event_id,
                    alias_type="legacy_event_id",
                    alias_value=source.event_id,
                    redirect_enabled=True,
                    valid_from=utcnow_naive(),
                    created_at=utcnow_naive(),
                )
            )
        else:
            alias_exists.canonical_event_id = canonical.event_id
            alias_exists.redirect_enabled = True
        _copy_personal_state(db, source.event_id, canonical.event_id)
    canonical.status = "active"
    canonical.updated_at = utcnow_naive()
    db.flush()
    representative_membership = (
        db.query(EventMembershipV1)
        .filter(EventMembershipV1.event_id == canonical.event_id, EventMembershipV1.active.is_(True))
        .first()
    )
    if representative_membership is not None:
        representative = db.get(Content, representative_membership.content_id)
        signature_row = (
            db.query(EventSignature)
            .filter(
                EventSignature.content_id == representative_membership.content_id,
                EventSignature.signature_version == event_config().signature_version,
            )
            .first()
        )
        if representative is not None and signature_row is not None:
            from app.domains.events.engine import _refresh_event_and_snapshot, _signature_payload

            _refresh_event_and_snapshot(db, canonical, representative, _signature_payload(signature_row))
    checksum = hashlib.sha256(
        json.dumps({"canonical": canonical.event_id, "sources": sorted(row.event_id for row in sources)}).encode()
    ).hexdigest()
    operation = EventOperation(
        event_id=canonical.event_id,
        operation_type="merge",
        input_event_ids=[row.event_id for row in sources],
        output_event_ids=[canonical.event_id],
        reason=reason,
        actor=actor,
        checksum=checksum,
        rollback_payload={"before": before},
        created_at=utcnow_naive(),
    )
    db.add(operation)
    return operation


def split_event(
    db: Session,
    *,
    event_id: str,
    groups: list[list[str]],
    actor: str,
    reason: str,
) -> EventOperation:
    source = db.get(ContentEvent, event_id)
    if source is None:
        raise LookupError("event not found")
    active = {
        str(row.content_id): row
        for row in (
            db.query(EventMembershipV1)
            .filter(EventMembershipV1.event_id == event_id, EventMembershipV1.active.is_(True))
            .all()
        )
    }
    flat = [str(content_id) for group in groups for content_id in group]
    if len(groups) < 2 or len(flat) != len(set(flat)) or set(flat) != set(active):
        raise ValueError("split groups must partition all active memberships exactly once")
    mapping: dict[str, str] = {}
    output_ids: list[str] = []
    for group in groups:
        new_id = uuid7_hex()
        output_ids.append(new_id)
        new_event = ContentEvent(
            event_id=new_id,
            event_key=f"evt-split-{new_id[-12:]}",
            title=source.title,
            summary=source.summary,
            status="active",
            first_seen_at=source.first_seen_at,
            last_seen_at=source.last_seen_at,
            anchor_signature=source.anchor_signature,
            cluster_version=event_config().cluster_version,
            event_state=source.event_state,
            centroid=source.centroid or {},
            metadata_={"split_from": source.event_id, "snapshot_truth_source": True},
            created_at=utcnow_naive(),
            updated_at=utcnow_naive(),
        )
        db.add(new_event)
        db.flush()
        db.add(
            EventAlias(
                canonical_event_id=new_id,
                alias_type="event_key",
                alias_value=new_event.event_key,
                valid_from=utcnow_naive(),
                redirect_enabled=True,
                created_at=utcnow_naive(),
            )
        )
        for content_id in group:
            prior = active[str(content_id)]
            mapping[str(content_id)] = new_id
            db.add(
                EventMembershipV1(
                    event_id=new_id,
                    content_id=str(content_id),
                    assignment_version=prior.assignment_version,
                    role=prior.role,
                    confidence=prior.confidence,
                    explanation={**(prior.explanation or {}), "operation": "split", "source_event_id": source.event_id},
                    shadow_only=prior.shadow_only,
                    active=True,
                    assignment_method="manual_split",
                    relation="same_event",
                    effective_threshold=prior.effective_threshold,
                    created_at=utcnow_naive(),
                    updated_at=utcnow_naive(),
                )
            )
            prior.active = False
            prior.updated_at = utcnow_naive()
        source_snapshot = (
            db.query(ContentEventSnapshot)
            .filter(ContentEventSnapshot.event_id == source.event_id)
            .order_by(ContentEventSnapshot.version.desc())
            .first()
        )
        if source_snapshot is not None:
            group_fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "source_fingerprint": source_snapshot.change_fingerprint,
                        "content_ids": sorted(str(value) for value in group),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            db.add(
                ContentEventSnapshot(
                    event_id=new_id,
                    version=1,
                    title=source_snapshot.title,
                    summary=source_snapshot.summary,
                    what_changed=f"从 Event {source.event_id} 拆分。",
                    why_matters=source_snapshot.why_matters,
                    source_content_ids=[str(value) for value in group],
                    change_type="corrected_fact",
                    change_fingerprint=group_fingerprint,
                    facts=source_snapshot.facts or [],
                    evidence_refs=[
                        row
                        for row in (source_snapshot.evidence_refs or [])
                        if str(row.get("content_id") or "") in {str(value) for value in group}
                    ],
                    uncertainty=source_snapshot.uncertainty or [],
                    canonical_content_id=str(group[0]),
                    generator_version=event_config().snapshot_version,
                    explanation={
                        **(source_snapshot.explanation or {}),
                        "what_changed_since_last_read": f"从 Event {source.event_id} 拆分并纠正成员边界。",
                    },
                    metadata_={"split_from": source.event_id},
                    created_at=utcnow_naive(),
                )
            )
            new_event.latest_snapshot_version = 1
            new_event.canonical_content_id = str(group[0])
    source.status = "split"
    source.metadata_ = {**(source.metadata_ or {}), "split_mapping": mapping, "split_event_ids": output_ids}
    source.updated_at = utcnow_naive()
    operation = EventOperation(
        event_id=source.event_id,
        operation_type="split",
        input_event_ids=[source.event_id],
        output_event_ids=output_ids,
        reason=reason,
        actor=actor,
        checksum=hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest(),
        rollback_payload={"source_status": "active", "mapping": mapping},
        created_at=utcnow_naive(),
    )
    db.add(operation)
    return operation


def set_event_lifecycle(db: Session, event_id: str, *, action: str, actor: str, reason: str) -> EventOperation:
    event = db.get(ContentEvent, event_id)
    if event is None:
        raise LookupError("event not found")
    allowed = {"close": "closed", "reopen": "reopened"}
    if action not in allowed:
        raise ValueError("unsupported lifecycle action")
    previous = event.status
    event.status = allowed[action]
    event.lifecycle_reason = reason
    event.updated_at = utcnow_naive()
    operation = EventOperation(
        event_id=event.event_id,
        operation_type=action,
        input_event_ids=[event.event_id],
        output_event_ids=[event.event_id],
        reason=reason,
        actor=actor,
        rollback_payload={"status": previous},
        created_at=utcnow_naive(),
    )
    db.add(operation)
    if action == "reopen":
        event_metrics.increment("pim_event_reopened_total")
    return operation


def revert_operation(db: Session, operation_id: str, *, actor: str, reason: str) -> EventOperation:
    operation = db.get(EventOperation, operation_id)
    if operation is None:
        raise LookupError("operation not found")
    if operation.operation_type in {"close", "reopen", "lifecycle"}:
        event = db.get(ContentEvent, operation.event_id)
        if event is None:
            raise LookupError("event not found")
        current = event.status
        event.status = str((operation.rollback_payload or {}).get("status") or "active")
        event.updated_at = utcnow_naive()
        payload = {"status": current}
    elif operation.operation_type == "split":
        source = db.get(ContentEvent, operation.event_id)
        if source is None:
            raise LookupError("event not found")
        mapping = (operation.rollback_payload or {}).get("mapping") or {}
        for content_id, output_id in mapping.items():
            db.query(EventMembershipV1).filter(
                EventMembershipV1.event_id == output_id,
                EventMembershipV1.content_id == content_id,
                EventMembershipV1.active.is_(True),
            ).update({"active": False, "updated_at": utcnow_naive()}, synchronize_session=False)
        db.query(EventMembershipV1).filter(
            EventMembershipV1.event_id == source.event_id,
        ).update({"active": True, "updated_at": utcnow_naive()}, synchronize_session=False)
        for output_id in operation.output_event_ids or []:
            target = db.get(ContentEvent, output_id)
            if target:
                target.status = "merged"
                target.metadata_ = {**(target.metadata_ or {}), "redirect_event_id": source.event_id}
        source.status = str((operation.rollback_payload or {}).get("source_status") or "active")
        source.updated_at = utcnow_naive()
        payload = {"split_operation_id": str(operation.id)}
    elif operation.operation_type == "merge":
        canonical = db.get(ContentEvent, operation.event_id)
        if canonical is None:
            raise LookupError("canonical event not found")
        before = (operation.rollback_payload or {}).get("before") or {}
        canonical_before = before.get(canonical.event_id) or {}
        canonical.status = str(canonical_before.get("status") or canonical.status)
        canonical.metadata_ = canonical_before.get("metadata") or canonical.metadata_
        canonical.updated_at = utcnow_naive()
        for source_id in operation.input_event_ids or []:
            source = db.get(ContentEvent, source_id)
            if source is None:
                continue
            source_before = before.get(source_id) or {}
            source.status = str(source_before.get("status") or "active")
            source.metadata_ = source_before.get("metadata") or {}
            source.updated_at = utcnow_naive()
            migrated = (
                db.query(EventMembershipV1)
                .filter(
                    EventMembershipV1.event_id == canonical.event_id,
                    EventMembershipV1.assignment_method == "manual_merge",
                    EventMembershipV1.active.is_(True),
                )
                .all()
            )
            migrated_ids = [
                membership.id
                for membership in migrated
                if str((membership.explanation or {}).get("source_event_id") or "") == source_id
            ]
            if migrated_ids:
                db.query(EventMembershipV1).filter(EventMembershipV1.id.in_(migrated_ids)).update(
                    {"active": False, "updated_at": utcnow_naive()},
                    synchronize_session=False,
                )
            db.query(EventMembershipV1).filter(
                EventMembershipV1.event_id == source_id,
            ).update({"active": True, "updated_at": utcnow_naive()}, synchronize_session=False)
            alias = (
                db.query(EventAlias)
                .filter(EventAlias.alias_type == "legacy_event_id", EventAlias.alias_value == source_id)
                .first()
            )
            if alias is not None:
                alias.canonical_event_id = source_id
        payload = {"merge_operation_id": str(operation.id)}
    else:
        raise ValueError("this operation type requires explicit recovery policy")
    reverted = EventOperation(
        event_id=operation.event_id,
        operation_type="revert",
        input_event_ids=operation.output_event_ids or [operation.event_id],
        output_event_ids=operation.input_event_ids or [operation.event_id],
        reason=reason,
        actor=actor,
        checkpoint=str(operation.id),
        rollback_payload=payload,
        created_at=utcnow_naive(),
    )
    db.add(reverted)
    return reverted


__all__ = [
    "merge_events",
    "resolve_event",
    "revert_operation",
    "set_event_lifecycle",
    "split_event",
]
