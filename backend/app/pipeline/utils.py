"""Pipeline utility compatibility facade.

.. deprecated::
    ``get_website_content_reject_reason`` (and the constants /
    helpers backing it) moved to :mod:`app.domains.ingest.quality`
    as part of Phase 2/3 of the module refactor. This module keeps
    a re-export so existing ``unittest.mock.patch`` targets and
    ``from app.pipeline.utils import …`` callers continue to work;
    new code SHOULD import from the new home.
"""

from app.domains.fetch.collector_stage import (  # noqa: F401
    dedupe_raw_contents,
    get_source_urls,
    normalize_extra_urls,
)
from app.domains.ingest.publish_time import (  # noqa: F401
    _parse_iso_publish_time,
    normalize_publish_time,
    resolve_website_publish_time,
)
from app.domains.ingest.quality import (  # noqa: F401 — re-export
    _DOMAIN_NON_ARTICLE_PATH_SEGMENTS,
    _DOMAIN_WEBSITE_SECTION_TITLES,
    _NON_ARTICLE_PATH_SEGMENTS,
    _STRONG_WEBSITE_NAV_TITLES,
    _host_matches_domain,
    _looks_like_section_path,
    _matches_known_title,
    _normalize_host,
    _normalize_title_key,
    _same_site,
    _word_count,
    get_website_content_reject_reason,
)
from app.utils.url import normalize_external_id, normalize_source_url_for_dedupe  # noqa: F401

__all__ = [
    "_DOMAIN_NON_ARTICLE_PATH_SEGMENTS",
    "_DOMAIN_WEBSITE_SECTION_TITLES",
    "_NON_ARTICLE_PATH_SEGMENTS",
    "_STRONG_WEBSITE_NAV_TITLES",
    "_host_matches_domain",
    "_looks_like_section_path",
    "_matches_known_title",
    "_normalize_host",
    "_normalize_title_key",
    "_parse_iso_publish_time",
    "_same_site",
    "_word_count",
    "dedupe_raw_contents",
    "get_source_urls",
    "get_website_content_reject_reason",
    "normalize_external_id",
    "normalize_extra_urls",
    "normalize_publish_time",
    "normalize_source_url_for_dedupe",
    "resolve_website_publish_time",
]
