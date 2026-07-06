import json
from pathlib import Path

import pytest

from scripts.check_ble001_budget import (
    Ble001Violation,
    check_budget,
    format_top_files,
    load_budget,
    parse_ruff_json,
)


def test_parse_ruff_json_normalizes_filenames(tmp_path: Path):
    payload = json.dumps(
        [
            {
                "filename": str(tmp_path / "app" / "example.py"),
                "location": {"row": 7, "column": 12},
                "message": "Do not catch blind exception: `Exception`",
            }
        ]
    )

    violations = parse_ruff_json(payload, tmp_path)

    assert violations == [
        Ble001Violation(
            filename="app/example.py",
            row=7,
            message="Do not catch blind exception: `Exception`",
        )
    ]


def test_check_budget_allows_equal_or_lower_count():
    violations = [
        Ble001Violation(filename="app/a.py", row=1, message="first"),
        Ble001Violation(filename="app/b.py", row=2, message="second"),
    ]

    assert check_budget(violations, max_total=2).ok is True
    assert check_budget(violations[:1], max_total=2).ok is True
    assert check_budget(violations, max_total=1).ok is False


def test_format_top_files_counts_per_file():
    violations = [
        Ble001Violation(filename="app/a.py", row=1, message="first"),
        Ble001Violation(filename="app/a.py", row=2, message="second"),
        Ble001Violation(filename="app/b.py", row=3, message="third"),
    ]

    assert format_top_files(violations, limit=1) == "    2 app/a.py"


def test_load_budget_requires_non_negative_integer(tmp_path: Path):
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"max_total": 3}))

    assert load_budget(budget) == 3

    budget.write_text(json.dumps({"max_total": "3"}))
    with pytest.raises(ValueError):
        load_budget(budget)
