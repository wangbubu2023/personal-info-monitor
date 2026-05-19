"""Backwards-compatible facade for :mod:`app.domains.fetch.collectors.website_parser`.

.. deprecated::
   Import from :mod:`app.domains.fetch.collectors.website_parser`. This
   shim will be removed in Phase 7.
"""

from app.domains.fetch.collectors.website_parser import *  # noqa: F401,F403 — re-export
from app.domains.fetch.collectors.website_parser import (  # noqa: F401 — explicit patch targets
    append_fallback_links,
    get_website_content_reject_reason,
    logger,
    parse_article_candidate,
    parse_html_content,
)
