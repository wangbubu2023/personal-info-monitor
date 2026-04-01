"""Output helpers for pimctl."""

from __future__ import annotations

import json
import sys
from typing import Any


def emit_success(
    data: Any,
    *,
    as_json: bool,
    meta: dict[str, Any] | None = None,
    renderer=None,
) -> None:
    payload_meta = meta or {}
    if as_json:
        _print_json({
            "ok": True,
            "data": data,
            "error": None,
            "meta": payload_meta,
        })
        return

    if renderer is not None:
        renderer(data)
        return

    if isinstance(data, (dict, list)):
        _print_json(data)
    elif data is not None:
        print(data)


def emit_error(*, code: str, message: str, details: Any = None, meta: dict[str, Any] | None = None, as_json: bool) -> None:
    payload_meta = meta or {}
    if as_json:
        _print_json({
            "ok": False,
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "meta": payload_meta,
        }, stream=sys.stderr)
        return
    print(f"Error [{code}]: {message}", file=sys.stderr)


def print_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("No results.")
        return

    widths: list[int] = []
    for header, key in columns:
        width = len(header)
        for row in rows:
            value = _stringify(row.get(key))
            width = max(width, len(value))
        widths.append(width)

    header_line = "  ".join(header.ljust(widths[idx]) for idx, (header, _) in enumerate(columns))
    separator_line = "  ".join("-" * widths[idx] for idx, _ in enumerate(columns))
    print(header_line)
    print(separator_line)
    for row in rows:
        line = "  ".join(
            _stringify(row.get(key)).ljust(widths[idx])
            for idx, (_, key) in enumerate(columns)
        )
        print(line)


def print_key_values(items: list[tuple[str, Any]]) -> None:
    if not items:
        print("No data.")
        return
    width = max(len(label) for label, _ in items)
    for label, value in items:
        print(f"{label.ljust(width)}  {_stringify(value)}")


def _stringify(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _print_json(payload: Any, *, stream=None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream or sys.stdout)
