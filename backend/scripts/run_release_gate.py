"""Produce a fail-closed M6 release-gate report without hiding external blockers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/release_gate.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    checks: dict[str, dict] = {}
    manifest = subprocess.run([sys.executable, str(root / "scripts/validate_architecture_manifest.py")], cwd=root, capture_output=True, text=True)
    checks["architecture_manifest"] = {"ok": manifest.returncode == 0, "output": (manifest.stdout or manifest.stderr).strip()}
    required = {
        "core_eval_dataset": root / "tests/fixtures/core_eval_1_0.jsonl",
        "shadow_eval_dataset": root / "tests/fixtures/shadow_eval_1_0.jsonl",
        "security_review_approval": root / "docs/SECURITY_REVIEW_APPROVAL.md",
    }
    blockers = []
    for name, path in required.items():
        present = path.exists() or bool(os.getenv(name.upper()))
        checks[name] = {"ok": present, "path": str(path.relative_to(root))}
        if not present:
            blockers.append(f"missing external release evidence: {name}")
    checks["real_data_shadow_canary"] = {
        "ok": bool(os.getenv("PIM_REAL_DATA_SHADOW_APPROVED")),
        "reason": "requires operator approval and authenticated paid-source fixtures",
    }
    if not checks["real_data_shadow_canary"]["ok"]:
        blockers.append("real paid-source 7-14d Shadow/Canary evidence is not available in this workspace")
    report = {"schema_version": "release-gate/v1", "status": "GO" if not blockers and all(item["ok"] for item in checks.values()) else "NO_GO", "checks": checks, "blockers": blockers}
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # The report is intentionally non-zero on NO_GO so CI cannot silently
    # publish an artifact whose real-data or approval gates are absent.
    return 0 if report["status"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
