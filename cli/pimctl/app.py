"""Main application for pimctl."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from cli.pimctl import __version__
from cli.pimctl.client import APIClient, CLIError
from cli.pimctl.config import (
    DEFAULT_PROFILE,
    DEFAULT_SERVER,
    clear_profile_api_key,
    get_profile,
    load_config,
    upsert_profile,
)
from cli.pimctl.output import emit_error, emit_success, print_key_values, print_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pimctl", description="Personal Info Monitor control CLI")
    parser.add_argument("--server", help="Base server URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("--api-key", help="API key for authenticated endpoints")
    parser.add_argument("--profile", default=None, help="Named CLI profile")
    parser.add_argument("--json", action="store_true", help="Emit JSON envelope output")
    parser.add_argument("--output", choices=["json", "table", "text"], help="Output format")
    parser.add_argument("--quiet", action="store_true", help="Reduce non-essential output")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds")
    parser.add_argument("--version", action="store_true", help="Show CLI version")

    subparsers = parser.add_subparsers(dest="resource")

    _build_auth_parser(subparsers)
    _build_system_parser(subparsers)
    _build_sources_parser(subparsers)
    _build_contents_parser(subparsers)
    _build_settings_parser(subparsers)
    _build_digest_parser(subparsers)

    return parser


def _build_auth_parser(subparsers) -> None:
    parser = subparsers.add_parser("auth", help="Manage CLI authentication profiles")
    sub = parser.add_subparsers(dest="command")

    login = sub.add_parser("login", help="Save server/API key into a profile")
    login.add_argument("--set-default", action="store_true", help="Set this profile as default")

    sub.add_parser("whoami", help="Show the resolved CLI profile")
    sub.add_parser("logout", help="Remove the stored API key from the selected profile")


def _build_system_parser(subparsers) -> None:
    parser = subparsers.add_parser("system", help="Inspect system status")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("health", help="Check server health")
    sub.add_parser("queue", help="Inspect queue/runtime status")
    sub.add_parser("stats", help="Show dashboard summary stats")


def _build_sources_parser(subparsers) -> None:
    parser = subparsers.add_parser("sources", help="Manage monitoring sources")
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List sources")
    list_parser.add_argument("--type")
    list_parser.add_argument("--category-id")
    list_parser.add_argument("--enabled", choices=["true", "false"])
    list_parser.add_argument("--search")
    list_parser.add_argument("--page", type=int, default=1)
    list_parser.add_argument("--page-size", type=int, default=20)

    get_parser = sub.add_parser("get", help="Get one source")
    get_parser.add_argument("id")

    add_parser = sub.add_parser("add", help="Create a source")
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--type", required=True, choices=["website", "rss", "x", "youtube", "podcast"])
    add_parser.add_argument("--url", required=True)
    add_parser.add_argument("--extra-url", action="append", default=[])
    add_parser.add_argument("--category-id")
    add_parser.add_argument("--fetch-interval", type=int, default=60)
    add_parser.add_argument("--priority", type=int, default=0)
    add_parser.add_argument("--disabled", action="store_true")
    add_parser.add_argument("--auth-required", action="store_true")
    add_parser.add_argument("--auth-config-id")

    delete_parser = sub.add_parser("delete", help="Delete a source")
    delete_parser.add_argument("id")

    probe_parser = sub.add_parser("probe", help="Probe an existing source")
    probe_parser.add_argument("id")

    probe_url_parser = sub.add_parser("probe-url", help="Probe a URL without creating a source")
    probe_url_parser.add_argument("url")
    probe_url_parser.add_argument("--type", default="website")

    fetch_parser = sub.add_parser("fetch", help="Trigger a fetch for one source")
    fetch_parser.add_argument("id")

    sub.add_parser("fetch-all", help="Trigger fetch for all active sources")


def _build_contents_parser(subparsers) -> None:
    parser = subparsers.add_parser("contents", help="Inspect collected contents")
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List contents")
    list_parser.add_argument("--source-id")
    list_parser.add_argument("--source-type")
    list_parser.add_argument("--category-id")
    list_parser.add_argument("--read", choices=["true", "false"])
    list_parser.add_argument("--favorited", choices=["true", "false"])
    list_parser.add_argument("--archived", choices=["true", "false"])
    list_parser.add_argument("--from-date")
    list_parser.add_argument("--to-date")
    list_parser.add_argument("--search")
    list_parser.add_argument("--page", type=int, default=1)
    list_parser.add_argument("--page-size", type=int, default=20)

    get_parser = sub.add_parser("get", help="Get one content item")
    get_parser.add_argument("id")

    search_parser = sub.add_parser("search", help="Search contents by keyword")
    search_parser.add_argument("query")
    search_parser.add_argument("--page", type=int, default=1)
    search_parser.add_argument("--page-size", type=int, default=20)

    cleanup_parser = sub.add_parser("cleanup-low-signal", help="Dry-run or delete historical low-signal website contents")
    cleanup_parser.add_argument("--apply", action="store_true", help="Delete matched contents instead of dry-run only")
    cleanup_parser.add_argument("--source-id")
    cleanup_parser.add_argument("--preview-limit", type=int, default=20)


def _build_settings_parser(subparsers) -> None:
    parser = subparsers.add_parser("settings", help="Inspect system settings")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("get", help="Get current settings")
    sub.add_parser("limits", help="Get runtime limits")


def _build_digest_parser(subparsers) -> None:
    parser = subparsers.add_parser("digest", help="Inspect digest data")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("latest", help="Get today's digest")
    day = sub.add_parser("day", help="Get digest for a date")
    day.add_argument("date")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    normalized_argv = _normalize_global_args(argv or sys.argv[1:])
    args = parser.parse_args(normalized_argv)

    if args.version:
        print(__version__)
        return 0

    if not args.resource:
        parser.print_help()
        return 2

    as_json = bool(args.json or args.output == "json")
    try:
        return dispatch(args, as_json=as_json)
    except CLIError as exc:
        emit_error(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            meta=_build_meta(args),
            as_json=as_json,
        )
        return exc.exit_code


def dispatch(args, *, as_json: bool) -> int:
    if args.resource == "auth":
        return handle_auth(args, as_json=as_json)

    profile = _resolve_profile(args)
    client = APIClient(
        server=profile["server"],
        api_key=profile["api_key"],
        timeout=profile["timeout"],
    )

    if args.resource == "system":
        return handle_system(args, client, as_json=as_json)
    if args.resource == "sources":
        return handle_sources(args, client, as_json=as_json)
    if args.resource == "contents":
        return handle_contents(args, client, as_json=as_json)
    if args.resource == "settings":
        return handle_settings(args, client, as_json=as_json)
    if args.resource == "digest":
        return handle_digest(args, client, as_json=as_json)

    raise CLIError("unsupported_command", "Unsupported command", 2)


def handle_auth(args, *, as_json: bool) -> int:
    config = load_config()
    profile_name = args.profile or str(config.get("default_profile") or DEFAULT_PROFILE)

    if args.command == "login":
        server = args.server or _env_or_profile_server(config, profile_name)
        api_key = args.api_key or _env_or_profile_api_key(config, profile_name)
        if not api_key:
            raise CLIError("missing_api_key", "Missing API key. Pass `--api-key` to save credentials.", 2)

        client = APIClient(server=server, api_key=api_key, timeout=args.timeout or 30)
        client.request("GET", "/api/system/queue")
        saved = upsert_profile(
            profile_name,
            server=server,
            api_key=api_key,
            output=args.output,
            timeout=args.timeout,
            make_default=bool(args.set_default),
        )
        emit_success(
            {
                "profile": saved.name,
                "server": saved.server,
                "has_api_key": True,
                "default_profile": load_config().get("default_profile"),
            },
            as_json=as_json,
            meta=_build_meta(args, server=saved.server),
            renderer=lambda data: print_key_values([
                ("Profile", data["profile"]),
                ("Server", data["server"]),
                ("Has API Key", data["has_api_key"]),
                ("Default", data["default_profile"]),
            ]),
        )
        return 0

    if args.command == "logout":
        saved = clear_profile_api_key(profile_name)
        emit_success(
            {
                "profile": saved.name,
                "server": saved.server,
                "has_api_key": False,
            },
            as_json=as_json,
            meta=_build_meta(args, server=saved.server),
            renderer=lambda data: print_key_values([
                ("Profile", data["profile"]),
                ("Server", data["server"]),
                ("Has API Key", data["has_api_key"]),
            ]),
        )
        return 0

    if args.command == "whoami":
        profile = get_profile(config, profile_name)
        server = args.server or profile.server
        api_key = args.api_key or profile.api_key
        emit_success(
            {
                "profile": profile.name,
                "server": server,
                "has_api_key": bool(api_key),
                "default_profile": config.get("default_profile"),
            },
            as_json=as_json,
            meta=_build_meta(args, server=server),
            renderer=lambda data: print_key_values([
                ("Profile", data["profile"]),
                ("Server", data["server"]),
                ("Has API Key", data["has_api_key"]),
                ("Default", data["default_profile"]),
            ]),
        )
        return 0

    raise CLIError("missing_command", "Missing auth subcommand", 2)


def handle_system(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "health":
        data = client.request("GET", "/livez", auth_required=False)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_key_values([
                ("Status", data.get("status")),
            ]),
        )
        return 0

    if args.command == "queue":
        data = client.request("GET", "/api/system/queue")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_key_values([
                ("Running Fetches", data.get("running_fetches")),
                ("Running Processes", data.get("running_processes")),
                ("Fetch Concurrency", data.get("fetch_concurrency")),
                ("Sources Status Count", len(data.get("sources_status") or [])),
            ]),
        )
        return 0

    if args.command == "stats":
        data = client.request("GET", "/api/dashboard/stats")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_key_values([
                ("Today Total", data.get("today_total")),
                ("Unread Count", data.get("unread_count")),
                ("Active Sources", data.get("active_sources")),
                ("Favorited Count", data.get("favorited_count")),
            ]),
        )
        return 0

    raise CLIError("missing_command", "Missing system subcommand", 2)


def handle_sources(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "list":
        params = {
            "page": args.page,
            "page_size": args.page_size,
            "type": args.type,
            "category_id": args.category_id,
            "enabled": _optional_bool(args.enabled),
            "search": args.search,
        }
        data = client.request("GET", "/api/sources", params=params)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_table(
                data.get("items") or [],
                [
                    ("ID", "id"),
                    ("TYPE", "type"),
                    ("NAME", "name"),
                    ("STATUS", "fetch_status"),
                    ("STRATEGY", "fetch_strategy"),
                    ("ENABLED", "enabled"),
                ],
            ),
        )
        return 0

    if args.command == "get":
        data = client.request("GET", f"/api/sources/{args.id}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "add":
        payload = {
            "name": args.name,
            "type": args.type,
            "url": args.url,
            "extra_urls": args.extra_url,
            "category_id": args.category_id,
            "fetch_interval": args.fetch_interval,
            "enabled": not args.disabled,
            "priority": args.priority,
            "auth_required": args.auth_required,
            "auth_config_id": args.auth_config_id,
            "metadata": {},
        }
        data = client.request("POST", "/api/sources", json_body=payload)
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "delete":
        data = client.request("DELETE", f"/api/sources/{args.id}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "probe":
        data = client.request("POST", f"/api/sources/{args.id}/probe")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "probe-url":
        data = client.request(
            "POST",
            "/api/sources/probe",
            json_body={"url": args.url, "type": args.type},
        )
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "fetch":
        data = client.request("POST", f"/api/sources/{args.id}/fetch")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "fetch-all":
        data = client.request("POST", "/api/sources/fetch-all")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    raise CLIError("missing_command", "Missing sources subcommand", 2)


def handle_contents(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "list":
        params = {
            "source_id": args.source_id,
            "source_type": args.source_type,
            "category_id": args.category_id,
            "read_status": _optional_bool(args.read),
            "favorited": _optional_bool(args.favorited),
            "archived": _optional_bool(args.archived),
            "date_from": args.from_date,
            "date_to": args.to_date,
            "search": args.search,
            "page": args.page,
            "page_size": args.page_size,
        }
        data = client.request("GET", "/api/contents", params=params)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_table(
                data.get("items") or [],
                [
                    ("ID", "id"),
                    ("TYPE", "content_type"),
                    ("SOURCE", "source_name"),
                    ("TITLE", "title"),
                    ("READ", "read_status"),
                    ("FAV", "favorited"),
                ],
            ),
        )
        return 0

    if args.command == "get":
        data = client.request("GET", f"/api/contents/{args.id}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "search":
        data = client.request(
            "GET",
            "/api/contents",
            params={
                "search": args.query,
                "page": args.page,
                "page_size": args.page_size,
            },
        )
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_table(
                data.get("items") or [],
                [
                    ("ID", "id"),
                    ("SOURCE", "source_name"),
                    ("TITLE", "title"),
                    ("URL", "original_url"),
                ],
            ),
        )
        return 0

    if args.command == "cleanup-low-signal":
        data = client.request(
            "POST",
            "/api/contents/cleanup-low-signal",
            params={
                "apply": args.apply,
                "source_id": args.source_id,
                "preview_limit": args.preview_limit,
            },
        )
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=_render_cleanup_report,
        )
        return 0

    raise CLIError("missing_command", "Missing contents subcommand", 2)


def handle_settings(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "get":
        data = client.request("GET", "/api/configs/settings")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0
    if args.command == "limits":
        data = client.request("GET", "/api/configs/settings")
        limits = (data or {}).get("limits") or {}
        payload = {
            "max_sources": limits.get("max_sources"),
            "max_digest_candidates": limits.get("max_digest_candidates"),
            "max_hourly_digest_input_items": limits.get("max_hourly_digest_input_items"),
        }
        emit_success(
            payload,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values([
                ("Max Sources", d.get("max_sources")),
                ("Max Digest Candidates", d.get("max_digest_candidates")),
                ("Max Hourly Digest Input Items", d.get("max_hourly_digest_input_items")),
            ]),
        )
        return 0
    raise CLIError("missing_command", "Missing settings subcommand", 2)


def handle_digest(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "latest":
        data = client.request("GET", "/api/digest")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0
    if args.command == "day":
        data = client.request("GET", "/api/digest", params={"date": args.date})
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0
    raise CLIError("missing_command", "Missing digest subcommand", 2)


def _resolve_profile(args) -> dict[str, Any]:
    config = load_config()
    profile = get_profile(config, args.profile)
    server = args.server or _env_or_profile_server(config, profile.name)
    api_key = args.api_key or _env_or_profile_api_key(config, profile.name)
    timeout = args.timeout or _env_int("PIM_TIMEOUT") or profile.timeout or 30
    return {
        "profile": profile.name,
        "server": server,
        "api_key": api_key,
        "timeout": timeout,
    }


def _env_or_profile_server(config: dict[str, Any], profile_name: str) -> str:
    return (
        _env_value("PIM_SERVER")
        or get_profile(config, profile_name).server
        or DEFAULT_SERVER
    )


def _env_or_profile_api_key(config: dict[str, Any], profile_name: str) -> str | None:
    return _env_value("PIM_API_KEY") or get_profile(config, profile_name).api_key


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _env_int(name: str) -> int | None:
    value = _env_value(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _build_meta(args, *, server: str | None = None) -> dict[str, Any]:
    return {
        "server": server or getattr(args, "server", None) or _env_value("PIM_SERVER") or DEFAULT_SERVER,
        "cli_version": __version__,
        "profile": getattr(args, "profile", None),
    }


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "true"


def _render_cleanup_report(data: dict[str, Any]) -> None:
    print_key_values(
        [
            ("Mode", data.get("mode")),
            ("Scanned", data.get("scanned_count")),
            ("Matched", data.get("matched_count")),
            ("Deleted", data.get("deleted_count")),
            ("By Reason", data.get("by_reason")),
            ("By Source", data.get("by_source")),
        ]
    )
    preview = data.get("preview") or []
    if preview:
        print()
        print_table(
            preview,
            [
                ("ID", "id"),
                ("REASON", "reason"),
                ("SOURCE", "source_name"),
                ("TITLE", "title"),
                ("URL", "url"),
            ],
        )


def _normalize_global_args(argv: list[str]) -> list[str]:
    flags_without_values = {"--json", "--quiet", "--version"}
    flags_with_values = {"--server", "--api-key", "--profile", "--output", "--timeout"}
    extracted: list[str] = []
    remaining: list[str] = []
    idx = 0

    while idx < len(argv):
        token = argv[idx]
        if token in flags_without_values:
            extracted.append(token)
            idx += 1
            continue
        if token in flags_with_values:
            extracted.append(token)
            if idx + 1 >= len(argv):
                return argv
            extracted.append(argv[idx + 1])
            idx += 2
            continue
        remaining.append(token)
        idx += 1

    return extracted + remaining


if __name__ == "__main__":
    raise SystemExit(main())
