"""Source/host web-clean template validation, matching and variable rendering."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Mapping
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from soupsieve.util import SelectorSyntaxError

from .contracts import TemplateSpec
from .filters import FilterValidationError, apply_filters, validate_filters
from .structured import schema_value

MAX_SELECTOR_LENGTH = 256
MAX_REGEX_LENGTH = 256
VARIABLE_PREFIXES = ("preset:", "meta:", "selector:", "selectorHtml:", "schema:")


class TemplateValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)


def _coerce_template(value: Mapping[str, Any]) -> TemplateSpec:
    return TemplateSpec(
        id=str(value.get("id") or "").strip(),
        triggers=tuple(str(item) for item in value.get("triggers", []) if str(item).strip()),
        article_html=str(value["article_html"]).strip() if value.get("article_html") else None,
        title=str(value["title"]).strip() if value.get("title") else None,
        author=str(value["author"]).strip() if value.get("author") else None,
        published=str(value["published"]).strip() if value.get("published") else None,
        remove_html=tuple(str(item) for item in value.get("remove_html", []) if str(item).strip()),
        markdown_filters=tuple(str(item) for item in value.get("markdown_filters", []) if str(item).strip()),
        notes=str(value["notes"]).strip() if value.get("notes") else None,
    )


def _selector_error(selector: str) -> str | None:
    if len(selector) > MAX_SELECTOR_LENGTH or selector.count(" ") > 12:
        return "selector is too long or complex"
    try:
        BeautifulSoup("<html></html>", "lxml").select(selector)
    except (SelectorSyntaxError, ValueError, TypeError) as exc:
        return f"invalid selector: {exc}"
    return None


def validate_template(value: Mapping[str, Any]) -> TemplateSpec:
    spec = _coerce_template(value)
    errors: list[str] = []
    if not spec.id or len(spec.id) > 120 or not re.fullmatch(r"[A-Za-z0-9._-]+", spec.id):
        errors.append("id must contain only letters, numbers, '.', '_' or '-'")
    for trigger in spec.triggers:
        if trigger.startswith("regex:"):
            pattern = trigger[6:]
            if len(pattern) > MAX_REGEX_LENGTH:
                errors.append("trigger regex is too long")
            else:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append(f"invalid trigger regex: {exc}")
        elif trigger.startswith("schema:@") or trigger.startswith(("http://", "https://")):
            continue
        else:
            errors.append(f"unsupported trigger: {trigger}")
    for field_name in ("article_html", "title", "author", "published"):
        expression = getattr(spec, field_name)
        if not expression:
            continue
        variable = expression.split("|", 1)[0].strip()
        if not variable.startswith(VARIABLE_PREFIXES):
            errors.append(f"{field_name} uses an unknown variable: {variable}")
        if variable.startswith(("selector:", "selectorHtml:")):
            selector = variable.split(":", 1)[1]
            error = _selector_error(selector)
            if error:
                errors.append(f"{field_name}: {error}")
        try:
            validate_filters(expression.split("|", 1)[1] if "|" in expression else ())
        except FilterValidationError as exc:
            errors.append(f"{field_name}: {exc}")
    for selector in spec.remove_html:
        error = _selector_error(selector)
        if error:
            errors.append(f"remove_html: {error}")
    try:
        validate_filters(spec.markdown_filters)
    except FilterValidationError as exc:
        errors.append(f"markdown_filters: {exc}")
    if errors:
        raise TemplateValidationError(errors)
    return spec


def template_matches(spec: TemplateSpec, *, url: str, structured: dict[str, Any]) -> bool:
    if not spec.triggers:
        return True
    for trigger in spec.triggers:
        if trigger.startswith(("http://", "https://")) and url.startswith(trigger):
            return True
        if trigger.startswith("regex:") and re.search(trigger[6:], url):
            return True
        if trigger.startswith("schema:@") and schema_value(structured, trigger[7:]) is not None:
            return True
    return False


def _meta_value(soup: BeautifulSoup, key: str) -> Any:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return tag.get("content") if tag else None


def resolve_variable(
    expression: str,
    *,
    soup: BeautifulSoup,
    structured: dict[str, Any],
    presets: Mapping[str, Any],
    base_url: str,
) -> Any:
    variable, _, filters = expression.partition("|")
    kind, key = variable.strip().split(":", 1)
    if kind == "preset":
        value = presets.get(key)
    elif kind == "meta":
        value = _meta_value(soup, key)
    elif kind in {"selector", "selectorHtml"}:
        matches = soup.select(key)
        values = [str(node) if kind == "selectorHtml" else node.get_text(" ", strip=True) for node in matches]
        value = values[0] if len(values) == 1 else values
    elif kind == "schema":
        value = schema_value(structured, key)
    else:
        raise TemplateValidationError([f"unknown variable type: {kind}"])
    return apply_filters(value, filters, base_url=base_url) if filters else value


def render_template(
    spec: TemplateSpec,
    *,
    html: str,
    url: str,
    structured: dict[str, Any],
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    presets = {
        "title": structured.get("title"),
        "author": structured.get("author"),
        "published": structured.get("published_time_raw"),
        "canonical": structured.get("canonical_url"),
        "site_name": structured.get("site_name"),
    }
    output: dict[str, Any] = {"template_id": spec.id}
    for field_name in ("article_html", "title", "author", "published"):
        expression = getattr(spec, field_name)
        if expression:
            output[field_name] = resolve_variable(
                expression,
                soup=soup,
                structured=structured,
                presets=presets,
                base_url=url,
            )
    return output


def template_from_metadata(metadata: Mapping[str, Any] | None) -> TemplateSpec | None:
    raw = metadata.get("web_clean_template") if isinstance(metadata, Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    return validate_template(raw)


def template_dict(spec: TemplateSpec) -> dict[str, Any]:
    return asdict(spec)
