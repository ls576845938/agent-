"""Fail-closed reconciliation between OMS fills and ledger projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_cn.execution.models import OrderState
from quant_cn.ledger.accounting import derive_account_state
from quant_cn.ledger.store import InMemoryLedgerStore


@dataclass(frozen=True)
class ReconciliationResult:
    status: str
    blockers: tuple[str, ...]
    expected_cash: Decimal
    actual_cash: Decimal
    expected_positions: tuple[tuple[str, int], ...]
    actual_positions: tuple[tuple[str, int], ...]

    @property
    def blocks_gate(self) -> bool:
        return bool(self.blockers)


def reconcile(
    *,
    orders: tuple[OrderState, ...],
    ledger: InMemoryLedgerStore,
    opening_cash: Decimal,
) -> ReconciliationResult:
    cash = opening_cash
    positions: dict[str, int] = {}
    fill_ids: list[str] = []
    for order in orders:
        for fill in order.fills:
            fill_ids.append(fill.fill_id)
            sign = 1 if fill.side == "buy" else -1
            positions[fill.stable_security_id] = positions.get(fill.stable_security_id, 0) + sign * fill.quantity
            cash += (
                -fill.notional - fill.total_fee
                if fill.side == "buy"
                else fill.notional - fill.total_fee
            )
    state = derive_account_state(ledger)
    ledger_fill_ids = [
        record.event_id for record in ledger.records() if record.record_type == "fill"
    ]
    blockers: list[str] = []
    if len(fill_ids) != len(set(fill_ids)):
        blockers.append("oms_duplicate_fill_id")
    if sorted(fill_ids) != sorted(ledger_fill_ids):
        blockers.append("fill_ledger_mismatch")
    if cash != state.cash:
        blockers.append("cash_reconciliation_difference")
    expected_positions = tuple(sorted(positions.items()))
    if expected_positions != state.positions:
        blockers.append("position_reconciliation_difference")
    canonical = tuple(sorted(set(blockers)))
    return ReconciliationResult(
        status="blocked" if canonical else "reconciled",
        blockers=canonical,
        expected_cash=cash,
        actual_cash=state.cash,
        expected_positions=expected_positions,
        actual_positions=state.positions,
    )
