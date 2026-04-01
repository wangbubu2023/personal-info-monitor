"""Configuration helpers for pimctl."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SERVER = "http://127.0.0.1:8000"
DEFAULT_PROFILE = "local"


@dataclass
class Profile:
    name: str
    server: str = DEFAULT_SERVER
    api_key: str | None = None
    output: str | None = None
    timeout: int | None = None


def config_path() -> Path:
    override = os.getenv("PIM_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "pim" / "config.toml"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"default_profile": DEFAULT_PROFILE, "profiles": {}}

    with path.open("rb") as f:
        data = tomllib.load(f)

    if not isinstance(data, dict):
        return {"default_profile": DEFAULT_PROFILE, "profiles": {}}
    data.setdefault("default_profile", DEFAULT_PROFILE)
    data.setdefault("profiles", {})
    return data


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    default_profile = str(config.get("default_profile") or DEFAULT_PROFILE)
    profiles = config.get("profiles") or {}

    lines = [f'default_profile = "{_escape(default_profile)}"', ""]
    for name in sorted(profiles.keys()):
        profile = profiles[name] or {}
        lines.append(f"[profiles.{name}]")
        server = str(profile.get("server") or DEFAULT_SERVER)
        lines.append(f'server = "{_escape(server)}"')
        api_key = profile.get("api_key")
        if api_key:
            lines.append(f'api_key = "{_escape(str(api_key))}"')
        output = profile.get("output")
        if output:
            lines.append(f'output = "{_escape(str(output))}"')
        timeout = profile.get("timeout")
        if timeout is not None:
            lines.append(f"timeout = {int(timeout)}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def get_profile(config: dict[str, Any], profile_name: str | None = None) -> Profile:
    profiles = config.get("profiles") or {}
    name = profile_name or str(config.get("default_profile") or DEFAULT_PROFILE)
    raw = profiles.get(name) or {}
    return Profile(
        name=name,
        server=str(raw.get("server") or DEFAULT_SERVER),
        api_key=str(raw.get("api_key")) if raw.get("api_key") else None,
        output=str(raw.get("output")) if raw.get("output") else None,
        timeout=int(raw.get("timeout")) if raw.get("timeout") is not None else None,
    )


def upsert_profile(
    profile_name: str,
    *,
    server: str | None = None,
    api_key: str | None = None,
    output: str | None = None,
    timeout: int | None = None,
    make_default: bool = False,
) -> Profile:
    config = load_config()
    profiles = config.setdefault("profiles", {})
    current = profiles.get(profile_name) or {}

    if server is not None:
        current["server"] = server
    elif "server" not in current:
        current["server"] = DEFAULT_SERVER

    if api_key is not None:
        current["api_key"] = api_key
    if output is not None:
        current["output"] = output
    if timeout is not None:
        current["timeout"] = int(timeout)

    profiles[profile_name] = current
    if make_default or not config.get("default_profile"):
        config["default_profile"] = profile_name
    save_config(config)
    return get_profile(config, profile_name)


def clear_profile_api_key(profile_name: str) -> Profile:
    config = load_config()
    profiles = config.setdefault("profiles", {})
    current = profiles.get(profile_name) or {"server": DEFAULT_SERVER}
    current.pop("api_key", None)
    profiles[profile_name] = current
    save_config(config)
    return get_profile(config, profile_name)
