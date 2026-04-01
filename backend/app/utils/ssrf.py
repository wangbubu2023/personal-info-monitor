"""SSRF protection utilities."""

import asyncio
import ipaddress
import socket
import logging
from typing import List
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
