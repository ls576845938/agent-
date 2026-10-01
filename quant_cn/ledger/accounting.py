"""Fill-driven CN cash, positions, sellability, and PnL accounting."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from quant_cn.execution.models import Fill
from quant_cn.ledger.models import AccountState, LedgerRecord
from quant_cn.ledger.store import InMemoryLedgerStore


def _state(records: tuple[LedgerRecord, ...]) -> AccountState:
    cash = Decimal("0")
    opening_cash = Decimal("0")
    positions: dict[str, int] = {}
    marks: dict[str, Decimal] = {}
    for record in records:
        cash += record.cash_delta
        if record.record_type == "opening_cash":
            opening_cash += record.cash_delta
        if record.stable_security_id is not None:
            positions[record.stable_security_id] = (
                positions.get(record.stable_security_id, 0) + record.quantity_delta
            )
            if positions[record.stable_security_id] < 0:
                raise ValueError("negative_position_blocked")
            if record.record_type == "mark" and record.price is not None:
                marks[record.stable_security_id] = record.price
    return AccountState(
        cash=cash,
        positions=tuple(sorted(positions.items())),
        marks=tuple(sorted(marks.items())),
        opening_cash=opening_cash,
    )


def derive_account_state(store: InMemoryLedgerStore) -> AccountState:
    """Derive all balances from immutable ledger records, never external PnL."""

    return _state(store.records())


def post_opening_cash(
    store: InMemoryLedgerStore,
    *,
    record_id: str,
    amount: Decimal,
    occurred_at: datetime,
    source_hash: str,
) -> bool:
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
        raise ValueError("opening_cash_invalid")
    return store.append(
        LedgerRecord(
            record_id=record_id,
            record_type="opening_cash",
            event_id=record_id,
            occurred_at=occurred_at,
            stable_security_id=None,
            quantity_delta=0,
            cash_delta=amount,
            price=None,
            session_sequence=None,
            source_hash=source_hash,
        )
    )


def post_fill(store: InMemoryLedgerStore, fill: Fill) -> None:
    """Atomically post fill, cash, and position entries; rollback on any failure."""

    sign = 1 if fill.side == "buy" else -1
    cash_delta = (
        -fill.notional - fill.total_fee
        if fill.side == "buy"
        else fill.notional - fill.total_fee
    )
    with store.unit_of_work() as uow:
        uow.append(
            LedgerRecord(
                record_id=f"fill:{fill.fill_id}",
                record_type="fill",
                event_id=fill.fill_id,
                occurred_at=fill.occurred_at,
                stable_security_id=fill.stable_security_id,
                quantity_delta=0,
                cash_delta=Decimal("0"),
                price=fill.price,
                session_sequence=fill.session_sequence,
                source_hash=fill.fingerprint,
            )
        )
        uow.append(
            LedgerRecord(
                record_id=f"cash:{fill.fill_id}",
                record_type="cash",
                event_id=fill.fill_id,
                occurred_at=fill.occurred_at,
                stable_security_id=None,
                quantity_delta=0,
                cash_delta=cash_delta,
                price=fill.price,
                session_sequence=fill.session_sequence,
                source_hash=fill.fingerprint,
            )
        )
        uow.append(
            LedgerRecord(
                record_id=f"position:{fill.fill_id}",
                record_type="position",
                event_id=fill.fill_id,
                occurred_at=fill.occurred_at,
                stable_security_id=fill.stable_security_id,
                quantity_delta=sign * fill.quantity,
                cash_delta=Decimal("0"),
                price=fill.price,
                session_sequence=fill.session_sequence,
                source_hash=fill.fingerprint,
            )
        )
        state = derive_account_state(store)
        if state.cash < 0:
            raise ValueError("ledger_cash_negative")
        uow.commit()


def post_mark(
    store: InMemoryLedgerStore,
    *,
    record_id: str,
    stable_security_id: str,
    price: Decimal,
    occurred_at: datetime,
    source_hash: str,
) -> bool:
    return store.append(
        LedgerRecord(
            record_id=record_id,
            record_type="mark",
            event_id=record_id,
            occurred_at=occurred_at,
            stable_security_id=stable_security_id,
            quantity_delta=0,
            cash_delta=Decimal("0"),
            price=price,
            session_sequence=None,
            source_hash=source_hash,
        )
    )


def sellable_quantity(
    store: InMemoryLedgerStore,
    *,
    stable_security_id: str,
    current_session_sequence: int,
    settlement_sessions: int,
) -> int:
    """Return fill-derived inventory visible after the injected session lag."""

    quantity = 0
    for record in store.records():
        if record.record_type != "position" or record.stable_security_id != stable_security_id:
            continue
        if record.session_sequence is None:
            raise ValueError("position_session_sequence_missing")
        if record.quantity_delta > 0:
            if current_session_sequence - record.session_sequence >= settlement_sessions:
                quantity += record.quantity_delta
        else:
            quantity += record.quantity_delta
    if quantity < 0:
        raise ValueError("sellability_reconciliation_negative")
    return quantity
