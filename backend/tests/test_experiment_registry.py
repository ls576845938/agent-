from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.backtest.result_store import BacktestResultStore
from quant_us.core.enums import SessionName
from quant_us.core.types import Bar
from quant_us.research.experiments import ArtifactRef, ExperimentRegistry, ExperimentSpec, ModelArtifact
from quant_us.strategies.momentum_strategy import MomentumStrategy


def bars(count: int = 60) -> list[Bar]:
    timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
    price = 100.0
    output: list[Bar] = []
    while len(output) < count:
        if timestamp.weekday() < 5:
            price *= 1.004
            output.append(
                Bar(
                    timestamp_utc=timestamp,
                    symbol="AAPL",
                    open=price * 0.99,
                    high=price * 1.01,
                    low=price * 0.98,
                    close=price,
                    volume=10_000_000,
                    source="unit",
                    session=SessionName.REGULAR.value,
                )
            )
        timestamp += timedelta(days=1)
    return output


class ExperimentRegistryTests(unittest.TestCase):
    def test_backtest_result_store_writes_queryable_artifacts(self) -> None:
        result = EventDrivenBacktestEngine(
            [MomentumStrategy(lookback_bars=5, entry_threshold=0.01)],
            config=BacktestConfig(initial_cash=100_000.0),
        ).run(bars())

        with TemporaryDirectory() as directory:
            persisted = BacktestResultStore(directory).write(result)

            self.assertTrue(Path(persisted.summary_path).exists())
            self.assertTrue(Path(persisted.metadata_path).exists())
            self.assertGreater(len(pd.read_parquet(persisted.orders_path)), 0)
            self.assertGreater(len(pd.read_parquet(persisted.fills_path)), 0)
            self.assertEqual(len(pd.read_parquet(persisted.snapshots_path)), len(result.snapshots))
            summary = json.loads(Path(persisted.summary_path).read_text(encoding="utf-8"))
            self.assertIn("sharpe_ratio", summary)

    def test_experiment_registry_registers_and_compares_runs(self) -> None:
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry(directory)
            spec = ExperimentSpec(
                experiment_name="momentum_core",
                run_type="event_backtest",
                symbols=["AAPL"],
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                strategy_id="trend_momentum",
                strategy_version="strategy_v1",
                data_version="data_v1",
                promotion_decision="warn",
                promotion_stage="research_iteration",
                promotion_manifest_id="manifest_1",
                parameters={"lookback_bars": 5},
                tags=["unit"],
            )
            low = registry.create_record(
                run_id="bt_low",
                spec=spec,
                metrics={"sharpe_ratio": 0.5, "total_return_pct": 1.0, "max_drawdown_pct": -2.0},
                artifacts=[ArtifactRef("summary", "/tmp/summary.json", "json")],
            )
            high = registry.create_record(
                run_id="bt_high",
                spec=spec,
                metrics={"sharpe_ratio": 1.2, "total_return_pct": 3.0, "max_drawdown_pct": -1.0},
                artifacts=[],
            )

            low_path = registry.register(low)
            high_path = registry.register(high)
            rows = registry.compare(metric="sharpe_ratio", experiment_name="momentum_core")

            self.assertTrue(low_path.exists())
            self.assertTrue(high_path.exists())
            self.assertEqual(rows[0]["run_id"], "bt_high")
            self.assertEqual(rows[1]["run_id"], "bt_low")
            self.assertEqual(rows[0]["strategy_version"], "strategy_v1")
            self.assertEqual(rows[0]["data_version"], "data_v1")
            self.assertEqual(rows[0]["promotion_decision"], "warn")
            self.assertEqual(rows[0]["promotion_stage"], "research_iteration")
            self.assertEqual(rows[0]["promotion_manifest_id"], "manifest_1")
            self.assertEqual(len(registry.load_records("momentum_core")), 2)

    def test_model_artifact_registry_writes_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            registry = ExperimentRegistry(directory)
            path = registry.register_model(
                ModelArtifact(
                    model_id="model_1",
                    model_type="lightgbm",
                    path="/tmp/model.txt",
                    feature_names=["momentum_score"],
                    feature_version="v1",
                    dataset_run_id="ds_1",
                    metrics={"ic": 0.03},
                )
            )

            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["model_id"], "model_1")
            self.assertEqual(manifest["feature_names"], ["momentum_score"])


if __name__ == "__main__":
    unittest.main()
