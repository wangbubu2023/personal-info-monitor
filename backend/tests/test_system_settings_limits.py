import copy

from app.services.system_settings import DEFAULT_SYSTEM_SETTINGS, _apply_patch


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
