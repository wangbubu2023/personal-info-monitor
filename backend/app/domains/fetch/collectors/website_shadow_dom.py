"""Best-effort, bounded Shadow DOM materialization for browser-backed extraction."""

from __future__ import annotations

import asyncio
from typing import Any

from patchright.async_api import Error as PatchrightError
from playwright.async_api import Error as PlaywrightError

from app.config import get_settings

_MAX_ROOTS = 128
_MAX_NODES = 20_000
_MAX_DEPTH = 12
_MAX_CHARS = 1_000_000

_MATERIALIZE_SCRIPT = r"""
(limits) => {
  const deadline = performance.now() + limits.deadlineMs;
  let roots = 0;
  let nodes = 0;
  let chars = 0;
  let timedOut = false;
  const blockedTags = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'TEMPLATE']);

  const allowed = (depth) => {
    if (performance.now() > deadline) timedOut = true;
    return !timedOut && depth <= limits.maxDepth && nodes < limits.maxNodes &&
      chars < limits.maxChars && roots < limits.maxRoots;
  };

  const cloneVisible = (node, depth) => {
    if (!allowed(depth)) return null;
    nodes += 1;
    if (node.nodeType === Node.TEXT_NODE) {
      const value = (node.nodeValue || '').slice(0, Math.max(0, limits.maxChars - chars));
      chars += value.length;
      return document.createTextNode(value);
    }
    if (node.nodeType !== Node.ELEMENT_NODE || blockedTags.has(node.tagName)) return null;
    if (node.hidden || ['true', '1'].includes((node.getAttribute('aria-hidden') || '').toLowerCase())) {
      return null;
    }
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') return null;

    const copy = node.cloneNode(false);
    const assigned = node.tagName === 'SLOT' ? node.assignedNodes({flatten: true}) : [];
    // Assigned nodes remain in the host's light DOM and will already be
    // serialized there. Cloning them again inside the materialized wrapper
    // duplicates visible article text. Only clone slot fallback children.
    const children = node.tagName === 'SLOT' && assigned.length
      ? []
      : Array.from(node.childNodes);
    for (const child of children) {
      const childCopy = cloneVisible(child, depth + 1);
      if (childCopy) copy.appendChild(childCopy);
      if (!allowed(depth)) break;
    }

    if (node.shadowRoot && allowed(depth + 1)) {
      const shadowCopy = document.createElement('div');
      shadowCopy.setAttribute('data-pim-shadow-root', 'open');
      roots += 1;
      for (const child of Array.from(node.shadowRoot.childNodes)) {
        const childCopy = cloneVisible(child, depth + 1);
        if (childCopy) shadowCopy.appendChild(childCopy);
        if (!allowed(depth)) break;
      }
      copy.appendChild(shadowCopy);
    }
    return copy;
  };

  for (const host of Array.from(document.querySelectorAll('*'))) {
    if (!allowed(0)) break;
    if (!host.shadowRoot || host.querySelector(':scope > [data-pim-shadow-root]')) continue;
    const wrapper = document.createElement('div');
    wrapper.setAttribute('data-pim-shadow-root', 'open');
    roots += 1;
    for (const child of Array.from(host.shadowRoot.childNodes)) {
      const childCopy = cloneVisible(child, 1);
      if (childCopy) wrapper.appendChild(childCopy);
      if (!allowed(0)) break;
    }
    host.appendChild(wrapper);
  }

  document.documentElement.setAttribute('data-pim-shadow-materialized-count', String(roots));
  document.documentElement.setAttribute('data-pim-shadow-timeout', timedOut ? 'true' : 'false');
  return {count: roots, timedOut, nodes, chars};
}
"""

_STAMP_TIMEOUT_SCRIPT = """
() => {
  document.documentElement.setAttribute('data-pim-shadow-timeout', 'true');
  if (!document.documentElement.hasAttribute('data-pim-shadow-materialized-count')) {
    document.documentElement.setAttribute('data-pim-shadow-materialized-count', '0');
  }
}
"""


async def _stamp_timeout(page: Any) -> None:
    try:
        await asyncio.wait_for(page.evaluate(_STAMP_TIMEOUT_SCRIPT), timeout=0.5)
    except (
        asyncio.TimeoutError,
        PatchrightError,
        PlaywrightError,
        AttributeError,
        TypeError,
        ValueError,
    ):
        return


async def materialize_shadow_dom(page: Any, *, logger: Any) -> tuple[int, bool]:
    """Clone open roots/slots into the serialized DOM without blocking fetch."""
    settings = get_settings()
    if not (settings.pim_web_clean_enabled or settings.pim_web_clean_shadow):
        return 0, False
    limits = {
        "maxRoots": _MAX_ROOTS,
        "maxNodes": _MAX_NODES,
        "maxDepth": _MAX_DEPTH,
        "maxChars": _MAX_CHARS,
        "deadlineMs": 2_800,
    }
    try:
        result = await asyncio.wait_for(page.evaluate(_MATERIALIZE_SCRIPT, limits), timeout=3.0)
        if isinstance(result, dict):
            return max(0, min(_MAX_ROOTS, int(result.get("count") or 0))), bool(
                result.get("timedOut")
            )
        return max(0, min(_MAX_ROOTS, int(result or 0))), False
    except asyncio.TimeoutError:
        logger.debug("Shadow DOM materialization timed out")
        await _stamp_timeout(page)
        return 0, True
    except (
        PatchrightError,
        PlaywrightError,
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        logger.debug("Shadow DOM materialization skipped: %s", exc)
        return 0, False
