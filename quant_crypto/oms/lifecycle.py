from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from quant_shared.core.time import ensure_utc, utc_now

from quant_crypto.trading_contracts import OrderIntent
from quant_crypto.adapters.shared_platform import new_btc_id


BTC_PAPER_OMS_LIFECYCLE_VERSION = "btc_paper_oms_lifecycle_v1"


class BTCPaperOrderStatus(str, Enum):
    CREATED = "created"
    RISK_CHECKED = "risk_checked"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    RECONCILED = "reconciled"
    UNKNOWN = "unknown"


TERMINAL_STATUSES = {
    BTCPaperOrderStatus.FILLED,
    BTCPaperOrderStatus.CANCELLED,
    BTCPaperOrderStatus.REJECTED,
    BTCPaperOrderStatus.EXPIRED,
    BTCPaperOrderStatus.RECONCILED,
}

ALLOWED_TRANSITIONS: dict[BTCPaperOrderStatus, set[BTCPaperOrderStatus]] = {
    BTCPaperOrderStatus.CREATED: {BTCPaperOrderStatus.RISK_CHECKED, BTCPaperOrderStatus.REJECTED},
    BTCPaperOrderStatus.RISK_CHECKED: {BTCPaperOrderStatus.SUBMITTED, BTCPaperOrderStatus.REJECTED},
    BTCPaperOrderStatus.SUBMITTED: {
        BTCPaperOrderStatus.ACCEPTED,
        BTCPaperOrderStatus.PARTIALLY_FILLED,
        BTCPaperOrderStatus.FILLED,
        BTCPaperOrderStatus.REJECTED,
        BTCPaperOrderStatus.EXPIRED,
        BTCPaperOrderStatus.UNKNOWN,
    },
    BTCPaperOrderStatus.ACCEPTED: {
        BTCPaperOrderStatus.PARTIALLY_FILLED,
        BTCPaperOrderStatus.FILLED,
        BTCPaperOrderStatus.CANCEL_REQUESTED,
        BTCPaperOrderStatus.REJECTED,
        BTCPaperOrderStatus.EXPIRED,
        BTCPaperOrderStatus.UNKNOWN,
    },
    BTCPaperOrderStatus.PARTIALLY_FILLED: {
        BTCPaperOrderStatus.PARTIALLY_FILLED,
        BTCPaperOrderStatus.FILLED,
        BTCPaperOrderStatus.CANCEL_REQUESTED,
        BTCPaperOrderStatus.EXPIRED,
        BTCPaperOrderStatus.UNKNOWN,
    },
    BTCPaperOrderStatus.CANCEL_REQUESTED: {
        BTCPaperOrderStatus.PARTIALLY_FILLED,
        BTCPaperOrderStatus.FILLED,
        BTCPaperOrderStatus.CANCELLED,
        BTCPaperOrderStatus.REJECTED,
        BTCPaperOrderStatus.UNKNOWN,
    },
    BTCPaperOrderStatus.UNKNOWN: {
        BTCPaperOrderStatus.ACCEPTED,
        BTCPaperOrderStatus.PARTIALLY_FILLED,
        BTCPaperOrderStatus.FILLED,
        BTCPaperOrderStatus.CANCELLED,
        BTCPaperOrderStatus.REJECTED,
        BTCPaperOrderStatus.EXPIRED,
    },
    BTCPaperOrderStatus.FILLED: {BTCPaperOrderStatus.RECONCILED},
    BTCPaperOrderStatus.CANCELLED: {BTCPaperOrderStatus.RECONCILED},
    BTCPaperOrderStatus.REJECTED: {BTCPaperOrderStatus.RECONCILED},
    BTCPaperOrderStatus.EXPIRED: {BTCPaperOrderStatus.RECONCILED},
    BTCPaperOrderStatus.RECONCILED: set(),
}


