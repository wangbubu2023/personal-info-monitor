"""Bounded parse/quality diagnostics used for rule degradation decisions."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class RuleHealth:
    rule_id: str
    parse_errors: int = 0
    empty_results: int = 0
    successful_runs: int = 0
    status: str = "active"


class RuleDiagnostics:
    def __init__(self, *, degrade_after: int = 3):
        self.degrade_after = max(1, int(degrade_after))
        self._health: dict[str, RuleHealth] = {}
        self._lock = RLock()

    def record(self, rule_id: str, *, success: bool, empty: bool = False) -> RuleHealth:
        key = str(rule_id).strip()
        with self._lock:
            current = self._health.get(key, RuleHealth(rule_id=key))
            next_health = RuleHealth(
                rule_id=key,
                parse_errors=current.parse_errors + (0 if success else 1),
                empty_results=current.empty_results + (1 if empty else 0),
                successful_runs=current.successful_runs + (1 if success else 0),
                status=("degraded" if (not success and current.parse_errors + 1 >= self.degrade_after) else current.status),
            )
            self._health[key] = next_health
            return next_health

    def get(self, rule_id: str) -> RuleHealth | None:
        return self._health.get(str(rule_id).strip())

    def snapshot(self) -> list[RuleHealth]:
        return sorted(self._health.values(), key=lambda item: item.rule_id)
