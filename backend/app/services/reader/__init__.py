"""Reader domain package.

Pipeline:

- :mod:`.body_loader` – fetch/backfill/clean body text
- :mod:`.translation` – translator orchestration (title + body)
- :mod:`.streaming`   – NDJSON frame rendering for the stream endpoint

The HTTP layer lives at ``app.api.contents_reader`` and is kept thin:
route definitions + legacy re-exports.
"""
