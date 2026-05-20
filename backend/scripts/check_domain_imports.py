#!/usr/bin/env python3
"""Static import-boundary checker for the domain refactor.

Walks ``backend/app`` once with the stdlib ``ast`` module and verifies that
inter-module imports respect the rules described in
``PIM 模块化重构实施蓝图 v3 §2.3``.

This script is **phase-aware**: pass ``--phase=N`` (or set
``PIM_REFACTOR_PHASE``) to enable the rule set for that phase. Earlier-phase
rules always remain in force, so each step ratchets the wall in tighter.

Usage::

    python backend/scripts/check_domain_imports.py            # auto-detect phase
    python backend/scripts/check_domain_imports.py --phase=2  # explicit phase
    python backend/scripts/check_domain_imports.py --list     # show rule table

Exit codes::

    0  — all checked files pass the rules for the active phase
    1  — at least one violation was found (printed to stdout)
    2  — invalid CLI usage or missing source tree

The checker is intentionally conservative:

* It only inspects ``import`` / ``from … import`` statements at module load
  time; runtime ``importlib.import_module`` calls are out of scope.
* It treats both absolute (``app.foo.bar``) and relative (``from .foo``)
  imports correctly by resolving against the importing module's package.
* Imports performed inside functions or ``TYPE_CHECKING`` blocks are still
  inspected — banned dependencies must not appear in source at all.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Phase rule table
# --------------------------------------------------------------------------- #

# Each rule is a tuple ``(source_prefix, banned_target_prefixes, phase, label)``.
# A violation is reported when a module under ``source_prefix`` imports from
# any module whose dotted name begins with one of ``banned_target_prefixes``
# AND the active phase is >= ``phase``.

Rule = tuple[str, tuple[str, ...], int, str]

RULES: tuple[Rule, ...] = (
    # Phase 0 — only the contracts package; it must remain dependency-free.
    (
        "app.domains.contracts",
        ("app.domains.sources", "app.domains.fetch", "app.domains.ingest",
         "app.domains.enrich", "app.domains.atoms", "app.api",
         "app.pipeline", "app.tasks", "app.services", "app.collectors",
         "app.processors"),
        0,
        "contracts must not import from other domains or legacy layers",
    ),
    # Phase 2 — background must not depend on domains OR on app.services
    # (Phase 2 step 1 migrates runtime_lock_service to platform.locks);
    # collectors must not import pipeline internals.
    (
        "app.background",
        ("app.domains.", "app.services."),
        2,
        "background.py is platform infrastructure; depend on platform.locks instead",
    ),
    (
        "app.collectors.",
        ("app.pipeline.",),
        2,
        "collectors only produce FetchBatch; do not import pipeline.utils",
    ),
    # Phase 3 — ingest must not depend on fetch internals or LLM providers;
    # HTTP layer must not reach into pipeline.
    (
        "app.domains.ingest",
        ("app.domains.fetch.collectors", "app.ai.", "app.processors.summarizer",
         "app.processors.translator"),
        3,
        "ingest must not import fetch collectors or LLM provider/summariser/translator",
    ),
    (
        "app.api.",
        ("app.pipeline.",),
        3,
        "HTTP layer must not import from pipeline (reject_reason now lives in ingest.quality)",
    ),
    # Phase 4 — enrich must not depend on fetch collectors; services must not
    # depend on the HTTP layer.
    (
        "app.domains.enrich",
        ("app.collectors.", "app.domains.fetch.collectors"),
        4,
        "enrich must not import fetch collectors",
    ),
    (
        "app.services.",
        ("app.api.",),
        4,
        "services must not import from app.api (the reverse dependency Phase 4 eliminates)",
    ),
    # Phase 5 — platform must not depend on domains; domains must not depend
    # on the HTTP interfaces layer.
    (
        "app.platform.",
        ("app.domains.",),
        5,
        "platform layer must not depend on any business domain",
    ),
    (
        "app.domains.",
        ("app.interfaces.", "app.api."),
        5,
        "business domains must not depend on the HTTP interfaces layer",
    ),
    # Phase 7 — sweep the last legacy paths out of the runtime.
    (
        "app.",
        ("app.pipeline.ai_stage",),
        7,
        "pipeline/ai_stage.py is dead code (no callers); removed by Phase 7",
    ),
    (
        "app.",
        (
            "app.interfaces.http.configs_common",
            "app.api.configs_common",
        ),
        7,
        "configs_common aggregator facade removed by Phase 7; address the split "
        "modules (configs_common_auth / configs_common_browser / configs_common_cookies) directly",
    ),
    # Phase 7 housekeeping — orphan shims removed by the post-Phase-7 audit.
    # These re-export facades were retained "just in case" during earlier
    # phases but had zero remaining callers (see audit notes); banning them
    # here prevents future code from accidentally reintroducing them.
    (
        "app.",
        (
            "app.collectors.podcast",
            "app.collectors.website_helpers",
            "app.collectors.x_twitter_formatters",
            "app.data.source_types",
            "app.exporters",
            "app.utils.ssrf",
            "app.utils.tracing",
            "app.tasks.email_tasks",
            "app.tasks.fetch_orchestrator",
            "app.tasks.hourly_digest_tasks",
            "app.services.runtime_lock_service",
            "app.services.system_settings",
            "app.services.hourly_digest",
            "app.services.reader",
        ),
        7,
        "orphan shim removed by post-Phase-7 audit; import the canonical path "
        "(domains.fetch.collectors / domains.sources.source_types / platform.export / "
        "platform.security.ssrf / platform.observability.tracing / domains.enrich.notifications / "
        "domains.sources.status / domains.enrich.hourly / platform.locks / platform.config / "
        "domains.enrich.reader) instead",
    ),
)


# --------------------------------------------------------------------------- #
# AST scanning
# --------------------------------------------------------------------------- #


@dataclass
class Violation:
    file: Path
    lineno: int
    source_module: str
    target_module: str
    rule_label: str
    rule_phase: int

    def format(self, *, root: Path) -> str:
        rel = self.file.relative_to(root)
        return (
            f"{rel}:{self.lineno}: {self.source_module} -> {self.target_module}\n"
            f"    rule (phase {self.rule_phase}): {self.rule_label}"
        )


@dataclass
class ScanReport:
    files_scanned: int = 0
    violations: list[Violation] = field(default_factory=list)


def _module_name_from_path(path: Path, app_root: Path) -> str:
    """Return the dotted module name for a ``path`` inside ``backend/app``."""
    rel = path.relative_to(app_root.parent)  # path relative to ``backend``
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(module: str | None, level: int, source_module: str) -> str:
    """Resolve a ``from .foo import bar`` style import into a dotted name."""
    if level == 0:
        return module or ""
    pieces = source_module.split(".")
    if level > len(pieces):
        return module or ""
    base = pieces[:-level]
    if module:
        base.append(module)
    return ".".join(base)


def _iter_imports(tree: ast.AST, source_module: str) -> Iterable[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            target = _resolve_relative(node.module, node.level, source_module)
            if target:
                yield node.lineno, target


def _rule_applies(rule: Rule, source_module: str, target_module: str) -> bool:
    src_prefix, banned_prefixes, _phase, _label = rule
    if src_prefix.endswith("."):
        if not source_module.startswith(src_prefix):
            return False
    else:
        if not (source_module == src_prefix or source_module.startswith(src_prefix + ".")):
            return False
    for banned in banned_prefixes:
        if banned.endswith("."):
            if target_module.startswith(banned):
                return True
        else:
            if target_module == banned or target_module.startswith(banned + "."):
                return True
    return False


def scan(app_root: Path, *, phase: int) -> ScanReport:
    report = ScanReport()
    active_rules = [r for r in RULES if r[2] <= phase]
    for py_path in sorted(app_root.rglob("*.py")):
        if "__pycache__" in py_path.parts:
            continue
        try:
            source = py_path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover — filesystem race
            print(f"warning: cannot read {py_path}: {exc}", file=sys.stderr)
            continue
        try:
            tree = ast.parse(source, filename=str(py_path))
        except SyntaxError as exc:
            print(f"warning: cannot parse {py_path}: {exc}", file=sys.stderr)
            continue
        report.files_scanned += 1
        source_module = _module_name_from_path(py_path, app_root)
        for lineno, target in _iter_imports(tree, source_module):
            for rule in active_rules:
                if _rule_applies(rule, source_module, target):
                    report.violations.append(
                        Violation(
                            file=py_path,
                            lineno=lineno,
                            source_module=source_module,
                            target_module=target,
                            rule_label=rule[3],
                            rule_phase=rule[2],
                        )
                    )
                    break  # one violation per import line is enough
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _detect_phase(default: int = 0) -> int:
    env = os.environ.get("PIM_REFACTOR_PHASE")
    if env is None:
        return default
    try:
        return int(env)
    except ValueError:
        print(f"warning: PIM_REFACTOR_PHASE={env!r} is not an integer; using {default}",
              file=sys.stderr)
        return default


def _print_rules() -> None:
    print(f"{'phase':>6}  {'source':<28} -> banned target(s)")
    print("-" * 72)
    for src, targets, phase, label in RULES:
        target_str = ", ".join(targets)
        print(f"{phase:>6}  {src:<28} -> {target_str}\n         {label}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", type=int, default=None,
                        help="Active refactor phase (default: $PIM_REFACTOR_PHASE or 0)")
    parser.add_argument("--app-root", type=Path, default=None,
                        help="Path to backend/app (auto-detected by default)")
    parser.add_argument("--list", action="store_true",
                        help="Print the rule table and exit")
    args = parser.parse_args(argv)

    if args.list:
        _print_rules()
        return 0

    phase = args.phase if args.phase is not None else _detect_phase()
    app_root = args.app_root or _default_app_root()
    if not app_root.is_dir():
        print(f"error: backend/app directory not found at {app_root}", file=sys.stderr)
        return 2

    report = scan(app_root, phase=phase)
    if report.violations:
        print(f"check_domain_imports: phase={phase} — {len(report.violations)} violation(s) "
              f"across {report.files_scanned} files\n")
        for v in report.violations:
            print(v.format(root=app_root.parent))
            print()
        return 1
    print(f"check_domain_imports: phase={phase} — clean ({report.files_scanned} files scanned)")
    return 0


def _default_app_root() -> Path:
    here = Path(__file__).resolve()
    # backend/scripts/check_domain_imports.py -> backend/app
    return here.parent.parent / "app"


if __name__ == "__main__":
    raise SystemExit(main())
