from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.configuration import build_backtest_config
from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.core.enums import OrderSide, SessionName
from quant_us.core.types import AccountState, Bar, OrderIntent, Position, TargetPosition
from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.portfolio.allocation import AllocationCombiner, AllocationConfig
from quant_us.portfolio.rebalance import RebalancePlanner, RebalanceConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.strategies.momentum_strategy import MomentumStrategy


def _regular_session_bars(count: int = 60) -> list[Bar]:
    timestamp = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    price = 100.0
    while len(bars) < count:
        if timestamp.weekday() < 5:
            price *= 1.004
            bars.append(
                Bar(
                    timestamp_utc=timestamp,
                    symbol="AAPL",
                    open=price * 0.99,
                    high=price * 1.01,
                    low=price * 0.98,
                    close=price,
                    volume=5_000_000,
                    source="fixture",
                    session=SessionName.REGULAR.value,
                )
            )
        timestamp += timedelta(days=1)
    return bars


class QuantUSArchitectureTests(unittest.TestCase):
    def test_event_driven_backtest_uses_oms_and_risk_ids(self) -> None:
        config = BacktestConfig(
            initial_cash=100_000.0,
            risk=PreTradeRiskConfig(max_symbol_weight=0.10, max_order_notional_pct=0.10),
        )
        engine = EventDrivenBacktestEngine(
            strategies=[MomentumStrategy(lookback_bars=5, entry_threshold=0.01)],
            config=config,
        )

        result = engine.run(_regular_session_bars())

        self.assertGreater(result.summary["trade_count"], 0)
        self.assertTrue(result.orders)
        self.assertTrue(all(order.risk_check_id for order in result.orders))
        self.assertTrue(all(fill.order_id for fill in result.fills))
        self.assertGreater(result.snapshots[-1].equity, 0)

    def test_pre_trade_risk_rejects_short_sale_in_long_only_mode(self) -> None:
        account = AccountState(
            timestamp_utc=datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc),
            account_id="test",
            cash=100_000.0,
            equity=100_000.0,
            buying_power=100_000.0,
            positions={"AAPL": Position(symbol="AAPL", quantity=1.0, avg_price=100.0, market_price=100.0)},
        )
        intent = OrderIntent(
            timestamp_utc=account.timestamp_utc,
            strategy_id="portfolio",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=2.0,
        )

        decision = PreTradeRiskEngine().evaluate(intent, account, market_price=100.0, timestamp=account.timestamp_utc)

        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "long_only_short_sale")

    def test_bar_cleaner_deduplicates_and_marks_us_session(self) -> None:
        timestamp = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)
        raw = pd.DataFrame(
            [
                {"timestamp": timestamp, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
                {"timestamp": timestamp, "open": 100, "high": 103, "low": 99, "close": 102, "volume": 2000},
            ]
        )

        result = BarCleaner().clean(raw, symbol="AAPL", source="unit")

        self.assertEqual(result.duplicate_rows, 1)
        self.assertEqual(len(result.frame), 1)
        self.assertEqual(result.frame.iloc[0]["session"], SessionName.REGULAR.value)
        self.assertTrue(bool(result.frame.iloc[0]["is_regular_session"]))

    def test_simulated_broker_snapshot_drawdown_uses_high_water_mark(self) -> None:
        broker = SimulatedBroker(initial_cash=0.0)
        broker.positions["AAPL"] = Position(symbol="AAPL", quantity=1.0, avg_price=100.0, market_price=100.0)
        timestamp = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)

        broker.update_market(
            Bar(timestamp_utc=timestamp, symbol="AAPL", open=100, high=100, low=100, close=100, volume=1_000_000)
        )
        first = broker.snapshot(timestamp)
        broker.update_market(
            Bar(timestamp_utc=timestamp + timedelta(days=1), symbol="AAPL", open=80, high=80, low=80, close=80, volume=1_000_000)
        )
        second = broker.snapshot(timestamp + timedelta(days=1))

        self.assertEqual(first.drawdown, 0.0)
        self.assertAlmostEqual(second.drawdown, -0.2)

    def test_allocation_combiner_enforces_gross_cash_and_group_caps(self) -> None:
        timestamp = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)
        targets = [
            TargetPosition(timestamp_utc=timestamp, strategy_id="s1", symbol="AAPL", target_weight=0.20),
            TargetPosition(timestamp_utc=timestamp, strategy_id="s2", symbol="MSFT", target_weight=0.20),
            TargetPosition(timestamp_utc=timestamp, strategy_id="s3", symbol="XOM", target_weight=0.20),
        ]

        combined = AllocationCombiner(
            AllocationConfig(
                max_symbol_weight=0.20,
                cash_reserve_weight=0.20,
                max_group_weight=0.25,
                group_map={"AAPL": "technology", "MSFT": "technology", "XOM": "energy"},
            )
        ).combine(targets)

        weights = {target.symbol: target.target_weight for target in combined}
        self.assertLessEqual(sum(abs(weight) for weight in weights.values()), 0.80)
        self.assertLessEqual(abs(weights["AAPL"]) + abs(weights["MSFT"]), 0.25)
        self.assertEqual({target.metadata["group"] for target in combined}, {"technology", "energy"})

    def test_rebalance_planner_skips_small_weight_change(self) -> None:
        timestamp = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)
        account = AccountState(
            timestamp_utc=timestamp,
            account_id="test",
            cash=90_000.0,
            equity=100_000.0,
            buying_power=90_000.0,
            positions={"AAPL": Position(symbol="AAPL", quantity=100.0, avg_price=100.0, market_price=100.0)},
        )
        targets = [TargetPosition(timestamp_utc=timestamp, strategy_id="portfolio", symbol="AAPL", target_weight=0.101)]

        intents = RebalancePlanner(RebalanceConfig(min_weight_change=0.005)).plan(targets, account, {"AAPL": 100.0}, "run")

        self.assertEqual(intents, [])

    def test_backtest_config_builder_wires_portfolio_and_risk_parameters(self) -> None:
        config = build_backtest_config(
            parameters={
                "default_strategy_weight": 0.2,
                "max_symbol_weight": 0.15,
                "cash_reserve_weight": 0.1,
                "min_trade_notional": 100.0,
                "min_weight_change": 0.002,
                "min_cash_buffer_pct": 0.03,
            }
        )

        self.assertEqual(config.sizing.default_strategy_weight, 0.2)
        self.assertEqual(config.allocation.cash_reserve_weight, 0.1)
        self.assertEqual(config.rebalance.min_trade_notional, 100.0)
        self.assertEqual(config.rebalance.min_weight_change, 0.002)
        self.assertEqual(config.risk.min_cash_buffer_pct, 0.03)


if __name__ == "__main__":
    unittest.main()
