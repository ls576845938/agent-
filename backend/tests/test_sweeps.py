from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from quant_us.research.sweeps import (
    ResearchSweepRunner,
    SweepConfig,
    SweepResult,
    expand_parameter_grid,
)


class ExpandParameterGridTests(unittest.TestCase):
    """Tests for the expand_parameter_grid helper function."""

    def test_expand_parameter_grid_empty(self) -> None:
        """Empty grid returns a list containing one empty dict."""
        self.assertEqual(expand_parameter_grid({}), [{}])

    def test_expand_parameter_grid_single_param(self) -> None:
        """Single list-valued parameter produces one combination per value."""
        result = expand_parameter_grid({"a": [1, 2]})
        self.assertEqual(result, [{"a": 1}, {"a": 2}])

    def test_expand_parameter_grid_multi_param(self) -> None:
        """Two list-valued parameters produce the cartesian product."""
        result = expand_parameter_grid({"a": [1, 2], "b": [3, 4]})
        self.assertEqual(
            result,
            [
                {"a": 1, "b": 3},
                {"a": 1, "b": 4},
                {"a": 2, "b": 3},
                {"a": 2, "b": 4},
            ],
        )

    def test_expand_parameter_grid_non_list_value(self) -> None:
        """Scalar (non-list) values are treated as single-element lists."""
        result = expand_parameter_grid({"a": 5})
        self.assertEqual(result, [{"a": 5}])


class SweepConfigTests(unittest.TestCase):
    """Tests for SweepConfig dataclass construction and defaults."""

    def test_sweep_config_construction(self) -> None:
        """All fields are set correctly when provided."""
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 6, 30, tzinfo=timezone.utc)
        config = SweepConfig(
            experiment_name="test_sweep",
            symbols=["AAPL", "MSFT"],
            start=start,
            end=end,
            strategy_id="trend_momentum",
            parameter_grid={"lookback_bars": [5, 10]},
            portfolio_grid={"cash_reserve_weight": [0.05, 0.10]},
            data_root="/tmp/data",
            vendor="yfinance",
            asset_class="equity",
            bar_size="1d",
            feature_version="v1",
            feature_universe="default",
            feature_names=["momentum"],
            capital=200_000.0,
            max_symbol_weight=0.15,
            max_order_notional_pct=0.08,
            cash_reserve_weight=0.03,
            default_strategy_weight=0.12,
            min_trade_notional=50.0,
            min_weight_change=0.01,
            tags=["unit"],
            notes="test notes",
        )

        self.assertEqual(config.experiment_name, "test_sweep")
        self.assertEqual(config.symbols, ["AAPL", "MSFT"])
        self.assertEqual(config.start, start)
        self.assertEqual(config.end, end)
        self.assertEqual(config.strategy_id, "trend_momentum")
        self.assertEqual(config.parameter_grid, {"lookback_bars": [5, 10]})
        self.assertEqual(config.portfolio_grid, {"cash_reserve_weight": [0.05, 0.10]})
        self.assertEqual(config.data_root, "/tmp/data")
        self.assertEqual(config.vendor, "yfinance")
        self.assertEqual(config.asset_class, "equity")
        self.assertEqual(config.bar_size, "1d")
        self.assertEqual(config.feature_version, "v1")
        self.assertEqual(config.feature_universe, "default")
        self.assertEqual(config.feature_names, ["momentum"])
        self.assertEqual(config.capital, 200_000.0)
        self.assertEqual(config.max_symbol_weight, 0.15)
        self.assertEqual(config.max_order_notional_pct, 0.08)
        self.assertEqual(config.cash_reserve_weight, 0.03)
        self.assertEqual(config.default_strategy_weight, 0.12)
        self.assertEqual(config.min_trade_notional, 50.0)
        self.assertEqual(config.min_weight_change, 0.01)
        self.assertEqual(config.tags, ["unit"])
        self.assertEqual(config.notes, "test notes")

    def test_sweep_config_defaults(self) -> None:
        """Verify default values for optional fields."""
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 6, 30, tzinfo=timezone.utc)
        config = SweepConfig(
            experiment_name="default_sweep",
            symbols=["AAPL"],
            start=start,
            end=end,
        )

        self.assertEqual(config.strategy_id, "trend_momentum")
        self.assertEqual(config.parameter_grid, {})
        self.assertEqual(config.portfolio_grid, {})
        self.assertEqual(config.data_root, "data")
        self.assertEqual(config.vendor, "yfinance")
        self.assertEqual(config.asset_class, "equity")
        self.assertEqual(config.bar_size, "1d")
        self.assertEqual(config.feature_version, "")
        self.assertEqual(config.feature_universe, "default")
        self.assertEqual(config.feature_names, [])
        self.assertEqual(config.capital, 100_000.0)
        self.assertEqual(config.max_symbol_weight, 0.10)
        self.assertEqual(config.max_order_notional_pct, 0.10)
        self.assertEqual(config.cash_reserve_weight, 0.05)
        self.assertEqual(config.default_strategy_weight, 0.10)
        self.assertEqual(config.min_trade_notional, 25.0)
        self.assertEqual(config.min_weight_change, 0.0)
        self.assertEqual(config.tags, [])
        self.assertEqual(config.notes, "")


