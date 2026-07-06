"""Fetch finalization — second-hop body hydration before ingest/score.

Completes the fetch contract: title + body (+ listing summary derived from
body when missing). Acceptance assessment runs later once quality metadata
is stamped (see :func:`app.domains.fetch.acceptance.assess_fetch_acceptance`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domains.fetch.acceptance import ensure_listing_summary
from app.domains.fetch.article_body import (
    ensure_content_bodies_during_finish,
    fetch_cookie_article_body,
)
from app.utils.logger import get_logger
from app.utils.text import truncate_content

if TYPE_CHECKING:
    from app.models import Content, Source

logger = get_logger(__name__)


async def hydrate_fetched_content(
    content: Content,
    source: Source | None,
    *,
    processor=None,
) -> None:
    """Second-hop fetch: cookie full-text, public URL body, X long-article."""
    from app.domains.fetch.auth import try_parse_auth_credentials
    from app.utils.cookies import normalize_cookie_dict

    content_type = (content.content_type or "").strip().lower()
    if source and source.auth_config_id and content_type != "x":
        _ = processor
        try:
            creds = try_parse_auth_credentials(source.auth_config)
            cookies = normalize_cookie_dict(creds.get("cookies"))
            if cookies and (not content.full_content or len(content.full_content) < 600):
                fetched = await fetch_cookie_article_body(
                    content.original_url,
                    cookies,
                    source_url=source.url,
                )
                if fetched and len(fetched) > len(content.full_content or ""):
                    content.full_content = truncate_content(
                        fetched, url=content.original_url or ""
                    )
        except Exception as exc:  # noqa: BLE001 - cookie hydration is best-effort
            logger.debug("Cookie body hydration skipped for %s: %s", content.id, exc)

    await ensure_content_bodies_during_finish(content, source)
    ensure_listing_summary(content)


__all__ = ["hydrate_fetched_content"]
