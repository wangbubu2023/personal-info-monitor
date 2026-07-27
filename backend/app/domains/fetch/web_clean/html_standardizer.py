"""Safe DOM normalization before any main-content extractor runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_DROP_TAGS = ("script", "style", "noscript", "template", "iframe")
_NOISE_TAGS = ("nav", "header", "footer", "aside", "form")
_NOISE_RE = re.compile(
    r"(?:^|[-_\s])(?:ad|ads|advert|advertisement|banner|cookie|comment|"
    r"footer|menu|nav|newsletter|promo|recommend|related|share|sidebar|social)(?:$|[-_\s])",
    re.IGNORECASE,
)
_URL_ATTRS = ("href", "src", "poster", "cite")
_SAFE_SCHEMES = {"http", "https", "mailto", "tel", ""}


@dataclass(frozen=True)
class StandardizedHTML:
    html: str
    trace: dict[str, object]


def _safe_url(value: str, base_url: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw.startswith(("#", "data:")):
        return raw
    absolute = urljoin(base_url, raw)
    parsed = urlparse(absolute)
    return absolute if parsed.scheme.lower() in _SAFE_SCHEMES else ""


def _absolutize_srcset(value: str, base_url: str) -> str:
    items: list[str] = []
    for item in str(value or "").split(","):
        parts = item.strip().split()
        if not parts:
            continue
        url = _safe_url(parts[0], base_url)
        if url:
            items.append(" ".join([url, *parts[1:]]))
    return ", ".join(items)


def standardize_html(
    html: str,
    *,
    base_url: str = "",
    remove_selectors: Iterable[str] = (),
    preserve_noise: bool = False,
    max_html_bytes: int = 3_000_000,
) -> StandardizedHTML:
    raw = str(html or "")
    truncated = len(raw.encode("utf-8", errors="ignore")) > max_html_bytes
    if truncated:
        raw = raw.encode("utf-8", errors="ignore")[:max_html_bytes].decode("utf-8", errors="ignore")
    soup = BeautifulSoup(raw, "lxml")
    shadow_materialized_count = len(soup.select("[data-pim-shadow-root]"))
    removed_elements = 0
    removed_attributes = 0
    absolutized_urls = 0
    invalid_selectors: list[str] = []

    for node in list(soup.find_all(_DROP_TAGS)):
        node.decompose()
        removed_elements += 1
    if not preserve_noise:
        for node in list(soup.find_all(_NOISE_TAGS)):
            node.decompose()
            removed_elements += 1
        for node in list(soup.find_all(True)):
            marker = " ".join(
                [
                    str(node.get("id") or ""),
                    *[str(value) for value in (node.get("class") or [])],
                    str(node.get("role") or ""),
                ]
            )
            if marker and _NOISE_RE.search(marker):
                node.decompose()
                removed_elements += 1

    for selector in remove_selectors:
        try:
            matches = list(soup.select(selector))
        except (ValueError, TypeError):
            invalid_selectors.append(str(selector))
            continue
        for node in matches:
            node.decompose()
            removed_elements += 1

    for node in soup.find_all(True):
        for attr in list(node.attrs):
            lower = str(attr).lower()
            if lower == "style" or lower.startswith("on"):
                del node.attrs[attr]
                removed_attributes += 1
        for attr in _URL_ATTRS:
            if node.has_attr(attr):
                before = str(node.get(attr) or "")
                after = _safe_url(before, base_url)
                if after:
                    node[attr] = after
                    absolutized_urls += int(after != before)
                else:
                    del node.attrs[attr]
                    removed_attributes += 1
        if node.has_attr("srcset"):
            before = str(node.get("srcset") or "")
            after = _absolutize_srcset(before, base_url)
            if after:
                node["srcset"] = after
                absolutized_urls += int(after != before)
            else:
                del node.attrs["srcset"]
                removed_attributes += 1

    return StandardizedHTML(
        html=str(soup),
        trace={
            "input_chars": len(html or ""),
            "output_chars": len(str(soup)),
            "truncated": truncated,
            "removed_elements": removed_elements,
            "removed_attributes": removed_attributes,
            "absolutized_urls": absolutized_urls,
            "invalid_selectors": invalid_selectors,
            "shadow_materialized_count": shadow_materialized_count,
            "shadow": shadow_materialized_count > 0,
        },
    )
