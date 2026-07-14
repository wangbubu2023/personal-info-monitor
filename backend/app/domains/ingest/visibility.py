"""Shared visibility predicates for list, digest, and brief candidate queries."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.domains.ingest.metadata_sql import duplicate_group_id_expression
from app.models import Content


def visible_content_clause(content_model=Content, *, include_archived: bool = False):
    """Return the default user-visible content predicate.

    It hides archived rows unless requested, explicit duplicate rows, rows
    pointing at a canonical duplicate, and legacy duplicate-group followers
    where only ``metadata.duplicate_group_id`` exists. Fresh writes should stamp
    explicit duplicate fields via ingest canonical selection; the legacy fallback
    remains only for older rows that have not been reprocessed.
    """
    other = aliased(Content)
    group_id = duplicate_group_id_expression(content_model.metadata_)
    other_group_id = duplicate_group_id_expression(other.metadata_)
    earlier_same_group = (
        select(other.id)
        .where(
            other.id != content_model.id,
            other_group_id == group_id,
            or_(
                other.fetched_at < content_model.fetched_at,
                and_(other.fetched_at == content_model.fetched_at, other.id < content_model.id),
            ),
        )
        .exists()
    )
    explicit_duplicate_state = or_(
        content_model.is_duplicate.is_not(None),
        content_model.duplicate_of.is_not(None),
        func.json_type(content_model.metadata_, "$.is_duplicate").is_not(None),
        func.json_type(content_model.metadata_, "$.duplicate_of").is_not(None),
    )
    archived_clause = True if include_archived else or_(content_model.archived.is_(False), content_model.archived.is_(None))
    return and_(
        archived_clause,
        or_(content_model.is_duplicate.is_(False), content_model.is_duplicate.is_(None)),
        content_model.duplicate_of.is_(None),
        or_(group_id.is_(None), explicit_duplicate_state, ~earlier_same_group),
    )


__all__ = ["visible_content_clause"]
