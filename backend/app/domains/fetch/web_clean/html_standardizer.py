"""Safe DOM normalization before any main-content extractor runs."""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .safety import selector_error

_DROP_TAGS = ("script", "style", "template", "iframe", "object", "embed", "applet")
_NOISE_TAGS = ("nav", "header", "footer", "aside", "form")
_NOISE_RE = re.compile(
    r"(?:^|[-_\s])(?:ad|ads|advert|advertisement|banner|cookie|comment|"
    r"footer|menu|nav|newsletter|promo|recommend|related|share|sidebar|social)(?:$|[-_\s])",
    re.IGNORECASE,
)
_URL_ATTR_SCHEMES = {
    "href": frozenset({"http", "https", "mailto", "tel", ""}),
    "cite": frozenset({"http", "https", ""}),
    "src": frozenset({"http", "https", ""}),
    "poster": frozenset({"http", "https", ""}),
}
_LAZY_SRC_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-url")
_LAZY_SRCSET_ATTRS = ("data-srcset", "data-lazy-srcset")
_HIDDEN_STYLE_RE = re.compile(
    r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)(?:\s*!important)?\s*(?:;|$)",
    re.IGNORECASE,
)
_PLACEHOLDER_SRC_RE = re.compile(
    r"^(?:#|about:blank|data:image/(?:gif|png);base64,|javascript:)",
    re.IGNORECASE,
)
_MAX_URL_CHARS = 2_048


@dataclass(frozen=True)
class StandardizedHTML:
    html: str
    trace: dict[str, object]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def _safe_url(
    value: str,
    base_url: str,
    *,
    allowed_schemes: frozenset[str],
    allow_fragment: bool = False,
) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > _MAX_URL_CHARS:
        return ""
    if raw.startswith("#"):
        if not allow_fragment:
            return ""
        return raw
    absolute = urljoin(base_url, raw)
    parsed = urlparse(absolute)
    return (
        absolute
        if parsed.scheme.lower() in allowed_schemes and len(absolute) <= _MAX_URL_CHARS
        else ""
    )


def _safe_base_url(soup: BeautifulSoup, page_url: str) -> str:
    safe_page_url = str(page_url or "")[:_MAX_URL_CHARS]
    base = soup.find("base", href=True)
    if not base:
        return safe_page_url
    candidate = urljoin(safe_page_url, str(base.get("href") or "").strip())
    return (
        candidate
        if urlparse(candidate).scheme.lower() in {"http", "https"} and len(candidate) <= _MAX_URL_CHARS
        else safe_page_url
    )


def _bounded_non_negative_int(value: object, *, maximum: int = 128) -> int:
    try:
        parsed = int(str(value or "0"))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(parsed, maximum))


def _absolutize_srcset(value: str, base_url: str) -> str:
    items: list[str] = []
    for item in str(value or "").split(","):
        parts = item.strip().split()
        if not parts:
            continue
        url = _safe_url(
            parts[0],
            base_url,
            allowed_schemes=frozenset({"http", "https", ""}),
        )
        if url:
            items.append(" ".join([url, *parts[1:]]))
    return ", ".join(items)


def _materialize_noscript(soup: BeautifulSoup) -> int:
    materialized = 0
    for node in list(soup.find_all("noscript")):
        fragment_html = html_lib.unescape(node.decode_contents())
        fragment = BeautifulSoup(fragment_html, "lxml")
        container = fragment.body or fragment
        children = list(container.contents)
        for child in children:
            node.insert_before(child)
        node.decompose()
        materialized += 1
    return materialized


def _promote_lazy_media(soup: BeautifulSoup) -> int:
    promoted = 0
    for node in soup.find_all(("img", "source", "video", "audio")):
        current = str(node.get("src") or "").strip()
        if not current or _PLACEHOLDER_SRC_RE.match(current):
            for attr in _LAZY_SRC_ATTRS:
                lazy = str(node.get(attr) or "").strip()
                if lazy:
                    node["src"] = lazy
                    promoted += 1
                    break
        if not str(node.get("srcset") or "").strip():
            for attr in _LAZY_SRCSET_ATTRS:
                lazy_srcset = str(node.get(attr) or "").strip()
                if lazy_srcset:
                    node["srcset"] = lazy_srcset
                    promoted += 1
                    break
    return promoted


