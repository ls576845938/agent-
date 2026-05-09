from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import Order
from quant_us.execution.fill_idempotency import (
    FillIdempotencyIndex,
    append_fill_idempotent,
)

if TYPE_CHECKING:
    from quant_us.execution.broker_base import BrokerBase
    from quant_us.execution.ledger import JsonlLedgerStore
    from quant_us.execution.oms import OrderManagementSystem
    from quant_us.risk.kill_switch import KillSwitch
    from quant_us.risk.risk_event_log import RiskEventLog

_TERMINAL_STATUSES: frozenset = frozenset({
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
    OrderStatus.ERROR,
    OrderStatus.UNKNOWN,
})

_ACTIVE_STATUSES: frozenset = frozenset({
    OrderStatus.SUBMITTED,
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.CANCEL_PENDING,
})


class OrderSyncAction(str, Enum):
    """Action taken when resolving an order's state."""

    NOOP = "noop"
    SYNCED = "synced"
    FILL_SYNCED = "fill_synced"
    MARKED_UNKNOWN = "marked_unknown"
    PARTIAL_FILL = "partial_fill"
    EXTERNAL_ALERT = "external_alert"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class OrderPollResult:
    """Summary of a single poll cycle."""

    total_processed: int = 0
    synced: int = 0
    filled: int = 0
    cancelled: int = 0
    rejected: int = 0
    unknown: list[str] = field(default_factory=list)
    external: list[Order] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class OrderPollingLoop:
    """Polls broker for open orders and syncs state transitions.

    Core rules:
    - LOCAL SUBMITTED, BROKER FILLED -> pull fill, write to ledger
    - LOCAL SUBMITTED, BROKER NOT FOUND -> mark UNKNOWN, stop new orders
    - LOCAL CANCEL_PENDING, BROKER PARTIALLY_FILLED -> write partial fill,
      continue cancel
    - BROKER order exists, LOCAL doesn't -> mark external_order, alert
    - All state changes logged to event log
    """

    def __init__(
        self,
        broker: BrokerBase,
        ledger: JsonlLedgerStore,
        oms: OrderManagementSystem,
        kill_switch: KillSwitch,
        risk_event_log: RiskEventLog | None = None,
    ) -> None:
        self._broker = broker
        self._ledger = ledger
        self._oms = oms
        self._kill_switch = kill_switch
        self._risk_event_log = risk_event_log
        self._lock = threading.Lock()
        self._orders: dict[str, Order] = {}
        self._processed_ids: set[str] = set()
        self._fill_index = FillIdempotencyIndex()
        self._log = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> OrderPollResult:
        """Single poll cycle. Returns summary of changes."""
        self._load_local_orders()

        broker_orders = self._safe_get_orders()
        broker_index = _index_orders(broker_orders)

        result = OrderPollResult()

        for coid, local in list(self._orders.items()):
            if local.status in _TERMINAL_STATUSES:
                continue

            broker = broker_index.pop(coid, None)
            action = self.sync_order(local, broker)
            self._record_result(result, action, coid)

        for coid, broker in broker_index.items():
            self._log.warning("External order not in ledger: client_order_id=%s", coid)
            result.external.append(broker)
            if self._risk_event_log is not None:
                self._risk_event_log.record(
                    "external_order_detected",
                    {"client_order_id": coid, "symbol": broker.symbol},
                )

        return result

    def sync_order(
        self,
        local_order: Order,
        broker_order: Order | None,
    ) -> OrderSyncAction:
        """Resolve one order's state. Returns the action taken.

        Idempotent: processing the same order_id twice in a session returns
        NOOP on subsequent calls.
        """
        with self._lock:
            if local_order.client_order_id in self._processed_ids:
                return OrderSyncAction.NOOP
            self._processed_ids.add(local_order.client_order_id)

        return self._resolve(local_order, broker_order)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _resolve(
        self,
        local: Order,
        broker: Order | None,
    ) -> OrderSyncAction:
        if broker is None:
            # LOCAL exists, BROKER NOT FOUND
            if local.status in _ACTIVE_STATUSES:
                self._mark_unknown(local)
                return OrderSyncAction.MARKED_UNKNOWN
            return OrderSyncAction.NOOP

        if local.status == broker.status:
            return OrderSyncAction.NOOP

        # LOCAL SUBMITTED/ACCEPTED, BROKER FILLED
        if (
            local.status in {OrderStatus.SUBMITTED, OrderStatus.ACCEPTED}
            and broker.status == OrderStatus.FILLED
        ):
            self._sync_fills(broker)
            self._update_local(local, broker)
            return OrderSyncAction.FILL_SYNCED

        # LOCAL SUBMITTED/ACCEPTED, BROKER PARTIALLY_FILLED
        if (
            local.status in {OrderStatus.SUBMITTED, OrderStatus.ACCEPTED}
            and broker.status == OrderStatus.PARTIALLY_FILLED
        ):
            self._sync_fills(broker)
            self._update_local(local, broker)
            return OrderSyncAction.PARTIAL_FILL

        # LOCAL CANCEL_PENDING, BROKER PARTIALLY_FILLED
        if (
            local.status == OrderStatus.CANCEL_PENDING
            and broker.status == OrderStatus.PARTIALLY_FILLED
        ):
            self._sync_fills(broker)
            self._update_local(local, broker)
            return OrderSyncAction.PARTIAL_FILL

        # Generic state change
        old_status = local.status
        self._update_local(local, broker)
        self._log.info(
            "Order %s state changed: %s -> %s",
            local.client_order_id,
            old_status.value,
            broker.status.value,
        )

        if broker.status == OrderStatus.FILLED:
            self._sync_fills(broker)
            return OrderSyncAction.FILL_SYNCED
        if broker.status == OrderStatus.CANCELLED:
            return OrderSyncAction.CANCELLED
        if broker.status == OrderStatus.REJECTED:
            return OrderSyncAction.REJECTED

        return OrderSyncAction.SYNCED

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_local_orders(self) -> None:
        """Load orders from ledger into tracked set.

        Safe to call repeatedly; only new orders are added.
        """
        records = self._ledger.read_records("orders.jsonl")
        for record in records:
            coid = record.get("client_order_id") or ""
            if not coid or coid in self._orders:
                continue
            try:
                self._orders[coid] = _order_from_record(record)
            except Exception as exc:
                self._log.warning(
                    "Failed to parse order record %s: %s", coid, exc,
                )

    def _safe_get_orders(self) -> list[Order]:
        """Fetch orders from broker with graceful degradation."""
        try:
            return self._broker.get_orders()
        except Exception as exc:
            self._log.error("Failed to fetch broker orders: %s", exc)
            if self._kill_switch is not None:
                self._kill_switch.record_order_failure()
            if self._risk_event_log is not None:
                self._risk_event_log.record(
                    "broker_poll_failure",
                    {"error": str(exc)},
                )
            return []

    def _sync_fills(self, broker_order: Order) -> None:
        """Pull fills from broker and write missing ones to ledger."""
        try:
            fills = self._broker.get_fills(order_id=broker_order.order_id)
            for fill in fills or []:
                appended = append_fill_idempotent(
                    self._ledger,
                    fill,
                    index=self._fill_index,
                    logger=self._log,
                )
                if appended.appended:
                    self._log.info(
                        "Fill synced: order=%s fill=%s qty=%s price=%s",
                        broker_order.client_order_id,
                        fill.fill_id,
                        fill.quantity,
                        fill.price,
                    )
                elif appended.conflict:
                    self._log.error(
                        "Conflicting fill skipped: order=%s key=%s",
                        broker_order.client_order_id,
                        appended.key,
                    )
        except Exception as exc:
            self._log.error(
                "Failed to sync fills for order %s: %s",
                broker_order.client_order_id,
                exc,
            )

    def _update_local(self, local: Order, broker: Order) -> None:
        """Update local order state to match broker state."""
        local.status = broker.status
        local.updated_at = utc_now()
        local.broker_order_id = broker.broker_order_id
        self._ledger.append_order(local)

    def _mark_unknown(self, local: Order) -> None:
        """Mark an order as UNKNOWN and engage safety measures."""
        local.status = OrderStatus.UNKNOWN
        local.updated_at = utc_now()
        self._ledger.append_order(local)
        self._kill_switch.record_order_failure()
        self._oms.reduce_only = True
        self._log.warning(
            "Order %s marked UNKNOWN, system in reduce-only mode",
            local.client_order_id,
        )
        if self._risk_event_log is not None:
            self._risk_event_log.record(
                "order_marked_unknown",
                {
                    "client_order_id": local.client_order_id,
                    "symbol": local.symbol,
                },
            )

    def _record_result(
        self,
        result: OrderPollResult,
        action: OrderSyncAction,
        coid: str,
    ) -> None:
        result.total_processed += 1
        if action == OrderSyncAction.FILL_SYNCED:
            result.filled += 1
        elif action == OrderSyncAction.CANCELLED:
            result.cancelled += 1
        elif action == OrderSyncAction.REJECTED:
            result.rejected += 1
        elif action == OrderSyncAction.MARKED_UNKNOWN:
            result.unknown.append(coid)
        elif action in {OrderSyncAction.SYNCED, OrderSyncAction.PARTIAL_FILL}:
            result.synced += 1


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _order_from_record(record: dict[str, Any]) -> Order:
    """Deserialize a JSON record back into an Order dataclass.

    Handles enum and datetime fields serialized by ``JsonlLedgerStore``.
    """
    limit_price = record.get("limit_price")
    return Order(
        timestamp_utc=_parse_dt(record["timestamp_utc"]),
        strategy_id=str(record.get("strategy_id", "")),
        symbol=str(record.get("symbol", "")),
        side=OrderSide(str(record["side"])),
        quantity=float(record["quantity"]),
        order_type=OrderType(str(record["order_type"])),
        time_in_force=TimeInForce(str(record["time_in_force"])),
        client_order_id=str(record["client_order_id"]),
        run_id=str(record.get("run_id", "")),
        signal_id=str(record.get("signal_id", "")),
        risk_check_id=str(record.get("risk_check_id", "")),
        broker_order_id=str(record.get("broker_order_id", "")),
        limit_price=float(limit_price) if limit_price is not None else None,
        status=OrderStatus(str(record["status"])),
        created_at=_parse_dt(record["created_at"]),
        updated_at=_parse_dt(record["updated_at"]),
        order_id=str(record["order_id"]),
    )


def _index_orders(orders: list[Order]) -> dict[str, Order]:
    """Index orders by client_order_id.  Returns a new dict."""
    index: dict[str, Order] = {}
    for order in orders:
        if order.client_order_id:
            index[order.client_order_id] = order
    return index


def _parse_dt(value: str | datetime) -> datetime:
    """Parse an isoformat datetime string, handling possible Z suffix."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or utc_now().tzinfo)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=utc_now().tzinfo)
    return parsed