class SweepResultTests(unittest.TestCase):
    """Tests for SweepResult dataclass."""

    def test_sweep_result_structure(self) -> None:
        """SweepResult holds records list and best dict."""
        result = SweepResult(
            experiment_name="test",
            records=[],
            best=None,
        )
        self.assertEqual(result.experiment_name, "test")
        self.assertEqual(result.records, [])
        self.assertIsNone(result.best)

        result_with_best = SweepResult(
            experiment_name="test",
            records=[],
            best={"run_id": "bt_1", "sharpe_ratio": 1.5},
        )
        self.assertEqual(result_with_best.best, {"run_id": "bt_1", "sharpe_ratio": 1.5})


class ResearchSweepRunnerTests(unittest.TestCase):
    """Tests for ResearchSweepRunner.run() with mocked dependencies."""

    def _make_config(
        self,
        parameter_grid: dict[str, Any] | None = None,
        portfolio_grid: dict[str, Any] | None = None,
    ) -> SweepConfig:
        return SweepConfig(
            experiment_name="unit_sweep",
            symbols=["AAPL"],
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 1, 31, tzinfo=timezone.utc),
            strategy_id="trend_momentum",
            parameter_grid=parameter_grid or {},
            portfolio_grid=portfolio_grid or {},
        )

    def _make_mock_backtest_result(self, run_id: str) -> MagicMock:
        result = MagicMock()
        result.run_id = run_id
        result.summary = {"sharpe_ratio": 1.0, "total_return_pct": 5.0}
        return result

    def _make_mock_persist_result(self) -> MagicMock:
        persisted = MagicMock()
        persisted.summary_path = "/tmp/summary.json"
        persisted.metadata_path = "/tmp/metadata.json"
        persisted.orders_path = "/tmp/orders.parquet"
        persisted.fills_path = "/tmp/fills.parquet"
        persisted.snapshots_path = "/tmp/snapshots.parquet"
        return persisted

    def test_run_sweep_with_fixture(self) -> None:
        """Mock run_event_backtest_from_lake and registry, verify sweep produces records for each param combo."""
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 1, 31, tzinfo=timezone.utc)

        config = SweepConfig(
            experiment_name="unit_sweep",
            symbols=["AAPL"],
            start=start,
            end=end,
            strategy_id="trend_momentum",
            parameter_grid={"lookback_bars": [5, 10], "entry_threshold": [0.01, 0.02]},
            portfolio_grid={"cash_reserve_weight": [0.05, 0.10]},
        )

        # 2 * 2 * 2 = 8 combinations
        expected_combo_count = 8

        # Mock the backtest runner at the import site in sweeps.py
        with patch("quant_us.research.sweeps.run_event_backtest_from_lake") as mock_run:
            # Mock result_store
            mock_result_store = MagicMock()
            mock_persisted = self._make_mock_persist_result()
            mock_result_store.write.return_value = mock_persisted

            # Mock registry
            mock_registry = MagicMock()
            mock_registry.create_record.side_effect = lambda run_id, spec, metrics, artifacts, status="completed", error=None: MagicMock(
                run_id=run_id,
                spec=spec,
                metrics=metrics,
                artifacts=artifacts,
                status=status,
            )
            mock_registry.compare.return_value = [
                {"run_id": "bt_1", "sharpe_ratio": 1.5},
                {"run_id": "bt_2", "sharpe_ratio": 0.5},
            ]

            # Make run_event_backtest_from_lake return a known result per call
            def side_effect(**kwargs: Any) -> MagicMock:
                params = kwargs.get("strategy_params", {})
                lookback = params.get("lookback_bars", 5)
                threshold = params.get("entry_threshold", 0.01)
                run_id = f"bt_l{lookback}_t{threshold}"
                return self._make_mock_backtest_result(run_id)

            mock_run.side_effect = side_effect

            runner = ResearchSweepRunner(result_store=mock_result_store, registry=mock_registry)
            result = runner.run(config=config, compare_metric="sharpe_ratio")

            # Should produce expected number of records
            self.assertEqual(len(result.records), expected_combo_count)
            self.assertEqual(mock_registry.register.call_count, expected_combo_count)
            self.assertEqual(mock_registry.compare.call_count, 1)

            # Verify registry.create_record was called each time
            self.assertEqual(mock_registry.create_record.call_count, expected_combo_count)

            # Verify result_store.write was called each time
            self.assertEqual(mock_result_store.write.call_count, expected_combo_count)

            # Verify best is set
            self.assertIsNotNone(result.best)
            self.assertEqual(result.best["run_id"], "bt_1")

    def test_run_sweep_empty_grid(self) -> None:
        """Empty parameter and portfolio grids produce exactly 1 record."""
        config = self._make_config()

        with patch("quant_us.research.sweeps.run_event_backtest_from_lake") as mock_run:
            mock_result_store = MagicMock()
            mock_persisted = self._make_mock_persist_result()
            mock_result_store.write.return_value = mock_persisted

            mock_registry = MagicMock()
            mock_registry.create_record.return_value = MagicMock(
                run_id="bt_single",
                spec=None,
                metrics={},
                artifacts=[],
                status="completed",
            )
            mock_registry.compare.return_value = [{"run_id": "bt_single", "sharpe_ratio": 1.0}]

            mock_run.return_value = self._make_mock_backtest_result("bt_single")

            runner = ResearchSweepRunner(result_store=mock_result_store, registry=mock_registry)
            result = runner.run(config=config)

            self.assertEqual(len(result.records), 1)
            self.assertEqual(mock_registry.register.call_count, 1)


if __name__ == "__main__":
    unittest.main()
