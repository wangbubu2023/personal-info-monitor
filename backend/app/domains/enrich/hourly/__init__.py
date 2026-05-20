"""Hourly digest domain package.

Canonical home of the digest generator (Phase 4 step 6 moved this from
``app/services/hourly_digest/`` + ``app/tasks/hourly_digest_tasks.py``).
The HTTP-facing ``hourly`` naming on ``app/api/digest.py`` is preserved
per the blueprint's "must keep" list.

Pipeline:

- :mod:`.text_utils`  – pure text / category / limit helpers
- :mod:`.selection`   – LLM selection + local-ranking fallback
- :mod:`.synthesis`   – LLM synthesis + rule-based fallback rendering
- :mod:`.repository`  – DB reads / upserts + window computation
- :mod:`.tasks`       – thin orchestrator: load context → pick →
  synthesize → store (with progressive AI-failure degradation)

This is the only path for the hourly digest pipeline — the legacy
``app.services.hourly_digest`` and ``app.tasks.hourly_digest_tasks``
re-export shims were retired by the post-Phase-7 audit (zero remaining
callers) and the import-boundary checker now bans them.
"""
