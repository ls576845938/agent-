"""Read-only risk budget contract helpers for promotion gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


REQUIRED_RISK_BUDGET_FIELDS = (
    "max_drawdown_limit",
    "position_limit",
    "exposure_limit",
)


@dataclass(frozen=True)
class RiskBudgetContractVerdict:
    promotion_ready: bool
    blockers: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {"promotion_ready": self.promotion_ready, "blockers": list(self.blockers)}


def evaluate_risk_budget_contract(payload: Mapping[str, Any] | None) -> RiskBudgetContractVerdict:
    data = dict(payload or {})
    blockers: list[str] = []
    if not data:
        blockers.append("risk_budget_missing")
    for field in REQUIRED_RISK_BUDGET_FIELDS:
        value = data.get(field)
        if value is None:
            blockers.append(f"{field}_missing")
            continue
        try:
            if float(value) <= 0:
                blockers.append(f"{field}_invalid")
        except (TypeError, ValueError):
            blockers.append(f"{field}_invalid")
    return RiskBudgetContractVerdict(promotion_ready=not blockers, blockers=_dedupe(blockers))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
