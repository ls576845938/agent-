"""Deterministic replay over injected CN orders and fills only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json

from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty
from quant_cn.execution.models import Fill, OrderIntent, SAFETY_FLAGS
from quant_cn.execution.oms import OMSConflictError, OfflineOMS
from quant_cn.ledger.accounting import derive_account_state, post_fill, post_opening_cash
from quant_cn.ledger.reconciliation import reconcile
from quant_cn.ledger.store import InMemoryLedgerStore, LedgerConflictError


FORBIDDEN_SOURCE_TOKENS = (
    "latest",
    "live",
    "broker",
    "network",
    "private",
    "paper_queue",
    "order_endpoint",
)


@dataclass(frozen=True)
class ReplayInput:
    replay_id: str
    source_mode: str
    source_ref: str
    fixed_clock: datetime
    seed: int
    opening_cash: Decimal
    orders: tuple[OrderIntent, ...]
    fills: tuple[Fill, ...]
    expected_cash: Decimal | None = None
    expected_positions: tuple[tuple[str, int], ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "replay_id", require_non_empty(self.replay_id, "replay_id"))
        mode = require_non_empty(self.source_mode, "source_mode").lower()
        if mode != "injected_history":
            raise ValueError("replay_source_mode_must_be_injected_history")
        object.__setattr__(self, "source_mode", mode)
        source_ref = require_non_empty(self.source_ref, "source_ref")
        if any(token in source_ref.lower() for token in FORBIDDEN_SOURCE_TOKENS):
            raise ValueError("replay_external_or_mutable_source_forbidden")
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "fixed_clock", ensure_aware_timestamp(self.fixed_clock, "fixed_clock"))
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise TypeError("replay_seed_must_be_integer")
        if not isinstance(self.opening_cash, Decimal) or self.opening_cash < 0:
            raise ValueError("opening_cash_invalid")
        if any(not isinstance(item, OrderIntent) for item in self.orders):
            raise TypeError("replay_order_type_invalid")
        if any(not isinstance(item, Fill) for item in self.fills):
            raise TypeError("replay_fill_type_invalid")
        if any(item.created_at > self.fixed_clock for item in self.orders):
            raise ValueError("replay_order_after_fixed_clock")
        if any(item.occurred_at > self.fixed_clock for item in self.fills):
            raise ValueError("replay_fill_after_fixed_clock")
        if self.expected_cash is not None and not isinstance(self.expected_cash, Decimal):
            raise TypeError("expected_cash_must_be_decimal")
        if self.expected_positions is not None:
            object.__setattr__(self, "expected_positions", tuple(sorted(self.expected_positions)))


@dataclass(frozen=True)
class ReplayResult:
    status: str
    blockers: tuple[str, ...]
    cash: Decimal
    positions: tuple[tuple[str, int], ...]
    pnl: Decimal
    replay_hash: str
    safety_flags: dict[str, bool]


def run_replay(replay_input: ReplayInput) -> ReplayResult:
    """Rebuild OMS and ledger deterministically; any discrepancy blocks."""

    oms = OfflineOMS()
    ledger = InMemoryLedgerStore()
    blockers: list[str] = []
    post_opening_cash(
        ledger,
        record_id=f"opening:{replay_input.replay_id}",
        amount=replay_input.opening_cash,
        occurred_at=min(
            (
                *(item.created_at for item in replay_input.orders),
                replay_input.fixed_clock,
            )
        ),
        source_hash=replay_input.source_ref,
    )
    try:
        for intent in sorted(replay_input.orders, key=lambda item: (item.created_at, item.order_id)):
            oms.submit(intent)
        # Arrival order is deliberately ignored.  Economic event time + fill ID
        # define the canonical replay sequence.
        for fill in sorted(replay_input.fills, key=lambda item: (item.occurred_at, item.fill_id)):
            oms.apply_fill(fill)
            post_fill(ledger, fill)
    except (OMSConflictError, LedgerConflictError, ValueError) as error:
        blockers.append(str(error))

    try:
        state = derive_account_state(ledger)
        reconciliation = reconcile(
            orders=oms.states(),
            ledger=ledger,
            opening_cash=replay_input.opening_cash,
        )
        blockers.extend(reconciliation.blockers)
    except ValueError as error:
        blockers.append(str(error))
        state = derive_account_state(InMemoryLedgerStore())

    if replay_input.expected_cash is not None and replay_input.expected_cash != state.cash:
        blockers.append("expected_cash_mismatch")
    if (
        replay_input.expected_positions is not None
        and replay_input.expected_positions != state.positions
    ):
        blockers.append("expected_positions_mismatch")
    canonical = tuple(sorted(set(blockers)))
    payload = {
        "blockers": canonical,
        "cash": str(state.cash),
        "fixed_clock": replay_input.fixed_clock.isoformat(),
        "orders": tuple((item.intent.order_id, item.status, item.filled_quantity) for item in oms.states()),
        "positions": state.positions,
        "records": tuple((item.record_id, item.fingerprint) for item in ledger.records()),
        "replay_id": replay_input.replay_id,
        "seed": replay_input.seed,
        "source_ref": replay_input.source_ref,
    }
    replay_hash = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return ReplayResult(
        status="blocked" if canonical else "reconciled",
        blockers=canonical,
        cash=state.cash,
        positions=state.positions,
        pnl=state.pnl,
        replay_hash=replay_hash,
        safety_flags=dict(SAFETY_FLAGS),
    )
