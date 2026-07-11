"""Event clustering and ranking for digest generation."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any, Dict, List, Mapping, Sequence, Set
from urllib.parse import urlparse

from app.domains.score.score_event import compute_event_score


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


_MULTILINGUAL_EVENT_ANCHORS = {
    "模型": "model",
    "大模型": "model",
    "发布": "launch",
    "推出": "launch",
    "上线": "launch",
    "版本": "version",
    "政策": "policy",
    "监管": "policy",
    "利率": "rate",
    "银行": "bank",
    "公司": "company",
    "芯片": "chip",
    "安全": "safety",
    "报告": "report",
    "model": "model",
    "launch": "launch",
    "release": "launch",
    "version": "version",
    "policy": "policy",
    "regulation": "policy",
    "rate": "rate",
    "bank": "bank",
    "company": "company",
    "chip": "chip",
    "safety": "safety",
    "report": "report",
}


def _semantic_anchor_tokens(normalized: str, words: list[str]) -> list[str]:
    anchors: list[str] = []
    for needle, anchor in _MULTILINGUAL_EVENT_ANCHORS.items():
        if needle in normalized or needle in words:
            anchors.append(f"sem:{anchor}")
    return anchors


def _tokenize(text: str) -> Set[str]:
    """Tokenize mixed Chinese/English text into a compact multilingual token set.

    Chinese: bigrams + trigrams to better capture 3-character terms.
    English: 2+ character words. A small deterministic semantic-anchor layer
    maps common Chinese/English event terms onto shared tokens so v0 can handle
    cross-language pairs without calling an external embedding service.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return set()

    words = re.findall(r"[a-z0-9]{2,}", normalized)
    zh_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    zh_bigrams = ["".join(zh_chars[i : i + 2]) for i in range(len(zh_chars) - 1)]
    zh_trigrams = ["".join(zh_chars[i : i + 3]) for i in range(len(zh_chars) - 2)]

    return set(words + zh_bigrams + zh_trigrams + _semantic_anchor_tokens(normalized, words))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _metadata(item: Mapping[str, Any], key: str = "metadata") -> Mapping[str, Any]:
    value = item.get(key)
    return value if isinstance(value, Mapping) else {}


