from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.backtest.runner import bars_from_frame, run_event_backtest_from_lake
from quant_us.backtest.walk_forward import WalkForwardConfig, run_walk_forward
from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.data.storage.feature_store import ParquetFeatureStore
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.factors.feature_pipeline import FeaturePipeline
from quant_us.strategies.momentum_strategy import MomentumStrategy


def synthetic_equity_frame(count: int = 90, symbol: str = "AAPL", drift: float = 1.003) -> pd.DataFrame:
    timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
    price = 100.0
    rows: list[dict[str, object]] = []
    while len(rows) < count:
        if timestamp.weekday() < 5:
            price *= drift
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "open": price * 0.99,
                    "high": price * 1.01,
                    "low": price * 0.98,
                    "close": price,
                    "volume": 10_000_000,
                }
            )
        timestamp += timedelta(days=1)
    return pd.DataFrame(rows)


class QuantUSDataLakeTests(unittest.TestCase):
    def test_cleaned_parquet_features_and_event_backtest(self) -> None:
        with TemporaryDirectory() as directory:
            service = DataLakeService(DataLakeConfig(data_root=Path(directory)))
            cleaned = BarCleaner().clean(synthetic_equity_frame(), symbol="AAPL", source="unit").frame
            write = service.cleaned_store.write_bars(
                cleaned,
                vendor="yfinance",
                asset_class="equity",
                bar_size="1d",
                symbol="AAPL",
            )

            self.assertGreater(write.rows_written, 0)
            loaded = service.read_cleaned_bars(
                symbol="AAPL",
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                bar_size="1d",
            )
            self.assertEqual(len(loaded), len(cleaned))

            features = FeaturePipeline(feature_root=f"{directory}/features").build_bar_factors(loaded, version="test")
            self.assertEqual(features.status, "completed")
            self.assertGreater(features.rows_written, 0)

            result = run_event_backtest_from_lake(
                data_root=directory,
                symbol="AAPL",
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                strategy_id="trend_momentum",
            )
            self.assertGreater(result.summary["trade_count"], 0)
            self.assertIn("cagr_pct", result.summary)
            self.assertIn("annual_return_pct", result.summary)
            self.assertIn("sortino_ratio", result.summary)
            self.assertIn("win_rate_pct", result.summary)
            self.assertIn("profit_factor", result.summary)
            self.assertIn("turnover_pct", result.summary)

            walk_forward = run_walk_forward(
                bars_from_frame(loaded),
                strategy_factory=lambda: MomentumStrategy(lookback_bars=10, entry_threshold=0.01),
                config=WalkForwardConfig(train_bars=30, test_bars=15, step_bars=15),
            )
            self.assertTrue(walk_forward)
            self.assertIn("max_drawdown_pct", walk_forward[0].result.summary)

            ledger = JsonlLedgerStore(Path(directory) / "ledger")
            ledger.write_result(result)
            self.assertEqual(len(ledger.read_records("orders.jsonl")), len(result.orders))
            self.assertEqual(len(ledger.read_records("fills.jsonl")), len(result.fills))
            self.assertEqual(len(ledger.read_records("portfolio_snapshots.jsonl")), len(result.snapshots))

    def test_multi_symbol_event_backtest_groups_snapshots_by_timestamp(self) -> None:
        with TemporaryDirectory() as directory:
            service = DataLakeService(DataLakeConfig(data_root=Path(directory)))
            aapl = BarCleaner().clean(synthetic_equity_frame(count=80, symbol="AAPL", drift=1.003), symbol="AAPL", source="unit").frame
            msft = BarCleaner().clean(synthetic_equity_frame(count=80, symbol="MSFT", drift=1.004), symbol="MSFT", source="unit").frame
            service.cleaned_store.write_bars(aapl, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="AAPL")
            service.cleaned_store.write_bars(msft, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="MSFT")

            result = run_event_backtest_from_lake(
                data_root=directory,
                symbol="AAPL",
                symbols=["AAPL", "MSFT"],
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                strategy_id="trend_momentum",
            )

            self.assertEqual(result.metadata["symbols"], ["AAPL", "MSFT"])
            self.assertEqual(len(result.snapshots), len(aapl))
            self.assertGreater(result.summary["trade_count"], 0)

    def test_factor_rank_strategy_uses_versioned_feature_store(self) -> None:
        with TemporaryDirectory() as directory:
            service = DataLakeService(DataLakeConfig(data_root=Path(directory)))
            frames = {
                "AAPL": BarCleaner().clean(synthetic_equity_frame(count=80, symbol="AAPL", drift=1.003), symbol="AAPL", source="unit").frame,
                "MSFT": BarCleaner().clean(synthetic_equity_frame(count=80, symbol="MSFT", drift=1.003), symbol="MSFT", source="unit").frame,
                "XOM": BarCleaner().clean(synthetic_equity_frame(count=80, symbol="XOM", drift=1.003), symbol="XOM", source="unit").frame,
            }
            for symbol, frame in frames.items():
                service.cleaned_store.write_bars(frame, vendor="yfinance", asset_class="equity", bar_size="1d", symbol=symbol)

            values = []
            scores = {"AAPL": 3.0, "MSFT": 2.0, "XOM": 1.0}
            for symbol, frame in frames.items():
                for date_value in frame["timestamp_utc"].dt.date:
                    values.append(
                        {
                            "date": date_value,
                            "symbol": symbol,
                            "factor_name": "rank_score",
                            "factor_value": scores[symbol],
                            "universe": "core",
                            "version": "rank_v1",
                            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        }
                    )
            ParquetFeatureStore(Path(directory) / "features").write_factor_values(pd.DataFrame(values), version="rank_v1")

            result = run_event_backtest_from_lake(
                data_root=directory,
                symbol="AAPL",
                symbols=["AAPL", "MSFT", "XOM"],
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                strategy_id="factor_rank",
                strategy_params={"factor_name": "rank_score", "top_n": 1, "min_symbols": 3},
                feature_version="rank_v1",
                feature_universe="core",
            )

            self.assertGreater(result.metadata["feature_rows"], 0)
            self.assertEqual(result.metadata["feature_names"], ["rank_score"])
            self.assertGreater(result.summary["trade_count"], 0)
            self.assertTrue({fill.symbol for fill in result.fills}.issubset({"AAPL"}))


if __name__ == "__main__":
    unittest.main()
