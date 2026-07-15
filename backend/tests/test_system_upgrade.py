from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from app.platform.runtime import upgrade
from app.platform.runtime.upgrade_runner import LOG_FILE_NAME, STATUS_FILE_NAME


class _FakePopen:
    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.pid = 12345


def _write_project_version(root: Path, version: str) -> None:
    backend = root / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    (backend / "pyproject.toml").write_text(
        f'[project]\nname = "test-pim"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def test_configured_upgrade_args_skips_pull_for_detached_checkout(monkeypatch):
    monkeypatch.setattr(upgrade, "get_settings", lambda: SimpleNamespace(pim_ui_upgrade_args=""))
    monkeypatch.setattr(upgrade, "_checkout_is_detached", lambda: True)

    assert upgrade.configured_upgrade_args() == ["--no-pull"]


def test_configured_upgrade_args_preserves_explicit_override(monkeypatch):
    monkeypatch.setattr(
        upgrade,
        "get_settings",
        lambda: SimpleNamespace(pim_ui_upgrade_args="--no-pull --no-restart"),
    )
    monkeypatch.setattr(upgrade, "_checkout_is_detached", lambda: False)

    assert upgrade.configured_upgrade_args() == ["--no-pull", "--no-restart"]


def test_start_upgrade_launches_detached_runner(monkeypatch, tmp_path):
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return _FakePopen(command, **kwargs)

    monkeypatch.setattr(upgrade.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(upgrade, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(upgrade, "_checkout_is_detached", lambda: False)

    status = upgrade.start_upgrade(
        data_dir=tmp_path,
        root=tmp_path,
        python_executable="/python",
        runner_path=tmp_path / "runner.py",
        upgrade_args=["--server"],
    )
    again = upgrade.start_upgrade(
        data_dir=tmp_path,
        root=tmp_path,
        python_executable="/python",
        runner_path=tmp_path / "runner.py",
        upgrade_args=["--server"],
    )

    assert status["status"] == "running"
    assert status["command"] == ["./pim", "upgrade", "--server"]
    assert again["pid"] == 12345
    assert len(calls) == 1
    assert calls[0][0] == [
        "/python",
        str(tmp_path / "runner.py"),
        "--root",
        str(tmp_path),
        "--data-dir",
        str(tmp_path),
        "--",
        "--server",
    ]
    assert calls[0][1]["start_new_session"] is True


def test_start_upgrade_passes_expected_version_to_runner(monkeypatch, tmp_path):
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return _FakePopen(command, **kwargs)

    monkeypatch.setattr(upgrade.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(upgrade, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(upgrade, "_checkout_is_detached", lambda: False)

    status = upgrade.start_upgrade(
        data_dir=tmp_path,
        root=tmp_path,
        python_executable="/python",
        runner_path=tmp_path / "runner.py",
        upgrade_args=["--no-pull"],
        expected_version="v1.6.7",
    )

    assert status["expected_version"] == "v1.6.7"
    assert calls[0][0] == [
        "/python",
        str(tmp_path / "runner.py"),
        "--root",
        str(tmp_path),
        "--data-dir",
        str(tmp_path),
        "--expected-version",
        "v1.6.7",
        "--",
        "--no-pull",
    ]


def test_get_upgrade_status_marks_dead_runner_failed(monkeypatch, tmp_path):
    status_path = tmp_path / STATUS_FILE_NAME
    status_path.write_text(
        json.dumps(
            {
                "status": "running",
                "pid": 99999,
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": None,
                "exit_code": None,
                "command": ["./pim", "upgrade"],
                "log_path": str(tmp_path / LOG_FILE_NAME),
                "message": "Upgrade started",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(upgrade, "_pid_alive", lambda _pid: False)

    status = upgrade.get_upgrade_status(data_dir=tmp_path)

    assert status["status"] == "failed"
    assert "exited before writing" in status["message"]


def test_upgrade_runner_writes_success_status(tmp_path):
    pim = tmp_path / "pim"
    pim.write_text("#!/bin/sh\necho upgraded \"$@\"\nexit 0\n", encoding="utf-8")
    pim.chmod(0o755)

    runner = Path(upgrade.__file__).with_name("upgrade_runner.py")
    result = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--root",
            str(tmp_path),
            "--data-dir",
            str(tmp_path),
            "--",
            "--no-pull",
        ],
        cwd=str(tmp_path),
        check=False,
    )

    assert result.returncode == 0
    status = json.loads((tmp_path / STATUS_FILE_NAME).read_text(encoding="utf-8"))
    assert status["status"] == "succeeded"
    assert status["exit_code"] == 0
    assert status["command"] == ["./pim", "upgrade", "--no-pull"]
    assert status["message"] == "Refresh complete; code update was skipped (--no-pull)"
    assert "upgraded upgrade --no-pull" in (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")


def test_upgrade_runner_rejects_stale_no_pull_before_running_command(tmp_path):
    marker = tmp_path / "pim-ran"
    pim = tmp_path / "pim"
    pim.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
    pim.chmod(0o755)
    _write_project_version(tmp_path, "1.6.5")

    runner = Path(upgrade.__file__).with_name("upgrade_runner.py")
    result = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--root",
            str(tmp_path),
            "--data-dir",
            str(tmp_path),
            "--expected-version",
            "v1.6.7",
            "--",
            "--no-pull",
        ],
        cwd=str(tmp_path),
        check=False,
    )

    assert result.returncode == 1
    assert not marker.exists()
    status = json.loads((tmp_path / STATUS_FILE_NAME).read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["result_version"] == "1.6.5"
    assert "--no-pull prevents code updates" in status["message"]


def test_upgrade_runner_allows_no_pull_when_target_is_already_checked_out(tmp_path):
    pim = tmp_path / "pim"
    pim.write_text("#!/bin/sh\necho refreshed\nexit 0\n", encoding="utf-8")
    pim.chmod(0o755)
    _write_project_version(tmp_path, "1.6.7")

    runner = Path(upgrade.__file__).with_name("upgrade_runner.py")
    result = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--root",
            str(tmp_path),
            "--data-dir",
            str(tmp_path),
            "--expected-version",
            "v1.6.7",
            "--",
            "--no-pull",
        ],
        cwd=str(tmp_path),
        check=False,
    )

    assert result.returncode == 0
    status = json.loads((tmp_path / STATUS_FILE_NAME).read_text(encoding="utf-8"))
    assert status["status"] == "succeeded"
    assert status["result_version"] == "1.6.7"
    assert status["message"] == "Refresh complete; code is already at target v1.6.7"


def test_upgrade_runner_fails_when_pull_does_not_reach_target(tmp_path):
    pim = tmp_path / "pim"
    pim.write_text("#!/bin/sh\necho fake pull succeeded\nexit 0\n", encoding="utf-8")
    pim.chmod(0o755)
    _write_project_version(tmp_path, "1.6.5")

    runner = Path(upgrade.__file__).with_name("upgrade_runner.py")
    result = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--root",
            str(tmp_path),
            "--data-dir",
            str(tmp_path),
            "--expected-version",
            "v1.6.7",
        ],
        cwd=str(tmp_path),
        check=False,
    )

    assert result.returncode == 1
    status = json.loads((tmp_path / STATUS_FILE_NAME).read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert "target v1.6.7 was not reached" in status["message"]
