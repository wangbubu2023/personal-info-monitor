"""Humanized timing & scrolling helpers for anti-bot friendly browser automation.

Paywall publishers (NYT, WSJ, Bloomberg, FT, Economist…) run signals-based bot
detectors that flag deterministic fetch patterns even when the browser profile
is fully logged in. Three fingerprints that trip those detectors:

1. **Identical wait durations** — e.g. every article fetch waits exactly 1500ms
   after the warm-up, exactly 900ms after the scroll. Real users vary.
2. **Burst concurrency** — 8 parallel article hits to the same host within a
   second. Real users click one article at a time.
3. **Mechanical scrolling** — a single ``scrollTo(scrollHeight)`` followed by a
   fixed wait. Real readers scroll in chunks and pause between them.

These helpers centralize the randomization so the calling code stays readable
and tests can seed ``random`` (or patch) the helpers for determinism.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import datetime
from typing import Any, Optional


def humanized_wait_ms(
    base_ms: int,
    *,
    jitter_pct: float = 0.3,
    floor_ms: int = 0,
) -> int:
    """Return a jittered wait duration in ms centered on ``base_ms``.

    Jitter is symmetric around ``base_ms`` with range ``±base_ms*jitter_pct``.
    ``floor_ms`` clamps the low end so the caller can keep a minimum settle
    window even when ``base_ms`` is small (e.g. avoid 0ms after a goto).
    """
    if base_ms <= 0:
        return max(floor_ms, 0)
    delta = int(base_ms * max(jitter_pct, 0.0))
    lo = max(floor_ms, base_ms - delta)
    hi = base_ms + delta
    if hi < lo:
        return lo
    return random.randint(lo, hi)


async def human_inter_request_pause(
    *,
    min_ms: int = 800,
    max_ms: int = 2500,
) -> None:
    """Sleep a uniformly-random duration between successive requests.

    Used between hydrations of consecutive articles on the same host so the
    server sees click-paced traffic instead of a burst of parallel fetches.
    """
    lo = max(0, min_ms)
    hi = max(lo, max_ms)
    if hi <= 0:
        return
    await asyncio.sleep(random.uniform(lo, hi) / 1000.0)


async def human_scroll_page(
    page: Any,
    *,
    steps: int = 3,
    min_step_ms: int = 450,
    max_step_ms: int = 1300,
    scroll_to_bottom_prob: float = 0.7,
) -> None:
    """Scroll the page in a small number of random-sized chunks with pauses.

    Mimics a reader skimming an article: scroll a bit, pause to "read", repeat.
    Many paywall detectors look for the "scrollTop jumps straight to
    scrollHeight" signature as a bot tell, so we deliberately walk the page.
    ``scroll_to_bottom_prob`` controls whether the final step lands at the
    exact bottom (triggers lazy-loaded content) or a bit short of it.
    """
    try:
        height = await page.evaluate(
            "() => (document.scrollingElement || document.body).scrollHeight"
        )
    except Exception:  # noqa: BLE001 — page.evaluate can raise varied Playwright errors
        return
    if not isinstance(height, (int, float)) or height <= 0:
        return

    steps = max(2, steps + random.randint(-1, 1))
    chunk = int(height) // steps
    if chunk <= 0:
        return

    for i in range(1, steps + 1):
        jitter = random.randint(-chunk // 4, chunk // 4) if chunk >= 4 else 0
        if i < steps:
            offset = chunk * i + jitter
        elif random.random() < scroll_to_bottom_prob:
            offset = int(height)
        else:
            offset = int(height) - random.randint(0, max(chunk // 2, 1))
        offset = max(0, min(offset, int(height)))
        try:
            await page.evaluate(
                "(y) => window.scrollTo({top: y, behavior: 'smooth'})",
                offset,
            )
        except Exception:  # noqa: BLE001 — scroll helper tolerates transient page errors
            return
        await page.wait_for_timeout(
            random.randint(min_step_ms, max(min_step_ms, max_step_ms))
        )


def jittered_interval_minutes(
    source_id: str,
    base_minutes: float,
    last_fetched_at: Optional[datetime],
    *,
    jitter_pct: float = 0.1,
) -> float:
    """Return a per-cycle jittered fetch interval in minutes.

    Deterministic within a single cycle (stable across SQL-due check and the
    API's ``next_fetch_at`` display) but re-rolled the moment
    ``last_fetched_at`` advances. Uses a keyed SHA-256 hash of
    ``(source_id, last_fetched_at)`` rather than ``random.uniform`` so two
    code paths querying the same source observe the *same* next-due time —
    otherwise a scheduler tick and a status page can disagree on whether a
    source is overdue.

    Without this, every source with ``fetch_interval=60`` fires at
    60-minute intervals forever; bot-detectors on the publisher side
    fingerprint that cadence even when each individual request looks clean.
    """
    if base_minutes <= 0:
        return base_minutes
    if last_fetched_at is None:
        # First fetch — jitter only helps after we have an anchor.
        return base_minutes

    key = f"{source_id}|{last_fetched_at.isoformat()}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    raw = int.from_bytes(digest[:8], "big")
    # Normalize to [-1, 1].
    normalized = (raw / (1 << 64)) * 2 - 1
    factor = 1.0 + normalized * max(jitter_pct, 0.0)
    # Guard against pathological jitter_pct > 1 pushing factor negative.
    return max(base_minutes * factor, base_minutes * 0.5)
