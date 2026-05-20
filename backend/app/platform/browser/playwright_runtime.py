"""Playwright runtime shim.

We default to `patchright`_ when it's installed: it's a drop-in fork of
Playwright that patches the well-known CDP / Blink fingerprints which
Datadome, Cloudflare Turnstile, PerimeterX and friends key on. Paywalled
news sites (NYT, WSJ, Bloomberg) reliably serve a 403 + captcha to vanilla
Playwright even with a valid login cookie; patchright sails through.

Callers should always import from this module instead of ``playwright.async_api``
so we have one switch for the whole codebase.

Environment overrides:
- ``PIM_BROWSER_BACKEND=patchright|playwright``
  Force a specific backend. Defaults to ``patchright`` when importable,
  else falls back to vanilla playwright.
- ``PIM_PLAYWRIGHT_CHANNEL=chrome|chromium|msedge|<empty>``
  Chromium channel used by most launch sites. Empty (``""``) means "let
  Playwright pick its bundled Chromium". When the active backend is
  patchright, ``chrome`` is recommended (real Google Chrome binary).

.. _patchright: https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python
"""

from __future__ import annotations

import os
from typing import Any, Tuple

_cached_backend: Tuple[str, Any] | None = None


_cached_timeout_error: Tuple[type, ...] | None = None


def _load_backend() -> Tuple[str, Any]:
    """Return ``(backend_name, async_playwright_factory)`` for the current env."""
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend

    requested = (os.environ.get("PIM_BROWSER_BACKEND") or "").strip().lower()

    # Try patchright first unless the user explicitly asked for stock playwright.
    if requested != "playwright":
        try:
            from patchright.async_api import async_playwright as _patch_async  # type: ignore

            _cached_backend = ("patchright", _patch_async)
            return _cached_backend
        except ImportError:
            if requested == "patchright":
                raise RuntimeError(
                    "PIM_BROWSER_BACKEND=patchright but `patchright` is not installed. "
                    "Run `uv add patchright` inside backend/."
                ) from None

    from playwright.async_api import async_playwright as _pw_async  # type: ignore

    _cached_backend = ("playwright", _pw_async)
    return _cached_backend


def async_playwright() -> Any:
    """Return the active backend's ``async_playwright()`` context manager."""
    return _load_backend()[1]()


def timeout_error_types() -> Tuple[type, ...]:
    """Return TimeoutError classes for both backends, for cross-compatible ``except`` clauses.

    patchright and playwright ship *different* ``TimeoutError`` classes. Any
    code that catches timeouts must catch both so the collectors keep working
    when we later toggle backends at runtime.
    """
    global _cached_timeout_error
    if _cached_timeout_error is not None:
        return _cached_timeout_error
    errs: list[type] = []
    for mod in ("patchright.async_api", "playwright.async_api"):
        try:
            m = __import__(mod, fromlist=["TimeoutError"])
            errs.append(m.TimeoutError)
        except ImportError:
            continue
    if not errs:  # pragma: no cover - neither installed
        errs.append(Exception)
    _cached_timeout_error = tuple(errs)
    return _cached_timeout_error


def backend_name() -> str:
    """Return 'patchright' or 'playwright' depending on what's loaded."""
    return _load_backend()[0]


def default_channel(explicit: str | None = None) -> str | None:
    """Resolve the Chromium channel to launch with.

    Priority:
    1. Explicit caller arg (if truthy).
    2. ``PIM_PLAYWRIGHT_CHANNEL`` env var.
    3. ``"chrome"`` when backend is patchright (real Google Chrome — best for
       anti-bot evasion), otherwise ``None`` (use bundled Chromium).
    """
    explicit = (explicit or "").strip() or None
    if explicit is not None:
        return None if explicit.lower() == "none" else explicit

    env_channel = (os.environ.get("PIM_PLAYWRIGHT_CHANNEL") or "").strip() or None
    if env_channel is not None:
        return None if env_channel.lower() == "none" else env_channel

    if backend_name() == "patchright":
        return "chrome"
    return None


def is_patchright_active() -> bool:
    return backend_name() == "patchright"


def recommended_launch_args(base_args: list[str] | None = None) -> list[str]:
    """Adjust the caller's launch args for the active backend.

    Patchright explicitly discourages ``--disable-blink-features=AutomationControlled``
    (it's one of the signals the patched Chromium itself masks, and adding the
    flag tips the fingerprint in the *other* direction). For vanilla playwright
    we keep the legacy flag for a minor amount of stealth.
    """
    args = list(base_args or [])
    if is_patchright_active():
        args = [a for a in args if "blink-features=AutomationControlled" not in a]
        return args
    if not any("blink-features=AutomationControlled" in a for a in args):
        args.append("--disable-blink-features=AutomationControlled")
    return args
