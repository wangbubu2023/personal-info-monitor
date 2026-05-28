"""Regression tests for the top-level ``./pim`` operational CLI."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest


def _load_pim_cli():
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "pim"
    loader = importlib.machinery.SourceFileLoader("pim_cli_test_module", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_upgrade_allows_detached_checkout_when_no_pull(monkeypatch):
    pim = _load_pim_cli()

    def fake_check_output(cmd, **kwargs):  # noqa: ARG001
        if cmd[:2] == ["git", "status"]:
            return ""
        if cmd[:3] == ["git", "symbolic-ref", "--short"]:
            return ""
        raise AssertionError(cmd)

    monkeypatch.setattr(pim.subprocess, "check_output", fake_check_output)

    pim._ensure_git_ready(no_pull=True)


def test_upgrade_rejects_detached_checkout_when_pull_needed(monkeypatch):
    pim = _load_pim_cli()

    def fake_check_output(cmd, **kwargs):  # noqa: ARG001
        if cmd[:2] == ["git", "status"]:
            return ""
        if cmd[:3] == ["git", "symbolic-ref", "--short"]:
            return ""
        raise AssertionError(cmd)

    monkeypatch.setattr(pim.subprocess, "check_output", fake_check_output)

    with pytest.raises(SystemExit):
        pim._ensure_git_ready(no_pull=False)


def test_pid_file_recovers_legacy_location(monkeypatch, tmp_path):
    pim = _load_pim_cli()
    pid_file = tmp_path / "run" / "pim.pid"
    legacy_pid_file = tmp_path / "pim.pid"
    legacy_pid_file.write_text("123")

    monkeypatch.setattr(pim, "PID_FILE", pid_file)
    monkeypatch.setattr(pim, "LEGACY_PID_FILE", legacy_pid_file)
    monkeypatch.setattr(pim, "_is_launchd_backed", lambda: False)
    monkeypatch.setattr(pim, "_is_prod_uvicorn_pid", lambda pid: pid == 123)
    monkeypatch.setattr(pim, "_find_prod_uvicorn_pids", lambda: [])

    assert pim._currently_running_pid() == 123
    assert pid_file.read_text() == "123"
    assert not legacy_pid_file.exists()


def test_systemd_restart_skips_when_systemd_unavailable(monkeypatch, capsys):
    pim = _load_pim_cli()
    monkeypatch.setattr(pim.shutil, "which", lambda name: None)

    assert pim._restart_systemd_unit("personal-info-monitor") is False

    captured = capsys.readouterr()
    assert "systemd is not available" in captured.err
