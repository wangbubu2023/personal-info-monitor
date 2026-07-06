"""Cross-domain protocols and constants still used by multiple domains.

Earlier refactor drafts introduced unused DTOs for a future fetch/ingest
contract path. The running application kept the real fetch chain in
``tasks.fetch_tasks -> domains.fetch.coordinator -> CollectorStage`` instead,
so those DTO-only modules were removed to avoid a second, uncalled "main"
path.
"""

from app.domains.contracts.atoms import AtomReader
from app.domains.contracts.content_quality import (
    FULLTEXT_STATUS_BLOCKED,
    FULLTEXT_STATUS_FULL,
    FULLTEXT_STATUS_PARTIAL,
    FULLTEXT_STATUS_SUMMARY_ONLY,
    FULLTEXT_STATUS_TITLE_ONLY,
)

__all__ = [
    "AtomReader",
    "FULLTEXT_STATUS_BLOCKED",
    "FULLTEXT_STATUS_FULL",
    "FULLTEXT_STATUS_PARTIAL",
    "FULLTEXT_STATUS_SUMMARY_ONLY",
    "FULLTEXT_STATUS_TITLE_ONLY",
]
