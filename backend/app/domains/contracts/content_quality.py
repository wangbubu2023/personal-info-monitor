"""Shared fulltext-status constants for fetch acceptance and ingest quality."""

from __future__ import annotations

FULLTEXT_STATUS_FULL = "full"
FULLTEXT_STATUS_PARTIAL = "partial"
FULLTEXT_STATUS_SUMMARY_ONLY = "summary_only"
FULLTEXT_STATUS_TITLE_ONLY = "title_only"
FULLTEXT_STATUS_BLOCKED = "blocked"

__all__ = [
    "FULLTEXT_STATUS_FULL",
    "FULLTEXT_STATUS_PARTIAL",
    "FULLTEXT_STATUS_SUMMARY_ONLY",
    "FULLTEXT_STATUS_TITLE_ONLY",
    "FULLTEXT_STATUS_BLOCKED",
]
