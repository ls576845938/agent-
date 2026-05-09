from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus
from quant_us.core.events import BrokerOrderEvent, Event, FillEvent, RiskEvent
from quant_us.core.types import AccountState, Fill, Order, OrderIntent, RiskDecision
from quant_us.execution.broker_base import BrokerBase
from quant_us.risk.kill_switch import KillSwitch
from quant_us.risk.pre_trade import PreTradeRiskEngine

if TYPE_CHECKING:
    from quant_us.risk.risk_event_log import RiskEventLog


@dataclass
class OMSResult:
    intent: OrderIntent
    risk_decision: RiskDecision
    order: Order | None = None
    fills: list[Fill] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


class OrderManagementSystem:
    def __init__(
        self,
        broker: BrokerBase,
        risk_engine: PreTradeRiskEngine,
        calendar: USEquityCalendar | None = None,
        kill_switch: KillSwitch | None = None,
        idempotency_path: str | Path | None = None,
        risk_event_log: RiskEventLog | None = None,
    ) -> None:
        self.broker = broker
        self.risk_engine = risk_engine
        self.calendar = calendar or USEquityCalendar()
        self.kill_switch = kill_switch
        self.risk_event_log = risk_event_log
        self._client_order_ids: set[str] = set()
        self._idempotency_path = Path(idempotency_path) if idempotency_path else None
        self.reduce_only: bool = False

    def persist_idempotency(self) -> None:
        """Persist _client_order_ids to disk so restarts don't duplicate orders."""
        if self._idempotency_path is None:
            return
        self._idempotency_path.parent.mkdir(parents=True, exist_ok=True)
        self._idempotency_path.write_text(json.dumps(sorted(self._client_order_ids)))

    def load_idempotency(self) -> int:
        """Load previously persisted client_order_ids. Returns count loaded."""
        if self._idempotency_path is None or not self._idempotency_path.exists():
            return 0
        ids = json.loads(self._idempotency_path.read_text())
        self._client_order_ids.update(ids)
        return len(ids)

    def recover_from_ledger(self, ledger_path: str | Path) -> int:
        """Rebuild _client_order_ids from ledger orders.jsonl. Returns count."""
        ledger_dir = Path(ledger_path)
        orders_file = ledger_dir / "orders.jsonl"
        if not orders_file.exists():
            return 0
        count = 0
        for line in orders_file.read_text().strip().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                coid = record.get("client_order_id", "")
                if coid:
                    self._client_order_ids.add(coid)
                    count += 1
            except (json.JSONDecodeError, KeyError):
                continue
        return count

    # ------------------------------------------------------------------
    # Order state recovery
    # ------------------------------------------------------------------

    def _recover_order_state(self, order: Order) -> Order | None:
        """Query broker to locate an order after a failed ``submit_order()`` call.

        Searches ``broker.get_orders()`` by ``client_order_id`` (and fallback
        ``order_id``). Returns the order with synced status if found, or
        ``None`` when the broker has no record of the order (status set to
        ``UNKNOWN``).

        This is safe to call during exception handling because it catches its
        own broker errors.
        """
        try:
            broker_orders = self.broker.get_orders()
        except Exception:
            order.status = OrderStatus.UNKNOWN
            order.updated_at = utc_now()
            return None

        # Search by client_order_id first (most reliable cross-broker key)
        for bo in broker_orders:
            if bo.client_order_id == order.client_order_id:
                order.status = bo.status
                order.order_id = bo.order_id
                order.broker_order_id = bo.broker_order_id
                order.updated_at = utc_now()
                return order

        # Fallback: search by local order_id
        if order.order_id:
            for bo in broker_orders:
                if bo.order_id == order.order_id:
                    order.status = bo.status
                    order.order_id = bo.order_id
                    order.broker_order_id = bo.broker_order_id
                    order.updated_at = utc_now()
                    return order

        # Broker has no record of this order
        order.status = OrderStatus.UNKNOWN
        order.updated_at = utc_now()
        return None

    # ------------------------------------------------------------------
    # Risk event log helper
    # ------------------------------------------------------------------

    def _log_risk_rejection(
        self,
        rule_name: str,
        intent: OrderIntent,
        decision: RiskDecision,
    ) -> None:
        """Write a ``risk_rejected`` entry to the event log if configured."""
        if self.risk_event_log is not None:
            self.risk_event_log.record(
                "risk_rejected",
                details={
                    "rule": rule_name,
                    "symbol": intent.symbol,
                    "side": intent.side.value if hasattr(intent.side, "value") else str(intent.side),
                    "quantity": intent.quantity,
                    "strategy_id": intent.strategy_id,
                    "order_intent_id": intent.order_intent_id,
                    "reason": decision.reason,
                    "risk_version": decision.risk_version,
                },
            )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def handle_intent(
        self,
        intent: OrderIntent,
        account: AccountState,
        market_price: float,
        timestamp: datetime | None = None,
    ) -> OMSResult:
        effective_time = timestamp or intent.timestamp_utc
        if self.kill_switch is not None and self.kill_switch.update_equity(account.equity):
            decision = RiskDecision(False, f"kill_switch_{self.kill_switch.reason}", intent.order_intent_id)
            self._log_risk_rejection("kill_switch_triggered", intent, decision)
            return OMSResult(intent=intent, risk_decision=decision, events=[RiskEvent.from_decision(decision)])

        if intent.client_order_id in self._client_order_ids:
            decision = RiskDecision(False, "duplicate_client_order_id", intent.order_intent_id)
            self._log_risk_rejection("duplicate_client_order_id", intent, decision)
            return OMSResult(intent=intent, risk_decision=decision, events=[RiskEvent.from_decision(decision)])

        # Reduce-only mode: reconciliation halt — allow closing/reducing, block opening/increasing
        if self.reduce_only:
            current_pos = account.positions.get(intent.symbol)
            current_qty = current_pos.quantity if current_pos else 0.0
            allowed, reason = self._reduce_only_allows(intent, current_qty)
            if not allowed:
                decision = RiskDecision(False, reason, intent.order_intent_id)
                self._log_risk_rejection(reason, intent, decision)
                return OMSResult(intent=intent, risk_decision=decision, events=[RiskEvent.from_decision(decision)])

        decision = self.risk_engine.evaluate(intent, account, market_price, effective_time)
        events: list[Event] = [RiskEvent.from_decision(decision)]
        if not decision.approved:
            self._log_risk_rejection("risk_engine", intent, decision)
            return OMSResult(intent=intent, risk_decision=decision, events=events)

        order = Order.from_intent(intent, decision)
        order.status = OrderStatus.SUBMITTED
        order.updated_at = utc_now()
        try:
            submitted = self.broker.submit_order(order)
            self._client_order_ids.add(intent.client_order_id)
            self.persist_idempotency()
            if self.kill_switch is not None:
                if submitted.status in {OrderStatus.REJECTED, OrderStatus.ERROR}:
                    self.kill_switch.record_order_failure()
                else:
                    self.kill_switch.record_order_success()
        except Exception:
            if self.kill_switch is not None:
                self.kill_switch.record_order_failure()
            if self.risk_event_log is not None:
                self.risk_event_log.record(
                    "broker_timeout",
                    {"client_order_id": order.client_order_id, "symbol": order.symbol},
                )
            # Attempt to recover by querying broker for the order
            recovered = self._recover_order_state(order)
            if recovered is not None:
                # Broker accepted the order despite the timeout — treat as success
                self._client_order_ids.add(intent.client_order_id)
                self.persist_idempotency()
                fills = self.broker.get_fills(order_id=recovered.order_id)
                events.append(BrokerOrderEvent.from_order(recovered))
                events.extend(FillEvent.from_fill(fill) for fill in fills)
                return OMSResult(intent=intent, risk_decision=decision, order=recovered, fills=fills, events=events)
            order.status = OrderStatus.ERROR
            order.updated_at = utc_now()
            raise
        fills = self.broker.get_fills(order_id=submitted.order_id)
        events.append(BrokerOrderEvent.from_order(submitted))
        events.extend(FillEvent.from_fill(fill) for fill in fills)
        return OMSResult(intent=intent, risk_decision=decision, order=submitted, fills=fills, events=events)

    @staticmethod
    def _reduce_only_allows(intent: OrderIntent, current_qty: float) -> tuple[bool, str]:
        """Allow only orders that strictly reduce exposure without crossing zero."""
        eps = 1e-9
        qty = float(intent.quantity)
        if abs(current_qty) <= eps:
            if intent.side == OrderSide.BUY:
                return False, "reduce_only_no_new_buys"
            return False, "reduce_only_no_new_shorts"

        signed_delta = qty if intent.side == OrderSide.BUY else -qty
        projected_qty = current_qty + signed_delta

        if current_qty > eps:
            if intent.side == OrderSide.BUY:
                return False, "reduce_only_no_new_buys"
            if projected_qty < -eps:
                return False, "reduce_only_would_reverse_long"
            if abs(projected_qty) >= abs(current_qty) - eps:
                return False, "reduce_only_would_not_reduce_long"
            return True, "ok"

        if intent.side == OrderSide.SELL:
            return False, "reduce_only_no_new_shorts"
        if projected_qty > eps:
            return False, "reduce_only_would_reverse_short"
        if abs(projected_qty) >= abs(current_qty) - eps:
            return False, "reduce_only_would_not_reduce_short"
        return True, "ok"
