"""Fetch domain.

Canonical collector implementations, auth helpers, failure classification,
retry policy, discovery, session health, and RSS/fulltext quality helpers live
under this package.

The runtime fetch chain is intentionally single-sourced through
``app.tasks.fetch_tasks -> app.domains.fetch.coordinator ->
app.domains.fetch.collector_stage``. Older draft-only batch contract entry
points were removed because they were never called by production code, and
the legacy ``app.pipeline.coordinator`` path is only a compatibility alias.
"""

__all__: list[str] = []
