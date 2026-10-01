"""Offline-only CN execution contracts.

These objects describe intents and simulated outcomes.  They grant no broker,
paper-queue, or live-order capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty


SIDES = frozenset({"buy", "sell"})
ORDER_TYPES = frozenset({"limit"})
TIME_IN_FORCE = frozenset({"day", "ioc", "fok"})
TERMINAL_STATES = frozenset({"filled", "cancelled", "rejected", "expired"})

SAFETY_FLAGS: dict[str, bool] = {
    "broker": False,
    "demo": False,
    "live": False,
    "network": False,
    "oms": False,
    "order": False,
    "paper": False,
    "paper_queue": False,
    "private": False,
    "promotion": False,
    "real_order": False,
    "withdraw": False,
}


def _positive_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"decimal_required:{field_name}")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"positive_decimal_required:{field_name}")
    return value


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OrderIntent:
    order_id: str
    client_order_id: str
    risk_decision_id: str
    target_id: str
    run_id: str
    stable_security_id: str
    side: str
    quantity: int
    limit_price: Decimal
    order_type: str
    time_in_force: str
    decision_time: datetime
    created_at: datetime
    session_sequence: int
    rule_versions: tuple[tuple[str, str], ...]
    evidence_hash: str

    def __post_init__(self) -> None:
        for name in (
            "order_id",
            "client_order_id",
            "risk_decision_id",
            "target_id",
            "run_id",
            "stable_security_id",
            "evidence_hash",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        side = require_non_empty(self.side, "side").lower()
        if side not in SIDES:
            raise ValueError("side_unknown")
        object.__setattr__(self, "side", side)
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool) or self.quantity <= 0:
            raise ValueError("quantity_must_be_positive_integer")
        _positive_decimal(self.limit_price, "limit_price")
        order_type = require_non_empty(self.order_type, "order_type").lower()
        tif = require_non_empty(self.time_in_force, "time_in_force").lower()
        if order_type not in ORDER_TYPES:
            raise ValueError("order_type_not_supported_offline")
        if tif not in TIME_IN_FORCE:
            raise ValueError("time_in_force_unknown")
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "time_in_force", tif)
        object.__setattr__(
            self, "decision_time", ensure_aware_timestamp(self.decision_time, "decision_time")
        )
        object.__setattr__(self, "created_at", ensure_aware_timestamp(self.created_at, "created_at"))
        if self.created_at < self.decision_time:
            raise ValueError("order_created_before_decision")
        if not isinstance(self.session_sequence, int) or self.session_sequence < 0:
            raise ValueError("session_sequence_invalid")
        versions = tuple(sorted(self.rule_versions))
        if not versions or any(not key or not value for key, value in versions):
            raise ValueError("rule_versions_required")
        object.__setattr__(self, "rule_versions", versions)

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(
            {
                "client_order_id": self.client_order_id,
                "created_at": self.created_at.isoformat(),
                "evidence_hash": self.evidence_hash,
                "limit_price": str(self.limit_price),
                "order_id": self.order_id,
                "quantity": self.quantity,
                "risk_decision_id": self.risk_decision_id,
                "rule_versions": self.rule_versions,
                "run_id": self.run_id,
                "session_sequence": self.session_sequence,
                "side": self.side,
                "stable_security_id": self.stable_security_id,
                "target_id": self.target_id,
                "time_in_force": self.time_in_force,
            }
        )

    @property
    def safety_flags(self) -> dict[str, bool]:
        return dict(SAFETY_FLAGS)


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    stable_security_id: str
    side: str
    quantity: int
    price: Decimal
    fee_components: tuple[tuple[str, Decimal], ...]
    occurred_at: datetime
    received_at: datetime
    session_sequence: int
    source: str = "offline_fixture"

    def __post_init__(self) -> None:
        for name in ("fill_id", "order_id", "stable_security_id", "source"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        side = require_non_empty(self.side, "side").lower()
        if side not in SIDES:
            raise ValueError("side_unknown")
        object.__setattr__(self, "side", side)
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool) or self.quantity <= 0:
            raise ValueError("quantity_must_be_positive_integer")
        _positive_decimal(self.price, "price")
        fees = tuple(sorted(self.fee_components))
        if any(
            not name
            or not isinstance(amount, Decimal)
            or not amount.is_finite()
            or amount < 0
            for name, amount in fees
        ):
            raise ValueError("fee_components_invalid")
        if len({name for name, _ in fees}) != len(fees):
            raise ValueError("fee_component_duplicate")
        object.__setattr__(self, "fee_components", fees)
        object.__setattr__(self, "occurred_at", ensure_aware_timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "received_at", ensure_aware_timestamp(self.received_at, "received_at"))
        if self.received_at < self.occurred_at:
            raise ValueError("fill_received_before_occurrence")
        if not isinstance(self.session_sequence, int) or self.session_sequence < 0:
            raise ValueError("session_sequence_invalid")

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity

    @property
    def total_fee(self) -> Decimal:
        return sum((amount for _, amount in self.fee_components), Decimal("0"))

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(
            {
                "fee_components": tuple((name, str(value)) for name, value in self.fee_components),
                "fill_id": self.fill_id,
                "occurred_at": self.occurred_at.isoformat(),
                "order_id": self.order_id,
                "price": str(self.price),
                "quantity": self.quantity,
                "session_sequence": self.session_sequence,
                "side": self.side,
                "stable_security_id": self.stable_security_id,
            }
        )


@dataclass(frozen=True)
class OrderState:
    intent: OrderIntent
    status: str = "accepted"
    filled_quantity: int = 0
    fills: tuple[Fill, ...] = ()
    blockers: tuple[str, ...] = ()
    audit_events: tuple[str, ...] = field(default_factory=lambda: ("accepted",))

    @property
    def remaining_quantity(self) -> int:
        return self.intent.quantity - self.filled_quantity

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def safety_flags(self) -> dict[str, bool]:
        return dict(SAFETY_FLAGS)
