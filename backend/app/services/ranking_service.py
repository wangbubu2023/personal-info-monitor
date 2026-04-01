"""Event clustering and ranking for digest generation."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Dict, List, Sequence, Set


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokenize(text: str) -> Set[str]:
    """Tokenize mixed Chinese/English text into a compact token set."""
    normalized = _normalize_text(text)
    if not normalized:
        return set()

    # English-like words
    words = re.findall(r"[a-z0-9]{2,}", normalized)

    # Chinese bigrams help similarity without external NLP deps
    zh_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    zh_bigrams = ["".join(zh_chars[i : i + 2]) for i in range(len(zh_chars) - 1)]

    return set(words + zh_bigrams)


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


class RankingService:
    """Cluster entries into events and rank by importance."""

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

        clusters: List[Dict] = []
        for item in prepared:
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
            else:
                clusters.append(
                    {
                        "items": [item],
                        "centroid_tokens": set(item["_tokens"]),
                    }
                )

        ranked = []
        for cluster in clusters:
            event_key = self._event_key(cluster["items"])
            if event_key in excluded:
                continue
            score = self._score_cluster(cluster["items"])
            ranked.append(
                {
                    "event_key": event_key,
                    "score": score,
                    "items": cluster["items"],
                    "topic": self._pick_topic(cluster["items"]),
                    "sources": self._collect_sources(cluster["items"]),
                }
            )

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    def _merge_tokens(self, items: Sequence[Dict]) -> Set[str]:
        counter: Counter = Counter()
        for item in items:
            counter.update(item.get("_tokens", set()))
        # Keep medium-frequency tokens as cluster centroid
        min_freq = max(1, math.ceil(len(items) * 0.3))
        return {token for token, count in counter.items() if count >= min_freq}

    def _entry_score(self, item: Dict) -> float:
        # Minimal heuristic:
        # 1) Prefer longer/more complete items
        # 2) Keep a light source-priority boost
        source_priority = float(item.get("source_priority") or 0)
        text_len = len((item.get("summary") or "")) + len((item.get("title") or ""))
        content_signal = min(5.0, text_len / 400.0)
        priority_signal = min(1.0, source_priority / 20.0)

        return content_signal + priority_signal

    def _score_cluster(self, items: Sequence[Dict]) -> float:
        # Minimal strategy: multi-source consensus first, then long-form signal.
        per_entry = [self._entry_score(item) for item in items]
        top = max(per_entry) if per_entry else 0.0
        source_count = len({(i.get("source_name") or "").strip() for i in items if i.get("source_name")})
        consensus_bonus = source_count * 10.0
        size_bonus = min(3.0, len(items) / 2.0)
        return consensus_bonus + top + size_bonus

    def _event_key(self, items: Sequence[Dict]) -> str:
        centroid = sorted(self._merge_tokens(items))
        if centroid:
            base = " ".join(centroid[:20])
        else:
            base = _normalize_text(self._pick_topic(items))
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()
        return digest[:16]

    def _pick_topic(self, items: Sequence[Dict]) -> str:
        # Prefer the longest/most-informative title from top-scored entries.
        if not items:
            return "未命名事件"
        best = max(items, key=lambda i: (len(i.get("title") or ""), self._entry_score(i)))
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
