"""Canonical text rendering for atoms.

``canonical_text`` is a compact, type-tagged single-line representation used for
FTS retrieval, embedding, reconcile prompt inputs, and concise frontend display.
It is derived from the structured payload, not the raw sentence.
"""

from __future__ import annotations

from typing import Any

from app.domains.atoms.types import AtomCreate, AtomRecord
from app.domains.atoms.vocab import AtomType

_MAX_LEN = 240


def _who_names(payload: dict[str, Any]) -> str:
    who = payload.get("who") or []
    names = [str(w.get("name")) for w in who if isinstance(w, dict) and w.get("name")]
    return "、".join(names[:3])


def _info_text(payload: dict[str, Any]) -> str:
    who = _who_names(payload)
    when = (payload.get("when") or "").strip()
    what = (payload.get("what") or "").strip()
    result = (payload.get("result") or "").strip()
    parts = [p for p in (who, when, what) if p]
    text = " ".join(parts)
    if result:
        text = f"{text}，结果：{result}" if text else result
    return text or what


def _opinion_text(payload: dict[str, Any]) -> str:
    who = _who_names(payload)
    say = (payload.get("say_what") or "").strip()
    sentiment = (payload.get("sentiment") or "").strip()
    intensity = (payload.get("intensity") or "").strip()
    head = f"{who}认为：{say}" if who else say
    tail = "/".join(p for p in (sentiment, intensity) if p)
    return f"{head}（{tail}）" if tail else head


def _data_text(payload: dict[str, Any]) -> str:
    org = (payload.get("source_org") or "").strip()
    metric = (payload.get("metric") or "").strip()
    value = payload.get("value")
    unit = (payload.get("unit") or "").strip()
    period = (payload.get("period") or "").strip()
    core = f"{metric} {value}{unit}".strip()
    bits = [b for b in (org, core) if b]
    text = "：".join(bits) if bits else core
    if period:
        text = f"{text}（{period}）"
    return text


def _render(atom_type: AtomType, payload: dict[str, Any]) -> str:
    if atom_type == AtomType.INFO:
        body = _info_text(payload)
        tag = "信息"
    elif atom_type == AtomType.OPINION:
        body = _opinion_text(payload)
        tag = "观点"
    else:
        body = _data_text(payload)
        tag = "数据"
    text = f"[{tag}] {body}".strip()
    if len(text) > _MAX_LEN:
        text = text[: _MAX_LEN - 1].rstrip() + "…"
    return text


def build_canonical_text(atom: AtomCreate | AtomRecord) -> str:
    """Return canonical text for an atom create payload or record."""
    if isinstance(atom, AtomCreate):
        payload = atom.payload.model_dump(mode="json")
        atom_type = atom.atom_type
    else:
        payload = dict(atom.payload or {})
        atom_type = atom.atom_type
    return _render(atom_type, payload)


__all__ = ["build_canonical_text"]
