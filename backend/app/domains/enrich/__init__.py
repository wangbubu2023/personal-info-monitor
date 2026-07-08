"""LLM summarisation/translation, reader, digest, notifications.

Phase 4 of the refactor moves all LLM-bound and user-facing post-processing
into this package:

* ``domains/enrich/content/`` — summariser, translator, manual reprocess
* ``domains/enrich/reader/`` — moved from ``app/services/reader/``
  (Reader body loader, NDJSON streaming, translation orchestration)
* ``domains/enrich/digest/`` — daily digest service
* ``domains/enrich/hourly/`` — hourly briefing (the ``hourly_digest_tasks``
  name is kept on the HTTP boundary for backwards compatibility)
* ``domains/enrich/ranking.py`` — event clustering / scoring
* ``domains/enrich/notifications.py`` — keyword/doctor alert content
  (SMTP transport lives in ``platform.notifications``)

The enrich domain consumes atoms exclusively through
:class:`app.domains.contracts.atoms.AtomReader` — it never imports the
atoms implementation directly.

Phase progress:

* ``domains/enrich/reader/shared.py`` — moved from
  ``app.api.content_shared`` in Phase 4 step 1 (paragraph split, X-body
  clean, title heuristics, translation-validity gates, X article URL
  extraction, reader-body hash, clean reader HTML builder). The reader
  service modules (``services/reader/{body_loader, streaming,
  translation}``) now import from this canonical location instead of
  reverse-depending on ``app.api``; the legacy
  ``app.api.content_shared`` path keeps the same symbols as re-exports
  through Phase 7.
* ``domains/enrich/content/reprocess.py`` — extracted from
  ``ContentProcessor.reprocess_content`` in Phase 4 step 4 (manual
  UI-triggered summary regeneration / re-translation of an existing
  Content row). The legacy method on ``ContentProcessor`` is now a
  thin wrapper that delegates here; ``tasks/process_tasks.process_content``
  keeps calling ``ContentProcessor().reprocess_content(...)`` unchanged.
* ``domains/enrich/reader/{body_loader, translation, streaming}.py`` —
  moved from ``app.services.reader.*`` in Phase 4 step 5 (Reader 整包
  平移). ``app.api.contents_reader`` switched to import these directly
  from the canonical location; the post-Phase-7 audit confirmed every
  remaining caller had moved over, so the ``app.services.reader.*``
  shim package was deleted. Address the new module path directly.
* ``domains/enrich/hourly/{tasks, repository, selection, synthesis,
  text_utils}.py`` — moved from ``app.services.hourly_digest.*`` +
  ``app.tasks.hourly_digest_tasks`` in Phase 4 step 6 (hourly digest
  整包平移). The HTTP-facing ``hourly`` naming on
  ``app/api/digest.py`` is preserved per the "must keep" list.
  ``tests/test_hourly_digest_limits.py`` was migrated to import
  ``synthesis``/``tasks``/``text_utils`` from the canonical module so
  that ``monkeypatch`` against wrapper-internal ``Translator`` /
  ``get_system_settings_sync`` hits the actual call sites. The
  ``app.services.hourly_digest.*`` and ``app.tasks.hourly_digest_tasks``
  re-export shims were retired by the post-Phase-7 audit (zero
  remaining callers); the import-boundary checker now bans both.
* ``domains/enrich/notifications/{daily_digest, doctor_digest,
  keyword_alert}.py`` — extracted from the legacy 407-line
  ``app.tasks.email_tasks`` module in Phase 4 step 7. SMTP transport
  moved to :mod:`app.platform.notifications.smtp`. ``app.scheduler``,
  ``app.tasks.__init__`` and ``app.domains.ingest.finish`` switched to
  import each entry point from its canonical location. The
  ``app.tasks.email_tasks`` re-export facade was retired by the
  post-Phase-7 audit; the import-boundary checker bans it. Test patches
  that previously targeted wrapper-internal ``asyncio.to_thread`` /
  ``send_email`` / ``send_keyword_alert`` references already live on
  the canonical submodule paths in ``tests/test_email_tasks.py`` and
  ``tests/test_process_tasks_extended.py``.
* :mod:`app.platform.llm.summarizer` / :mod:`app.platform.llm.translator`
  — moved from ``app.processors.summarizer`` / ``app.processors.translator``
  in Phase 4 step 3. The enrich domain reaches these via the platform
  layer; legacy ``app.processors.*`` paths remain as ``from new import *``
  re-export shims. ``app.platform.auth.api_credentials.decrypt_api_credentials``
  was also extracted from ``app.api.configs_common_auth`` in the same
  step, and model-settings enrichment now lives in
  ``app.platform.auth.api_config_credentials``. Test patches against
  wrapper-internal symbols
  (``get_settings`` / ``ModelProviderClient`` / ``get_translation_*``)
  were migrated to ``app.platform.llm.{summarizer,translator}.*`` in
  ``tests/test_processors.py``, and ``translator_module`` references
  in ``tests/test_stage_{a,v3}_fixes.py`` were rebound to the
  canonical module.
* Phase 4 step 8 introduced the ``ENRICH_*`` family of feature toggles
  in :mod:`app.config` (``ENRICH_AUTO_ON_INGEST`` /
  ``ENRICH_SUMMARY_ENABLED`` / ``ENRICH_TRANSLATE_ENABLED``).
  ``Summarizer.summarize_text`` now AND-gates on
  ``enrich_summary_enabled``; ``Translator._translate_with_openai`` and
  ``Translator.translate_text`` AND-gate on
  ``enrich_translate_enabled``; ``ai_processing_enabled`` is preserved
  as a master kill switch (and emits a ``DeprecationWarning`` once per
  process when set explicitly). The startup banner in :mod:`app.main`
  prints the new flags; ``backend/.env.example`` documents them; the
  frontend's :mod:`HOURLY_DIGEST_DEFAULT_PROMPT` in
  ``frontend/src/config/taskPromptDefaults.ts`` was resynced to match
  the backend's "本次简报窗口内" wording in
  :mod:`app.platform.config.system_settings` (relocated from
  ``app.services.system_settings`` in Phase 5 step 2; the legacy
  shim was retired by the post-Phase-7 audit). The pytest autouse fixture in
  ``conftest.py`` was extended to pin all four env vars so tests do
  not inherit a developer's per-feature overrides and do not spam
  ``DeprecationWarning`` during ``get_settings.cache_clear()`` loops.
"""
