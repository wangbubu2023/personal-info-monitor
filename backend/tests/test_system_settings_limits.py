import copy

from app.services.system_settings import (
    DEFAULT_SYSTEM_SETTINGS,
    HOURLY_DIGEST_DEFAULT_PROMPT,
    _apply_patch,
    effective_hourly_digest_prompt,
    get_system_settings_for_response,
    normalize_hourly_digest_content_types,
    normalize_hourly_digest_window_hours,
)


def test_system_settings_patch_limits_with_clamp():
    current = copy.deepcopy(DEFAULT_SYSTEM_SETTINGS)
    updated = _apply_patch(
        current,
        {
            "limits": {
                "max_sources": "350",
                "max_digest_candidates": 99,
                "max_hourly_digest_input_items": 10,
            }
        },
    )

    assert updated["limits"]["max_sources"] == 350
    assert updated["limits"]["max_digest_candidates"] == 30
    assert updated["limits"]["max_hourly_digest_input_items"] == 20


def test_system_settings_patch_limits_ignores_unknown_keys():
    current = copy.deepcopy(DEFAULT_SYSTEM_SETTINGS)
    updated = _apply_patch(current, {"limits": {"max_sources": 222, "not_exists": 1}})

    assert updated["limits"]["max_sources"] == 222
    assert "not_exists" not in updated["limits"]


def test_apply_patch_fallback_bools_coerced():
    """避免 str/非 bool 被 Python truthiness 误判（如 bool('false') == True）。"""
    current = copy.deepcopy(DEFAULT_SYSTEM_SETTINGS)
    updated = _apply_patch(
        current,
        {
            "translation_fallback_enabled": "true",
            "summarization_fallback_enabled": "false",
        },
    )
    assert updated["translation_fallback_enabled"] is True
    assert updated["summarization_fallback_enabled"] is False


def test_apply_patch_hourly_digest_prompt_and_content_types():
    current = copy.deepcopy(DEFAULT_SYSTEM_SETTINGS)
    updated = _apply_patch(
        current,
        {
            "hourly_digest": {
                "prompt": "只关心半导体，少用形容词",
                "content_types": ["rss", "website", "invalid"],
            }
        },
    )
    assert updated["hourly_digest"]["prompt"] == "只关心半导体，少用形容词"
    assert updated["hourly_digest"]["content_types"] == ["rss", "website"]
    assert updated["hourly_digest"]["window_hours"] == 3


def test_apply_patch_hourly_digest_window_hours_clamped():
    current = copy.deepcopy(DEFAULT_SYSTEM_SETTINGS)

    updated = _apply_patch(current, {"hourly_digest": {"window_hours": "99"}})

    assert updated["hourly_digest"]["window_hours"] == 24


def test_effective_hourly_digest_prompt_prefers_saved_and_legacy():
    assert effective_hourly_digest_prompt({"prompt": "  自定义  "}) == "自定义"
    assert effective_hourly_digest_prompt({"importance_prompt": "A", "synthesis_prompt": "B"}) == "A\n\nB"
    assert effective_hourly_digest_prompt({}) == HOURLY_DIGEST_DEFAULT_PROMPT


def test_get_system_settings_for_response_empty_prompt_not_replaced_keeps_effective():
    base = copy.deepcopy(DEFAULT_SYSTEM_SETTINGS)
    base["hourly_digest"] = {"prompt": "", "content_types": ["rss"]}
    out = get_system_settings_for_response(base)
    assert out["hourly_digest"]["prompt"] == ""
    assert out["hourly_digest"]["prompt_effective"] == HOURLY_DIGEST_DEFAULT_PROMPT


def test_get_system_settings_for_response_merges_legacy_into_prompt_field_only():
    base = copy.deepcopy(DEFAULT_SYSTEM_SETTINGS)
    base["hourly_digest"] = {
        "prompt": "",
        "importance_prompt": "A",
        "synthesis_prompt": "B",
        "content_types": ["rss"],
    }
    out = get_system_settings_for_response(base)
    assert out["hourly_digest"]["prompt"] == "A\n\nB"
    assert out["hourly_digest"]["prompt_effective"] == "A\n\nB"


def test_normalize_hourly_digest_content_types_defaults():
    assert normalize_hourly_digest_content_types({}) == ["website", "rss"]
    assert normalize_hourly_digest_content_types({"hourly_digest": {}}) == ["website", "rss"]


def test_normalize_hourly_digest_window_hours_defaults():
    assert normalize_hourly_digest_window_hours({}) == 3
    assert normalize_hourly_digest_window_hours({"hourly_digest": {"window_hours": "2"}}) == 2
