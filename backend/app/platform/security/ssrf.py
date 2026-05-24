"""SSRF protection utilities."""

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp

logger = logging.getLogger(__name__)
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
DEFAULT_MAX_PUBLIC_REDIRECTS = 5


@dataclass(frozen=True)
class PublicHttpTextResult:
    """HTTP text response returned after SSRF-checked manual redirects."""

    status: int
    url: str
    text: str


def _is_private_address(host: str) -> bool:
    """Check if a hostname or IP is private/loopback/reserved."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(
        [
            addr.is_private,
            addr.is_loopback,
            addr.is_link_local,
            addr.is_reserved,
            addr.is_multicast,
            addr.is_unspecified,
        ]
    )


async def _resolve_host_addresses(hostname: str, port: int) -> List[str]:
    """Resolve hostname to IP addresses."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        return list({info[4][0] for info in infos if info and info[4]})
    except socket.gaierror:
        return []


async def assert_public_http_target(url: str) -> None:
    """Raise ValueError if *url* points to a private/internal network target.

    Validates scheme, hostname and resolved IP addresses.  Use before any
    outbound HTTP request made on behalf of user-supplied URLs.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported scheme: {parsed.scheme or 'missing'}")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("missing hostname")
    if hostname == "localhost":
        raise ValueError("localhost is not allowed")
    if _is_private_address(hostname):
        raise ValueError(f"private address is not allowed: {hostname}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await _resolve_host_addresses(hostname, port)
    if not addresses:
        raise ValueError("hostname did not resolve")

    blocked = sorted(ip for ip in addresses if _is_private_address(ip))
    if blocked:
        raise ValueError(f"resolved to private address: {', '.join(blocked)}")


def hosts_match(url1: str, url2: str) -> bool:
    """Return True when both URLs resolve to the same hostname."""
    h1 = (urlparse(url1).hostname or "").lower().rstrip(".")
    h2 = (urlparse(url2).hostname or "").lower().rstrip(".")
    return h1 == h2


async def check_before_fetch(
    url: str,
    source_url: str = "",
    cookies: Optional[Dict[str, str]] = None,
) -> None:
    """Run SSRF check and optional cookie-host validation before an HTTP request.

    Raises ``ValueError`` if the URL targets a private network or if cookies
    would be sent cross-host.
    """
    await assert_public_http_target(url)
    if cookies and source_url and not hosts_match(url, source_url):
        raise ValueError(
            f"Cookie host mismatch: request to {urlparse(url).hostname} "
            f"but cookies belong to {urlparse(source_url).hostname}"
        )


async def fetch_public_http_text(
    session: aiohttp.ClientSession,
    url: str,
    *,
    method: str = "GET",
    source_url: str = "",
    validation_cookies: Optional[Dict[str, str]] = None,
    max_redirects: int = DEFAULT_MAX_PUBLIC_REDIRECTS,
    text_errors: str | None = None,
    read_body: bool = True,
    **request_kwargs,
) -> PublicHttpTextResult:
    """Fetch text while re-running SSRF and cookie-host checks on every redirect.

    aiohttp's automatic redirect handling does not re-enter PIM's SSRF guard.
    This helper disables automatic redirects, validates each target URL before
    the next request, and returns the first non-redirect response.
    """
    requester = getattr(session, method.lower())
    current_url = url
    for _ in range(max_redirects + 1):
        await check_before_fetch(
            current_url,
            source_url=source_url,
            cookies=validation_cookies,
        )
        kwargs = dict(request_kwargs)
        kwargs["allow_redirects"] = False
        async with requester(current_url, **kwargs) as response:
            if response.status in REDIRECT_STATUSES:
                location = (response.headers.get("Location") or "").strip()
                if not location:
                    return PublicHttpTextResult(response.status, str(response.url), "")
                current_url = urljoin(str(response.url), location)
                continue
            if read_body:
                if text_errors is None:
                    body = await response.text()
                else:
                    body = await response.text(errors=text_errors)
            else:
                body = ""
            return PublicHttpTextResult(response.status, str(response.url), body)
    raise ValueError(f"redirect limit exceeded for {url}")
