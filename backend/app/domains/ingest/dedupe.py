"""Deduplication helpers for ingest-side normalization."""

from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.domains.score.score_utils import normalize_authority_type, normalize_source_stars
from app.models import Content, Source
from app.utils.datetime import utcnow_naive
from app.utils.url import canonical_article_external_id, normalize_external_id
from app.utils.text import truncate_content
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _metadata_duplicate_group_id(content: Content) -> str:
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    return str(metadata.get("duplicate_group_id") or "").strip()


_FULLTEXT_STATUS_RANK = {
    "full": 5,
    "partial": 4,
    "summary_only": 3,
    "title_only": 1,
    "blocked": 0,
    "login_required": 0,
    "bot_wall": 0,
    "captcha": 0,
}

_AUTHORITY_TYPE_RANK = {
    "official": 5,
    "primary": 4,
    "wire": 3,
    "expert": 3,
    "analysis": 2,
    "community": 1,
    "aggregator": 0,
    "unknown": 0,
}


def _as_float(value, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fulltext_rank(member: Content, metadata: dict) -> tuple[int, float, int]:
    status = str(metadata.get("fulltext_status") or "").strip().lower()
    content_quality = _as_float(metadata.get("content_quality"), default=0.0)
    body_len = len((member.full_content or "").strip())
    if not status:
        if body_len >= 1200:
            status = "full"
        elif body_len >= 400:
            status = "partial"
        elif (member.summary or member.translated_summary or "").strip():
            status = "summary_only"
        else:
            status = "title_only"
    return (_FULLTEXT_STATUS_RANK.get(status, 0), content_quality, body_len)


def _source_rank(member: Content) -> tuple[int, int]:
    source = member.source
    source_metadata = source.metadata_ if source and isinstance(source.metadata_, dict) else {}
    content_metadata = member.metadata_ if isinstance(member.metadata_, dict) else {}
    authority_type = normalize_authority_type(
        content_metadata.get("authority_type") or source_metadata.get("authority_type")
    )
    source_stars = normalize_source_stars(
        content_metadata.get("source_stars") or source_metadata.get("source_stars"),
        default=1,
    )
    return (_AUTHORITY_TYPE_RANK.get(authority_type, 0), source_stars)


def _score_rank(member: Content, metadata: dict) -> float:
    for value in (
        member.final_score,
        member.article_score,
        metadata.get("final_score"),
        metadata.get("article_score"),
    ):
        if value is not None:
            return _as_float(value, default=-1.0)
    return -1.0


def _canonical_rank(member: Content) -> tuple:
    metadata = member.metadata_ if isinstance(member.metadata_, dict) else {}
    publish_time = member.publish_time or member.fetched_at or member.created_at or utcnow_naive()
    fetched_at = member.fetched_at or member.created_at or utcnow_naive()
    return (
        *_source_rank(member),
        *_fulltext_rank(member, metadata),
        _score_rank(member, metadata),
        publish_time,
        fetched_at,
        str(member.id),
    )


def _canonical_duplicate_member(members: list[Content]) -> Content:
    """Pick the best readable representative for a duplicate group.

    P1-08: prefer first-party / authoritative sources, then richer body quality,
    then score and freshness. This intentionally allows a later full-text row to
    replace an earlier summary-only canonical row.
    """
    return max(members, key=_canonical_rank)


def _merge_user_state_into_new_canonical(previous: Content | None, canonical: Content) -> None:
    """Keep user-visible state when the duplicate representative changes."""
    if previous is None or str(previous.id) == str(canonical.id):
        return
    canonical.read_status = bool(canonical.read_status or previous.read_status)
    canonical.favorited = bool(canonical.favorited or previous.favorited)


def mark_title_group_duplicate_members(db: Session, content: Content) -> None:
    """Collapse rows sharing a title duplicate group onto one canonical row."""
    group_id = _metadata_duplicate_group_id(content)
    if not group_id:
        return

    members = (
        db.query(Content)
        .filter(func.json_extract(Content.metadata_, "$.duplicate_group_id") == group_id)
        .all()
    )
    if len(members) < 2:
        return

    previous_canonical = next((member for member in members if not member.is_duplicate and not member.duplicate_of), None)
    canonical = _canonical_duplicate_member(members)
    _merge_user_state_into_new_canonical(previous_canonical, canonical)
    canonical_id = str(canonical.id)
    for member in members:
        metadata = member.metadata_ if isinstance(member.metadata_, dict) else {}
        merged = dict(metadata)
        if str(member.id) == canonical_id:
            member.is_duplicate = False
            member.duplicate_of = None
            merged["is_duplicate"] = False
            merged.pop("duplicate_of", None)
        else:
            member.is_duplicate = True
            member.duplicate_of = canonical_id
            merged["is_duplicate"] = True
            merged["duplicate_of"] = canonical_id
        member.metadata_ = merged
        member.updated_at = utcnow_naive()


def handle_external_id_duplicate(
    db: Session,
    source: Source,
    raw_content: dict,
    external_id: str,
) -> bool:
    """Handle duplicate external_id detection.

    Returns True when the incoming row should be skipped (same-source duplicate).
    Cross-source matches are recorded in metadata but preserved.

    The caller owns the surrounding transaction: this helper mutates ``existing``
    (backfilling fulltext/metadata) through the attached session but does NOT
    commit. ``run_fetch_pipeline`` issues a single commit after the normalize /
    store stages run, so a duplicate batch no longer triggers N independent
    write-ahead-log fsyncs.
    """
    raw_meta = raw_content.get("metadata") if isinstance(raw_content.get("metadata"), dict) else {}
    normalized_eid = normalize_external_id(external_id) or external_id
    identity_keys = {external_id, normalized_eid}
    article_url = str(raw_content.get("url") or "").strip()
    canonical_url = str(raw_meta.get("canonical_url") or "").strip()
    canonical_external_id = str(raw_meta.get("canonical_external_id") or "").strip()
    if canonical_url:
        identity_keys.add(canonical_article_external_id(canonical_url))
    if canonical_external_id:
        identity_keys.add(canonical_external_id)
        normalized_canonical = normalize_external_id(canonical_external_id)
        if normalized_canonical:
            identity_keys.add(normalized_canonical)
    identity_keys = {key for key in identity_keys if key}
    url_identities = {url for url in (article_url, canonical_url) if url}

    identity_filters = [Content.external_id.in_(list(identity_keys))]
    if url_identities:
        identity_filters.append(Content.original_url.in_(list(url_identities)))
    if identity_keys:
        identity_filters.append(func.json_extract(Content.metadata_, "$.canonical_external_id").in_(list(identity_keys)))
    if canonical_url:
        identity_filters.append(func.json_extract(Content.metadata_, "$.canonical_url") == canonical_url)

    existing = db.query(Content).filter(
        Content.source_id == source.id,
        or_(*identity_filters),
    ).first()

    cross_source_match = (
        db.query(Content.id)
        .join(Source)
        .filter(
            Source.type == source.type,
            or_(*identity_filters),
            Content.source_id != source.id,
        )
        .first()
    )
    if cross_source_match:
        merged = dict(raw_meta)
        merged["cross_source_external_id_match"] = str(cross_source_match[0])
        raw_content["metadata"] = merged

    if not existing:
        return False

    logger.info("Skipping duplicate content (same-source external_id): %s", external_id)
    raw_meta = raw_content.get("metadata") if isinstance(raw_content.get("metadata"), dict) else {}
    raw_text = str(raw_content.get("content") or "").strip()
    article_fulltext = bool(raw_meta.get("article_fulltext"))

    # Backfill richer payload to existing rows when this fetch has a better body.
    if raw_meta:
        merged_meta = existing.metadata_ if isinstance(existing.metadata_, dict) else {}
        merged_meta = {**merged_meta, **raw_meta}
        existing.metadata_ = merged_meta

    if article_fulltext and raw_text and len(raw_text) >= 280:
        # Never overwrite content if user has manually edited it
        should_upgrade = (not existing.is_user_edited) and (not existing.full_content or len(raw_text) > len(existing.full_content or ""))
        if should_upgrade:
            existing.full_content = truncate_content(raw_text, url=str(raw_content.get("url") or ""))
            if not existing.summary:
                existing.summary = raw_text[:300] + ("..." if len(raw_text) > 300 else "")
            if raw_content.get("url"):
                existing.original_url = str(raw_content.get("url"))
            if str(existing.title or "").startswith(("http://", "https://")) and raw_content.get("title"):
                existing.title = str(raw_content.get("title"))
            existing.updated_at = utcnow_naive()
            logger.info("Backfilled article fulltext for duplicate content: %s", external_id)

    # Intentionally no commit here — see docstring. The coordinator commits at
    # the batch boundary so duplicate backfills share a transaction with the
    # rest of the fetch pipeline.
    return True
