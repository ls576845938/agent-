from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Bar, Order, OrderIntent
from quant_us.execution.order_lifecycle import OrderLifecycleManager
from quant_us.execution.oms import OrderManagementSystem
from quant_us.execution.paper_broker import PaperBroker
from quant_us.live.heartbeat import Heartbeat
from quant_us.live.runner import LiveRunner, LiveRunnerConfig
from quant_us.risk.data_freshness import DataFreshnessGuard
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig
from quant_us.risk.pre_trade import PreTradeRiskEngine


class RuntimeControlsTests(unittest.TestCase):
    def test_data_freshness_guard_blocks_stale_bar(self) -> None:
        now = datetime(2024, 1, 2, 15, 35, tzinfo=timezone.utc)
        bar = Bar(
            timestamp_utc=now - timedelta(minutes=10),
            symbol="AAPL",
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1000,
        )

        decision = DataFreshnessGuard().evaluate_bar(bar, now=now)

        self.assertFalse(decision.fresh)
        self.assertEqual(decision.reason, "market_data_stale")

    def test_order_lifecycle_cancels_stale_open_orders(self) -> None:
        broker = PaperBroker()
        old_order = Order(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            strategy_id="portfolio",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="client_1",
            status=OrderStatus.ACCEPTED,
            updated_at=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
        )
        broker.orders.append(old_order)

        actions = OrderLifecycleManager().cancel_stale_orders(
            broker,
            now=datetime(2024, 1, 2, 15, 40, tzinfo=timezone.utc),
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].reason, "order_timeout")
        self.assertEqual(broker.orders[0].status, OrderStatus.CANCELLED)

    def test_oms_rejects_when_kill_switch_is_triggered(self) -> None:
        broker = PaperBroker()
        kill_switch = KillSwitch(KillSwitchConfig(max_daily_loss_pct=0.05))
        kill_switch.update_equity(100_000.0)
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=PreTradeRiskEngine(),
            kill_switch=kill_switch,
        )
        account = AccountState(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            account_id="paper",
            cash=90_000.0,
            equity=90_000.0,
            buying_power=90_000.0,
        )
        intent = OrderIntent(
            timestamp_utc=account.timestamp_utc,
            strategy_id="portfolio",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1.0,
        )

        result = oms.handle_intent(intent, account=account, market_price=100.0, timestamp=account.timestamp_utc)

        self.assertFalse(result.risk_decision.approved)
        self.assertTrue(result.risk_decision.reason.startswith("kill_switch_"))
        self.assertEqual(broker.orders, [])

    def test_live_runner_blocks_until_live_orders_enabled(self) -> None:
        runner = LiveRunner(
            oms=OrderManagementSystem(PaperBroker(), PreTradeRiskEngine()),
            heartbeat=Heartbeat("live"),
        )
        blocked = runner.start(dry_run=True)
        self.assertEqual(blocked.status, "blocked")
        self.assertIn("live_orders_disabled", blocked.errors)

        runner.config = LiveRunnerConfig(allow_live_orders=True)
        ready = runner.start(dry_run=True)
        self.assertEqual(ready.status, "ready")


if __name__ == "__main__":
    unittest.main()
