"""Backwards-compatible facade for :mod:`app.domains.fetch.collectors.x_twitter_text`.

.. deprecated::
   Import from :mod:`app.domains.fetch.collectors.x_twitter_text`. This
   shim will be removed in Phase 7.
"""

from app.domains.fetch.collectors.x_twitter_text import *  # noqa: F401,F403
from app.domains.fetch.collectors.x_twitter_text import (  # noqa: F401
    ARTICLE_URL_RE,
    build_api_since_id,
    build_title_from_text,
    build_x_cookie_items,
    clean_article_text,
    extract_article_urls,
    extract_tweet_id,
    extract_username_from_url,
    normalize_tweet_url,
    title_looks_like_url,
)
