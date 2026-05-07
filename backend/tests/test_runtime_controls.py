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
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine


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
            risk_engine=PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True)),
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

    def test_live_runner_paper_mode_is_ready_by_default(self) -> None:
        """Paper mode (allow_live_orders=False) is valid; readiness should pass."""
        runner = LiveRunner(
            oms=OrderManagementSystem(PaperBroker(), PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True))),
            heartbeat=Heartbeat("live"),
        )
        report = runner.start(dry_run=True)
        self.assertEqual(report.status, "ready")
        self.assertFalse(report.checks["live_orders_enabled"])


    def test_kill_switch_trip_public_api(self) -> None:
        """trip() is the public API for manually triggering the kill switch."""
        ks = KillSwitch(KillSwitchConfig())
        result = ks.trip("manual_override")
        self.assertTrue(result)
        self.assertTrue(ks.triggered)
        self.assertEqual(ks.reason, "manual_override")

    def test_kill_switch_trigger_delegates_to_trip(self) -> None:
        """_trigger() delegates to trip() — both produce the same result."""
        ks = KillSwitch(KillSwitchConfig())
        result = ks._trigger("via_internal")
        self.assertTrue(result)
        self.assertTrue(ks.triggered)
        self.assertEqual(ks.reason, "via_internal")

    def test_kill_switch_trip_with_risk_event_log(self) -> None:
        """trip() writes to risk_event_log when configured."""
        import tempfile
        from pathlib import Path

        from quant_us.risk.risk_event_log import RiskEventLog

        with tempfile.TemporaryDirectory() as tmp:
            log = RiskEventLog(Path(tmp) / "risk_events.jsonl")
            ks = KillSwitch(KillSwitchConfig(), risk_event_log=log)
            ks.trip("test_reason")
            events = log.query(event_type="kill_switch_triggered")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["details"]["reason"], "test_reason")


    def test_live_runtime_paper_mode_submits_to_oms(self) -> None:
        from quant_us.live.modes import RuntimeMode
        from quant_us.live.runtime import LiveRuntime
        from quant_us.live.runtime_config import LiveRuntimeConfig

        config = LiveRuntimeConfig(
            mode=RuntimeMode.PAPER,
            submit_orders=True,
        )
        runtime = LiveRuntime(config=config)
        runtime.bootstrap()

        oms = OrderManagementSystem(PaperBroker(), PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True)))
        runtime.oms = oms

        account = AccountState(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            account_id="paper",
            cash=100_000.0,
            equity=100_000.0,
            buying_power=100_000.0,
        )
        intent = OrderIntent(
            timestamp_utc=account.timestamp_utc,
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            client_order_id="paper_test_001",
        )

        result = runtime.submit_orders([intent], account=account, market_price=100.0)

        self.assertEqual(len(result["submitted"]), 1)
        self.assertEqual(len(result["rejected"]), 0)
        self.assertEqual(result["mode"], "paper")
        self.assertGreater(len(runtime._submitted_order_ids), 0)

    def test_live_runtime_paper_mode_rejects_duplicate(self) -> None:
        from quant_us.live.modes import RuntimeMode
        from quant_us.live.runtime import LiveRuntime
        from quant_us.live.runtime_config import LiveRuntimeConfig

        config = LiveRuntimeConfig(mode=RuntimeMode.PAPER, submit_orders=True)
        runtime = LiveRuntime(config=config)
        runtime.bootstrap()
        runtime.oms = OrderManagementSystem(PaperBroker(), PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True)))
        account = AccountState(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            account_id="paper", cash=100_000.0, equity=100_000.0, buying_power=100_000.0,
        )
        intent = OrderIntent(
            timestamp_utc=account.timestamp_utc,
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=10.0, client_order_id="dup_test_001",
        )

        r1 = runtime.submit_orders([intent], account=account, market_price=100.0)
        self.assertEqual(len(r1["submitted"]), 1)
        r2 = runtime.submit_orders([intent], account=account, market_price=100.0)
        self.assertEqual(len(r2["submitted"]), 0)
        self.assertEqual(len(r2["rejected"]), 1)
        self.assertIn("duplicate", r2["rejected"][0]["reason"])

    def test_live_runtime_kill_switch_blocks_orders(self) -> None:
        from quant_us.live.modes import RuntimeMode
        from quant_us.live.runtime import LiveRuntime
        from quant_us.live.runtime_config import LiveRuntimeConfig

        config = LiveRuntimeConfig(mode=RuntimeMode.PAPER, submit_orders=True)
        runtime = LiveRuntime(config=config)
        runtime.bootstrap()
        runtime.oms = OrderManagementSystem(PaperBroker(), PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True)))
        account = AccountState(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            account_id="paper", cash=100_000.0, equity=100_000.0, buying_power=100_000.0,
        )
        intent = OrderIntent(
            timestamp_utc=account.timestamp_utc,
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=10.0, client_order_id="ks_test_001",
        )
        result = runtime.submit_orders([intent], account=account, market_price=100.0, kill_switch_triggered=True)
        self.assertEqual(len(result["submitted"]), 0)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn("kill_switch_active", result["rejected"][0]["reason"])

    def test_live_runtime_reconciliation_dirty_blocks_orders(self) -> None:
        from quant_us.live.modes import RuntimeMode
        from quant_us.live.runtime import LiveRuntime
        from quant_us.live.runtime_config import LiveRuntimeConfig

        config = LiveRuntimeConfig(mode=RuntimeMode.PAPER, submit_orders=True, require_reconciliation_clean=True)
        runtime = LiveRuntime(config=config)
        runtime.bootstrap()
        runtime.oms = OrderManagementSystem(PaperBroker(), PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True)))
        account = AccountState(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            account_id="paper", cash=100_000.0, equity=100_000.0, buying_power=100_000.0,
        )
        intent = OrderIntent(
            timestamp_utc=account.timestamp_utc,
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=10.0, client_order_id="recon_test_001",
        )
        result = runtime.submit_orders([intent], account=account, market_price=100.0, reconciliation_clean=False)
        self.assertEqual(len(result["submitted"]), 0)
        self.assertIn("reconciliation_not_clean", result["rejected"][0]["reason"])

    def test_live_runtime_live_mode_default_blocked(self) -> None:
        from quant_us.live.modes import RuntimeMode
        from quant_us.live.runtime import LiveRuntime
        from quant_us.live.runtime_config import LiveRuntimeConfig

        config = LiveRuntimeConfig(mode=RuntimeMode.LIVE, allow_live_orders=False, confirm_live=False)
        runtime = LiveRuntime(config=config)
        runtime.bootstrap()
        runtime.oms = OrderManagementSystem(PaperBroker(), PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True)))
        account = AccountState(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            account_id="live", cash=100_000.0, equity=100_000.0, buying_power=100_000.0,
        )
        intent = OrderIntent(
            timestamp_utc=account.timestamp_utc,
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=10.0, client_order_id="live_test_001",
        )
        result = runtime.submit_orders([intent], account=account, market_price=100.0)
        self.assertEqual(len(result["submitted"]), 0)
        self.assertIn("live_blocked", result["rejected"][0]["reason"])

    def test_live_runtime_shadow_mode_audit_marked(self) -> None:
        from quant_us.live.modes import RuntimeMode
        from quant_us.live.runtime import LiveRuntime
        from quant_us.live.runtime_config import LiveRuntimeConfig

        config = LiveRuntimeConfig(mode=RuntimeMode.SHADOW_LIVE, submit_orders=True)
        runtime = LiveRuntime(config=config)
        runtime.bootstrap()
        runtime.oms = OrderManagementSystem(PaperBroker(), PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True)))
        account = AccountState(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            account_id="paper", cash=100_000.0, equity=100_000.0, buying_power=100_000.0,
        )
        intent = OrderIntent(
            timestamp_utc=account.timestamp_utc,
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=10.0, client_order_id="shadow_test_001",
        )
        result = runtime.submit_orders([intent], account=account, market_price=100.0)
        self.assertEqual(len(result["submitted"]), 1)
        shadow_events = [e for e in result["audit_events"] if e["event"] == "shadow_order_submitted"]
        self.assertEqual(len(shadow_events), 1)
        self.assertIn("paper broker only", shadow_events[0]["note"])


if __name__ == "__main__":
    unittest.main()
