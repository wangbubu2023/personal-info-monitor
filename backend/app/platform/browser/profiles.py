"""Filesystem helpers for persistent Playwright browser profiles.

* ``profiles_root`` — resolve (and ensure) the directory that holds every
  persistent profile (``$PLAYWRIGHT_PROFILE_ROOT`` or ``~/.pim/playwright-sessions``).
* ``slugify_profile_name`` — make a filesystem-safe folder name out of an
  arbitrary label, falling back to a short uuid suffix when the input is empty.

These are pure platform concerns: domain code (e.g. browser-session bootstrap)
delegates here rather than touching ``os.environ`` / ``pathlib`` itself.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def profiles_root() -> Path:
    root = os.getenv(
        "PLAYWRIGHT_PROFILE_ROOT",
        str(Path.home() / ".pim" / "playwright-sessions"),
    )
    path = Path(root).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify_profile_name(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in (text or "").strip().lower())
    collapsed = "-".join([p for p in cleaned.split("-") if p])
    return collapsed or f"session-{uuid.uuid4().hex[:8]}"
