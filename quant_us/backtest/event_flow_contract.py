"""Event-driven backtest flow evidence contracts.

Promotion-grade portfolio evidence must prove the full path:
data -> signal -> portfolio -> risk -> order intent -> simulated fill ->
ledger -> report.  Optimizer-only weights or fixture ledgers are not enough.
"""

from __future__ import annotations

from typing import Any, Mapping


REQUIRED_EVENT_FLOW_SEQUENCE = [
    "data",
    "signal",
    "portfolio",
    "risk",
    "order_intent",
    "simulated_fill",
    "ledger",
    "report",
]


def build_portfolio_backtest_flow_evidence(
    *,
    source_type: str,
    event_ledger_status: Mapping[str, Any],
    ledger_validation: Mapping[str, Any],
    explicit_steps: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    steps = _steps(explicit_steps)
    status = str(event_ledger_status.get("status") or "missing")
    blockers = []
    if source_type != "production":
        blockers.append(f"event_driven_backtest_source_type_not_production:{source_type}")
    if status != "pass":
        blockers.append(f"event_driven_backtest_event_ledger_not_passed:{status}")
    if ledger_validation.get("event_ledger_candidate") is not True:
        blockers.append("event_driven_backtest_event_ledger_candidate_required")
    if ledger_validation.get("fills_available") is not True:
        blockers.append("event_driven_backtest_fills_required")
    if ledger_validation.get("ledger_pnl_available") is not True:
        blockers.append("event_driven_backtest_ledger_pnl_required")
    missing_steps = [step for step, present in steps.items() if present is not True]
    blockers.extend(f"event_driven_backtest_step_missing:{step}" for step in missing_steps)
    passed = not blockers
    return {
        "status": "pass" if passed else "blocked",
        "source_type": source_type,
        "required_sequence": list(REQUIRED_EVENT_FLOW_SEQUENCE),
        "steps": steps,
        "all_steps_present": not missing_steps,
        "pnl_source": "ledger_fills" if passed else "",
        "blockers": _dedupe(blockers),
    }


def _steps(explicit_steps: Mapping[str, Any] | None) -> dict[str, bool]:
    if not explicit_steps:
        return {step: False for step in REQUIRED_EVENT_FLOW_SEQUENCE}
    return {step: bool(explicit_steps.get(step, False)) for step in REQUIRED_EVENT_FLOW_SEQUENCE}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
