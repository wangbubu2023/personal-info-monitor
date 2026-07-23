"""Typed failures emitted by the ingest finalization pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IngestFailureCode(StrEnum):
    CONTENT_NOT_FOUND = "CONTENT_NOT_FOUND"


@dataclass(frozen=True)
class IngestFailure:
    code: IngestFailureCode
    message: str
    retryable: bool = False
    severity: str = "error"


class ContentNotFoundError(RuntimeError):
    def __init__(self, content_id: str):
        self.content_id = str(content_id)
        self.failure = IngestFailure(
            code=IngestFailureCode.CONTENT_NOT_FOUND,
            message=f"Content row does not exist: {self.content_id}",
        )
        super().__init__(self.failure.message)


__all__ = ["ContentNotFoundError", "IngestFailure", "IngestFailureCode"]
