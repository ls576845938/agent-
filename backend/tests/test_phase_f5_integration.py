from __future__ import annotations

import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.cli import main
from quant_us.core.enums import OrderSide, OrderType, SignalDirection, TimeInForce
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, OrderIntent, Position, Signal
from quant_us.execution.oms import OrderManagementSystem
from quant_us.execution.paper_broker import PaperBroker
from quant_us.live.modes import RuntimeMode
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig
from quant_us.live.runtime import LiveRuntime
from quant_us.live.runtime_config import LiveRuntimeConfig
from quant_us.live.shadow_live import ReadOnlyBrokerProxy, ShadowLiveConfig
from quant_us.risk.kill_switch import KillSwitch
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.strategies.base import Strategy, StrategyContext


UTC = timezone.utc


def _bar(symbol: str = "AAPL", price: float = 100.0, minute: int = 30) -> Bar:
    return Bar(
        timestamp_utc=datetime(2026, 5, 4, 14, minute, tzinfo=UTC),
        symbol=symbol,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=100_000,
        source="test",
    )


class NoopStrategy(Strategy):
    strategy_id = "noop"

    def __init__(self) -> None:
        self.calls = 0

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        self.calls += 1
        return []


class OneSignalStrategy(Strategy):
    strategy_id = "one_signal"

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=0.1,
                horizon="1d",
            )
        ]


class RecordingBroker(SimulatedBroker):
    def __init__(self) -> None:
        super().__init__(initial_cash=100_000.0, broker_name="recording")
        self.update_calls = 0

    def update_market(self, bar: Bar) -> None:
        self.update_calls += 1
        super().update_market(bar)


