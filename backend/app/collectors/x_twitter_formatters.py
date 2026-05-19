"""Backwards-compatible facade for :mod:`app.domains.fetch.collectors.x_twitter_formatters`.

.. deprecated::
   Import from :mod:`app.domains.fetch.collectors.x_twitter_formatters`.
   This shim will be removed in Phase 7.
"""

from app.domains.fetch.collectors.x_twitter_formatters import *  # noqa: F401,F403
from app.domains.fetch.collectors.x_twitter_formatters import (  # noqa: F401
    format_rss_entry,
    format_tweet_api,
    format_tweet_graphql,
)
