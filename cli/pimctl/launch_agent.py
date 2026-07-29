"""Small launchd orchestration helpers used by the top-level ``pim`` CLI."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class LaunchAgentError(RuntimeError):
    """Raised when launchd cannot replace or verify the PIM LaunchAgent."""


def wait_for_launchctl_unloaded(target: str, *, timeout: float = 5.0) -> bool:
    """Wait until launchd no longer exposes ``target`` after a bootout."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        result = subprocess.run(
            ["launchctl", "print", target],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _failure_detail(result: Any) -> str:
    return (result.stderr or result.stdout or "").strip() or "unknown error"


def install_launch_agent(
    *,
    launchctl_domain: str,
    launchctl_target: str,
    plist_path: Path,
    run: Callable[..., Any] = subprocess.run,
    wait_for_unloaded: Callable[[str], bool] = wait_for_launchctl_unloaded,
) -> None:
    """Replace, enable, bootstrap, and verify a launchd agent."""
    bootout = run(
        ["launchctl", "bootout", launchctl_target],
        capture_output=True,
        text=True,
    )
    if bootout.returncode == 0 and not wait_for_unloaded(launchctl_target):
        raise LaunchAgentError("Timed out waiting for the previous LaunchAgent instance to stop.")

    enabled = run(
        ["launchctl", "enable", launchctl_target],
        capture_output=True,
        text=True,
    )
    if enabled.returncode != 0:
        raise LaunchAgentError(f"launchctl enable failed: {_failure_detail(enabled)}")

    bootstrapped = run(
        ["launchctl", "bootstrap", launchctl_domain, str(plist_path)],
        capture_output=True,
        text=True,
    )
    if bootstrapped.returncode != 0:
        raise LaunchAgentError(f"launchctl bootstrap failed: {_failure_detail(bootstrapped)}")

    verified = run(
        ["launchctl", "print", launchctl_target],
        capture_output=True,
        text=True,
    )
    if verified.returncode != 0:
        raise LaunchAgentError(
            f"LaunchAgent bootstrap could not be verified: {_failure_detail(verified)}"
        )
