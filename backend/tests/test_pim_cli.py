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


def test_currently_running_pid_discovers_unmanaged_uvicorn(monkeypatch, tmp_path):
    pim = _load_pim_cli()
    pid_file = tmp_path / "run" / "pim.pid"

    monkeypatch.setattr(pim, "PID_FILE", pid_file)
    monkeypatch.setattr(pim, "LEGACY_PID_FILE", tmp_path / "pim.pid")
    monkeypatch.setattr(pim, "_is_launchd_backed", lambda: False)
    monkeypatch.setattr(pim, "_find_prod_uvicorn_pids", lambda: [123])
    monkeypatch.setattr(pim, "_is_prod_uvicorn_pid", lambda pid: pid == 123)

    assert pim._currently_running_pid() == 123
    assert pid_file.read_text() == "123"


def test_systemd_restart_skips_when_systemd_unavailable(monkeypatch, capsys):
    pim = _load_pim_cli()
    monkeypatch.setattr(pim.shutil, "which", lambda name: None)

    assert pim._restart_systemd_unit("personal-info-monitor") is False

    captured = capsys.readouterr()
    assert "systemd is not available" in captured.err


def test_playwright_install_module_prefers_patchright(monkeypatch):
    pim = _load_pim_cli()

    monkeypatch.delenv("PIM_BROWSER_BACKEND", raising=False)
    monkeypatch.setattr(pim, "_python_module_available", lambda module: module == "patchright")

    assert pim._playwright_install_module() == "patchright"


def test_playwright_install_module_respects_playwright_override(monkeypatch):
    pim = _load_pim_cli()

    monkeypatch.setenv("PIM_BROWSER_BACKEND", "playwright")
    monkeypatch.setattr(pim, "_python_module_available", lambda _module: True)

    assert pim._playwright_install_module() == "playwright"


def test_auth_bundle_dispatches_to_pimctl(monkeypatch, tmp_path):
    pim = _load_pim_cli()
    calls = []
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)

    monkeypatch.setattr(pim, "VENV", venv)
    monkeypatch.setattr(pim.sys, "argv", ["pim", "auth-bundle", "export", "https://example.com"])
    monkeypatch.setattr(pim.subprocess, "call", lambda cmd, **kwargs: calls.append((cmd, kwargs)) or 0)

    with pytest.raises(SystemExit) as exc:
        pim.cmd_auth_bundle()

    assert exc.value.code == 0
    assert calls
    cmd, kwargs = calls[0]
    assert cmd[:3] == [str(venv / "bin" / "python"), str(pim.ROOT / "pimctl"), "auth-bundle"]
    assert cmd[3:] == ["export", "https://example.com"]
    assert kwargs["cwd"] == str(pim.ROOT)


def test_capture_session_dispatches_to_auth_bundle_export(monkeypatch, tmp_path):
    pim = _load_pim_cli()
    calls = []
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)

    monkeypatch.setattr(pim, "VENV", venv)
    monkeypatch.setattr(
        pim.sys,
        "argv",
        ["pim", "capture-session", "https://x.com", "--out", "x.pim-auth-bundle.json"],
    )
    monkeypatch.setattr(pim.subprocess, "call", lambda cmd, **kwargs: calls.append((cmd, kwargs)) or 0)

    with pytest.raises(SystemExit) as exc:
        pim.cmd_capture_session()

    assert exc.value.code == 0
    assert calls
    cmd, kwargs = calls[0]
    assert cmd[:4] == [str(venv / "bin" / "python"), str(pim.ROOT / "pimctl"), "auth-bundle", "export"]
    assert cmd[4:] == ["https://x.com", "--out", "x.pim-auth-bundle.json"]
    assert kwargs["cwd"] == str(pim.ROOT)


