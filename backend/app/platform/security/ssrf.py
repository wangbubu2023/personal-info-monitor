"""SSRF protection utilities."""

import asyncio
import ipaddress
import socket
import logging
from typing import Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


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
