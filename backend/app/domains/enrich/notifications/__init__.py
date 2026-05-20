"""Enrich-domain notification templates and orchestration.

Phase 4 step 7 split the legacy ``app/tasks/email_tasks.py`` into a
transport layer (``app.platform.notifications.smtp``) and these
domain-owned templates:

* :mod:`.daily_digest`   – HTML rendering + scheduled delivery of the
  daily digest to every configured :class:`EmailSchedule`.
* :mod:`.doctor_digest`  – the ``DoctorService`` audit nag email
  triggered when ``overall_status`` is degraded/error.
* :mod:`.keyword_alert`  – per-content keyword match notification.

All three call into :func:`app.platform.notifications.smtp.send_email`
for outbound delivery. The legacy ``app.tasks.email_tasks`` re-export
shim was retired by the post-Phase-7 audit; the import-boundary checker
bans it. Importers must address the canonical submodule path here
(or :mod:`app.platform.notifications.smtp` for raw transport).
"""
