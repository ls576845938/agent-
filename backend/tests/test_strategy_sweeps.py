from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.research.experiments import ExperimentRegistry
from quant_us.research.sweeps import ResearchSweepRunner, SweepConfig, expand_parameter_grid
from quant_us.strategies.factory import build_strategy, strategy_parameter_names


def synthetic_frame(count: int = 90) -> pd.DataFrame:
    timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
    price = 100.0
    rows: list[dict[str, object]] = []
    while len(rows) < count:
        if timestamp.weekday() < 5:
            price *= 1.004
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": "AAPL",
                    "open": price * 0.99,
                    "high": price * 1.01,
                    "low": price * 0.98,
                    "close": price,
                    "volume": 10_000_000,
                }
            )
        timestamp += timedelta(days=1)
    return pd.DataFrame(rows)


class StrategySweepTests(unittest.TestCase):
    def test_strategy_factory_builds_configured_strategy_and_rejects_unknown_params(self) -> None:
        strategy = build_strategy("trend_momentum", {"lookback_bars": 7, "entry_threshold": 0.02})

        self.assertEqual(strategy.lookback_bars, 7)
        self.assertEqual(strategy.entry_threshold, 0.02)
        self.assertIn("lookback_bars", strategy_parameter_names("trend_momentum"))
        self.assertEqual(build_strategy("factor_rank", {"factor_name": "rank_score", "top_n": 3}).factor_name, "rank_score")
        with self.assertRaises(ValueError):
            build_strategy("trend_momentum", {"not_a_param": 1})

    def test_expand_parameter_grid_is_deterministic(self) -> None:
        grid = expand_parameter_grid({"lookback_bars": [5, 10], "entry_threshold": [0.01, 0.02]})

        self.assertEqual(
            grid,
            [
                {"lookback_bars": 5, "entry_threshold": 0.01},
                {"lookback_bars": 5, "entry_threshold": 0.02},
                {"lookback_bars": 10, "entry_threshold": 0.01},
                {"lookback_bars": 10, "entry_threshold": 0.02},
            ],
        )

    def test_research_sweep_registers_each_parameter_run(self) -> None:
        with TemporaryDirectory() as directory:
            service = DataLakeService(DataLakeConfig(data_root=Path(directory)))
            cleaned = BarCleaner().clean(synthetic_frame(), symbol="AAPL", source="unit").frame
            service.cleaned_store.write_bars(cleaned, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="AAPL")

            result = ResearchSweepRunner().run(
                SweepConfig(
                    experiment_name="momentum_sweep",
                    symbols=["AAPL"],
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                    strategy_id="trend_momentum",
                    parameter_grid={"lookback_bars": [5, 10], "entry_threshold": [0.01]},
                    portfolio_grid={"cash_reserve_weight": [0.05, 0.10]},
                    data_root=directory,
                )
            )

            records = ExperimentRegistry(Path(directory) / "experiments").load_records("momentum_sweep")
            self.assertEqual(len(result.records), 4)
            self.assertEqual(len(records), 4)
            self.assertTrue(all(record["status"] == "completed" for record in records))
            self.assertIsNotNone(result.best)
            self.assertEqual({record["spec"]["parameters"]["strategy_params"]["lookback_bars"] for record in records}, {5, 10})
            self.assertEqual({record["spec"]["parameters"]["backtest_params"]["cash_reserve_weight"] for record in records}, {0.05, 0.10})


if __name__ == "__main__":
    unittest.main()