class PhaseF5IntegrationTests(unittest.TestCase):
    def test_runtime_quality_imports_and_killswitch_public_api(self) -> None:
        from quant_us.live.shadow_live import PaperBroker as ImportedPaperBroker

        self.assertIs(ImportedPaperBroker, PaperBroker)
        kill_switch = KillSwitch()
        self.assertTrue(kill_switch.trip("manual_phase_f5_test"))
        self.assertTrue(kill_switch.triggered)
        self.assertEqual(kill_switch.reason, "manual_phase_f5_test")

    def test_engine_broker_injection(self) -> None:
        broker = RecordingBroker()
        engine = EventDrivenBacktestEngine(
            strategies=[],
            config=BacktestConfig(),
            broker=broker,
        )

        result = engine.run([_bar()])

        self.assertIs(engine.broker, broker)
        self.assertEqual(broker.update_calls, 1)
        self.assertEqual(len(result.snapshots), 1)
        self.assertEqual(engine.connection_health()["broker"], "recording")

    def test_engine_streaming_market_events(self) -> None:
        engine = EventDrivenBacktestEngine(strategies=[NoopStrategy()], config=BacktestConfig())
        events = [MarketEvent.from_bar(_bar("AAPL", 100, 30)), MarketEvent.from_bar(_bar("MSFT", 250, 30))]

        result = engine.run_streaming(events)

        self.assertEqual(len(result.snapshots), 1)
        self.assertEqual(len([evt for evt in result.events if isinstance(evt, MarketEvent)]), 2)
        self.assertEqual(len(engine._stream_events), 0)

    def test_strategy_stream_adapter_falls_back_to_on_bar(self) -> None:
        strategy = NoopStrategy()
        event = MarketEvent.from_bar(_bar())
        context = StrategyContext(run_id="adapter")

        signals = list(strategy.on_market_event(event, context))

        self.assertEqual(signals, [])
        self.assertEqual(strategy.calls, 1)

    def test_trading_mode_live_is_gate_blocked(self) -> None:
        runtime = LiveRuntime(LiveRuntimeConfig(mode=RuntimeMode.LIVE))

        health = runtime.bootstrap()

        self.assertFalse(health.ok)
        self.assertIn("allow_live_orders_false", health.errors)
        self.assertIn("confirm_live_missing", health.errors)

    def test_shadow_live_cannot_submit_real_order(self) -> None:
        with self.assertRaises(ValueError):
            ShadowLiveConfig(submit_real_orders=True)
        with self.assertRaises(ValueError):
            LiveRuntimeConfig(mode=RuntimeMode.SHADOW_LIVE, allow_live_orders=True)

    def test_reconciliation_fail_blocks_new_orders(self) -> None:
        broker = PaperBroker()
        oms = OrderManagementSystem(
            broker,
            PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True)),
        )
        oms.reduce_only = True
        account = AccountState(
            timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
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
            quantity=1,
        )

        result = oms.handle_intent(intent, account, market_price=100.0, timestamp=account.timestamp_utc)

        self.assertFalse(result.risk_decision.approved)
        self.assertEqual(result.risk_decision.reason, "reduce_only_no_new_buys")
        self.assertEqual(broker.get_orders(), [])

    def test_runtime_restart_no_duplicate_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "idempotency.json"
            account = AccountState(
                timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
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
                quantity=1,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                client_order_id="stable-client-order-id",
            )
            risk = PreTradeRiskEngine(PreTradeRiskConfig(skip_session_check=True))
            first = OrderManagementSystem(PaperBroker(), risk, idempotency_path=path)
            first_result = first.handle_intent(intent, account, market_price=100.0, timestamp=account.timestamp_utc)
            self.assertTrue(first_result.risk_decision.approved)

            restarted = OrderManagementSystem(PaperBroker(), risk, idempotency_path=path)
            self.assertEqual(restarted.load_idempotency(), 1)
            duplicate = restarted.handle_intent(intent, account, market_price=100.0, timestamp=account.timestamp_utc)

            self.assertFalse(duplicate.risk_decision.approved)
            self.assertEqual(duplicate.risk_decision.reason, "duplicate_client_order_id")

    def test_live_command_default_is_safe(self) -> None:
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            main(["live", "dry-run"])

        text = stdout.getvalue()
        self.assertIn("Live Dry Run", text)
        self.assertIn("real_order_submission: DISABLED", text)

    def test_live_start_is_gate_blocked(self) -> None:
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    main(["live", "start"])

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Readiness checks failed", stderr.getvalue())

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_paper_runtime_full_day_with_simulated_broker(self, mock_loop_cls: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mock_loop = mock_loop_cls.return_value
            status = mock.MagicMock()
            status.fresh = True
            status.stale_seconds = 0.0
            status.symbols_updated = ["AAPL"]
            mock_loop.run_once.return_value = status
            mock_loop.fetch_latest_bars.return_value = pd.DataFrame([
                {
                    "symbol": "AAPL",
                    "timestamp_utc": datetime(2026, 5, 4, 14, 30, tzinfo=UTC).isoformat(),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 100_000.0,
                }
            ])
            runtime = PaperRuntime(
                PaperRuntimeConfig(
                    symbols=["AAPL"],
                    ledger_root=str(Path(tmp) / "ledger"),
                    reconcile_on_start=False,
                    reconcile_on_close=False,
                    submit_orders=False,
                    poll_interval_seconds=0.0,
                    max_data_delay_seconds=10_000_000.0,
                )
            )
            runtime.bootstrap(strategy=OneSignalStrategy())
            calls = {"count": 0}

            def one_cycle() -> bool:
                calls["count"] += 1
                return calls["count"] <= 1

            runtime._should_keep_running = one_cycle  # type: ignore[method-assign]
            runtime._sleep = lambda: None  # type: ignore[method-assign]

            runtime.run_market_session()
            runtime.on_session_close()
            runtime.shutdown()

            self.assertEqual(len(runtime.metrics_log), 1)
            self.assertEqual(runtime.metrics_log[0].signals_generated, 1)
            self.assertEqual(runtime.metrics_log[0].intents_submitted, 0)


if __name__ == "__main__":
    unittest.main()
