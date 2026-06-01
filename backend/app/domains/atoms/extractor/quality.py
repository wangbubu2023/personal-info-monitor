"""Post-extraction quality gate for atoms.

The LLM returns candidate atoms that still need rule-based filtering before they
enter the library: title duplicates, boilerplate, code/label fragments,
under-confident facts, and data atoms with broken field integrity. This module
also dedupes the same ``source_sentence`` across atom types by keeping only the
highest-priority type.
"""

from __future__ import annotations

from app.domains.atoms.extractor.sentence_split import sentence_quality_reason
from app.domains.atoms.types import AtomCreate
from app.domains.atoms.vocab import AtomType, PeriodType, Unit

# Same source sentence can only yield one atom type. A sentence that legally
# becomes a data atom usually carries more information than an opinion atom.
_TYPE_PRIORITY: dict[AtomType, int] = {
    AtomType.DATA: 3,
    AtomType.INFO: 2,
    AtomType.OPINION: 1,
}

# Confidence floors below which atoms are discarded (LLM self-rated, but the
# prompt is calibrated to use these bands).
_MIN_CONFIDENCE: dict[AtomType, float] = {
    AtomType.INFO: 0.7,
    AtomType.DATA: 0.7,
    AtomType.OPINION: 0.6,
}

# Generic metric names the model tends to fabricate when no real metric exists.
_SUSPICIOUS_METRICS: frozenset[str] = frozenset(
    {
        "occurrence_count",
        "occurrences",
        "count",
        "number",
        "数量",
        "次数",
        "出现次数",
    }
)

_NUMERIC_CHARS = set("0123456789%％")


def _has_numeric_evidence(text: str) -> bool:
    return any(ch in _NUMERIC_CHARS for ch in (text or ""))


def _reject_data_payload(payload) -> str | None:
    """Field-integrity checks specific to data atoms."""
    period = (getattr(payload, "period", "") or "").strip()
    if not period or period == "未知":
        return "data_missing_period"

    unit = getattr(payload, "unit", None)
    caliber = (getattr(payload, "caliber", None) or "").strip()
    if unit == Unit.CUSTOM and not caliber:
        return "data_custom_unit_without_caliber"

    period_type = getattr(payload, "period_type", None)
    if period_type == PeriodType.AS_OF and period == "未知":
        return "data_missing_period"

    metric = (getattr(payload, "metric", "") or "").strip().lower()
    if metric in _SUSPICIOUS_METRICS:
        return "data_suspicious_metric"

    return None


def reject_atom_reason(
    atom: AtomCreate,
    *,
    title: str,
    source_text: str,
) -> str | None:
    """Return a rejection reason for a low-quality atom, else ``None``.

    ``title`` and ``source_text`` provide article context; ``source_text`` is the
    cleaned body the atom was extracted from.
    """
    sentence = (atom.source_sentence or "").strip()

    if title and sentence == title.strip():
        return "title_duplicate"

    sentence_reason = sentence_quality_reason(sentence)
    if sentence_reason is not None:
        return sentence_reason

    floor = _MIN_CONFIDENCE.get(atom.atom_type, 0.7)
    if atom.fact_confidence < floor:
        return "low_confidence"

    if atom.atom_type == AtomType.DATA:
        if not _has_numeric_evidence(sentence):
            return "data_no_numeric_evidence"
        data_reason = _reject_data_payload(atom.payload)
        if data_reason is not None:
            return data_reason

    return None


def dedupe_by_source_sentence(atoms: list[AtomCreate]) -> list[AtomCreate]:
    """Keep one atom per ``source_sentence``, choosing the highest-priority type.

    Priority: 数据 > 信息 > 观点. Ties break on ``fact_confidence``, then input order.
    """
    best: dict[str, AtomCreate] = {}
    order: list[str] = []
    for atom in atoms:
        key = atom.source_sentence
        current = best.get(key)
        if current is None:
            best[key] = atom
            order.append(key)
            continue
        if _is_better(atom, current):
            best[key] = atom
    return [best[key] for key in order]


def _is_better(candidate: AtomCreate, incumbent: AtomCreate) -> bool:
    cand_priority = _TYPE_PRIORITY.get(candidate.atom_type, 0)
    inc_priority = _TYPE_PRIORITY.get(incumbent.atom_type, 0)
    if cand_priority != inc_priority:
        return cand_priority > inc_priority
    return candidate.fact_confidence > incumbent.fact_confidence


def filter_atoms(
    atoms: list[AtomCreate],
    *,
    title: str,
    source_text: str,
) -> tuple[list[AtomCreate], dict[str, int]]:
    """Apply the quality gate and per-sentence dedup, returning kept atoms + stats."""
    kept: list[AtomCreate] = []
    stats: dict[str, int] = {}
    for atom in atoms:
        reason = reject_atom_reason(atom, title=title, source_text=source_text)
        if reason is None:
            kept.append(atom)
            continue
        stats[reason] = stats.get(reason, 0) + 1

    deduped = dedupe_by_source_sentence(kept)
    dropped_dups = len(kept) - len(deduped)
    if dropped_dups > 0:
        stats["duplicate_sentence_type"] = dropped_dups
    return deduped, stats


def rank_atoms_for_cap(atoms: list[AtomCreate]) -> list[AtomCreate]:
    """Order atoms by retention priority for per-content capping."""
    return sorted(
        atoms,
        key=lambda a: (
            a.verified,
            a.fact_confidence,
            a.source_credibility,
            _TYPE_PRIORITY.get(a.atom_type, 0),
        ),
        reverse=True,
    )


__all__ = [
    "dedupe_by_source_sentence",
    "filter_atoms",
    "rank_atoms_for_cap",
    "reject_atom_reason",
]
