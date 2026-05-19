"""Backwards-compatible facade for :class:`WebsiteCollector`.

Implementation lives at :mod:`app.domains.fetch.collectors.website`. We
re-export the class plus the module attributes that existing tests patch
through ``unittest.mock.patch("app.collectors.website.<name>", ...)``:

* ``human_inter_request_pause`` — read by ``_hydrate_direct_articles``;
  tests stub it to control timing.
* ``_helpers`` / ``_parser`` — internal aliases that tests reach via
  ``__import__("app.collectors.website", fromlist=["_helpers"])._helpers``.

.. deprecated::
   Import :class:`WebsiteCollector` from
   :mod:`app.domains.fetch.collectors.website` directly. This shim will be
   removed in Phase 7.
"""

from app.domains.fetch.collectors import (
    website_helpers as _helpers,
    website_parser as _parser,
)
from app.domains.fetch.collectors.website import (
    WebsiteCollector,
    human_inter_request_pause,
    logger,
)

__all__ = [
    "WebsiteCollector",
    "_helpers",
    "_parser",
    "human_inter_request_pause",
    "logger",
]
