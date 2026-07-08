from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.platform.runtime import upgrade
from app.platform.runtime.upgrade_runner import LOG_FILE_NAME, STATUS_FILE_NAME


class _FakePopen:
    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.pid = 12345


def test_start_upgrade_launches_detached_runner(monkeypatch, tmp_path):
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return _FakePopen(command, **kwargs)

    monkeypatch.setattr(upgrade.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(upgrade, "_pid_alive", lambda _pid: True)

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
    assert "upgraded upgrade --no-pull" in (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
