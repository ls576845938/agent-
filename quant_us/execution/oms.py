from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderStatus
from quant_us.core.events import BrokerOrderEvent, Event, FillEvent, RiskEvent
from quant_us.core.types import AccountState, Fill, Order, OrderIntent, RiskDecision
from quant_us.execution.broker_base import BrokerBase
from quant_us.risk.kill_switch import KillSwitch
from quant_us.risk.pre_trade import PreTradeRiskEngine


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
    ) -> None:
        self.broker = broker
        self.risk_engine = risk_engine
        self.calendar = calendar or USEquityCalendar()
        self.kill_switch = kill_switch
        self._client_order_ids: set[str] = set()

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
            return OMSResult(intent=intent, risk_decision=decision, events=[RiskEvent.from_decision(decision)])

        if intent.client_order_id in self._client_order_ids:
            decision = RiskDecision(False, "duplicate_client_order_id", intent.order_intent_id)
            return OMSResult(intent=intent, risk_decision=decision, events=[RiskEvent.from_decision(decision)])

        decision = self.risk_engine.evaluate(intent, account, market_price, effective_time)
        events: list[Event] = [RiskEvent.from_decision(decision)]
        if not decision.approved:
            return OMSResult(intent=intent, risk_decision=decision, events=events)

        order = Order.from_intent(intent, decision)
        order.status = OrderStatus.SUBMITTED
        order.updated_at = utc_now()
        try:
            submitted = self.broker.submit_order(order)
            self._client_order_ids.add(intent.client_order_id)
            if self.kill_switch is not None:
                if submitted.status in {OrderStatus.REJECTED, OrderStatus.ERROR}:
                    self.kill_switch.record_order_failure()
                else:
                    self.kill_switch.record_order_success()
        except Exception:
            if self.kill_switch is not None:
                self.kill_switch.record_order_failure()
            order.status = OrderStatus.ERROR
            order.updated_at = utc_now()
            raise
        fills = self.broker.get_fills(order_id=submitted.order_id)
        events.append(BrokerOrderEvent.from_order(submitted))
        events.extend(FillEvent.from_fill(fill) for fill in fills)
        return OMSResult(intent=intent, risk_decision=decision, order=submitted, fills=fills, events=events)
