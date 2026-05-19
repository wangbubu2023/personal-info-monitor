"""Backwards-compatible facade for the email notification pipeline.

Phase 4 step 7 of the module-refactor blueprint split the legacy 407-line
module into a platform transport (``send_email``) and three
domain-owned templates:

* :mod:`app.platform.notifications.smtp` — ``send_email``
* :mod:`app.domains.enrich.notifications.daily_digest` —
  ``render_digest_email``, ``send_daily_digest_emails``
* :mod:`app.domains.enrich.notifications.doctor_digest` —
  ``send_doctor_digest_email``
* :mod:`app.domains.enrich.notifications.keyword_alert` —
  ``send_keyword_alert``

This shim re-exports every public symbol so any out-of-tree consumer
still importing ``app.tasks.email_tasks`` keeps resolving.

Note for test authors: ``patch("app.tasks.email_tasks.X", ...)`` patches
the **shim**'s local binding, not the canonical modules where the
actual call sites live. Patches that need to intercept internals
(``asyncio.to_thread``, ``send_email`` inside ``send_keyword_alert`` /
``send_daily_digest_emails``) must target the canonical submodule
directly. Phase 7 will retire this facade entirely.
"""

from app.domains.enrich.notifications.daily_digest import (  # noqa: F401
    render_digest_email,
    send_daily_digest_emails,
)
from app.domains.enrich.notifications.doctor_digest import (  # noqa: F401
    send_doctor_digest_email,
)
from app.domains.enrich.notifications.keyword_alert import (  # noqa: F401
    send_keyword_alert,
)
from app.platform.notifications.smtp import send_email  # noqa: F401
