"""Persist ingest rows and report exactly what reached durable storage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy.exc import IntegrityError, OperationalError, StatementError
from sqlalchemy.orm import Session

from app.models import Content
from app.domains.ingest.dedupe import mark_title_group_duplicate_members
from app.utils.logger import get_logger
from app.utils.url import normalize_external_id

logger = get_logger(__name__)

PIPELINE_VERSION = "ingest-finish-v1"


class StorageOutcome(StrEnum):
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


@dataclass(frozen=True)
class StorageFailure:
    input_ref: str
    failure_code: str
    failure_class: str
    retryable: bool
    message: str
    stage: str = "storage"


@dataclass(frozen=True)
class PostprocessCandidate:
    content_id: str
    trigger_reason: str
    content_fingerprint: str
    pipeline_version: str = PIPELINE_VERSION

    @property
    def idempotency_suffix(self) -> str:
        return f"{self.pipeline_version}:{self.content_fingerprint}"


@dataclass(frozen=True)
class UnchangedDuplicateRef:
    input_ref: str
    content_id: str | None
    duplicate_key: str


@dataclass
class StorageResult:
    requested_count: int
    saved_ids: list[str] = field(default_factory=list)
    updated_ids: list[str] = field(default_factory=list)
    unchanged_duplicate_refs: list[UnchangedDuplicateRef] = field(default_factory=list)
    postprocess_candidates: list[PostprocessCandidate] = field(default_factory=list)
    failed_items: list[StorageFailure] = field(default_factory=list)
    latest_saved_marker: str | None = None
    transaction_id: str | None = None

    @property
    def saved_count(self) -> int:
        return len(self.saved_ids)

    @property
    def updated_count(self) -> int:
        return len(self.updated_ids)

    @property
    def unchanged_duplicate_count(self) -> int:
        return len(self.unchanged_duplicate_refs)

    @property
    def failed_count(self) -> int:
        return len(self.failed_items)

    @property
    def outcome(self) -> StorageOutcome:
        if self.failed_count == 0:
            return StorageOutcome.SUCCESS
        if self.saved_count or self.updated_count or self.unchanged_duplicate_count:
            return StorageOutcome.PARTIAL_FAILURE
        return StorageOutcome.FAILED

    def assert_conservation(self) -> None:
        classified = self.saved_count + self.updated_count + self.unchanged_duplicate_count + self.failed_count
        if classified != self.requested_count:
            raise RuntimeError(
                f"storage result conservation failed: requested={self.requested_count} classified={classified}"
            )


_COPY_FIELDS = (
    "title",
    "translated_title",
    "summary",
    "translated_summary",
    "original_url",
    "full_content",
    "content_type",
    "publish_time",
)
_SUBSTANTIVE_FIELDS = {
    "summary",
    "translated_summary",
    "full_content",
    "publish_time",
}
_SUBSTANTIVE_METADATA_KEYS = {
    "fetch_acceptance",
    "fetch_acceptance_reason",
    "fulltext_status",
    "article_fulltext",
    "article_text_chars",
    "event_id",
    "event_key",
    "facts",
    "pipeline_version",
}


def _input_ref(content: Content) -> str:
    return str(content.external_id or content.original_url or content.id or "<unknown>")


def _duplicate_key(content: Content) -> str:
    return f"{content.source_id}:{content.external_id or content.original_url}"


def _identity_query(db: Session, content: Content):
    query = db.query(Content).filter(Content.source_id == content.source_id)
    if content.external_id:
        return query.filter(Content.external_id == content.external_id)
    return query.filter(Content.external_id.is_(None), Content.original_url == content.original_url)


def _fingerprint(content: Content) -> str:
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    payload = {
        "title": content.title or "",
        "summary": content.summary or "",
        "translated_summary": content.translated_summary or "",
        "full_content": content.full_content or "",
        "publish_time": content.publish_time.isoformat() if content.publish_time else None,
        "content_type": content.content_type or "",
        "metadata": {key: metadata.get(key) for key in sorted(_SUBSTANTIVE_METADATA_KEYS) if key in metadata},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _merge_existing(existing: Content, incoming: Content) -> tuple[bool, bool, str]:
    changed_fields: set[str] = set()
    substantive = False
    old_metadata = existing.metadata_ if isinstance(existing.metadata_, dict) else {}
    new_metadata = incoming.metadata_ if isinstance(incoming.metadata_, dict) else {}

    for name in _COPY_FIELDS:
        incoming_value = getattr(incoming, name, None)
        existing_value = getattr(existing, name, None)
        if incoming_value is None and existing_value is not None:
            continue
        if incoming_value == existing_value:
            continue
        setattr(existing, name, incoming_value)
        changed_fields.add(name)
        if name in _SUBSTANTIVE_FIELDS:
            substantive = True

    merged_metadata = {**old_metadata, **new_metadata}
    if merged_metadata != old_metadata:
        existing.metadata_ = merged_metadata
        changed_fields.add("metadata_")
        if any(old_metadata.get(key) != merged_metadata.get(key) for key in _SUBSTANTIVE_METADATA_KEYS):
            substantive = True
    if not changed_fields:
        return False, False, "unchanged_duplicate"
    if substantive:
        return True, True, "substantive_update"
    return True, False, "non_substantive_update"


def _failure(content: Content, exc: BaseException) -> StorageFailure:
    if isinstance(exc, OperationalError):
        code, failure_class, retryable = "DATABASE_RETRYABLE", "database", True
    elif isinstance(exc, StatementError):
        code, failure_class, retryable = "DEAD_DATA_SCHEMA", "schema", False
    elif isinstance(exc, IntegrityError):
        code, failure_class, retryable = "CONSTRAINT_VIOLATION", "schema", False
    else:
        code, failure_class, retryable = "UNKNOWN_STORAGE_FAILURE", "unknown", False
    return StorageFailure(
        input_ref=_input_ref(content),
        failure_code=code,
        failure_class=failure_class,
        retryable=retryable,
        message=str(exc or exc.__class__.__name__)[:500],
    )


class StorageStage:

    @staticmethod
    def execute(db: Session, contents: list[Content]) -> StorageResult:
        """Persist a batch with an exhaustive, conservation-checked result."""
        result = StorageResult(requested_count=len(contents))
        for content in contents:
            try:
                existing = _identity_query(db, content).first()
                if existing is not None:
                    with db.begin_nested():
                        changed, should_postprocess, trigger_reason = _merge_existing(existing, content)
                        if changed:
                            db.flush()
                            mark_title_group_duplicate_members(db, existing)
                    if not changed:
                        result.unchanged_duplicate_refs.append(
                            UnchangedDuplicateRef(_input_ref(content), str(existing.id), _duplicate_key(content))
                        )
                        continue
                    content_id = str(existing.id)
                    result.updated_ids.append(content_id)
                    if should_postprocess:
                        result.postprocess_candidates.append(
                            PostprocessCandidate(content_id, trigger_reason, _fingerprint(existing))
                        )
                    marker_candidate = normalize_external_id(existing.external_id)
                    if marker_candidate and not result.latest_saved_marker:
                        result.latest_saved_marker = marker_candidate
                    continue

                with db.begin_nested():
                    db.add(content)
                    db.flush()
                    mark_title_group_duplicate_members(db, content)
                content_id = str(content.id)
                result.saved_ids.append(content_id)
                result.postprocess_candidates.append(
                    PostprocessCandidate(content_id, "new_insert", _fingerprint(content))
                )
                marker_candidate = normalize_external_id(content.external_id)
                if marker_candidate and not result.latest_saved_marker:
                    result.latest_saved_marker = marker_candidate
            except IntegrityError as exc:
                # A concurrent insert may win after the preflight lookup. Only
                # classify it as a duplicate when the business identity exists;
                # other constraints are real failures.
                existing = _identity_query(db, content).first()
                if existing is not None:
                    result.unchanged_duplicate_refs.append(
                        UnchangedDuplicateRef(_input_ref(content), str(existing.id), _duplicate_key(content))
                    )
                    logger.info("Skipping duplicate content on insert: %s", _input_ref(content))
                else:
                    result.failed_items.append(_failure(content, exc))
                    logger.exception("Storage constraint failure for %s", _input_ref(content))
            except Exception as exc:  # noqa: BLE001 - converted to an explicit typed result
                result.failed_items.append(_failure(content, exc))
                logger.exception("Error saving content %s", _input_ref(content))

        result.assert_conservation()
        return result


__all__ = [
    "PIPELINE_VERSION",
    "PostprocessCandidate",
    "StorageFailure",
    "StorageOutcome",
    "StorageResult",
    "StorageStage",
    "UnchangedDuplicateRef",
]
