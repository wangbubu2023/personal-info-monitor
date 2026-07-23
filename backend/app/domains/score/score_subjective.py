"""Shadow-only, business-idempotent LLM subjective scoring."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from threading import Lock
import time
from typing import Any, Protocol
from weakref import WeakValueDictionary

from app.utils.datetime import utcnow_naive

FIXED_BASELINE_SUBJECTIVE_SCORE = 5.0
SUBJECTIVE_PROMPT_VERSION = "pim-subjective-v1"
SUBJECTIVE_SCHEMA_VERSION = 1
SUBJECTIVE_MAX_BODY_CHARS = 800
SUBJECTIVE_MAX_TOKENS = 150

_SCORE_RE = re.compile(r"\b([1-9]|10)\b")
_URL_TITLE_RE = re.compile(r"^\s*(?:https?://|www\.)\S+\s*$", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_cache_locks_guard = Lock()
_cache_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
_score_semaphores: dict[int, asyncio.Semaphore] = {}
_metrics_lock = Lock()
_metrics: Counter[str] = Counter()
_metric_totals = {"token_estimate": 0.0, "latency_ms": 0.0, "estimated_cost": 0.0}


@dataclass(frozen=True)
class SubjectiveScoreResult:
    score: float
    source: str
    rationale: str | None = None
    model: str | None = None
    provider: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    input_hash: str | None = None
    input_scope: str | None = None
    token_estimate: int = 0
    actual_usage: dict[str, Any] | None = None
    estimated_cost: float = 0.0
    generated_at: str | None = None
    cache_hit: bool = False
    failure_reason: str | None = None
    schema_version: int = SUBJECTIVE_SCHEMA_VERSION

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "score": round(max(0.0, min(10.0, float(self.score))), 1),
            "source": self.source,
            "rationale": self.rationale,
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "input_hash": self.input_hash,
            "input_scope": self.input_scope,
            "token_estimate": self.token_estimate,
            "actual_usage": self.actual_usage,
            "estimated_cost": round(max(0.0, float(self.estimated_cost)), 8),
            "generated_at": self.generated_at,
            "cache_hit": self.cache_hit,
            "failure_reason": self.failure_reason,
        }


class SubjectiveScorer(Protocol):
    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult: ...


class FixedBaselineSubjectiveScorer:
    """Neutral placeholder while policy or input eligibility blocks LLM work."""

    def __init__(self, score: float = FIXED_BASELINE_SUBJECTIVE_SCORE, *, reason: str | None = None) -> None:
        self._score = score
        self._reason = reason

    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult:
        del content, lane
        return SubjectiveScoreResult(
            score=self._score,
            source="fixed_baseline",
            failure_reason=self._reason,
        )


@dataclass(frozen=True)
class SubjectiveInput:
    prompt: str
    input_hash: str
    input_scope: str
    token_estimate: int


def _normalize_text(value: Any, limit: int) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()[:limit]


def build_subjective_input(content: Any) -> tuple[SubjectiveInput | None, str | None]:
    """Build the exact bounded input or return a stable ineligibility reason."""

    metadata = getattr(content, "metadata_", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    if metadata.get("fetch_acceptance") != "accepted":
        return None, "fetch_not_accepted"

    fulltext_status = str(metadata.get("fulltext_status") or "").strip().lower()
    if fulltext_status in {"title_only", "blocked"}:
        return None, fulltext_status

    title = _normalize_text(
        getattr(content, "title", None) or getattr(content, "translated_title", None),
        200,
    )
    if not title:
        return None, "missing_title"
    if _URL_TITLE_RE.match(title):
        return None, "url_title"

    summary = _normalize_text(
        getattr(content, "summary", None) or getattr(content, "translated_summary", None),
        800,
    )
    body = _normalize_text(getattr(content, "full_content", None), SUBJECTIVE_MAX_BODY_CHARS)
    if not summary and not body:
        return None, "missing_evidence"

    parts = [f"标题：{title}"]
    scope = "title_summary"
    if summary:
        parts.append(f"摘要：{summary}")
    if len(summary) < 120 and body:
        parts.append(f"正文补充：{body}")
        scope = "title_summary_body" if summary else "title_body"

    canonical = json.dumps(
        {"title": title, "summary": summary, "body": body if "body" in scope else ""},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    input_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    prompt = "\n".join(parts)
    token_estimate = max(1, len(prompt) // 4 + SUBJECTIVE_MAX_TOKENS)
    return SubjectiveInput(prompt, input_hash, scope, token_estimate), None


def subjective_cache_key(input_hash: str, model_version: str, prompt_version: str) -> str:
    raw = f"{input_hash}\0{model_version}\0{prompt_version}".encode()
    return hashlib.sha256(raw).hexdigest()


def _cache_lock(cache_key: str) -> Lock:
    with _cache_locks_guard:
        return _cache_locks.setdefault(cache_key, Lock())


def _score_semaphore() -> asyncio.Semaphore:
    loop_key = id(asyncio.get_running_loop())
    with _cache_locks_guard:
        return _score_semaphores.setdefault(loop_key, asyncio.Semaphore(2))


def _record_metric(name: str, value: float = 1.0) -> None:
    with _metrics_lock:
        if name in _metric_totals:
            _metric_totals[name] += max(0.0, value)
        else:
            _metrics[name] += int(value)


def subjective_metrics_snapshot() -> dict[str, Any]:
    with _metrics_lock:
        counters = dict(_metrics)
        totals = dict(_metric_totals)
    requests = counters.get("request", 0)
    return {
        **counters,
        **{key: round(value, 4) for key, value in totals.items()},
        "average_latency_ms": round(totals["latency_ms"] / requests, 2) if requests else 0.0,
        "max_concurrency": 2,
        "shadow_weight": 0.0,
    }


def _cache_lookup(cache_key: str) -> SubjectiveScoreResult | None:
    from app.models.ai_governance import AiSubjectiveScoreCache
    from app.platform.persistence.database import SessionLocal

    db = SessionLocal()
    try:
        row = (
            db.query(AiSubjectiveScoreCache)
            .filter(
                AiSubjectiveScoreCache.cache_key == cache_key,
                AiSubjectiveScoreCache.state == "ready",
            )
            .first()
        )
        if row is None:
            return None
        row.hit_count = int(row.hit_count or 0) + 1
        row.last_hit_at = utcnow_naive()
        db.commit()
        return SubjectiveScoreResult(
            score=float(row.score),
            source="llm",
            rationale=row.rationale,
            provider=row.provider,
            model=row.model,
            model_version=row.model_version,
            prompt_version=row.prompt_version,
            input_hash=row.input_hash,
            input_scope=row.input_scope,
            token_estimate=int(row.token_estimate or 0),
            actual_usage=row.actual_usage,
            estimated_cost=float(row.estimated_cost or 0.0),
            generated_at=row.created_at.isoformat() if row.created_at else None,
            cache_hit=True,
        )
    finally:
        db.close()


def _cache_store(
    *,
    cache_key: str,
    content_id: str | None,
    prepared: SubjectiveInput,
    result: SubjectiveScoreResult,
) -> None:
    from app.models.ai_governance import AiSubjectiveScoreCache
    from app.platform.persistence.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(AiSubjectiveScoreCache).filter(AiSubjectiveScoreCache.cache_key == cache_key).first()
        if row is None:
            row = AiSubjectiveScoreCache(cache_key=cache_key)
            db.add(row)
        row.content_id = content_id
        row.input_hash = prepared.input_hash
        row.input_scope = prepared.input_scope
        row.provider = result.provider or "unknown"
        row.model = result.model or "unknown"
        row.model_version = result.model_version or "unknown"
        row.prompt_version = result.prompt_version or SUBJECTIVE_PROMPT_VERSION
        row.score = result.score if result.source == "llm" else None
        row.rationale = result.rationale
        row.token_estimate = prepared.token_estimate
        row.actual_usage = result.actual_usage
        row.estimated_cost = result.estimated_cost
        row.state = "ready" if result.source == "llm" else "failed"
        row.failure_code = result.failure_reason
        row.created_at = utcnow_naive()
        db.commit()
    finally:
        db.close()


class LlmSubjectiveScorer:
    """Score eligible content once per input/model/prompt version."""

    _SYSTEM = (
        "你是新闻重要性评估助手。只根据提供的标题、摘要和可选正文补充，输出 1–10 整数分和不超过30字理由。"
        f" schema_version={SUBJECTIVE_SCHEMA_VERSION}。只输出两行：\n"
        "score: <1-10整数>\n"
        "rationale: <理由>"
    )

    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult:
        del lane
        prepared, blocked_reason = build_subjective_input(content)
        if prepared is None:
            _record_metric("fallback")
            return SubjectiveScoreResult(
                score=FIXED_BASELINE_SUBJECTIVE_SCORE,
                source="fixed_baseline",
                failure_reason=blocked_reason,
            )

        from app.ai.provider import get_runtime_from_system_settings

        runtime = await get_runtime_from_system_settings(
            setting_key="score_model",
            default_provider="ollama",
            default_model="",
            default_api_base="http://localhost:11434",
            default_temperature=0.1,
            default_max_tokens=SUBJECTIVE_MAX_TOKENS,
        )
        if runtime is None:
            _record_metric("fallback")
            return SubjectiveScoreResult(
                score=FIXED_BASELINE_SUBJECTIVE_SCORE,
                source="fixed_baseline",
                failure_reason="runtime_unavailable",
                input_hash=prepared.input_hash,
                input_scope=prepared.input_scope,
                prompt_version=SUBJECTIVE_PROMPT_VERSION,
            )

        provider = str(runtime.provider or "unknown")
        model = str(runtime.model or "unknown")
        model_version = f"{provider}:{model}"
        cache_key = subjective_cache_key(prepared.input_hash, model_version, SUBJECTIVE_PROMPT_VERSION)
        lock = _cache_lock(cache_key)
        await asyncio.to_thread(lock.acquire)
        try:
            cached = await asyncio.to_thread(_cache_lookup, cache_key)
            if cached is not None:
                _record_metric("cache_hit")
                return cached

            _record_metric("request")
            _record_metric("token_estimate", prepared.token_estimate)
            started = time.perf_counter()
            try:
                async with _score_semaphore():
                    raw = await self._call_llm(prepared.prompt, runtime)
                parsed = self._parse(raw)
                failure_reason = None
                if parsed.source != "llm":
                    from app.platform.llm.policy import get_recent_ai_runtime_failure

                    failure_reason = get_recent_ai_runtime_failure(runtime) or "invalid_response"
                result = SubjectiveScoreResult(
                    score=parsed.score,
                    source=parsed.source,
                    rationale=parsed.rationale,
                    provider=provider,
                    model=model,
                    model_version=model_version,
                    prompt_version=SUBJECTIVE_PROMPT_VERSION,
                    input_hash=prepared.input_hash,
                    input_scope=prepared.input_scope,
                    token_estimate=prepared.token_estimate,
                    estimated_cost=0.0,
                    generated_at=datetime.utcnow().isoformat(),
                    failure_reason=failure_reason,
                )
            except Exception as exc:  # noqa: BLE001 - shadow path must never break deterministic scoring
                result = SubjectiveScoreResult(
                    score=FIXED_BASELINE_SUBJECTIVE_SCORE,
                    source="fixed_baseline",
                    provider=provider,
                    model=model,
                    model_version=model_version,
                    prompt_version=SUBJECTIVE_PROMPT_VERSION,
                    input_hash=prepared.input_hash,
                    input_scope=prepared.input_scope,
                    token_estimate=prepared.token_estimate,
                    failure_reason=_failure_code(exc),
                )
            latency_ms = (time.perf_counter() - started) * 1000
            _record_metric("latency_ms", latency_ms)
            _record_metric("success" if result.source == "llm" else "failure")
            if result.source != "llm":
                _record_metric("fallback")
            await asyncio.to_thread(
                _cache_store,
                cache_key=cache_key,
                content_id=str(getattr(content, "id", "") or "") or None,
                prepared=prepared,
                result=result,
            )
            return result
        finally:
            lock.release()

    async def _call_llm(self, prompt: str, runtime: Any) -> str:
        from app.ai.provider import ModelProviderClient

        return await ModelProviderClient().generate_text(
            runtime,
            prompt=prompt,
            system_prompt=self._SYSTEM,
            temperature=0.1,
            max_tokens=SUBJECTIVE_MAX_TOKENS,
            timeout_seconds=30.0,
        )

    def _parse(self, raw: str) -> SubjectiveScoreResult:
        if not (raw or "").strip():
            return SubjectiveScoreResult(
                score=FIXED_BASELINE_SUBJECTIVE_SCORE,
                source="fixed_baseline",
            )
        score: float | None = None
        rationale: str | None = None
        for line in raw.splitlines():
            line = line.strip()
            if line.lower().startswith("score:"):
                match = _SCORE_RE.search(line)
                if match:
                    score = float(match.group(1))
            elif line.lower().startswith("rationale:"):
                rationale = line.split(":", 1)[-1].strip()[:120] or None
        if score is None:
            return SubjectiveScoreResult(
                score=FIXED_BASELINE_SUBJECTIVE_SCORE,
                source="fixed_baseline",
            )
        return SubjectiveScoreResult(score=score, source="llm", rationale=rationale)


def _failure_code(exc: BaseException) -> str:
    text = f"{exc.__class__.__name__}: {exc}".lower()
    if "429" in text or "rate" in text and "limit" in text:
        return "rate_limited"
    if "401" in text or "403" in text or "auth" in text or "credential" in text:
        return "credentials_invalid"
    if "circuit" in text and "open" in text:
        return "circuit_open"
    if "timeout" in text or "connect" in text or "network" in text:
        return "provider_unreachable"
    return "provider_failure"


async def subjective_scoring_effective() -> bool:
    from app.platform.llm.policy import resolve_subjective_scoring_state

    return (await resolve_subjective_scoring_state()).effective


async def get_subjective_scorer() -> SubjectiveScorer:
    if await subjective_scoring_effective():
        return LlmSubjectiveScorer()
    return FixedBaselineSubjectiveScorer(reason="policy_not_effective")


def resolve_subjective_score(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Synchronous rule-scoring path always remains a neutral baseline."""
    del content, lane
    return SubjectiveScoreResult(
        score=FIXED_BASELINE_SUBJECTIVE_SCORE,
        source="fixed_baseline",
    )


async def score_subjective_async(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Shadow-score eligible content without affecting deterministic outputs."""
    _, blocked_reason = build_subjective_input(content)
    if blocked_reason is not None:
        _record_metric("fallback")
        return SubjectiveScoreResult(
            score=FIXED_BASELINE_SUBJECTIVE_SCORE,
            source="fixed_baseline",
            failure_reason=blocked_reason,
        )
    scorer = await get_subjective_scorer()
    return await scorer.score(content, lane=lane)


__all__ = [
    "FIXED_BASELINE_SUBJECTIVE_SCORE",
    "LlmSubjectiveScorer",
    "SUBJECTIVE_MAX_BODY_CHARS",
    "SUBJECTIVE_MAX_TOKENS",
    "SUBJECTIVE_PROMPT_VERSION",
    "SubjectiveScoreResult",
    "build_subjective_input",
    "score_subjective_async",
    "subjective_cache_key",
    "subjective_metrics_snapshot",
]
