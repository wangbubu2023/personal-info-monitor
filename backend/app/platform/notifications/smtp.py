"""SMTP transport for outbound notifications.

Single public coroutine: :func:`send_email`. Reads SMTP host /
credentials from :mod:`app.config` settings, retries the send three
times with linear backoff (0s / 3s / 10s) on any exception, and
returns ``True`` on success or ``False`` if SMTP is not configured /
every retry failed.

Phase 4 step 7 of the refactor extracted this from the legacy
``app.tasks.email_tasks`` module; domain layers
(``app.domains.enrich.notifications.*``) call into this transport
exclusively for outbound delivery.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.platform.observability.logger import get_logger

logger = get_logger(__name__)


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    from_email: Optional[str] = None,
):
    """Send an email using SMTP."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    import aiosmtplib

    from app.platform.config.settings import get_settings
    settings = get_settings()

    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP not configured, skipping email")
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_email or settings.smtp_user
    message["To"] = to

    html_part = MIMEText(html_body, "html")
    message.attach(html_part)

    backoff_seconds = (0.0, 3.0, 10.0)
    last_err: Exception | None = None
    for delay in backoff_seconds:
        if delay:
            await asyncio.sleep(delay)
        try:
            await aiosmtplib.send(
                message,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=True,
            )
            logger.info(f"Email sent to {to}")
            return True
        except Exception as e:
            last_err = e
            logger.warning("SMTP send failed (will retry if attempts remain): %s", e)
    logger.error("Failed to send email after retries: %s", last_err)
    return False
