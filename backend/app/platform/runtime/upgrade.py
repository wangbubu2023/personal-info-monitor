"""Server-side orchestration for the UI-triggered PIM upgrade."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.platform.config.settings import get_settings

from .upgrade_runner import LOG_FILE_NAME, STATUS_FILE_NAME

_START_LOCK = threading.Lock()
_ROOT = Path(__file__).resolve().parents[4]
_RUNNER_PATH = Path(__file__).resolve().with_name("upgrade_runner.py")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_dir() -> Path:
    return Path(get_settings().data_dir).expanduser().resolve()


def _status_path(data_dir: Path | None = None) -> Path:
    return (data_dir or _data_dir()) / STATUS_FILE_NAME


def _log_path(data_dir: Path | None = None) -> Path:
    return (data_dir or _data_dir()) / LOG_FILE_NAME


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _tail(path: Path, *, max_chars: int = 6000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _checkout_is_detached() -> bool:
    """Return whether the project root is a detached Git checkout.

    A non-Git directory and an unexpected Git error are deliberately treated
    as "not detached" here. The upgrade command will provide the authoritative
    error for those cases; adding ``--no-pull`` would only obscure it.
    """
    try:
        subprocess.check_output(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],
            cwd=str(_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return False
    except subprocess.CalledProcessError as exc:
        # Git uses exit status 1 specifically for a detached HEAD. Other
        # failures (for example, a directory that is not a checkout) should
        # retain the normal CLI error rather than silently changing behavior.
        return exc.returncode == 1
    except OSError:
        return False


def configured_upgrade_args() -> list[str]:
    """Return effective fixed args for the UI-triggered ``./pim upgrade``.

    The browser cannot supply shell arguments. Operators who need systemd or a
    backend-only VPS can set PIM_UI_UPGRADE_ARGS in the service environment,
    e.g. ``--server --systemd pim``. When no override is supplied, a detached
    checkout gets ``--no-pull`` automatically: it can refresh the current
    checkout instead of failing because Git cannot fast-forward a detached
    HEAD. A branch checkout keeps the historical pull-and-upgrade behavior.
    """
    raw = str(getattr(get_settings(), "pim_ui_upgrade_args", "") or "").strip()
    if raw:
        return shlex.split(raw)
    return ["--no-pull"] if _checkout_is_detached() else []


def get_upgrade_status(*, data_dir: Path | None = None) -> dict[str, Any]:
    data_root = data_dir or _data_dir()
    status_path = _status_path(data_root)
    log_path = _log_path(data_root)
    status = _read_json(status_path)
    if not status:
        status = {
            "status": "idle",
            "pid": None,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "command": ["./pim", "upgrade", *configured_upgrade_args()],
            "log_path": str(log_path),
            "message": "No upgrade has been run yet",
        }

    if status.get("status") == "running" and not _pid_alive(int(status.get("pid") or 0)):
        status = {
            **status,
            "status": "failed",
            "finished_at": status.get("finished_at") or _utc_now(),
            "exit_code": status.get("exit_code"),
            "message": "Upgrade runner exited before writing a final status",
        }
        _atomic_write_json(status_path, status)

    status["log_tail"] = _tail(Path(str(status.get("log_path") or log_path)))
    status["configured_args"] = configured_upgrade_args()
    return status


def start_upgrade(
    *,
    data_dir: Path | None = None,
    root: Path | None = None,
    python_executable: str | None = None,
    runner_path: Path | None = None,
    upgrade_args: list[str] | None = None,
    expected_version: str | None = None,
) -> dict[str, Any]:
    data_root = data_dir or _data_dir()
    project_root = root or _ROOT
    runner = runner_path or _RUNNER_PATH
    args = configured_upgrade_args() if upgrade_args is None else upgrade_args

    with _START_LOCK:
        current = get_upgrade_status(data_dir=data_root)
        if current.get("status") == "running":
            return current

        command = [
            python_executable or sys.executable,
            str(runner),
            "--root",
            str(project_root),
            "--data-dir",
            str(data_root),
        ]
        if expected_version:
            command.extend(["--expected-version", expected_version])
        command.extend(["--", *args])
        proc = subprocess.Popen(
            command,
            cwd=str(project_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        status = {
            "status": "running",
            "pid": proc.pid,
            "started_at": _utc_now(),
            "finished_at": None,
            "exit_code": None,
            "command": ["./pim", "upgrade", *args],
            "log_path": str(_log_path(data_root)),
            "message": "Upgrade started",
            "configured_args": args,
            "expected_version": expected_version,
            "log_tail": "",
        }
        _atomic_write_json(_status_path(data_root), status)
        return status


__all__ = ["configured_upgrade_args", "get_upgrade_status", "start_upgrade"]
