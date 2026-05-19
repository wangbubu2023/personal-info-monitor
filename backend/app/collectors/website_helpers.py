"""Backwards-compatible facade for :mod:`app.domains.fetch.collectors.website_helpers`.

.. deprecated::
   Import from :mod:`app.domains.fetch.collectors.website_helpers`. This
   shim will be removed in Phase 7.
"""

from app.domains.fetch.collectors.website_helpers import *  # noqa: F401,F403 — re-export
from app.domains.fetch.collectors.website_helpers import (  # noqa: F401 — explicit patch targets
    logger,
    looks_like_article_url,
    utcnow_naive,
)
