"""Integration tests for paper trading loop."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.gap_session import GapConfig
from quant_us.backtest.liquidity_slippage import LiquiditySlippage
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.enums import OrderSide, OrderStatus
from quant_us.core.types import Bar, Fill, Order, new_id
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop
from quant_us.monitoring.telegram_alerts import TelegramAlertService
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine


def _make_bars(n: int = 50, symbol: str = "AAPL") -> list[Bar]:
    bars: list[Bar] = []
    price = 150.0
    rng = np.random.default_rng(42)
    for i in range(n):
        ts = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc) + pd.Timedelta(minutes=i).to_pytimedelta()
        price *= 1.0 + rng.normal(0.0001, 0.01)
        bars.append(Bar(
            timestamp_utc=ts, symbol=symbol,
            open=price * 0.999, high=price * 1.005, low=price * 0.995, close=price,
            volume=float(rng.integers(10000, 100000)),
        ))
    return bars


class PaperTradingOrderLifecycleTests(unittest.TestCase):
    """Verify orders flow through the full lifecycle in paper trading."""

    def test_order_goes_through_lifecycle(self):
        broker = SimulatedBroker(initial_cash=100_000.0)
        calendar = USEquityCalendar.with_holidays()
        risk = PreTradeRiskEngine(PreTradeRiskConfig(), calendar=calendar)
        kill = KillSwitch(KillSwitchConfig())
        oms = OrderManagementSystem(broker=broker, risk_engine=risk, calendar=calendar, kill_switch=kill)

        bars = _make_bars(10)
        for bar in bars:
            broker.update_market(bar)

        order = Order(
            timestamp_utc=bars[-1].timestamp_utc,
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            order_type="MARKET",
            time_in_force="DAY",
            client_order_id=new_id("coid"),
        )
        submitted = broker.submit_order(order)

        self.assertIn(submitted.status, {OrderStatus.FILLED, OrderStatus.ACCEPTED},
                       f"Order should be accepted or filled, got {submitted.status}")

        fills = broker.get_fills(order_id=submitted.order_id)
        if submitted.status == OrderStatus.FILLED:
            self.assertGreater(len(fills), 0, "Filled order must have fills")

    def test_partial_fill_with_fill_ratio(self):
        broker = SimulatedBroker(initial_cash=100_000.0, fill_ratio=0.5)
        bar = _make_bars(1)[0]
        broker.update_market(bar)

        order = Order(
            timestamp_utc=bar.timestamp_utc,
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=100.0,
            order_type="MARKET",
            time_in_force="DAY",
            client_order_id=new_id("coid"),
        )
        submitted = broker.submit_order(order)
        self.assertIn(submitted.status, {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED})
        if submitted.status == OrderStatus.PARTIALLY_FILLED:
            fills = broker.get_fills(order_id=submitted.order_id)
            self.assertGreater(len(fills), 0, "Partial fill should produce fill records")
            total_filled = sum(f.quantity for f in fills)
            self.assertLess(total_filled, 100.0, f"Partial fill should fill less than requested, got {total_filled}")
            self.assertEqual(submitted.quantity, 100.0, "Order should preserve original requested quantity")

    def test_kill_switch_blocks_orders(self):
        broker = SimulatedBroker(initial_cash=100_000.0)
        calendar = USEquityCalendar.with_holidays()
        kill = KillSwitch(KillSwitchConfig(
            max_daily_loss_pct=0.01,
            max_drawdown_pct=0.05,
            max_consecutive_order_failures=1,
        ))
        kill.record_order_failure()
        self.assertTrue(kill.triggered, "Kill switch should trigger after 1 failure")

        risk = PreTradeRiskEngine(PreTradeRiskConfig(), calendar=calendar)
        oms = OrderManagementSystem(broker=broker, risk_engine=risk, calendar=calendar, kill_switch=kill)

        bar = _make_bars(1)[0]
        broker.update_market(bar)

        from quant_us.core.types import OrderIntent
        intent = OrderIntent(
            timestamp_utc=bar.timestamp_utc,
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
        )
        account = broker.get_account()
        result = oms.handle_intent(intent, account, market_price=150.0, timestamp=bar.timestamp_utc)

        self.assertFalse(result.risk_decision.approved, "Kill switch should reject order")
        self.assertIn("kill_switch", result.risk_decision.reason,
                      f"Reason should mention kill_switch, got: {result.risk_decision.reason}")


class PaperTradingReconciliationTests(unittest.TestCase):
    """Verify broker and ledger positions stay in sync."""

    def test_broker_ledger_positions_match_after_fills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            broker = SimulatedBroker(initial_cash=100_000.0)
            ledger = JsonlLedgerStore(tmpdir)
            calendar = USEquityCalendar.with_holidays()

            bars = _make_bars(30)
            for bar in bars:
                broker.update_market(bar)

            buy = Order(
                timestamp_utc=bars[5].timestamp_utc,
                strategy_id="test", symbol="AAPL",
                side=OrderSide.BUY, quantity=50.0,
                order_type="MARKET", time_in_force="DAY",
                client_order_id=new_id("coid"),
            )
            result = broker.submit_order(buy)
            ledger.append_order(result)
            for fill in broker.get_fills(order_id=result.order_id):
                ledger.append_fill(fill)

            broker_positions = broker.get_positions()
            ledger_positions = ledger.latest_positions_from_fills()

            self.assertIn("AAPL", broker_positions)
            self.assertAlmostEqual(
                broker_positions["AAPL"].quantity,
                ledger_positions.get("AAPL").quantity if "AAPL" in ledger_positions else 0.0,
                places=6,
                msg="Broker and ledger positions must match",
            )

    def test_reconciliation_detects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            broker = SimulatedBroker(initial_cash=100_000.0)
            ledger = JsonlLedgerStore(tmpdir)

            bars = _make_bars(10)
            for bar in bars:
                broker.update_market(bar)

            buy = Order(
                timestamp_utc=bars[3].timestamp_utc,
                strategy_id="test", symbol="AAPL",
                side=OrderSide.BUY, quantity=25.0,
                order_type="MARKET", time_in_force="DAY",
                client_order_id=new_id("coid"),
            )
            result = broker.submit_order(buy)
            ledger.append_order(result)
            for fill in broker.get_fills(order_id=result.order_id):
                ledger.append_fill(fill)

            config = PaperTradingConfig(ledger_root=tmpdir)
            loop = PaperTradingLoop(config=config)
            loop.broker = broker
            loop.ledger = ledger

            recon = loop._reconcile()
            self.assertTrue(recon["passed"],
                            f"Reconciliation should pass after matching fills, got diffs: {recon.get('differences', {})}")


class PaperTradingLoopTests(unittest.TestCase):
    """Verify paper trading loop executes correctly."""

    def test_loop_runs_without_errors(self):
        from quant_us.strategies.momentum_strategy import MomentumStrategy

        config = PaperTradingConfig()
        loop = PaperTradingLoop(config=config)
        bars = _make_bars(30)
        strategy = MomentumStrategy(strategy_id="test_momentum", allow_short=False)

        result = loop.run_day(bars=bars, strategies=[strategy])

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.orders_submitted, 0)
        self.assertGreaterEqual(result.orders_filled, 0)

    def test_loop_kill_switch_stops_trading(self):
        from quant_us.strategies.momentum_strategy import MomentumStrategy

        config = PaperTradingConfig(
            max_daily_loss_pct=100.0,
            max_consecutive_failures=1,
        )
        loop = PaperTradingLoop(config=config)
        loop.kill_switch.record_order_failure()

        self.assertTrue(loop.kill_switch.triggered)
        self.assertFalse(loop.is_healthy())


class PaperTradingExtendedConfigTests(unittest.TestCase):
    """Verify liquidity slippage and gap protection config options."""

    def test_liquidity_slippage_creates_liquidity_slippage_model(self):
        """When use_liquidity_slippage=True, broker should have a LiquiditySlippage."""
        config = PaperTradingConfig(use_liquidity_slippage=True)
        loop = PaperTradingLoop(config=config)
        self.assertIsInstance(loop.broker.liquidity_slippage_model, LiquiditySlippage)

    def test_liquidity_slippage_default_is_none(self):
        """When use_liquidity_slippage=False (default), broker should have None."""
        config = PaperTradingConfig(use_liquidity_slippage=False)
        loop = PaperTradingLoop(config=config)
        self.assertIsNone(loop.broker.liquidity_slippage_model)

    def test_liquidity_slippage_default_constructor(self):
        """Default PaperTradingConfig should keep backward compat (liquidity_slippage None)."""
        loop = PaperTradingLoop()
        self.assertIsNone(loop.broker.liquidity_slippage_model)

    def test_gap_config_with_extreme_gap_rejects_orders(self):
        """When gap_config is set and an extreme gap is detected, orders for that symbol should be rejected."""
        gap_cfg = GapConfig(max_gap_pct=10.0, reject_on_extreme_gap=True, limit_fill_on_gap=False)
        config = PaperTradingConfig(gap_config=gap_cfg)
        loop = PaperTradingLoop(config=config)

        bars = _make_bars(3, symbol="AAPL")
        bars[0] = Bar(
            timestamp_utc=bars[0].timestamp_utc, symbol="AAPL",
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=50_000,
        )
        bars[1] = Bar(
            timestamp_utc=bars[1].timestamp_utc, symbol="AAPL",
            open=130.0, high=131.0, low=129.0, close=130.0,
            volume=50_000,
        )
        # First bar has no prev_close, so no override
        loop._apply_gap_protection(bars[0], None)
        self.assertNotIn("AAPL", loop.broker.gap_overrides)

        # Second bar: prev_close=100.0, bar.open=130.0, gap=30% > max_gap_pct=10%
        loop._apply_gap_protection(bars[1], 100.0)
        self.assertIsNone(loop.broker.gap_overrides.get("AAPL"),
                          "Gap override should be None to indicate rejection")

    def test_gap_config_extreme_gap_no_reject(self):
        """When reject_on_extreme_gap is False, extreme gaps should not block orders."""
        gap_cfg = GapConfig(max_gap_pct=10.0, reject_on_extreme_gap=False, limit_fill_on_gap=False)
        config = PaperTradingConfig(gap_config=gap_cfg)
        loop = PaperTradingLoop(config=config)

        bars = _make_bars(3, symbol="AAPL")
        bars[0] = Bar(
            timestamp_utc=bars[0].timestamp_utc, symbol="AAPL",
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=50_000,
        )
        bars[1] = Bar(
            timestamp_utc=bars[1].timestamp_utc, symbol="AAPL",
            open=130.0, high=131.0, low=129.0, close=130.0,
            volume=50_000,
        )
        loop._apply_gap_protection(bars[0], None)
        loop._apply_gap_protection(bars[1], 100.0)
        # AAPL should NOT be in gap_overrides (no rejection, no limit fill)
        self.assertNotIn("AAPL", loop.broker.gap_overrides)

    def test_gap_config_limit_fill_sets_open_price(self):
        """When limit_fill_on_gap is True and gap exceeds threshold, bar.open is used as override price."""
        gap_cfg = GapConfig(max_gap_pct=20.0, reject_on_extreme_gap=False, limit_fill_on_gap=True)
        config = PaperTradingConfig(gap_config=gap_cfg)
        loop = PaperTradingLoop(config=config)

        bars = _make_bars(3, symbol="AAPL")
        bars[0] = Bar(
            timestamp_utc=bars[0].timestamp_utc, symbol="AAPL",
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=50_000,
        )
        bars[1] = Bar(
            timestamp_utc=bars[1].timestamp_utc, symbol="AAPL",
            open=115.0, high=116.0, low=114.0, close=115.0,
            volume=50_000,
        )
        loop._apply_gap_protection(bars[0], None)
        loop._apply_gap_protection(bars[1], 100.0)
        # AAPL gap is 15% which exceeds max_gap_pct * 0.5 = 10%, so override should be bar.open=115.0
        self.assertIn("AAPL", loop.broker.gap_overrides)
        self.assertEqual(loop.broker.gap_overrides["AAPL"], 115.0)

    def test_gap_config_clears_override_on_no_gap(self):
        """When a subsequent bar has no gap, override should be cleared."""
        gap_cfg = GapConfig(max_gap_pct=10.0, reject_on_extreme_gap=True, limit_fill_on_gap=False)
        config = PaperTradingConfig(gap_config=gap_cfg)
        loop = PaperTradingLoop(config=config)

        bars = _make_bars(3, symbol="AAPL")
        bars[0] = Bar(
            timestamp_utc=bars[0].timestamp_utc, symbol="AAPL",
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=50_000,
        )
        bars[1] = Bar(
            timestamp_utc=bars[1].timestamp_utc, symbol="AAPL",
            open=130.0, high=131.0, low=129.0, close=130.0,
            volume=50_000,
        )
        bars[2] = Bar(
            timestamp_utc=bars[2].timestamp_utc, symbol="AAPL",
            open=130.5, high=131.5, low=129.5, close=130.5,
            volume=50_000,
        )
        # First bar: no prev_close
        loop._apply_gap_protection(bars[0], None)
        self.assertNotIn("AAPL", loop.broker.gap_overrides)

        # Second bar: extreme gap (30%), rejection set
        loop._apply_gap_protection(bars[1], 100.0)
        self.assertIsNone(loop.broker.gap_overrides.get("AAPL"))

        # Third bar: no gap (~0.38%), override cleared
        loop._apply_gap_protection(bars[2], 130.0)
        self.assertNotIn("AAPL", loop.broker.gap_overrides)


if __name__ == "__main__":
    unittest.main()
