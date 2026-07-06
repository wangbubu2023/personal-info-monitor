"""Architecture boundary checks for retired shim import paths."""

from __future__ import annotations

import ast
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"

RETIRED_PRODUCTION_IMPORTS = {
    "app.processors.extractor",
    "app.processors.content_processor",
    "app.processors.keyword_matcher",
    "app.processors.summarizer",
    "app.processors.translator",
    "app.collectors.x_twitter",
    "app.services.api_config_credentials",
    "app.services.keyword_rules",
    "app.pipeline.collector_stage",
    "app.pipeline.coordinator",
    "app.pipeline.utils",
}


def _is_retired(name: str) -> bool:
    return any(name == retired or name.startswith(f"{retired}.") for retired in RETIRED_PRODUCTION_IMPORTS)


def _importlib_target(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "import_module":
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
    if isinstance(func, ast.Name) and func.id == "__import__":
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
    return None


def test_production_code_uses_canonical_processor_and_x_collector_paths():
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_retired(alias.name):
                        offenders.append(f"{path.relative_to(APP_DIR)}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_retired(module):
                    offenders.append(f"{path.relative_to(APP_DIR)}:{node.lineno} from {module}")
            elif isinstance(node, ast.Call):
                target = _importlib_target(node)
                if target and _is_retired(target):
                    offenders.append(f"{path.relative_to(APP_DIR)}:{node.lineno} importlib {target}")

    assert offenders == []
