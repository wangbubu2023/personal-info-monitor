"""HTTP client for pimctl."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class CLIError(Exception):
    """Structured CLI error."""

    def __init__(self, code: str, message: str, exit_code: int = 1, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details


@dataclass
class APIClient:
    server: str
    api_key: str | None = None
    timeout: int = 30

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        auth_required: bool = True,
    ) -> Any:
        url = self._build_url(path, params=params)
        headers = {
            "Accept": "application/json",
        }
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if auth_required:
            if not self.api_key:
                raise CLIError("auth_required", "Missing API key. Run `pimctl auth login` or pass `--api-key`.", 3)
            headers["X-API-Key"] = self.api_key

        req = urllib.request.Request(url=url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return _decode_response(resp.read(), resp.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as exc:
            payload = _decode_response(exc.read(), exc.headers.get("Content-Type", ""))
            detail = _extract_error_message(payload) or f"HTTP {exc.code}"
            raise CLIError(
                _map_http_code_to_error(exc.code),
                detail,
                _map_http_code_to_exit_code(exc.code),
                details=payload,
            ) from exc
        except urllib.error.URLError as exc:
            raise CLIError("server_unreachable", f"Failed to reach server {self.server}: {exc.reason}", 5) from exc
        except socket.timeout as exc:
            raise CLIError("timeout", f"Request timed out after {self.timeout}s", 5) from exc

    def _build_url(self, path: str, *, params: dict[str, Any] | None = None) -> str:
        base = self.server.rstrip("/")
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{base}{path}"
        if not params:
            return url
        query_items: list[tuple[str, str]] = []
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    query_items.append((key, _normalize_query_value(item)))
            else:
                query_items.append((key, _normalize_query_value(value)))
        if not query_items:
            return url
        return f"{url}?{urllib.parse.urlencode(query_items)}"


def _normalize_query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _decode_response(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if "application/json" in (content_type or ""):
        return json.loads(text)
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return text
    return text


def _extract_error_message(payload: Any) -> str | None:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            return str(detail.get("message") or detail)
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return None


def _map_http_code_to_error(status: int) -> str:
    return {
        400: "bad_request",
        401: "auth_failed",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
    }.get(status, "request_failed")


def _map_http_code_to_exit_code(status: int) -> int:
    return {
        401: 3,
        404: 4,
    }.get(status, 1)
