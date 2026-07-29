"""Shared complexity guards for user-configurable Web Clean expressions."""

from __future__ import annotations

import re

import regex as bounded_regex
from soupsieve import compile as compile_selector
from soupsieve.util import SelectorSyntaxError

MAX_SELECTOR_LENGTH = 256
MAX_SELECTOR_COMBINATORS = 12
MAX_SELECTOR_TOKENS = 64
MAX_REGEX_LENGTH = 256
REGEX_TIMEOUT_SECONDS = 0.05

_SELECTOR_TOKEN_RE = re.compile(r"[#.:[\]()=*~|^$>+]|\s+")
_FORBIDDEN_SELECTOR_RE = re.compile(
    r":(?:has|contains|-soup-contains|-soup-contains-own)\s*\(",
    re.IGNORECASE,
)


def selector_error(selector: str) -> str | None:
    """Return a readable validation error for unsafe/invalid selectors."""
    value = str(selector or "").strip()
    if not value:
        return "selector is empty"
    token_count = len(_SELECTOR_TOKEN_RE.findall(value))
    descendant_combinators = len(re.findall(r"\s+", value))
    combinator_count = descendant_combinators + sum(
        value.count(token) for token in (">", "+", "~", ",")
    )
    if _FORBIDDEN_SELECTOR_RE.search(value):
        return "selector uses a disallowed expensive pseudo-class"
    if (
        len(value) > MAX_SELECTOR_LENGTH
        or token_count > MAX_SELECTOR_TOKENS
        or combinator_count > MAX_SELECTOR_COMBINATORS
    ):
        return "selector is too complex or too long"
    try:
        compile_selector(value)
    except (SelectorSyntaxError, ValueError, TypeError):
        return "invalid selector syntax"
    return None


def compile_bounded_regex(pattern: str):
    """Compile a regex after enforcing the shared length limit."""
    value = str(pattern or "")
    if len(value) > MAX_REGEX_LENGTH:
        raise ValueError("regex is too long")
    try:
        return bounded_regex.compile(value)
    except bounded_regex.error as exc:
        raise ValueError(f"invalid regex: {exc}") from exc


def bounded_regex_search(pattern: str, value: str) -> bool:
    """Execute a configured regex with a deterministic timeout."""
    try:
        compiled = compile_bounded_regex(pattern)
        return compiled.search(str(value or ""), timeout=REGEX_TIMEOUT_SECONDS) is not None
    except (TimeoutError, ValueError, TypeError):
        return False
