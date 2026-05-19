"""Canonical catalog of monitoring source types.

This module is the single source of truth for:

* which source types exist at runtime,
* how each type is presented to humans (Chinese display label,
  short description, Tailwind accent color),
* whether the type is currently exposed to operators (feature-flagged
  via :mod:`app.features`).

Historically the same mapping was duplicated across:

* ``frontend/src/components/SourceList/hooks/useSourceList.ts`` (filter pills)
* ``frontend/src/components/SourceList/SourceEditorModal.tsx`` (create/edit form)
* ``frontend/src/components/Settings/TaskPromptsTab.tsx`` (AI prompt grid)
* ``frontend/src/components/Dashboard/dashboardTypes.ts`` (dashboard tabs)

The audit 2026-04-20 (Q3) called this out as drift-prone. The frontend now
pulls these labels from ``GET /api/system/source-types`` (falling back to
its bundled copy if the API call fails), so adding a new type only requires
updating this file + the :class:`app.models.source.SourceType` enum.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.features import PODCAST_SOURCES_ENABLED
from app.models.source import SourceType


@dataclass(frozen=True)
class SourceTypeInfo:
    """Presentation metadata for a ``SourceType``."""

    key: str
    label: str
    short_label: str
    description: str
    accent: str
    enabled: bool

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "short_label": self.short_label,
            "description": self.description,
            "accent": self.accent,
            "enabled": self.enabled,
        }


_CATALOG: List[SourceTypeInfo] = [
    SourceTypeInfo(
        key=SourceType.RSS.value,
        label="RSS",
        short_label="RSS",
        description="标准 RSS / Atom 订阅源，按 Feed 条目抓取。",
        accent="blue",
        enabled=True,
    ),
    SourceTypeInfo(
        key=SourceType.WEBSITE.value,
        label="网站 / 博客",
        short_label="网站",
        description="普通网页与博客，支持 HTTP 及 Playwright 回退。",
        accent="slate",
        enabled=True,
    ),
    SourceTypeInfo(
        key=SourceType.X.value,
        label="X (Twitter)",
        short_label="X",
        description="X 时间线；可经 RSSHub / Nitter / API 抓取。",
        accent="cyan",
        enabled=True,
    ),
    SourceTypeInfo(
        key=SourceType.YOUTUBE.value,
        label="YouTube",
        short_label="YouTube",
        description="YouTube 频道视频与描述。",
        accent="red",
        enabled=True,
    ),
    SourceTypeInfo(
        key=SourceType.PODCAST.value,
        label="播客",
        short_label="播客",
        description="播客 RSS。",
        accent="violet",
        enabled=PODCAST_SOURCES_ENABLED,
    ),
]


def source_type_catalog(*, include_disabled: bool = False) -> List[SourceTypeInfo]:
    """Return canonical source types.

    :param include_disabled: include feature-flagged-off types too. Operators
        talking to the admin surface sometimes need to see disabled types so
        they can migrate legacy data.
    """
    if include_disabled:
        return list(_CATALOG)
    return [info for info in _CATALOG if info.enabled]


def source_type_label(key: str) -> str:
    """Look up the Chinese display label for a source-type key.

    Unknown keys round-trip as-is so that logs and error messages never crash
    when a legacy record holds an unknown value.
    """
    for info in _CATALOG:
        if info.key == key:
            return info.label
    return key
