"""Standalone PIM upgrade runner.

This module is launched as a separate process by the HTTP API. It must stay
stdlib-only because the parent PIM server may be stopped while the upgrade is
still running.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_FILE_NAME = "upgrade-status.json"
LOG_FILE_NAME = "upgrade.log"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--data-dir", required=True)
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

    status: dict[str, Any] = {
        "status": "running",
        "pid": os.getpid(),
        "started_at": _utc_now(),
        "finished_at": None,
        "exit_code": None,
        "command": command,
        "log_path": str(log_path),
        "message": "Upgrade started",
    }
    _atomic_write_json(status_path, status)

    data_dir.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n\n=== PIM UI upgrade started at {status['started_at']} ===\n")
        log.write(f"$ {' '.join(command)}\n\n")
        log.flush()
        proc = subprocess.run(command, cwd=str(root), stdout=log, stderr=subprocess.STDOUT)

    finished_status = dict(status)
    finished_status["finished_at"] = _utc_now()
    finished_status["exit_code"] = proc.returncode
    finished_status["status"] = "succeeded" if proc.returncode == 0 else "failed"
    finished_status["message"] = "Upgrade complete" if proc.returncode == 0 else "Upgrade failed"
    _atomic_write_json(status_path, finished_status)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