def _clamp_float(value: Any, *, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def _normalized_article_score(item: Mapping[str, Any]) -> float | None:
    meta = _metadata(item)
    raw = item.get("article_score", item.get("final_score", meta.get("article_score", meta.get("final_score"))))
    if raw is None:
        return None
    return _clamp_float(raw, default=0.0, min_value=0.0, max_value=100.0)


def _duplicate_group_id(item: Mapping[str, Any]) -> str:
    meta = _metadata(item)
    return str(item.get("duplicate_group_id") or meta.get("duplicate_group_id") or "").strip()


def _explicit_event_key(item: Mapping[str, Any]) -> str:
    meta = _metadata(item)
    return str(item.get("event_key") or item.get("event_id") or meta.get("event_key") or meta.get("event_id") or "").strip()


def _source_domain_for_signature(item: Mapping[str, Any]) -> str:
    meta = _metadata(item)
    for raw in (item.get("source_url"), item.get("article_url"), item.get("url"), meta.get("source_url")):
        if not raw:
            continue
        parsed = urlparse(str(raw) if "://" in str(raw) else f"https://{raw}")
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        if host:
            return host
    return str(item.get("source_name") or meta.get("source_name") or "unknown").strip().lower() or "unknown"


def _event_signature(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tokens = sorted(set().union(*[set(item.get("_tokens", set())) for item in items])) if items else []
    entity_tokens = [token for token in tokens if len(token) >= 3][:12]
    source_domains = sorted({_source_domain_for_signature(item) for item in items})
    explicit_keys = sorted({_explicit_event_key(item) for item in items if _explicit_event_key(item)})
    duplicate_groups = sorted({_duplicate_group_id(item) for item in items if _duplicate_group_id(item)})
    return {
        "signature_version": "hybrid-v0",
        "entity_tokens": entity_tokens,
        "source_domains": source_domains,
        "explicit_event_keys": explicit_keys,
        "duplicate_group_ids": duplicate_groups,
    }


def _threshold_band(similarity: float | None, *, weak: float = 0.18, default: float = 0.28, strong: float = 0.42) -> str:
    if similarity is None:
        return "explicit_or_single"
    if similarity >= strong:
        return "strong"
    if similarity >= default:
        return "normal"
    if similarity >= weak:
        return "weak_review"
    return "below"


def _explain_cluster(items: Sequence[Mapping[str, Any]], best_similarity: float | None = None) -> list[str]:
    reasons: list[str] = []
    duplicate_groups = {_duplicate_group_id(item) for item in items if _duplicate_group_id(item)}
    explicit_keys = {_explicit_event_key(item) for item in items if _explicit_event_key(item)}
    if explicit_keys:
        reasons.append("explicit_event_key")
    if duplicate_groups:
        reasons.append("article_duplicate_signal")
    if len({_source_domain_for_signature(item) for item in items}) >= 2:
        reasons.append("independent_sources")
    if best_similarity is not None:
        reasons.append(f"token_similarity={best_similarity:.3f}")
    return reasons or ["single_report_candidate"]


class RankingService:
    """Cluster entries into events and rank by event_score (pim-score-v2)."""

    def __init__(
        self,
        similarity_threshold: float = 0.28,
        *,
        weak_similarity_threshold: float = 0.18,
        strong_similarity_threshold: float | None = None,
    ):
        self.similarity_threshold = similarity_threshold
        self.weak_similarity_threshold = weak_similarity_threshold
        self.strong_similarity_threshold = strong_similarity_threshold or max(0.42, similarity_threshold * 1.5)

    def cluster_and_rank(self, entries: Sequence[Dict], excluded_event_keys: Set[str] | None = None) -> List[Dict]:
        """Return ranked event clusters."""
        excluded = excluded_event_keys or set()
        prepared = []
        for item in entries:
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or "").strip()
            tokens = _tokenize(f"{title} {summary}")
            prepared.append({**item, "_tokens": tokens})
        prepared.sort(
            key=lambda item: (
                _normalized_article_score(item) if _normalized_article_score(item) is not None else -1.0,
                len(item.get("title") or ""),
            ),
            reverse=True,
        )

        clusters: List[Dict] = []
        explicit_event_to_cluster: dict[str, int] = {}
        for item in prepared:
            explicit_event = _explicit_event_key(item)
            forced_idx = explicit_event_to_cluster.get(explicit_event) if explicit_event else None
            if forced_idx is not None and forced_idx < len(clusters):
                cluster = clusters[forced_idx]
                cluster["items"].append(item)
                cluster["centroid_tokens"] = self._merge_tokens(cluster["items"])
                cluster["explain_reasons"] = _explain_cluster(cluster["items"])
                continue

            best_idx = -1
            best_sim = 0.0
            for idx, cluster in enumerate(clusters):
                sim = _jaccard(item["_tokens"], cluster["centroid_tokens"])
                if sim > best_sim:
                    best_sim = sim
                    best_idx = idx

            if best_idx >= 0 and best_sim >= self.similarity_threshold:
                cluster = clusters[best_idx]
                cluster["items"].append(item)
                cluster["centroid_tokens"] = self._merge_tokens(cluster["items"])
                cluster["best_similarity"] = max(float(cluster.get("best_similarity") or 0.0), best_sim)
                cluster["explain_reasons"] = _explain_cluster(cluster["items"], cluster["best_similarity"])
                if explicit_event:
                    explicit_event_to_cluster.setdefault(explicit_event, best_idx)
            else:
                new_idx = len(clusters)
                clusters.append(
                    {
                        "items": [item],
                        "centroid_tokens": set(item["_tokens"]),
                        "best_similarity": None,
                        "explain_reasons": _explain_cluster([item]),
                    }
                )
                if explicit_event:
                    explicit_event_to_cluster[explicit_event] = new_idx

        ranked = []
        for cluster in clusters:
            items = cluster["items"]
            event_key = self._event_key(items)
            if event_key in excluded:
                continue
            event_fields = compute_event_score(items)
            signature = _event_signature(items)
            best_similarity = cluster.get("best_similarity")
            threshold_band = _threshold_band(
                best_similarity,
                weak=self.weak_similarity_threshold,
                default=self.similarity_threshold,
                strong=self.strong_similarity_threshold,
            )
            ranked.append(
                {
                    "event_key": event_key,
                    "score": event_fields["event_score"],
                    "event_score": event_fields["event_score"],
                    "momentum": event_fields["momentum"],
                    "corroboration": event_fields["corroboration"],
                    "corroboration_tier": event_fields["corroboration_tier"],
                    "independent_source_count": event_fields["independent_source_count"],
                    "component_scores": event_fields,
                    "event_signature": signature,
                    "threshold_band": threshold_band,
                    "similarity_thresholds": {
                        "weak": self.weak_similarity_threshold,
                        "default": self.similarity_threshold,
                        "strong": self.strong_similarity_threshold,
                        "best_similarity": best_similarity,
                    },
                    "explain_reasons": cluster.get("explain_reasons") or _explain_cluster(items),
                    "items": items,
                    "topic": self._pick_topic(items),
                    "sources": self._collect_sources(items),
                }
            )

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    def _merge_tokens(self, items: Sequence[Dict]) -> Set[str]:
        counter: Counter = Counter()
        for item in items:
            counter.update(item.get("_tokens", set()))
        min_freq = max(1, math.ceil(len(items) * 0.3))
        return {token for token, count in counter.items() if count >= min_freq}

    def _entry_score(self, item: Dict) -> float:
        """Legacy helper: article score on 0-10 scale for pick_topic tie-breaks."""
        article = _normalized_article_score(item)
        if article is not None:
            return article / 10.0
        text_len = len((item.get("summary") or "")) + len((item.get("title") or ""))
        return min(5.0, text_len / 400.0)

    def _event_key(self, items: Sequence[Dict]) -> str:
        explicit_keys = sorted({_explicit_event_key(item) for item in items if _explicit_event_key(item)})
        if explicit_keys:
            return explicit_keys[0]
        centroid = sorted(self._merge_tokens(items))
        if centroid:
            base = " ".join(centroid[:20])
        else:
            base = _normalize_text(self._pick_topic(items))
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()
        return digest[:16]

    def _pick_topic(self, items: Sequence[Dict]) -> str:
        if not items:
            return "未命名事件"
        best = max(items, key=lambda i: (self._entry_score(i), len(i.get("title") or "")))
        return (best.get("title") or "未命名事件").strip()

    def _collect_sources(self, items: Sequence[Dict]) -> List[Dict]:
        seen = set()
        sources = []
        for item in items:
            key = (item.get("source_name"), item.get("source_url"))
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "source_name": item.get("source_name") or "Unknown",
                    "source_url": item.get("source_url") or "",
                }
            )
        return sources


__all__ = ["RankingService", "_jaccard", "_tokenize"]
