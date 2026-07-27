"""Best-effort Shadow DOM materialization for browser-backed extraction."""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings

_MATERIALIZE_SCRIPT = """
() => {
  let count = 0;
  const walk = (root) => {
    for (const host of root.querySelectorAll('*')) {
      if (!host.shadowRoot || host.querySelector(':scope > [data-pim-shadow-root]')) continue;
      const clone = document.createElement('div');
      clone.setAttribute('data-pim-shadow-root', 'open');
      clone.innerHTML = host.shadowRoot.innerHTML;
      host.appendChild(clone);
      count += 1;
      walk(clone);
    }
  };
  walk(document);
  return count;
}
"""


async def materialize_shadow_dom(page: Any, *, logger: Any) -> tuple[int, bool]:
    """Clone open Shadow DOM roots into the serialized DOM for extraction."""
    settings = get_settings()
    if not (settings.pim_web_clean_enabled or settings.pim_web_clean_shadow):
        return 0, False
    try:
        count = await asyncio.wait_for(page.evaluate(_MATERIALIZE_SCRIPT), timeout=3.0)
        return int(count or 0), False
    except asyncio.TimeoutError:
        logger.debug("Shadow DOM materialization timed out")
        return 0, True
    except Exception as exc:  # noqa: BLE001 — browser DOMs are best-effort
        logger.debug("Shadow DOM materialization skipped: %s", exc)
        return 0, False