def test_playwright_system_deps_uses_dnf_mapping(monkeypatch):
    pim = _load_pim_cli()
    calls = []

    monkeypatch.setattr(pim.sys, "platform", "linux")
    monkeypatch.setattr(
        pim.shutil,
        "which",
        lambda name: "/usr/bin/dnf" if name == "dnf" else None,
    )
    monkeypatch.setattr(pim.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(
        pim.subprocess,
        "check_call",
        lambda cmd, **_kwargs: calls.append(cmd),
    )

    pim._install_playwright_system_deps("patchright", set())

    assert calls
    assert calls[0][:3] == ["/usr/bin/dnf", "install", "-y"]
    assert "mesa-libgbm" in calls[0]
    assert "libxshmfence" in calls[0]


def test_playwright_system_deps_prints_manual_command_without_sudo(monkeypatch, capsys):
    pim = _load_pim_cli()
    calls = []

    monkeypatch.setattr(pim.sys, "platform", "linux")
    monkeypatch.setattr(
        pim.shutil,
        "which",
        lambda name: "/usr/bin/dnf" if name == "dnf" else None,
    )
    monkeypatch.setattr(pim.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(
        pim.subprocess,
        "check_call",
        lambda cmd, **_kwargs: calls.append(cmd),
    )

    pim._install_playwright_system_deps("patchright", set())

    captured = capsys.readouterr()
    assert not calls
    assert "sudo /usr/bin/dnf install -y" in captured.out


def test_ensure_noops_when_livez_is_healthy(monkeypatch, capsys):
    pim = _load_pim_cli()
    launched = False

    monkeypatch.setattr(pim.sys, "argv", ["pim", "ensure", "--server"])
    monkeypatch.setattr(pim, "_ensure_runtime_ready", lambda: "test-api-key")
    monkeypatch.setattr(pim, "_currently_running_pid", lambda: 123)
    monkeypatch.setattr(pim, "_is_livez_healthy", lambda: True)

    def fake_launch():
        nonlocal launched
        launched = True
        return 456

    monkeypatch.setattr(pim, "_launch_detached_backend", fake_launch)

    pim.cmd_ensure()

    captured = capsys.readouterr()
    assert "Healthy (PID 123)" in captured.out
    assert launched is False


def test_ensure_restarts_unhealthy_pim_process(monkeypatch, capsys):
    pim = _load_pim_cli()
    stopped = False
    launched = False

    monkeypatch.setattr(pim.sys, "argv", ["pim", "ensure", "--server"])
    monkeypatch.setattr(pim.sys, "platform", "linux")
    monkeypatch.setattr(pim, "_ensure_runtime_ready", lambda: None)
    monkeypatch.setattr(pim, "_currently_running_pid", lambda: 123)
    monkeypatch.setattr(pim, "_is_livez_healthy", lambda: False)
    monkeypatch.setattr(pim, "_wait_for_livez", lambda: True)

    def fake_stop():
        nonlocal stopped
        stopped = True

    def fake_launch():
        nonlocal launched
        launched = True
        return 456

    monkeypatch.setattr(pim, "_stop_by_pid", fake_stop)
    monkeypatch.setattr(pim, "_launch_detached_backend", fake_launch)

    pim.cmd_ensure()

    captured = capsys.readouterr()
    assert "Existing PIM process is not healthy (PID 123); restarting." in captured.out
    assert stopped is True
    assert launched is True


def test_ensure_refuses_foreign_port_owner(monkeypatch):
    pim = _load_pim_cli()

    monkeypatch.setattr(pim.sys, "argv", ["pim", "ensure", "--server"])
    monkeypatch.setattr(pim, "_ensure_runtime_ready", lambda: None)
    monkeypatch.setattr(pim, "_currently_running_pid", lambda: None)
    monkeypatch.setattr(pim, "_is_port_8000_open", lambda: True)

    with pytest.raises(SystemExit) as exc:
        pim.cmd_ensure()

    assert exc.value.code == 1


def test_restart_dispatches_stop_then_up_with_same_args(monkeypatch):
    pim = _load_pim_cli()
    calls = []

    monkeypatch.setattr(pim.sys, "argv", ["pim", "restart", "--server"])
    monkeypatch.setattr(pim, "cmd_stop", lambda: calls.append(("stop", tuple(pim.sys.argv))))
    monkeypatch.setattr(pim, "cmd_up", lambda: calls.append(("up", tuple(pim.sys.argv))))

    pim.cmd_restart()

    assert calls == [
        ("stop", ("pim", "restart", "--server")),
        ("up", ("pim", "restart", "--server")),
    ]
