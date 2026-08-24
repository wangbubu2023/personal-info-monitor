"""Feature flags for temporarily disabled product areas.

Static flags live in-module. Runtime-overridable flags read ``PIM_FEATURE_*``
environment variables through :func:`feature_enabled` so operators can flip
them without code changes.
"""

import os

PODCAST_SOURCES_ENABLED = False
KEYWORD_MONITORING_ENABLED = True
# Product-level switch. The main branch can freeze the atoms surface without
# deleting the domain implementation or its database schema.
ATOMS_PRODUCT_ENABLED = True

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
#     touch X Terms of Service grey area. **Default OFF** per the 2026-04-20
#     audit S5 recommendation; operators must opt in.
#
#   ATOMS_ENABLED
#     Opt-in for the normalized news atom library (``atoms`` /
#     ``atom_relations`` tables in pim.db). **Default OFF**.
_FEATURE_FLAG_DEFAULTS = {
    "PIM_FEATURE_PLAYWRIGHT": True,
    "PIM_FEATURE_X_PLAYWRIGHT": False,
    "ATOMS_ENABLED": False,
    "ATOMS_RELATIONS_ENABLED": False,
    "ATOMS_RECONCILE_ENABLED": False,
    "ATOMS_KNOWLEDGE_ENABLED": False,
}

_RUNTIME_PROFILES = {"production", "development", "test"}


def runtime_profile() -> str:
    """Return the active runtime profile.

    Git branches describe code maturity; runtime profiles describe behaviour.
    Keeping those concerns separate lets the same commit move from ``dev`` to
    ``main`` without editing product flags during every release.
    """

    value = (os.environ.get("PIM_RUNTIME_PROFILE") or "production").strip().lower()
    return value if value in _RUNTIME_PROFILES else "production"


def development_profile_enabled() -> bool:
    """Whether local development-only product surfaces may be exposed."""

    return runtime_profile() == "development"


def inline_annotations_enabled() -> bool:
    """Human annotation is intentionally available only in local development."""

    return development_profile_enabled()


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
    return atoms_enabled() and _settings_or_env_feature_enabled(
        setting_key="atoms_relations_enabled",
        env_name="ATOMS_RELATIONS_ENABLED",
    )


def atoms_reconcile_enabled() -> bool:
    """Atom reconcile worker (ADD/MERGE/SUPERSEDE/CONTRADICT/IGNORE). Requires atoms layer."""
    return atoms_enabled() and _settings_or_env_feature_enabled(
        setting_key="atoms_reconcile_enabled",
        env_name="ATOMS_RECONCILE_ENABLED",
    )


def atoms_knowledge_enabled() -> bool:
    """Event clustering + entity layer (L3/L5). Rule-based, requires atoms layer."""
    return atoms_enabled() and _settings_or_env_feature_enabled(
        setting_key="atoms_knowledge_enabled",
        env_name="ATOMS_KNOWLEDGE_ENABLED",
    )


def atoms_enabled() -> bool:
    """Convenience wrapper for the ``ATOMS_ENABLED`` opt-in.

    When ``False`` (default), the atoms layer is fully inert: the
    extractor short-circuits without touching the DB and the
    :class:`SqlAtomReader` port returns an empty tuple.
    """
    return _settings_or_env_feature_enabled(
        setting_key="atoms_enabled",
        env_name="ATOMS_ENABLED",
    )


def atoms_product_enabled() -> bool:
    """Whether the atoms product surface is exposed in this branch.

    ``main`` keeps the implementation and schema for later reuse on ``dev``
    but intentionally does not expose or execute the product surface.
    """
    return ATOMS_PRODUCT_ENABLED or development_profile_enabled()


def _settings_or_env_feature_enabled(*, setting_key: str, env_name: str) -> bool:
    if os.environ.get(env_name) is not None:
        return feature_enabled(env_name)
    try:
        from app.platform.config.system_settings import get_system_settings_sync

        return _parse_bool(
            str((get_system_settings_sync() or {}).get(setting_key, "")),
            default=_FEATURE_FLAG_DEFAULTS[env_name],
        )
    except (ImportError, KeyError, RuntimeError):
        return feature_enabled(env_name)


class PlaywrightDisabledError(RuntimeError):
    """Raised when caller tries to use Playwright while the feature flag is off."""
