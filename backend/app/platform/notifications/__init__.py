"""Notifications transport — SMTP delivery for the platform layer.

Phase 4 step 7 split the legacy ``app/tasks/email_tasks.py`` into two
layers:

* :mod:`app.platform.notifications.smtp` — wire-level transport
  (``send_email`` using ``aiosmtplib`` with retry/backoff).
* :mod:`app.domains.enrich.notifications` — business templates and
  orchestration (daily digest, doctor digest, keyword alert).

The transport layer has zero domain knowledge — it accepts a
recipient / subject / HTML body and pushes them through SMTP. Domain
templates compose into HTML and call into this transport.
"""
