#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema as stable JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT.parent / "frontend" / "src" / "types" / "openapi.json"
RUNTIME_UI_PATHS = {"/", "/{full_path}"}


def schema_to_json(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove routes whose presence depends on a local frontend build."""
    normalized = dict(schema)
    paths = schema.get("paths")
    if isinstance(paths, dict):
        normalized["paths"] = {
            path: definition
            for path, definition in paths.items()
            if path not in RUNTIME_UI_PATHS
        }
    return normalized


def export_openapi(output_path: Path = DEFAULT_OUTPUT) -> Path:
    from app.main import app

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(schema_to_json(normalize_schema(app.openapi())))
    return output_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output_path = export_openapi(args.output)
    print(f"Wrote OpenAPI schema to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
