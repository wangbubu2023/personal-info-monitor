"""Event clustering and ranking for digest generation."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any, Dict, List, Mapping, Sequence, Set

from app.domains.score.score_event import compute_event_score


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokenize(text: str) -> Set[str]:
    """Tokenize mixed Chinese/English text into a compact token set.

    Chinese: bigrams + trigrams to better capture 3-character terms.
    English: 2+ character words (lowercased after _normalize_text).
    """
    normalized = _normalize_text(text)
    if not normalized:
        return set()

    words = re.findall(r"[a-z0-9]{2,}", normalized)
    zh_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    zh_bigrams = ["".join(zh_chars[i : i + 2]) for i in range(len(zh_chars) - 1)]
    zh_trigrams = ["".join(zh_chars[i : i + 3]) for i in range(len(zh_chars) - 2)]

    return set(words + zh_bigrams + zh_trigrams)


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


class RankingService:
    """Cluster entries into events and rank by event_score (pim-score-v2)."""

    def __init__(self, similarity_threshold: float = 0.28):
        self.similarity_threshold = similarity_threshold

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
        duplicate_group_to_cluster: dict[str, int] = {}
        for item in prepared:
            duplicate_group = _duplicate_group_id(item)
            forced_idx = duplicate_group_to_cluster.get(duplicate_group) if duplicate_group else None
            if forced_idx is not None and forced_idx < len(clusters):
                cluster = clusters[forced_idx]
                cluster["items"].append(item)
                cluster["centroid_tokens"] = self._merge_tokens(cluster["items"])
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
                if duplicate_group:
                    duplicate_group_to_cluster.setdefault(duplicate_group, best_idx)
            else:
                new_idx = len(clusters)
                clusters.append(
                    {
                        "items": [item],
                        "centroid_tokens": set(item["_tokens"]),
                    }
                )
                if duplicate_group:
                    duplicate_group_to_cluster[duplicate_group] = new_idx

        ranked = []
        for cluster in clusters:
            items = cluster["items"]
            event_key = self._event_key(items)
            if event_key in excluded:
                continue
            event_fields = compute_event_score(items)
            ranked.append(
                {
                    "event_key": event_key,
                    "score": event_fields["event_score"],
                    "event_score": event_fields["event_score"],
                    "momentum": event_fields["momentum"],
                    "corroboration": event_fields["corroboration"],
                    "corroboration_tier": event_fields["corroboration_tier"],
                    "independent_source_count": event_fields["independent_source_count"],
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
