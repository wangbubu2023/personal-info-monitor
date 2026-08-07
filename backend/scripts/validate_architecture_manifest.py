"""Validate the machine-readable M6 architecture manifest."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "docs" / "architecture_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "architecture-manifest/v1":
        print("invalid architecture manifest schema", file=sys.stderr)
        return 2
    missing: list[str] = []
    for entry in payload.get("entrypoints", []) + [{"path": item} for item in payload.get("shared_contracts", [])]:
        path = root / str(entry["path"])
        if not path.is_file():
            missing.append(str(entry["path"]))
    if missing:
        print(json.dumps({"ok": False, "missing": missing}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "entrypoints": len(payload.get("entrypoints", [])), "contracts": len(payload.get("shared_contracts", []))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
