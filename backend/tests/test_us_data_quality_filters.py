from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.backtest.runner import run_event_backtest_from_lake
from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.cleaners.corporate_action_adjuster import CorporateAction, CorporateActionAdjuster
from quant_us.data.events import EarningsBlackoutFilter, EarningsEvent
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.data.universe.universe_builder import UniverseBuilder, UniverseRule


def make_frame(symbol: str = "AAPL", count: int = 80, price: float = 100.0, volume: float = 1_000_000.0) -> pd.DataFrame:
    timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    current = price
    while len(rows) < count:
        if timestamp.weekday() < 5:
            current *= 1.002
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "open": current * 0.99,
                    "high": current * 1.01,
                    "low": current * 0.98,
                    "close": current,
                    "volume": volume,
                }
            )
        timestamp += timedelta(days=1)
    return pd.DataFrame(rows)


class USDataQualityFilterTests(unittest.TestCase):
    def test_split_adjuster_backward_adjusts_price_and_volume(self) -> None:
        cleaned = BarCleaner().clean(make_frame(count=10), symbol="AAPL", source="unit").frame
        action = CorporateAction(symbol="AAPL", action_type="split", ex_date=date(2024, 1, 10), ratio=2.0)

        adjusted = CorporateActionAdjuster().adjust_bars(cleaned, [action])

        before = cleaned[cleaned["timestamp_utc"].dt.date < action.ex_date].iloc[0]
        after = adjusted[adjusted["timestamp_utc"].dt.date < action.ex_date].iloc[0]
        self.assertAlmostEqual(after["close"], before["close"] / 2.0)
        self.assertAlmostEqual(after["volume"], before["volume"] * 2.0)
        self.assertTrue(bool(adjusted.iloc[0]["adjusted_flag"]))

    def test_dividend_adjuster_backward_adjusts_pre_ex_date_prices(self) -> None:
        cleaned = BarCleaner().clean(make_frame(count=10, price=50), symbol="AAPL", source="unit").frame
        action = CorporateAction(symbol="AAPL", action_type="dividend", ex_date=date(2024, 1, 10), cash_amount=1.0)

        adjusted = CorporateActionAdjuster().adjust_bars(cleaned, [action])

        reference_close = float(cleaned[cleaned["timestamp_utc"].dt.date < action.ex_date].iloc[-1]["close"])
        expected_factor = (reference_close - action.cash_amount) / reference_close
        before = cleaned[cleaned["timestamp_utc"].dt.date < action.ex_date].iloc[0]
        after = adjusted[adjusted["timestamp_utc"].dt.date < action.ex_date].iloc[0]
        ex_date_row = cleaned[cleaned["timestamp_utc"].dt.date >= action.ex_date].iloc[0]
        adjusted_ex_date_row = adjusted[adjusted["timestamp_utc"].dt.date >= action.ex_date].iloc[0]
        self.assertAlmostEqual(after["close"], before["close"] * expected_factor)
        self.assertAlmostEqual(adjusted_ex_date_row["close"], ex_date_row["close"])

    def test_earnings_blackout_filter_removes_event_window(self) -> None:
        cleaned = BarCleaner().clean(make_frame(count=15), symbol="AAPL", source="unit").frame
        event = EarningsEvent(symbol="AAPL", event_date=date(2024, 1, 10))

        result = EarningsBlackoutFilter(days_before=1, days_after=1).filter_bars(cleaned, [event])

        self.assertGreater(result.removed_rows, 0)
        self.assertEqual(result.blocked_symbols, ["AAPL"])
        removed_dates = set(cleaned["timestamp_utc"].dt.date) - set(result.frame["timestamp_utc"].dt.date)
        self.assertIn(date(2024, 1, 10), removed_dates)

    def test_universe_builder_applies_liquidity_and_history_rules(self) -> None:
        liquid = BarCleaner().clean(make_frame("AAPL", count=30, price=100, volume=1_000_000), symbol="AAPL", source="unit").frame
        illiquid = BarCleaner().clean(make_frame("PENNY", count=30, price=2, volume=10_000), symbol="PENNY", source="unit").frame
        universe = UniverseBuilder(UniverseRule(min_price=5.0, min_dollar_volume=20_000_000.0, min_history_bars=20)).from_daily_bars(
            pd.concat([liquid, illiquid], ignore_index=True)
        )

        self.assertEqual(universe, ["AAPL"])

    def test_backtest_runner_accepts_corporate_actions_and_earnings_events(self) -> None:
        with TemporaryDirectory() as directory:
            service = DataLakeService(DataLakeConfig(data_root=Path(directory)))
            cleaned = BarCleaner().clean(make_frame(count=80), symbol="AAPL", source="unit").frame
            service.cleaned_store.write_bars(cleaned, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="AAPL")

            result = run_event_backtest_from_lake(
                data_root=directory,
                symbol="AAPL",
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                corporate_actions=[CorporateAction(symbol="AAPL", action_type="split", ex_date=date(2024, 2, 1), ratio=2.0)],
                earnings_events=[EarningsEvent(symbol="AAPL", event_date=date(2024, 2, 15))],
            )

            self.assertIn("total_return_pct", result.summary)
            self.assertEqual(result.metadata["corporate_action_count"], 1)
            self.assertGreater(result.metadata["earnings_blackout_removed_rows"], 0)


if __name__ == "__main__":
    unittest.main()