@dataclass(frozen=True)
class BTCPaperOrderEvent:
    status: BTCPaperOrderStatus
    timestamp_utc: datetime
    reason: str
    filled_quantity: float = 0.0
    remaining_quantity: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))
        object.__setattr__(self, "filled_quantity", float(self.filled_quantity))
        object.__setattr__(self, "remaining_quantity", float(self.remaining_quantity))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "reason": self.reason,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BTCRejectRecord:
    reject_code: str
    reject_reason: str
    original_order_intent_id: str
    risk_state: dict[str, Any]
    exchange_response: dict[str, Any]
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reject_code": self.reject_code,
            "reject_reason": self.reject_reason,
            "original_order_intent_id": self.original_order_intent_id,
            "risk_state": dict(self.risk_state),
            "exchange_response": dict(self.exchange_response),
            "next_action": self.next_action,
        }


@dataclass
class BTCPaperOrderLifecycle:
    order_intent: OrderIntent
    order_id: str = field(default_factory=lambda: new_btc_id("btc_order"))
    status: BTCPaperOrderStatus = BTCPaperOrderStatus.CREATED
    filled_quantity: float = 0.0
    remaining_quantity: float = 0.0
    broker_order_id: str = ""
    reject_record: BTCRejectRecord | None = None
    events: list[BTCPaperOrderEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.order_intent.client_order_id:
            raise ValueError("BTC paper order requires client_order_id.")
        if self.remaining_quantity == 0.0:
            self.remaining_quantity = float(self.order_intent.quantity)
        if not self.events:
            self.events.append(
                BTCPaperOrderEvent(
                    status=BTCPaperOrderStatus.CREATED,
                    timestamp_utc=self.order_intent.timestamp_utc,
                    reason="order_intent_received",
                    filled_quantity=0.0,
                    remaining_quantity=self.remaining_quantity,
                    metadata={
                        "lifecycle_version": BTC_PAPER_OMS_LIFECYCLE_VERSION,
                        "client_order_id": self.order_intent.client_order_id,
                        "order_intent_id": self.order_intent.order_intent_id,
                    },
                )
            )

    @property
    def client_order_id(self) -> str:
        return self.order_intent.client_order_id

    def transition(
        self,
        status: BTCPaperOrderStatus,
        *,
        reason: str,
        timestamp_utc: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._assert_transition(status)
        self.status = status
        self._append_event(status, reason, timestamp_utc=timestamp_utc, metadata=metadata)

    def mark_risk_checked(self, *, approved: bool, reason: str = "risk_checked") -> None:
        self.transition(
            BTCPaperOrderStatus.RISK_CHECKED if approved else BTCPaperOrderStatus.REJECTED,
            reason=reason,
            metadata={"risk_approved": approved},
        )

    def mark_submitted(
        self,
        *,
        broker_order_id: str = "",
        unknown_outcome: bool = False,
        reason: str = "submitted",
    ) -> None:
        self.transition(BTCPaperOrderStatus.SUBMITTED, reason=reason, metadata={"broker_order_id": broker_order_id})
        self.broker_order_id = broker_order_id
        if unknown_outcome:
            self.transition(
                BTCPaperOrderStatus.UNKNOWN,
                reason="submit_outcome_unknown_query_before_retry",
                metadata={"broker_order_id": broker_order_id, "retry_allowed_without_status_query": False},
            )

    def mark_accepted(self, *, broker_order_id: str, reason: str = "accepted") -> None:
        self.broker_order_id = broker_order_id
        self.transition(BTCPaperOrderStatus.ACCEPTED, reason=reason, metadata={"broker_order_id": broker_order_id})

    def apply_fill(
        self,
        *,
        fill_quantity: float,
        timestamp_utc: datetime | None = None,
        fill_id: str = "",
        price: float | None = None,
    ) -> None:
        qty = float(fill_quantity)
        if qty <= 0.0:
            raise ValueError("fill_quantity must be positive.")
        if qty > self.remaining_quantity:
            raise ValueError("fill_quantity exceeds remaining_quantity.")
        new_filled = self.filled_quantity + qty
        new_remaining = max(0.0, self.remaining_quantity - qty)
        next_status = BTCPaperOrderStatus.FILLED if new_remaining == 0.0 else BTCPaperOrderStatus.PARTIALLY_FILLED
        self._assert_transition(next_status)
        self.filled_quantity = new_filled
        self.remaining_quantity = new_remaining
        self.status = next_status
        self._append_event(
            next_status,
            "fill_received",
            timestamp_utc=timestamp_utc,
            metadata={"fill_id": fill_id, "fill_quantity": qty, "price": price},
        )

    def request_cancel(self, *, reason: str = "cancel_requested") -> None:
        self.transition(BTCPaperOrderStatus.CANCEL_REQUESTED, reason=reason)

    def confirm_cancelled(self, *, reason: str = "cancel_confirmed") -> None:
        self.transition(BTCPaperOrderStatus.CANCELLED, reason=reason)

    def reject(
        self,
        *,
        reject_code: str,
        reject_reason: str,
        risk_state: dict[str, Any] | None = None,
        exchange_response: dict[str, Any] | None = None,
        next_action: str = "do_not_retry",
    ) -> None:
        record = BTCRejectRecord(
            reject_code=reject_code,
            reject_reason=reject_reason,
            original_order_intent_id=self.order_intent.order_intent_id,
            risk_state=dict(risk_state or {}),
            exchange_response=dict(exchange_response or {}),
            next_action=next_action,
        )
        self.reject_record = record
        self.transition(BTCPaperOrderStatus.REJECTED, reason=reject_reason, metadata={"reject": record.to_dict()})

    def expire(self, *, reason: str = "expired") -> None:
        self.transition(BTCPaperOrderStatus.EXPIRED, reason=reason)

    def reconcile(self, *, reason: str = "reconciled", metadata: dict[str, Any] | None = None) -> None:
        if self.status not in {
            BTCPaperOrderStatus.FILLED,
            BTCPaperOrderStatus.CANCELLED,
            BTCPaperOrderStatus.REJECTED,
            BTCPaperOrderStatus.EXPIRED,
        }:
            raise ValueError("BTC paper order can only reconcile terminal external statuses.")
        self.transition(BTCPaperOrderStatus.RECONCILED, reason=reason, metadata=metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lifecycle_version": BTC_PAPER_OMS_LIFECYCLE_VERSION,
            "order_id": self.order_id,
            "order_intent_id": self.order_intent.order_intent_id,
            "target_position_id": self.order_intent.target_position_id,
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "strategy_id": self.order_intent.strategy_id,
            "symbol": self.order_intent.symbol,
            "side": self.order_intent.side.value,
            "quantity": self.order_intent.quantity,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "reject_record": None if self.reject_record is None else self.reject_record.to_dict(),
            "events": [event.to_dict() for event in self.events],
        }

    def _assert_transition(self, next_status: BTCPaperOrderStatus) -> None:
        if next_status not in ALLOWED_TRANSITIONS.get(self.status, set()):
            raise ValueError(f"Invalid BTC paper order transition: {self.status.value} -> {next_status.value}")

    def _append_event(
        self,
        status: BTCPaperOrderStatus,
        reason: str,
        *,
        timestamp_utc: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            BTCPaperOrderEvent(
                status=status,
                timestamp_utc=timestamp_utc or utc_now(),
                reason=reason,
                filled_quantity=self.filled_quantity,
                remaining_quantity=self.remaining_quantity,
                metadata=dict(metadata or {}),
            )
        )


@dataclass
class BTCPaperOMS:
    orders_by_client_id: dict[str, BTCPaperOrderLifecycle] = field(default_factory=dict)

    def create_order(self, order_intent: OrderIntent) -> BTCPaperOrderLifecycle:
        client_order_id = order_intent.client_order_id
        if not client_order_id:
            raise ValueError("BTC paper OMS requires client_order_id.")
        if client_order_id in self.orders_by_client_id:
            raise ValueError("duplicate_client_order_id")
        lifecycle = BTCPaperOrderLifecycle(order_intent=order_intent)
        self.orders_by_client_id[client_order_id] = lifecycle
        return lifecycle

    def get(self, client_order_id: str) -> BTCPaperOrderLifecycle | None:
        return self.orders_by_client_id.get(client_order_id)

    def to_records(self) -> list[dict[str, Any]]:
        return [order.to_dict() for order in self.orders_by_client_id.values()]
