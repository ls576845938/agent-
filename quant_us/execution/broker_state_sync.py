from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
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
    from quant_us.risk.risk_event_log import RiskEventLog

_ACTIVE_STATUSES: frozenset[OrderStatus] = frozenset({
    OrderStatus.SUBMITTED,
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.CANCEL_PENDING,
})


@dataclass
class BrokerSyncReport:
    """Detailed report of broker state synchronization."""

    orders_matched: int = 0
    orders_status_synced: int = 0
    orders_missing_local: list[Order] = field(default_factory=list)
    orders_missing_broker: list[Order] = field(default_factory=list)
    fills_synced: int = 0
    fills_duplicate: int = 0
    fills_conflict: int = 0
    positions_compared: int = 0
    positions_diverge: list[tuple[str, float, float]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reduce_only_engaged: bool = False


@dataclass
class _SyncState:
    orders_matched: int = 0
    orders_status_synced: int = 0
    orders_missing_local: list[Order] = field(default_factory=list)
    orders_missing_broker: list[Order] = field(default_factory=list)
    fills_synced: int = 0
    fills_duplicate: int = 0
    fills_conflict: int = 0


class BrokerStateSync:
    """Full broker state synchronization after restart or disconnection.

    Reconciles ALL local state against broker:
    - Orders: match by client_order_id, sync status
    - Positions: compare quantities
    - Fills: find missing fills
    """

    def __init__(
        self,
        broker: BrokerBase,
        ledger: JsonlLedgerStore,
        oms: OrderManagementSystem,
        risk_event_log: RiskEventLog | None = None,
    ) -> None:
        self._broker = broker
        self._ledger = ledger
        self._oms = oms
        self._risk_event_log = risk_event_log
        self._lock = threading.Lock()
        self._log = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def full_sync(self) -> BrokerSyncReport:
        """Complete broker state synchronization.

        Reconciles orders, fills, and positions between local ledger and
        broker.  Writes missing orders/fills to the ledger. Returns a
        detailed report of all differences found.

        Safe to call at any time. Does not modify broker state.
        """
        state = _SyncState()
        report = BrokerSyncReport()

        # 1. Sync orders
        self._sync_orders(state, report)
        if report.reduce_only_engaged and any(error.startswith("get_orders:") for error in report.errors):
            report.orders_matched = state.orders_matched
            report.orders_status_synced = state.orders_status_synced
            return report

        # 2. Sync fills
        self._sync_fills(state, report)

        # 3. Compare positions
        self._sync_positions(report)

        # Copy state counters into report
        report.orders_matched = state.orders_matched
        report.orders_status_synced = state.orders_status_synced

        self._log.info(
            "Full sync complete: matched=%d status_synced=%d "
            "missing_local=%d missing_broker=%d fills_synced=%d "
            "positions_diverge=%d errors=%d",
            state.orders_matched,
            state.orders_status_synced,
            len(state.orders_missing_local),
            len(state.orders_missing_broker),
            state.fills_synced,
            len(report.positions_diverge),
            len(report.errors),
        )

        return report

    def sync_after_restart(self) -> BrokerSyncReport:
        """Recovery sync: rebuild local state from broker after restart.

        Scans all broker orders and fills, writes any that are missing from
        the local ledger.  This is the primary recovery path after an
        unexpected shutdown.

        Does NOT clear existing ledger data -- only appends what is missing.
        """
        report = BrokerSyncReport()

        # Load existing local order IDs and fill identities for dedup
        local_fill_index = FillIdempotencyIndex.from_ledger(self._ledger)
        local_order_ids = _load_order_client_ids(self._ledger)
        for coid in local_order_ids:
            self._register_client_order_id(coid)

        # Fetch all broker orders
        try:
            broker_orders = self._broker.get_orders()
        except Exception as exc:
            self._log.error("Failed to fetch broker orders: %s", exc)
            report.errors.append(f"get_orders: {exc}")
            self._enter_reduce_only(report, "broker_orders_unavailable", {"error": str(exc)})
            return report

        for broker_order in broker_orders or []:
            coid = broker_order.client_order_id
            if not coid:
                continue
            self._register_client_order_id(coid)

            if coid not in local_order_ids:
                # Order exists on broker but not locally -- write it
                try:
                    self._ledger.append_order(broker_order)
                    local_order_ids.add(coid)
                    report.orders_missing_local.append(broker_order)
                    self._log.info(
                        "Restored broker order: client_order_id=%s status=%s",
                        coid,
                        broker_order.status.value,
                    )
                except Exception as exc:
                    self._log.error(
                        "Failed to write restored order %s: %s", coid, exc,
                    )
                    report.errors.append(f"append_order({coid}): {exc}")

            # Sync fills for this order
            try:
                fills = self._broker.get_fills(order_id=broker_order.order_id)
            except Exception as exc:
                self._log.error(
                    "Failed to fetch fills for order %s: %s", coid, exc,
                )
                report.errors.append(f"get_fills({coid}): {exc}")
                continue

            for fill in fills or []:
                try:
                    appended = append_fill_idempotent(
                        self._ledger,
                        fill,
                        index=local_fill_index,
                        logger=self._log,
                    )
                except Exception as exc:
                    self._log.error(
                        "Failed to write restored fill %s: %s",
                        fill.fill_id,
                        exc,
                    )
                    report.errors.append(f"append_fill({fill.fill_id}): {exc}")
                    continue
                if appended.appended:
                    report.fills_synced += 1
                elif appended.duplicate:
                    report.fills_duplicate += 1
                elif appended.conflict:
                    report.fills_conflict += 1
                    report.errors.append(f"fill_conflict({appended.key})")

            if broker_order.status not in {OrderStatus.FILLED, OrderStatus.CANCELLED}:
                report.orders_status_synced += 1

        # Compare positions
        self._sync_positions(report)

        self._log.info(
            "Restart sync complete: restored_orders=%d fills_synced=%d "
            "fills_dup=%d positions_diverge=%d errors=%d",
            len(report.orders_missing_local),
            report.fills_synced,
            report.fills_duplicate,
            len(report.positions_diverge),
            len(report.errors),
        )

        return report

    # ------------------------------------------------------------------
    # Internal sync helpers
    # ------------------------------------------------------------------

    def _sync_orders(self, state: _SyncState, report: BrokerSyncReport) -> None:
        """Match ledger orders against broker orders and sync statuses.

        Writes missing orders to the local ledger (broker orders not in
        ledger).  Reports orders in ledger but missing from broker.
        """
        # Load local orders
        local_records = self._ledger.read_records("orders.jsonl")
        local_by_coid: dict[str, dict[str, Any]] = {}
        for rec in local_records:
            coid = rec.get("client_order_id") or ""
            if coid:
                local_by_coid[coid] = rec
                self._register_client_order_id(coid)

        # Fetch broker orders
        try:
            broker_orders = self._broker.get_orders()
        except Exception as exc:
            self._log.error("Failed to fetch broker orders: %s", exc)
            report.errors.append(f"get_orders: {exc}")
            self._enter_reduce_only(report, "broker_orders_unavailable", {"error": str(exc)})
            return

        broker_by_coid: dict[str, Order] = {}
        for order in broker_orders or []:
            if order.client_order_id:
                broker_by_coid[order.client_order_id] = order
                self._register_client_order_id(order.client_order_id)

        # Match and compare
        all_coids = set(local_by_coid) | set(broker_by_coid)

        for coid in sorted(all_coids):
            local = local_by_coid.get(coid)
            broker = broker_by_coid.get(coid)

            if local and broker:
                state.orders_matched += 1
                local_status = OrderStatus(local.get("status", "unknown"))
                if local_status != broker.status:
                    # Sync the local record with the broker status
                    updated_order = _order_from_record(dict(local))
                    updated_order.status = broker.status
                    updated_order.updated_at = utc_now()
                    try:
                        self._ledger.append_order(updated_order)
                        state.orders_status_synced += 1
                        self._log.info(
                            "Order status synced: %s %s -> %s",
                            coid,
                            local_status.value,
                            broker.status.value,
                        )
                    except Exception as exc:
                        report.errors.append(f"append_order({coid}): {exc}")

            elif broker and not local:
                # Broker has order, ledger does not
                report.orders_missing_local.append(broker)
                try:
                    self._ledger.append_order(broker)
                    self._log.info(
                        "Missing local order written from broker: %s", coid,
                    )
                except Exception as exc:
                    report.errors.append(f"append_order({coid}): {exc}")

            elif local and not broker:
                # Ledger has order, broker does not
                order = _order_from_record(dict(local))
                if order.status in _ACTIVE_STATUSES:
                    order.status = OrderStatus.UNKNOWN
                    order.updated_at = utc_now()
                    try:
                        self._ledger.append_order(order)
                    except Exception as exc:
                        report.errors.append(f"append_order({coid}): {exc}")
                    self._enter_reduce_only(
                        report,
                        "active_local_order_missing_broker",
                        {"client_order_id": coid, "symbol": order.symbol},
                    )
                report.orders_missing_broker.append(order)
                self._log.warning(
                    "Order in ledger but missing from broker: %s", coid,
                )

    def _sync_fills(self, state: _SyncState, report: BrokerSyncReport) -> None:
        """Sync fills for all orders involved in the reconciliation.

        Compares broker fills against local fills (by fill_id) and writes
        missing ones.
        """
        local_fill_index = FillIdempotencyIndex.from_ledger(self._ledger)

        # Get all broker fill IDs so we can find ones we're missing
        try:
            all_fills = self._broker.get_fills(order_id=None)
        except Exception as exc:
            self._log.error("Failed to fetch fills: %s", exc)
            report.errors.append(f"get_fills: {exc}")
            return

        for fill in all_fills or []:
            try:
                appended = append_fill_idempotent(
                    self._ledger,
                    fill,
                    index=local_fill_index,
                    logger=self._log,
                )
            except Exception as exc:
                report.errors.append(f"append_fill({fill.fill_id}): {exc}")
                continue

            if appended.appended:
                state.fills_synced += 1
            elif appended.duplicate:
                state.fills_duplicate += 1
            elif appended.conflict:
                state.fills_conflict += 1
                report.errors.append(f"fill_conflict({appended.key})")

        report.fills_synced = state.fills_synced
        report.fills_duplicate = state.fills_duplicate
        report.fills_conflict = state.fills_conflict

    def _sync_positions(self, report: BrokerSyncReport) -> None:
        """Compare ledger-derived positions against broker positions."""
        try:
            broker_positions = self._broker.get_positions()
        except Exception as exc:
            self._log.error("Failed to fetch broker positions: %s", exc)
            report.errors.append(f"get_positions: {exc}")
            return

        local_positions = self._ledger.latest_positions_from_fills()

        all_symbols = set(local_positions) | set(broker_positions)
        report.positions_compared = len(all_symbols)

        for symbol in sorted(all_symbols):
            local_qty = local_positions[symbol].quantity if symbol in local_positions else 0.0
            broker_qty = broker_positions[symbol].quantity if symbol in broker_positions else 0.0
            if abs(local_qty - broker_qty) > 1e-6:
                report.positions_diverge.append((symbol, local_qty, broker_qty))
                self._log.warning(
                    "Position divergence: %s local=%.4f broker=%.4f",
                    symbol,
                    local_qty,
                    broker_qty,
                )

    def _enter_reduce_only(
        self,
        report: BrokerSyncReport,
        reason: str,
        details: dict[str, Any],
    ) -> None:
        self._oms.reduce_only = True
        report.reduce_only_engaged = True
        event_details = {"reason": reason, **details}
        if self._risk_event_log is not None:
            self._risk_event_log.record("broker_state_sync_reduce_only", event_details)
        self._log.warning("Broker state sync entered reduce-only: %s", reason)

    def _register_client_order_id(self, client_order_id: str) -> None:
        register = getattr(self._oms, "register_client_order_id", None)
        if callable(register):
            register(client_order_id)
            return
        ids = getattr(self._oms, "_client_order_ids", None)
        if isinstance(ids, set) and client_order_id:
            ids.add(client_order_id)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _order_from_record(record: dict[str, Any]) -> Order:
    """Deserialize a JSON record back into an Order dataclass."""
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


def _load_order_client_ids(ledger: JsonlLedgerStore) -> set[str]:
    """Load all client_order_ids from the ledger's orders.jsonl."""
    ids: set[str] = set()
    for record in ledger.read_records("orders.jsonl"):
        coid = record.get("client_order_id") or ""
        if coid:
            ids.add(coid)
    return ids


def _parse_dt(value: str | datetime) -> datetime:
    """Parse an isoformat datetime string, handling possible Z suffix."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or utc_now().tzinfo)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=utc_now().tzinfo)
    return parsed
