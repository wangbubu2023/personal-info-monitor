"""Logging configuration."""

from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_logging_configured = False


def set_request_id(request_id: str | None) -> None:
    """Bind the current request id into logging context."""
    _request_id.set(request_id)


def clear_request_id() -> None:
    """Clear request-scoped logging context."""
    _request_id.set(None)


def get_request_id() -> str | None:
    """Return the active request id, if any."""
    return _request_id.get()


class _RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class _JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for production-friendly logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _configure_logging() -> None:
    global _logging_configured
    if _logging_configured:
        return

    settings = get_settings()
    level = logging.DEBUG if settings.debug else logging.INFO
    log_format = os.getenv("LOG_FORMAT", "json").strip().lower()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.addFilter(_RequestContextFilter())
    if log_format == "text":
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    else:
        handler.setFormatter(_JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    log_dir = os.environ.get("PIM_LOG_DIR", ".pim-local-logs")
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "backend.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB per file
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.addFilter(_RequestContextFilter())
        file_handler.setFormatter(_JsonFormatter())
        root_logger.addHandler(file_handler)

    _logging_configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a configured logger instance."""
    _configure_logging()
    return logging.getLogger(name or "personal-info-monitor")
