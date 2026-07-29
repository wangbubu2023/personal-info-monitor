"""Source/host web-clean template validation, matching and variable rendering."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Mapping

from bs4 import BeautifulSoup

from .contracts import TemplateSpec
from .filters import MAX_OUTPUT_CHARS, FilterValidationError, apply_filters, validate_filters
from .safety import MAX_REGEX_LENGTH, bounded_regex_search, compile_bounded_regex, selector_error
from .structured import schema_value

VARIABLE_PREFIXES = ("preset:", "meta:", "selector:", "selectorHtml:", "schema:")
_TEMPLATE_KEYS = frozenset(
    {
        "id",
        "triggers",
        "article_html",
        "title",
        "author",
        "published",
        "remove_html",
        "markdown_filters",
        "notes",
    }
)
_LIST_FIELDS = ("triggers", "remove_html", "markdown_filters")
MAX_EXPRESSION_LENGTH = 2_048
MAX_TRIGGERS = 32
MAX_REMOVE_SELECTORS = 64
MAX_MARKDOWN_FILTERS = 24
MAX_NOTES_LENGTH = 2_000
MAX_TRIGGER_LENGTH = 2_048
MAX_SELECTOR_MATCHES = 128
_PRESET_KEYS = frozenset({"title", "author", "published", "canonical", "site_name"})


class TemplateValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)


def _list_values(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = value.get(key, [])
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise TemplateValidationError([f"{key} must be an array"])
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _coerce_template(value: Mapping[str, Any]) -> TemplateSpec:
    return TemplateSpec(
        id=str(value.get("id") or "").strip(),
        triggers=_list_values(value, "triggers"),
        article_html=str(value["article_html"]).strip() if value.get("article_html") else None,
        title=str(value["title"]).strip() if value.get("title") else None,
        author=str(value["author"]).strip() if value.get("author") else None,
        published=str(value["published"]).strip() if value.get("published") else None,
        remove_html=_list_values(value, "remove_html"),
        markdown_filters=_list_values(value, "markdown_filters"),
        notes=str(value["notes"]).strip() if value.get("notes") else None,
    )


def validate_template(value: Mapping[str, Any]) -> TemplateSpec:
    errors: list[str] = []
    unknown = sorted(str(key) for key in value if key not in _TEMPLATE_KEYS)
    if unknown:
        errors.append("unknown template fields: " + ", ".join(unknown))
    limits = {
        "triggers": MAX_TRIGGERS,
        "remove_html": MAX_REMOVE_SELECTORS,
        "markdown_filters": MAX_MARKDOWN_FILTERS,
    }
    for field_name in _LIST_FIELDS:
        raw = value.get(field_name, [])
        if raw is not None and not isinstance(raw, (list, tuple)):
            errors.append(f"{field_name} must be an array")
        elif isinstance(raw, (list, tuple)) and len(raw) > limits[field_name]:
            errors.append(f"{field_name} has more than {limits[field_name]} entries")
    if errors:
        raise TemplateValidationError(errors)

    spec = _coerce_template(value)
    if not spec.id or len(spec.id) > 120 or not re.fullmatch(r"[A-Za-z0-9._-]+", spec.id):
        errors.append("id must contain only letters, numbers, '.', '_' or '-'")
    if spec.notes and len(spec.notes) > MAX_NOTES_LENGTH:
        errors.append(f"notes is longer than {MAX_NOTES_LENGTH} characters")
    for trigger in spec.triggers:
        if len(trigger) > MAX_TRIGGER_LENGTH:
            errors.append(f"trigger is longer than {MAX_TRIGGER_LENGTH} characters")
            continue
        if trigger.startswith("regex:"):
            pattern = trigger[6:]
            if len(pattern) > MAX_REGEX_LENGTH:
                errors.append("trigger regex is too long")
            else:
                try:
                    compile_bounded_regex(pattern)
                except (ValueError, TypeError) as exc:
                    errors.append(f"invalid trigger regex: {exc}")
        elif trigger.startswith("schema:@") or trigger.startswith(("http://", "https://")):
            continue
        else:
            errors.append(f"unsupported trigger: {trigger}")
    for field_name in ("article_html", "title", "author", "published"):
        expression = getattr(spec, field_name)
        if not expression:
            continue
        if len(expression) > MAX_EXPRESSION_LENGTH:
            errors.append(f"{field_name} expression is too long")
            continue
        variable = expression.split("|", 1)[0].strip()
        if not variable.startswith(VARIABLE_PREFIXES):
            errors.append(f"{field_name} uses an unknown variable: {variable}")
        if variable.startswith("preset:") and variable.split(":", 1)[1] not in _PRESET_KEYS:
            errors.append(f"{field_name} uses an unknown preset: {variable}")
        if variable.startswith(("selector:", "selectorHtml:")):
            selector = variable.split(":", 1)[1]
            error = selector_error(selector)
            if error:
                errors.append(f"{field_name}: {error}")
        try:
            validate_filters(expression.split("|", 1)[1] if "|" in expression else ())
        except FilterValidationError as exc:
            errors.append(f"{field_name}: {exc}")
    for selector in spec.remove_html:
        error = selector_error(selector)
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
        if trigger.startswith("regex:") and bounded_regex_search(trigger[6:], url):
            return True
        if trigger.startswith("schema:@") and schema_value(structured, trigger[7:]) is not None:
            return True
    return False


def _meta_value(soup: BeautifulSoup, key: str) -> Any:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return tag.get("content") if tag else None


def _validate_variable_output(value: Any) -> Any:
    """Reject unexpectedly broad selectors/schema values instead of truncating silently."""
    values = value if isinstance(value, list) else [value]
    if len(values) > MAX_SELECTOR_MATCHES:
        raise TemplateValidationError(
            [f"variable matched more than {MAX_SELECTOR_MATCHES} values"]
        )
    total_chars = 0
    for item in values:
        total_chars += len(str(item or ""))
        if total_chars > MAX_OUTPUT_CHARS:
            raise TemplateValidationError(["variable output exceeds size limit"])
    return value


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
        error = selector_error(key)
        if error:
            raise TemplateValidationError([error])
        matches = soup.select(key, limit=MAX_SELECTOR_MATCHES + 1)
        values = [str(node) if kind == "selectorHtml" else node.get_text(" ", strip=True) for node in matches]
        value = values[0] if len(values) == 1 else values
    elif kind == "schema":
        value = schema_value(structured, key)
    else:
        raise TemplateValidationError([f"unknown variable type: {kind}"])
    value = _validate_variable_output(value)
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
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TemplateValidationError(["web_clean_template must be an object"])
    return validate_template(raw)


def template_dict(spec: TemplateSpec) -> dict[str, Any]:
    return asdict(spec)
