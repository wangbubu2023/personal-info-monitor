"""GitHub release update checks for PIM."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx

from app.platform.config.settings import get_settings

_PACKAGE_NAME = "personal-info-monitor-backend"
_ROOT = Path(__file__).resolve().parents[4]
_VERSION_RE = re.compile(r"\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?")


@dataclass(frozen=True)
class ReleaseVersion:
    """Normalized release version with semantic-ish comparison support."""

    raw: str
    major: int
    minor: int
    patch: int
    prerelease: str

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def stable_tuple(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_pyproject_version() -> str | None:
    path = _ROOT / "backend" / "pyproject.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def current_version() -> str:
    """Return the installed backend package version, falling back to pyproject."""

    try:
        return metadata.version(_PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return _read_pyproject_version() or "0.0.0"


def parse_release_version(value: str | None) -> ReleaseVersion | None:
    """Parse tags like ``v1.4.3`` / ``release-1.4.3`` into comparable parts."""

    if not value:
        return None
    match = _VERSION_RE.search(str(value).strip())
    if not match:
        return None
    raw = match.group(0)
    core, _, suffix = raw.partition("-")
    if "+" in core:
        core = core.split("+", 1)[0]
    parts = [int(part) for part in core.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return ReleaseVersion(raw=raw, major=parts[0], minor=parts[1], patch=parts[2], prerelease=suffix)


def is_newer_version(candidate: str | None, current: str | None) -> bool:
    """Return True when candidate is newer than current."""

    candidate_version = parse_release_version(candidate)
    current_version_value = parse_release_version(current)
    if candidate_version is None or current_version_value is None:
        return False
    if candidate_version.stable_tuple() != current_version_value.stable_tuple():
        return candidate_version.stable_tuple() > current_version_value.stable_tuple()
    if current_version_value.is_prerelease and not candidate_version.is_prerelease:
        return True
    return False


def _release_url(repo: str, tag: str | None = None) -> str:
    suffix = f"releases/tag/{tag}" if tag else "releases"
    return f"https://github.com/{repo}/{suffix}"


def _trim_release_notes(value: Any, *, limit: int = 600) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _disabled_payload(reason: str) -> dict[str, Any]:
    version = current_version()
    return {
        "status": "disabled",
        "current_version": version,
        "latest_version": None,
        "latest_tag": None,
        "update_available": False,
        "release_url": None,
        "published_at": None,
        "release_name": None,
        "release_notes": "",
        "checked_at": _utc_now(),
        "message": reason,
    }


async def check_for_updates(*, include_prerelease: bool = False) -> dict[str, Any]:
    """Query GitHub latest release metadata and compare it with current version."""

    settings = get_settings()
    repo = str(getattr(settings, "pim_update_check_repo", "") or "").strip().strip("/")
    if not repo:
        return _disabled_payload("GitHub update check is not configured")

    version = current_version()
    endpoint = "releases" if include_prerelease else "releases/latest"
    api_url = f"https://api.github.com/repos/{repo}/{endpoint}"
    timeout = max(float(getattr(settings, "pim_update_check_timeout_seconds", 4.0) or 4.0), 1.0)

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"PIM/{version} update-check",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        return _disabled_payload(f"GitHub update check failed: HTTP {exc.response.status_code}")
    except (httpx.RequestError, ValueError) as exc:
        return _disabled_payload(f"GitHub update check failed: {exc.__class__.__name__}")

    release: dict[str, Any] | None
    if include_prerelease and isinstance(payload, list):
        release = next((item for item in payload if isinstance(item, dict) and not item.get("draft")), None)
    else:
        release = payload if isinstance(payload, dict) else None

    if not release:
        return _disabled_payload("No GitHub release was found")

    tag = str(release.get("tag_name") or "").strip()
    latest = parse_release_version(tag)
    release_url = str(release.get("html_url") or _release_url(repo, tag or None))
    latest_version = latest.raw if latest else tag or None
    update_available = is_newer_version(latest_version, version)
    return {
        "status": "ok",
        "current_version": version,
        "latest_version": latest_version,
        "latest_tag": tag or None,
        "update_available": update_available,
        "release_url": release_url,
        "published_at": release.get("published_at"),
        "release_name": release.get("name") or tag or None,
        "release_notes": _trim_release_notes(release.get("body")),
        "checked_at": _utc_now(),
        "message": "New version available" if update_available else "Already up to date",
    }


__all__ = ["check_for_updates", "current_version", "is_newer_version", "parse_release_version"]
