"""Small fail-closed filter DSL; deliberately contains no code execution."""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import PurePath
from typing import Any, Iterable

import regex as bounded_regex
from bs4 import BeautifulSoup

from .markdown import html_to_markdown
from .safety import compile_bounded_regex, selector_error

MAX_FILTERS = 24
MAX_FILTER_LENGTH = 512
MAX_OUTPUT_CHARS = 1_000_000
FILTER_ARITY: dict[str, tuple[int, int | None]] = {
    "trim": (0, 0),
    "replace": (2, 3),
    "strip_tags": (0, 0),
    "remove_html": (1, 1),
    "remove_attr": (1, 32),
    "strip_attr": (0, 1),
    "markdown": (0, 0),
    "date": (0, 1),
    "join": (0, 1),
    "list": (0, 0),
    "table": (0, 0),
    "safe_name": (0, 0),
}
ALLOWED_FILTERS = frozenset(
    {
        "trim", "replace", "strip_tags", "remove_html", "remove_attr", "strip_attr",
        "markdown", "date", "join", "list", "table", "safe_name",
    }
)


class FilterValidationError(ValueError):
    pass


def _split_pipeline(expression: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    for char in expression:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise FilterValidationError("filter has an unmatched ')'")
            current.append(char)
        elif char == "|" and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if quote or depth:
        raise FilterValidationError("filter has an unterminated quote or parenthesis")
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _parse_filter(token: str) -> tuple[str, tuple[Any, ...]]:
    if len(token) > MAX_FILTER_LENGTH:
        raise FilterValidationError("filter is too long")
    if ":(" in token and token.endswith(")"):
        name, remainder = token.split(":(", 1)
        raw_args = remainder[:-1]
    elif ":" in token and "(" not in token:
        name, raw = token.split(":", 1)
        raw_args = raw
    elif "(" in token:
        name, remainder = token.split("(", 1)
        if not remainder.endswith(")"):
            raise FilterValidationError(f"invalid filter syntax: {token}")
        raw_args = remainder[:-1]
    else:
        name, raw_args = token, ""
    name = name.strip()
    if name not in ALLOWED_FILTERS:
        raise FilterValidationError(f"unknown filter: {name}")
    if not raw_args.strip():
        return name, ()
    try:
        parsed = ast.literal_eval(f"({raw_args},)")
    except (SyntaxError, ValueError) as exc:
        raise FilterValidationError(f"invalid arguments for filter {name}") from exc
    return name, tuple(parsed)


def validate_filters(filters: str | Iterable[str]) -> tuple[str, ...]:
    expressions = [filters] if isinstance(filters, str) else list(filters)
    tokens: list[str] = []
    for expression in expressions:
        tokens.extend(_split_pipeline(str(expression)))
    if len(tokens) > MAX_FILTERS:
        raise FilterValidationError(f"at most {MAX_FILTERS} filters are allowed")
    for token in tokens:
        name, args = _parse_filter(token)
        minimum, maximum = FILTER_ARITY[name]
        if len(args) < minimum or (maximum is not None and len(args) > maximum):
            expected = str(minimum) if maximum == minimum else f"{minimum}..{maximum or 'many'}"
            raise FilterValidationError(f"{name} expects {expected} argument(s)")
        if name == "replace":
            try:
                compile_bounded_regex(str(args[0]))
            except (ValueError, TypeError) as exc:
                raise FilterValidationError(f"invalid replace pattern: {exc}") from exc
            flag_text = str(args[2]) if len(args) > 2 else ""
            if set(flag_text) - {"i", "m", "s"}:
                raise FilterValidationError("replace flags may only contain i, m, s")
        if name == "strip_attr" and args and not isinstance(args[0], (list, tuple)):
            raise FilterValidationError("strip_attr expects a list/tuple allowlist")
    return tuple(tokens)


def _remove_html(value: Any, selector: str) -> str:
    error = selector_error(selector)
    if error:
        raise FilterValidationError(f"CSS selector {error}")
    soup = BeautifulSoup(str(value or ""), "lxml")
    for node in list(soup.select(selector)):
        node.decompose()
    return str(soup)


def _remove_attrs(value: Any, attrs: Iterable[str] | None, *, keep: bool = False) -> str:
    soup = BeautifulSoup(str(value or ""), "lxml")
    names = {str(item).lower() for item in (attrs or [])}
    for node in soup.find_all(True):
        for attr in list(node.attrs):
            if (attr.lower() not in names) if keep else (not names or attr.lower() in names):
                del node.attrs[attr]
    return str(soup)


def _markdown_table(value: Any) -> str:
    rows = value if isinstance(value, list) else [value]
    if not rows:
        return ""
    if all(isinstance(row, dict) for row in rows):
        headers = list(dict.fromkeys(key for row in rows for key in row))
        body = [[row.get(header, "") for header in headers] for row in rows]
    else:
        body = [row if isinstance(row, (list, tuple)) else [row] for row in rows]
        width = max(len(row) for row in body)
        headers = [f"Column {index + 1}" for index in range(width)]
    escape = lambda cell: str(cell or "").replace("|", "\\|").replace("\n", " ")
    lines = [
        "| " + " | ".join(escape(item) for item in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(escape(item) for item in row) + " |" for row in body)
    return "\n".join(lines)


def apply_filters(value: Any, filters: str | Iterable[str], *, base_url: str = "") -> Any:
    result = value
    for token in validate_filters(filters):
        name, args = _parse_filter(token)
        if name == "trim":
            result = str(result or "").strip()
        elif name == "replace":
            pattern, replacement = str(args[0]), str(args[1])
            flags = 0
            flag_text = str(args[2]) if len(args) > 2 else ""
            if set(flag_text) - {"i", "m", "s"}:
                raise FilterValidationError("replace flags may only contain i, m, s")
            flags |= bounded_regex.IGNORECASE if "i" in flag_text else 0
            flags |= bounded_regex.MULTILINE if "m" in flag_text else 0
            flags |= bounded_regex.DOTALL if "s" in flag_text else 0
            try:
                result = bounded_regex.sub(
                    pattern,
                    replacement,
                    str(result or ""),
                    flags=flags,
                    timeout=0.05,
                )
            except TimeoutError as exc:
                raise FilterValidationError("replace execution timed out") from exc
            except bounded_regex.error as exc:
                raise FilterValidationError(f"replace execution failed: {exc}") from exc
        elif name == "strip_tags":
            result = BeautifulSoup(str(result or ""), "lxml").get_text(" ", strip=True)
        elif name == "remove_html":
            result = _remove_html(result, str(args[0]))
        elif name == "remove_attr":
            result = _remove_attrs(result, [str(item) for item in args])
        elif name == "strip_attr":
            keep = args[0] if args and isinstance(args[0], (list, tuple)) else ()
            result = _remove_attrs(result, keep, keep=True)
        elif name == "markdown":
            result = html_to_markdown(str(result or ""), base_url=base_url)
        elif name == "date":
            fmt = str(args[0]) if args else "%Y-%m-%d"
            for token, replacement in (
                ("YYYY", "%Y"), ("MM", "%m"), ("DD", "%d"),
                ("HH", "%H"), ("mm", "%M"), ("ss", "%S"),
            ):
                fmt = fmt.replace(token, replacement)
            if isinstance(result, datetime):
                parsed = result
            else:
                parsed = datetime.fromisoformat(str(result).replace("Z", "+00:00"))
            result = parsed.strftime(fmt)
        elif name == "join":
            separator = str(args[0]) if args else ", "
            result = separator.join(str(item) for item in (result if isinstance(result, list) else [result]))
        elif name == "list":
            result = "\n".join(f"- {item}" for item in (result if isinstance(result, list) else [result]))
        elif name == "table":
            result = _markdown_table(result)
        elif name == "safe_name":
            name_value = PurePath(str(result or "")).name
            result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name_value).strip(" .")[:180]
        if isinstance(result, str) and len(result) > MAX_OUTPUT_CHARS:
            raise FilterValidationError("filter output exceeds size limit")
    return result


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
