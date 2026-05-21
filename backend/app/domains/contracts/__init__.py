"""Cross-domain Data Transfer Objects and protocols.

This package is the **only** module that may be imported by every other
domain. It defines the contracts that flow between ``sources``, ``fetch``,
``ingest``, ``enrich`` and ``atoms``:

* :mod:`app.domains.contracts.sources` — ``SourceSnapshot``, ``FetchRequest``,
  ``SourceStatusView``
* :mod:`app.domains.contracts.fetch`   — ``RawItem``, ``FetchWarning``,
  ``FetchBatch``, ``FetchOutcome``
* :mod:`app.domains.contracts.ingest`  — ``IngestResult``,
  ``FinishContentResult``
* :mod:`app.domains.contracts.enrich`  — ``EnrichRequest``,
  ``ReprocessRequest``
* :mod:`app.domains.contracts.atoms`   — ``AtomRecord``, ``AtomReader``

Rules:

* Contracts are frozen ``@dataclass`` (or :class:`typing.Protocol`) — they
  never carry ORM objects or SQLAlchemy sessions.
* The ``fetch`` domain returns ``FetchBatch`` to ``ingest``; the ``ingest``
  domain returns ``IngestResult`` back to schedulers; ``enrich`` receives
  ``EnrichRequest``/``ReprocessRequest``.
* No contract module may import from ``app.domains.*`` to avoid cycles.
"""

from app.domains.contracts.atoms import AtomReader
from app.domains.contracts.enrich import EnrichRequest, ReprocessRequest
from app.domains.contracts.fetch import (
    FetchBatch,
    FetchOutcome,
    FetchWarning,
    RawItem,
)
from app.domains.contracts.ingest import FinishContentResult, IngestResult
from app.domains.contracts.sources import (
    FetchRequest,
    SourceSnapshot,
    SourceStatusView,
)

__all__ = [
    "AtomReader",
    "EnrichRequest",
    "FetchBatch",
    "FetchOutcome",
    "FetchRequest",
    "FetchWarning",
    "FinishContentResult",
    "IngestResult",
    "RawItem",
    "ReprocessRequest",
    "SourceSnapshot",
    "SourceStatusView",
]