def standardize_html(
    html: str,
    *,
    base_url: str = "",
    remove_selectors: Iterable[str] = (),
    preserve_noise: bool = False,
    max_html_bytes: int = 3_000_000,
) -> StandardizedHTML:
    original = str(html or "")
    if max_html_bytes <= 0:
        raise ValueError("max_html_bytes must be positive")
    encoded = original.encode("utf-8", errors="ignore")
    truncated = len(encoded) > max_html_bytes
    raw = encoded[:max_html_bytes].decode("utf-8", errors="ignore") if truncated else original
    soup = BeautifulSoup(raw, "lxml")
    effective_base_url = _safe_base_url(soup, base_url)
    document_base_applied = effective_base_url != str(base_url or "")[:_MAX_URL_CHARS]
    root = soup.html
    marker_count = len(soup.select("[data-pim-shadow-root]"))
    stamped_count = _bounded_non_negative_int(
        root.get("data-pim-shadow-materialized-count") if root else 0
    )
    shadow_materialized_count = max(marker_count, stamped_count)
    shadow_timeout = bool(root and str(root.get("data-pim-shadow-timeout") or "").lower() == "true")
    removed_elements = 0
    removed_attributes = 0
    absolutized_urls = 0
    invalid_selectors: list[str] = []
    materialized_noscript = _materialize_noscript(soup)
    promoted_lazy_media = _promote_lazy_media(soup)

    for base in list(soup.find_all("base")):
        base.decompose()
        removed_elements += 1
    for node in list(soup.find_all(_DROP_TAGS)):
        node.decompose()
        removed_elements += 1
    for node in list(soup.select("[hidden], [aria-hidden='true'], [aria-hidden='1']")):
        node.decompose()
        removed_elements += 1
    for node in list(soup.find_all(style=True)):
        if _HIDDEN_STYLE_RE.search(str(node.get("style") or "")):
            node.decompose()
            removed_elements += 1
    if not preserve_noise:
        for node in list(soup.find_all(_NOISE_TAGS)):
            node.decompose()
            removed_elements += 1
        for node in list(soup.find_all(True)):
            # A parent removed earlier in this snapshot can leave descendants
            # decomposed with ``attrs is None``; skip those stale nodes.
            if node.attrs is None:
                continue
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

    for raw_selector in remove_selectors:
        selector = str(raw_selector or "").strip()
        error = selector_error(selector)
        if error:
            invalid_selectors.append(f"{selector[:240]}: {error}"[:300])
            continue
        for node in list(soup.select(selector)):
            node.decompose()
            removed_elements += 1

    for node in soup.find_all(True):
        for attr in list(node.attrs):
            lower = str(attr).lower()
            if lower == "style" or lower.startswith("on"):
                del node.attrs[attr]
                removed_attributes += 1
        for attr, schemes in _URL_ATTR_SCHEMES.items():
            if node.has_attr(attr):
                before = str(node.get(attr) or "")
                after = _safe_url(
                    before,
                    effective_base_url,
                    allowed_schemes=schemes,
                    allow_fragment=attr == "href",
                )
                if after:
                    node[attr] = after
                    absolutized_urls += int(after != before)
                else:
                    del node.attrs[attr]
                    removed_attributes += 1
        if node.has_attr("srcset"):
            before = str(node.get("srcset") or "")
            after = _absolutize_srcset(before, effective_base_url)
            if after:
                node["srcset"] = after
                absolutized_urls += int(after != before)
            else:
                del node.attrs["srcset"]
                removed_attributes += 1

    for node in soup.select("[data-pim-shadow-root]"):
        if node.has_attr("data-pim-shadow-root"):
            del node.attrs["data-pim-shadow-root"]
            removed_attributes += 1
    if soup.html:
        for attr in ("data-pim-shadow-materialized-count", "data-pim-shadow-timeout"):
            if soup.html.has_attr(attr):
                del soup.html.attrs[attr]
                removed_attributes += 1
    output = str(soup)
    max_output_bytes = max_html_bytes * 2
    output_encoded = output.encode("utf-8", errors="ignore")
    output_truncated = len(output_encoded) > max_output_bytes
    if output_truncated:
        # Reparse the bounded prefix so downstream extractors receive repaired
        # HTML instead of a raw mid-tag byte slice.
        bounded = output_encoded[:max_output_bytes].decode("utf-8", errors="ignore")
        output = str(BeautifulSoup(bounded, "lxml"))
    return StandardizedHTML(
        html=output,
        trace={
            "input_chars": len(original),
            "output_chars": len(output),
            "input_sha256": _sha256(original),
            "output_sha256": _sha256(output),
            "truncated": truncated,
            "output_truncated": output_truncated,
            "removed_elements": removed_elements,
            "removed_attributes": removed_attributes,
            "absolutized_urls": absolutized_urls,
            "promoted_lazy_media": promoted_lazy_media,
            "materialized_noscript": materialized_noscript,
            "invalid_selectors": invalid_selectors,
            "document_base_applied": document_base_applied,
            "shadow_materialized_count": shadow_materialized_count,
            "shadow_timeout": shadow_timeout,
            "shadow": shadow_materialized_count > 0,
        },
    )
