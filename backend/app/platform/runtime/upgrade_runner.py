"""Standalone PIM upgrade runner.

This module is launched as a separate process by the HTTP API. It must stay
stdlib-only because the parent PIM server may be stopped while the upgrade is
still running.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_FILE_NAME = "upgrade-status.json"
LOG_FILE_NAME = "upgrade.log"
_VERSION_RE = re.compile(r"\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _project_version(root: Path) -> str | None:
    """Read the checked-out backend version without importing project code."""

    try:
        text = (root / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _version_key(value: str | None) -> tuple[int, int, int, int] | None:
    """Return a small stdlib-only release ordering key."""

    match = _VERSION_RE.search(str(value or "").strip())
    if not match:
        return None
    raw = match.group(0)
    core = raw.split("-", 1)[0]
    parts = [int(part) for part in core.split(".")]
    while len(parts) < 3:
        parts.append(0)
    stable = 0 if "-" in raw else 1
    return parts[0], parts[1], parts[2], stable


def _target_reached(current: str | None, expected: str | None) -> bool:
    current_key = _version_key(current)
    expected_key = _version_key(expected)
    if current_key is None or expected_key is None:
        return False
    return current_key >= expected_key


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--expected-version")
    parser.add_argument("upgrade_args", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    if ns.upgrade_args and ns.upgrade_args[0] == "--":
        ns.upgrade_args = ns.upgrade_args[1:]
    return ns


def main() -> int:
    ns = _parse_args()
    root = Path(ns.root).expanduser().resolve()
    data_dir = Path(ns.data_dir).expanduser().resolve()
    status_path = data_dir / STATUS_FILE_NAME
    log_path = data_dir / LOG_FILE_NAME
    command = ["./pim", "upgrade", *ns.upgrade_args]
    expected_version = str(ns.expected_version or "").strip() or None
    initial_version = _project_version(root)

    status: dict[str, Any] = {
        "status": "running",
        "pid": os.getpid(),
        "started_at": _utc_now(),
        "finished_at": None,
        "exit_code": None,
        "command": command,
        "log_path": str(log_path),
        "message": "Upgrade started",
        "expected_version": expected_version,
        "initial_version": initial_version,
    }
    _atomic_write_json(status_path, status)

    data_dir.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n\n=== PIM UI upgrade started at {status['started_at']} ===\n")
        log.write(f"$ {' '.join(command)}\n\n")
        log.flush()
        if "--no-pull" in ns.upgrade_args and expected_version and not _target_reached(
            initial_version,
            expected_version,
        ):
            message = (
                "Upgrade refused: --no-pull prevents code updates, but current version "
                f"{initial_version or 'unknown'} has not reached target {expected_version}. "
                "Remove --no-pull or checkout the target version first."
            )
            log.write(f"ERROR: {message}\n")
            log.flush()
            finished_status = {
                **status,
                "finished_at": _utc_now(),
                "exit_code": 1,
                "status": "failed",
                "message": message,
                "result_version": initial_version,
            }
            _atomic_write_json(status_path, finished_status)
            return 1
        proc = subprocess.run(command, cwd=str(root), stdout=log, stderr=subprocess.STDOUT)

        result_version = _project_version(root)
        exit_code = proc.returncode
        if exit_code == 0 and expected_version and not _target_reached(result_version, expected_version):
            exit_code = 1
            message = (
                f"Upgrade command completed, but target {expected_version} was not reached "
                f"(current: {result_version or 'unknown'})."
            )
            log.write(f"ERROR: {message}\n")
            log.flush()
        elif exit_code != 0:
            message = "Upgrade failed"
        elif "--no-pull" in ns.upgrade_args:
            if expected_version:
                message = f"Refresh complete; code is already at target {expected_version}"
            else:
                message = "Refresh complete; code update was skipped (--no-pull)"
        else:
            message = "Upgrade complete"

    finished_status = dict(status)
    finished_status["finished_at"] = _utc_now()
    finished_status["exit_code"] = exit_code
    finished_status["status"] = "succeeded" if exit_code == 0 else "failed"
    finished_status["message"] = message
    finished_status["result_version"] = result_version
    _atomic_write_json(status_path, finished_status)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
