"""Feature flags for temporarily disabled product areas.

Static flags live in-module. Runtime-overridable flags read ``PIM_FEATURE_*``
environment variables through :func:`feature_enabled` so operators can flip
them without code changes.
"""

import os

PODCAST_SOURCES_ENABLED = False
KEYWORD_MONITORING_ENABLED = True

PODCAST_DISABLED_DETAIL = "播客监控功能已暂时下线"
KEYWORD_DISABLED_DETAIL = "关键词过滤功能未启用"


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "t", "yes", "y", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off", "disabled"}:
        return False
    return default


# Runtime feature flags.
#   PIM_FEATURE_PLAYWRIGHT
#     Master switch for any Playwright (Chromium) usage. Default ON because
#     website collection relies on it for JS-heavy sources. Operators who
#     deploy PIM on hardened / headless boxes and want to eliminate the
#     Chromium attack surface entirely can set this to ``false`` —
#     ``collectors/website`` will fall back to pure HTTP + RSS heuristics,
#     ``collectors/x_twitter`` will use only RSSHub / Nitter / API, and all
#     manual cookie-probe flows return a typed error.
#
#   PIM_FEATURE_X_PLAYWRIGHT
#     Narrower switch for X (Twitter) cookie-based auto-login flows which
#     touch X Terms of Service grey area (see ADR-003). **Default OFF** per
#     the 2026-04-20 audit S5 recommendation; operators must opt in.
#
#   ATOMS_ENABLED
#     Opt-in for the normalized news atom library (``atoms`` /
#     ``atom_relations`` tables in pim.db). **Default OFF**.
_FEATURE_FLAG_DEFAULTS = {
    "PIM_FEATURE_PLAYWRIGHT": True,
    "PIM_FEATURE_X_PLAYWRIGHT": False,
    "ATOMS_ENABLED": False,
    "ATOMS_RELATIONS_ENABLED": False,
    "PIM_SCORE_LLM_SUBJECTIVE": False,
}


def feature_enabled(name: str) -> bool:
    """Return the runtime value of a PIM_FEATURE_* flag.

    Unknown flag names raise ``KeyError`` to surface typos early — feature
    flags must be declared in ``_FEATURE_FLAG_DEFAULTS`` above.
    """
    if name not in _FEATURE_FLAG_DEFAULTS:
        raise KeyError(f"Unknown feature flag: {name!r}")
    return _parse_bool(os.environ.get(name), default=_FEATURE_FLAG_DEFAULTS[name])


def playwright_enabled() -> bool:
    """Convenience wrapper for the master Playwright switch."""
    return feature_enabled("PIM_FEATURE_PLAYWRIGHT")


def x_playwright_enabled() -> bool:
    """Convenience wrapper for X (Twitter) Playwright automation.

    Implicitly requires the master switch — if the operator disabled
    Playwright entirely, X-specific Playwright use is disabled too.
    """
    return feature_enabled("PIM_FEATURE_PLAYWRIGHT") and feature_enabled("PIM_FEATURE_X_PLAYWRIGHT")


def atoms_relations_enabled() -> bool:
    """Cross-article relation inference (P2). Requires atoms layer."""
    return atoms_enabled() and feature_enabled("ATOMS_RELATIONS_ENABLED")


def atoms_enabled() -> bool:
    """Convenience wrapper for the ``ATOMS_ENABLED`` opt-in.

    When ``False`` (default), the atoms layer is fully inert: the
    extractor short-circuits without touching the DB and the
    :class:`SqlAtomReader` port returns an empty tuple.
    """
    return feature_enabled("ATOMS_ENABLED")


class PlaywrightDisabledError(RuntimeError):
    """Raised when caller tries to use Playwright while the feature flag is off."""
