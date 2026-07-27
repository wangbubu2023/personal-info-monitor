"""Helpers for generating one-click Web bootstrap URLs."""

from __future__ import annotations

from urllib.parse import quote, urlsplit


class BootstrapUrlError(ValueError):
    """Raised when bootstrap URL CLI input is invalid."""


def resolve_bootstrap_host(
    args: list[str],
    *,
    configured_public_url: str | None,
) -> tuple[str, bool]:
    """Resolve and validate the browser-facing host from CLI/config input."""
    explicit_origin = None
    if "--origin" in args:
        idx = args.index("--origin")
        if idx + 1 >= len(args) or not args[idx + 1].strip():
            raise BootstrapUrlError(
                "Usage: ./pim bootstrap-url [--origin https://your-domain.com]"
            )
        explicit_origin = args[idx + 1].strip()

    host = explicit_origin or configured_public_url or "http://localhost:8000"
    parsed_host = urlsplit(host)
    try:
        parsed_host.port
    except ValueError as exc:
        raise BootstrapUrlError("Bootstrap URL contains an invalid port.") from exc
    if (
        parsed_host.scheme.lower() not in {"http", "https"}
        or not parsed_host.netloc
        or parsed_host.query
        or parsed_host.fragment
        or parsed_host.username
        or parsed_host.password
    ):
        raise BootstrapUrlError(
            "Bootstrap URL must be an absolute http(s) URL without credentials, "
            "query, or fragment."
        )
    return host, explicit_origin is not None


def build_bootstrap_url(host: str, code: str) -> str:
    """Place the short-lived code in a fragment so it is not sent in HTTP history."""
    return f"{host.rstrip('/')}/#bootstrap_code={quote(code, safe='')}"
