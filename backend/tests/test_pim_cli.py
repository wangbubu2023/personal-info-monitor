"""Regression tests for the top-level ``./pim`` operational CLI."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
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


def test_upgrade_handles_symbolic_ref_failure_as_detached_checkout(monkeypatch):
    pim = _load_pim_cli()

    def fake_check_output(cmd, **kwargs):  # noqa: ARG001
        if cmd[:2] == ["git", "status"]:
            return ""
        if cmd[:3] == ["git", "symbolic-ref", "--short"]:
            raise subprocess.CalledProcessError(1, cmd)
        raise AssertionError(cmd)

    monkeypatch.setattr(pim.subprocess, "check_output", fake_check_output)

    pim._ensure_git_ready(no_pull=True)


def test_minimal_env_fallback_does_not_reintroduce_legacy_ai_switches(monkeypatch, tmp_path):
    pim = _load_pim_cli()
    env_file = tmp_path / ".env"

    monkeypatch.setattr(pim, "ENV_FILE", env_file)
    monkeypatch.setattr(pim, "ENV_EXAMPLE_FILE", tmp_path / "missing.env.example")

    pim._ensure_env_file()

    payload = env_file.read_text(encoding="utf-8")
    assert "DATA_DIR=~/.pim/data" in payload
    assert "FETCH_CONCURRENCY=20" in payload
    assert "AI_PROCESSING_ENABLED" not in payload
    assert "ENRICH_SUMMARY_ENABLED" not in payload
    assert "ENRICH_TRANSLATE_ENABLED" not in payload


def test_build_frontend_uses_clean_install(monkeypatch, tmp_path):
    pim = _load_pim_cli()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}")
    calls = []

    monkeypatch.setattr(pim, "FRONTEND", frontend)
    monkeypatch.setattr(
        pim.subprocess,
        "check_call",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )

    pim._build_frontend()

    assert calls == [
        (["npm", "ci"], {"cwd": str(frontend)}),
        (["npm", "run", "build"], {"cwd": str(frontend)}),
    ]


def test_upgrade_first_frontend_build_uses_clean_install(monkeypatch, tmp_path):
    pim = _load_pim_cli()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}")
    calls = []

    monkeypatch.setattr(pim, "FRONTEND", frontend)
    monkeypatch.setattr(
        pim.shutil,
        "which",
        lambda name: "/usr/bin/npm" if name == "npm" else None,
    )
    monkeypatch.setattr(pim, "_frontend_dist_stale", lambda: (True, "dist/index.html missing"))
    monkeypatch.setattr(
        pim.subprocess,
        "check_call",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )

    assert pim._ensure_frontend_built(rebuild=False) is True
    assert calls == [
        (["npm", "ci"], {"cwd": str(frontend)}),
        (["npm", "run", "build"], {"cwd": str(frontend)}),
    ]


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


def test_install_service_reenables_and_bootstraps_launchagent(monkeypatch, tmp_path, capsys):
    pim = _load_pim_cli()
    root = tmp_path / "repo"
    venv = root / "backend" / ".venv"
    (venv / "bin").mkdir(parents=True)
    log_file = tmp_path / "data" / "pim.log"
    plist_path = tmp_path / "LaunchAgents" / "com.pim.server.plist"
    calls = []

    monkeypatch.setattr(pim, "ROOT", root)
    monkeypatch.setattr(pim, "VENV", venv)
    monkeypatch.setattr(pim, "LOG_FILE", log_file)
    monkeypatch.setattr(pim, "PLIST_PATH", plist_path)
    monkeypatch.setattr(pim.os, "getuid", lambda: 501)
    monkeypatch.setattr(pim, "_wait_for_launchctl_unloaded", lambda _target: True)

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(pim.subprocess, "run", fake_run)

    pim.cmd_install_service()

    assert [cmd for cmd, _ in calls] == [
        ["launchctl", "bootout", "gui/501/com.pim.server"],
        ["launchctl", "enable", "gui/501/com.pim.server"],
        ["launchctl", "bootstrap", "gui/501", str(plist_path)],
        ["launchctl", "print", "gui/501/com.pim.server"],
    ]
    assert "LaunchAgent installed" in capsys.readouterr().out


def test_install_service_stops_when_launchagent_cannot_be_enabled(monkeypatch, tmp_path):
    pim = _load_pim_cli()
    root = tmp_path / "repo"
    venv = root / "backend" / ".venv"
    (venv / "bin").mkdir(parents=True)

    monkeypatch.setattr(pim, "ROOT", root)
    monkeypatch.setattr(pim, "VENV", venv)
    monkeypatch.setattr(pim, "LOG_FILE", tmp_path / "data" / "pim.log")
    monkeypatch.setattr(
        pim,
        "PLIST_PATH",
        tmp_path / "LaunchAgents" / "com.pim.server.plist",
    )
    monkeypatch.setattr(pim.os, "getuid", lambda: 501)
    monkeypatch.setattr(pim, "_wait_for_launchctl_unloaded", lambda _target: True)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            5 if cmd[:2] == ["launchctl", "enable"] else 0,
            stdout="",
            stderr="Input/output error",
        )

    monkeypatch.setattr(pim.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        pim.cmd_install_service()

    assert exc.value.code == 1


def test_wait_for_launchctl_unloaded_polls_until_service_disappears(monkeypatch):
    pim = _load_pim_cli()
    return_codes = iter([0, 0, 113])
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            next(return_codes),
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(pim.subprocess, "run", fake_run)
    monkeypatch.setattr(pim.time, "sleep", lambda _seconds: None)

    assert pim._wait_for_launchctl_unloaded("gui/501/com.pim.server") is True
    assert len(calls) == 3


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


def test_bootstrap_url_outputs_one_click_fragment_without_raw_code_prompt(
    monkeypatch, tmp_path, capsys
):
    pim = _load_pim_cli()
    venv = tmp_path / "venv"
    venv.mkdir()
    values = {
        "PIM_PUBLIC_URL": "https://pim.example.com",
        "PIM_PUBLIC_ORIGIN": None,
    }

    monkeypatch.setattr(pim, "VENV", venv)
    monkeypatch.setattr(pim.sys, "argv", ["pim", "bootstrap-url"])
    monkeypatch.setattr(pim, "_read_env_var", lambda name: values.get(name))
    monkeypatch.setattr(
        pim.subprocess,
        "check_output",
        lambda *_args, **_kwargs: "one-time-code+/=\n",
    )

    pim.cmd_bootstrap_url()

    captured = capsys.readouterr()
    assert (
        captured.out.strip()
        == "https://pim.example.com/#bootstrap_code=one-time-code%2B%2F%3D"
    )
    assert "Bootstrap Code:" not in captured.out
    assert "no code entry is required" in captured.err


def test_bootstrap_url_origin_override_warns_about_server_configuration(
    monkeypatch, tmp_path, capsys
):
    pim = _load_pim_cli()
    venv = tmp_path / "venv"
    venv.mkdir()
    monkeypatch.setattr(pim, "VENV", venv)
    monkeypatch.setattr(
        pim.sys,
        "argv",
        ["pim", "bootstrap-url", "--origin", "https://pim.example.com"],
    )
    monkeypatch.setattr(pim, "_read_env_var", lambda _name: None)

    monkeypatch.setattr(
        pim.subprocess,
        "check_output",
        lambda *_args, **_kwargs: "one-time-code-123456",
    )

    pim.cmd_bootstrap_url()

    captured = capsys.readouterr()
    assert captured.out.startswith(
        "https://pim.example.com/#bootstrap_code=one-time-code-123456"
    )
    assert "running server also has this address in PIM_PUBLIC_URL" in captured.err


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
