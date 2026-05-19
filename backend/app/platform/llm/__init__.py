"""Platform-level LLM primitives.

Phase 4 step 3 of the module-refactor blueprint moved the
``Summarizer`` and ``Translator`` implementations out of
``app.processors.*`` into this platform package. Both classes wrap
``app.ai.provider`` (HTTP / aiosmtplib-style runtime) and read model
runtime config from system settings; they expose:

* :class:`app.platform.llm.summarizer.Summarizer` — summarisation +
  keyword-extraction over Ollama / OpenAI-compatible providers, with
  optional cloud-fallback when the primary model fails.
* :class:`app.platform.llm.translator.Translator` — best-effort
  translation between Chinese / English / Japanese / Korean with the
  same primary-then-fallback flow.

Legacy import paths ``app.processors.summarizer`` /
``app.processors.translator`` remain as re-export shims; Phase 7 will
retire them.
"""
