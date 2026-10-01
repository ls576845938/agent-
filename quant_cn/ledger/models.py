"""Immutable CN accounting ledger records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty


RECORD_TYPES = frozenset({"opening_cash", "fill", "cash", "position", "mark"})


def _hash(payload: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class LedgerRecord:
    record_id: str
    record_type: str
    event_id: str
    occurred_at: datetime
    stable_security_id: str | None
    quantity_delta: int
    cash_delta: Decimal
    price: Decimal | None
    session_sequence: int | None
    source_hash: str

    def __post_init__(self) -> None:
        for name in ("record_id", "event_id", "source_hash"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        record_type = require_non_empty(self.record_type, "record_type").lower()
        if record_type not in RECORD_TYPES:
            raise ValueError("ledger_record_type_unknown")
        object.__setattr__(self, "record_type", record_type)
        object.__setattr__(self, "occurred_at", ensure_aware_timestamp(self.occurred_at, "occurred_at"))
        if self.stable_security_id is not None:
            object.__setattr__(
                self,
                "stable_security_id",
                require_non_empty(self.stable_security_id, "stable_security_id"),
            )
        if not isinstance(self.quantity_delta, int) or isinstance(self.quantity_delta, bool):
            raise TypeError("quantity_delta_must_be_integer")
        if not isinstance(self.cash_delta, Decimal) or not self.cash_delta.is_finite():
            raise ValueError("cash_delta_invalid")
        if self.price is not None and (
            not isinstance(self.price, Decimal) or not self.price.is_finite() or self.price <= 0
        ):
            raise ValueError("ledger_price_invalid")
        if self.session_sequence is not None and (
            not isinstance(self.session_sequence, int) or self.session_sequence < 0
        ):
            raise ValueError("session_sequence_invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(
            {
                "cash_delta": str(self.cash_delta),
                "event_id": self.event_id,
                "occurred_at": self.occurred_at.isoformat(),
                "price": str(self.price) if self.price is not None else None,
                "quantity_delta": self.quantity_delta,
                "record_id": self.record_id,
                "record_type": self.record_type,
                "session_sequence": self.session_sequence,
                "source_hash": self.source_hash,
                "stable_security_id": self.stable_security_id,
            }
        )


@dataclass(frozen=True)
class AccountState:
    cash: Decimal
    positions: tuple[tuple[str, int], ...]
    marks: tuple[tuple[str, Decimal], ...]
    opening_cash: Decimal

    @property
    def equity(self) -> Decimal:
        mark_map = dict(self.marks)
        return self.cash + sum(
            (mark_map.get(security_id, Decimal("0")) * quantity for security_id, quantity in self.positions),
            Decimal("0"),
        )

    @property
    def pnl(self) -> Decimal:
        return self.equity - self.opening_cash
