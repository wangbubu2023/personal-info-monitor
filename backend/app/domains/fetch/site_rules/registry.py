"""Rule registry, built-in loading, and revision state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from app.domains.fetch.site_rules.contracts import SiteRule, SiteRuleStatus
from app.domains.fetch.site_rules.validation import RuleValidationError, rule_checksum, validate_rule


class SiteRuleStateStore:
    """Small JSON state store for current/LKG rule pointers and counters."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._lock = RLock()

    def read(self) -> dict[str, Any]:
        if not self.path or not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def write(self, value: dict[str, Any]) -> None:
        if not self.path:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            temporary.replace(self.path)


class RuleRegistry:
    def __init__(self, rules: Iterable[SiteRule] | None = None, state_path: str | Path | None = None):
        self._rules: dict[tuple[str, int], SiteRule] = {}
        self._lock = RLock()
        self.state_store = SiteRuleStateStore(state_path)
        for rule in rules or ():
            self.register(rule, allow_same_revision=True)

    def register(self, payload: SiteRule | dict[str, Any], *, allow_same_revision: bool = False) -> SiteRule:
        rule = validate_rule(payload)
        key = (rule.rule_id, rule.revision)
        with self._lock:
            existing = self._rules.get(key)
            if existing and not allow_same_revision and rule_checksum(existing) != rule_checksum(rule):
                raise RuleValidationError(f"immutable rule revision already exists: {rule.rule_id}/{rule.revision}")
            self._rules[key] = rule
        return rule

    def get(self, rule_id: str, revision: int | None = None) -> SiteRule | None:
        with self._lock:
            if revision is not None:
                return self._rules.get((rule_id, int(revision)))
            candidates = [rule for (candidate_id, _), rule in self._rules.items() if candidate_id == rule_id]
            return max(candidates, key=lambda item: item.revision) if candidates else None

    def list(self, *, rule_id: str | None = None) -> list[SiteRule]:
        with self._lock:
            values = list(self._rules.values())
        if rule_id:
            values = [rule for rule in values if rule.rule_id == rule_id]
        return sorted(values, key=lambda item: (item.rule_id, item.revision))

    def eligible(self) -> list[SiteRule]:
        return [
            rule
            for rule in self.list()
            if rule.status in {
                SiteRuleStatus.ACTIVE,
                SiteRuleStatus.CANARY,
                SiteRuleStatus.SHADOW,
                SiteRuleStatus.DEGRADED,
            }
        ]

    def promote(self, rule_id: str, revision: int, status: SiteRuleStatus) -> SiteRule:
        if status not in set(SiteRuleStatus):
            raise RuleValidationError(f"unsupported status: {status}")
        current = self.get(rule_id, revision)
        if current is None:
            raise RuleValidationError(f"rule revision not found: {rule_id}/{revision}")
        with self._lock:
            if status == SiteRuleStatus.ACTIVE:
                for key, value in list(self._rules.items()):
                    if key[0] == rule_id and value.status == SiteRuleStatus.ACTIVE and key != (rule_id, revision):
                        self._rules[key] = value.model_copy(update={"status": SiteRuleStatus.RETIRED})
            promoted = current.model_copy(update={"status": status})
            self._rules[(rule_id, revision)] = promoted
            state = self.state_store.read()
            state[rule_id] = {
                "current": revision,
                "lkg": revision if status == SiteRuleStatus.ACTIVE else state.get(rule_id, {}).get("lkg"),
                "status": status.value,
                "checksum": rule_checksum(promoted),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self.state_store.write(state)
            return promoted

    @classmethod
    def from_directory(cls, directory: str | Path, *, state_path: str | Path | None = None) -> "RuleRegistry":
        rules: list[SiteRule] = []
        for path in sorted(Path(directory).glob("*.json")):
            try:
                rules.append(validate_rule(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError, RuleValidationError) as exc:
                raise RuleValidationError(f"invalid built-in rule {path.name}: {exc}") from exc
        return cls(rules, state_path=state_path)


_BUILTINS_DIR = Path(__file__).with_name("builtins")
builtin_registry = RuleRegistry.from_directory(_BUILTINS_DIR)
