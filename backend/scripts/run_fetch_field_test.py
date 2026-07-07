#!/usr/bin/env python3
"""Run dry-run diagnostics across real sources and write a field-test report."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

backend_dir = Path(__file__).resolve().parents[1]
repo_root = backend_dir.parent
DEFAULT_REPORT = Path.home() / ".pim" / "data" / "reports" / "fetch-field-test.md"
DEFAULT_SERVER = "http://127.0.0.1:8000"
RUNTIME_SECRETS = Path.home() / ".pim" / "data" / "runtime-secrets.json"

RequestFn = Callable[[str, str, str | None, dict[str, Any] | None], Any]


class FieldTestError(RuntimeError):
    """Raised when the field-test runner cannot talk to PIM."""


def read_runtime_api_key(path: Path = RUNTIME_SECRETS) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    key = str(payload.get("PIM_API_KEY") or "").strip()
    return key or None


def request_json(
    method: str,
    server: str,
    path: str,
    api_key: str | None,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 60,
) -> Any:
    base = server.rstrip("/")
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    if query:
        url = f"{url}?{query}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url=url, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise FieldTestError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc
    except (urllib.error.URLError, socket.timeout) as exc:
        raise FieldTestError(f"{method} {path} failed: {exc}") from exc
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise FieldTestError(f"{method} {path} returned non-JSON response") from exc


def select_sources(
    list_payload: dict[str, Any],
    *,
    limit: int,
    source_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    exclude_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    items = list_payload.get("items") if isinstance(list_payload, dict) else []
    sources = [item for item in items if isinstance(item, dict)]
    if source_ids:
        wanted = {str(item) for item in source_ids}
        sources = [source for source in sources if str(source.get("id")) in wanted]
    if source_types:
        wanted_types = {str(item).lower() for item in source_types}
        sources = [source for source in sources if str(source.get("type") or "").lower() in wanted_types]
    if exclude_types:
        blocked_types = {str(item).lower() for item in exclude_types}
        sources = [source for source in sources if str(source.get("type") or "").lower() not in blocked_types]
    return sources[: max(0, limit)]


def _stage_count(payload: dict[str, Any], stage: str, key: str) -> int:
    stages = payload.get("stages") if isinstance(payload.get("stages"), dict) else {}
    data = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
    try:
        return int(data.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _format_skip_summary(summary: dict[str, Any]) -> str:
    parts = []
    for key, value in sorted(summary.items()):
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            parts.append(f"{key}={count}")
    return ", ".join(parts)


def summarize_source(source: dict[str, Any], dry_run: dict[str, Any] | None = None, *, error: str | None = None) -> dict[str, Any]:
    dry_run = dry_run if isinstance(dry_run, dict) else {}
    warnings = dry_run.get("warnings") if isinstance(dry_run.get("warnings"), dict) else {}
    samples = dry_run.get("samples") if isinstance(dry_run.get("samples"), dict) else {}
    would_store_samples = samples.get("would_store") if isinstance(samples.get("would_store"), list) else []
    raw_samples = samples.get("raw") if isinstance(samples.get("raw"), list) else []
    diagnostics = dry_run.get("diagnostics") if isinstance(dry_run.get("diagnostics"), dict) else {}
    skip_summary = diagnostics.get("normalizer_skip_summary")
    skip_summary_text = _format_skip_summary(skip_summary if isinstance(skip_summary, dict) else {})
    collected = _stage_count(dry_run, "collector", "count")
    valid = _stage_count(dry_run, "normalizer", "valid_count")
    stale_skipped = _stage_count(dry_run, "normalizer", "stale_skipped")
    other_skipped = _stage_count(dry_run, "normalizer", "other_skipped")
    would_store = _stage_count(dry_run, "builder", "would_store_count")
    warning = str(warnings.get("merged") or warnings.get("primary") or "").strip()
    if not warning and skip_summary_text and collected and not valid:
        warning = f"normalizer skipped all items ({skip_summary_text})"
    elif not warning and collected and not valid:
        skipped_parts = []
        if stale_skipped:
            skipped_parts.append(f"stale={stale_skipped}")
        if other_skipped:
            skipped_parts.append(f"other={other_skipped}")
        if skipped_parts:
            warning = f"normalizer skipped all items ({', '.join(skipped_parts)})"

    if error:
        status = "error"
    elif warning:
        status = "warning"
    elif would_store > 0:
        status = "ok"
    elif collected == 0:
        status = "empty"
    else:
        status = "warning"

    sample_titles = []
    display_samples = would_store_samples if would_store_samples else raw_samples
    for sample in display_samples[:3]:
        if isinstance(sample, dict):
            title = str(sample.get("title") or sample.get("url") or "").strip()
            if title:
                sample_titles.append(title)

    return {
        "source_id": str(source.get("id") or dry_run.get("source_id") or ""),
        "source_name": str(source.get("name") or dry_run.get("source_name") or ""),
        "source_type": str(source.get("type") or dry_run.get("source_type") or ""),
        "enabled": bool(source.get("enabled", True)),
        "status": status,
        "collected": collected,
        "valid": valid,
        "would_store": would_store,
        "warning": warning,
        "error": error or "",
        "normalizer_skip_summary": skip_summary if isinstance(skip_summary, dict) else {},
        "samples": sample_titles,
    }


def compute_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(rows),
        "ok": sum(1 for row in rows if row["status"] == "ok"),
        "warning": sum(1 for row in rows if row["status"] == "warning"),
        "empty": sum(1 for row in rows if row["status"] == "empty"),
        "error": sum(1 for row in rows if row["status"] == "error"),
        "would_store_total": sum(int(row.get("would_store") or 0) for row in rows),
    }


def run_field_test(
    *,
    server: str,
    api_key: str | None,
    limit: int = 20,
    sample_limit: int = 5,
    source_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    exclude_types: list[str] | None = None,
    request_fn: RequestFn | None = None,
) -> dict[str, Any]:
    request = request_fn or (lambda method, path, key, params=None: request_json(method, server, path, key, params))
    page_size = 200 if source_ids or source_types or exclude_types else max(limit, 1)
    list_payload = request(
        "GET",
        "/api/sources",
        api_key,
        {"enabled": "true", "page": 1, "page_size": min(200, page_size)},
    )
    sources = select_sources(
        list_payload,
        limit=limit,
        source_ids=source_ids,
        source_types=source_types,
        exclude_types=exclude_types,
    )
    rows: list[dict[str, Any]] = []
    for source in sources:
        source_id = str(source.get("id") or "")
        if not source_id:
            rows.append(summarize_source(source, error="missing source id"))
            continue
        try:
            dry_run = request("POST", f"/api/sources/{source_id}/dry-run", api_key, {"sample_limit": sample_limit})
            rows.append(summarize_source(source, dry_run))
        except (FieldTestError, RuntimeError, OSError, ValueError) as exc:
            rows.append(summarize_source(source, error=str(exc)))

    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "server": server,
        "limit": limit,
        "sample_limit": sample_limit,
        "summary": compute_summary(rows),
        "rows": rows,
    }


def _cell(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_markdown_report(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    lines = [
        "# PIM 20-Source Fetch Field Test",
        "",
        f"- Ran at: `{_cell(result.get('ran_at'))}`",
        f"- Server: `{_cell(result.get('server'))}`",
        f"- Source count: `{summary.get('total', 0)}`",
        f"- OK / warning / empty / error: `{summary.get('ok', 0)} / {summary.get('warning', 0)} / {summary.get('empty', 0)} / {summary.get('error', 0)}`",
        f"- Would-store total: `{summary.get('would_store_total', 0)}`",
        "",
        "| # | Source | Type | Status | Collected | Valid | Would Store | Warning/Error | Samples |",
        "|---:|---|---|---|---:|---:|---:|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        note = row.get("error") or row.get("warning") or ""
        samples = "; ".join(row.get("samples") or [])
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _cell(row.get("source_name") or row.get("source_id")),
                    _cell(row.get("source_type")),
                    _cell(row.get("status")),
                    _cell(row.get("collected")),
                    _cell(row.get("valid")),
                    _cell(row.get("would_store")),
                    _cell(note),
                    _cell(samples),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This report is generated from `/api/sources/{id}/dry-run`; it does not write content rows.",
            "- `empty` and `warning` rows need manual review against the source page and current publishing cadence.",
            "- Auth-required sources may need a fresh Auth Bundle or browser session before rerunning.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(result: dict[str, Any], *, report_path: Path, json_path: Path | None = None) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown_report(result), encoding="utf-8")
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run dry-run diagnostics across real PIM sources")
    parser.add_argument("--server", default=os.environ.get("PIM_SERVER") or DEFAULT_SERVER)
    parser.add_argument("--api-key", default=os.environ.get("PIM_API_KEY") or read_runtime_api_key())
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--source-type", action="append", default=[], help="Only include sources of this type")
    parser.add_argument("--exclude-type", action="append", default=[], help="Exclude sources of this type")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--print", action="store_true", help="Print the Markdown report to stdout")
    args = parser.parse_args()

    if not args.api_key:
        print("Missing API key. Pass --api-key or set PIM_API_KEY.", file=sys.stderr)
        return 3

    result = run_field_test(
        server=args.server,
        api_key=args.api_key,
        limit=args.limit,
        sample_limit=args.sample_limit,
        source_ids=args.source_id or None,
        source_types=args.source_type or None,
        exclude_types=args.exclude_type or None,
    )
    write_outputs(result, report_path=args.output, json_path=args.json_output)
    if args.print:
        print(render_markdown_report(result))
    else:
        print(f"Wrote {args.output}")
        if args.json_output:
            print(f"Wrote {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
