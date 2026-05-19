"""Hourly digest domain package.

Pipeline:

- :mod:`.text_utils`  – pure text / category / limit helpers
- :mod:`.selection`   – LLM selection + local-ranking fallback
- :mod:`.synthesis`   – LLM synthesis + rule-based fallback rendering
- :mod:`.repository`  – DB reads / upserts + window computation

The orchestrator lives at ``app.tasks.hourly_digest_tasks`` and stays
thin: load context → pick → synthesize → store.
"""
