"""Tests for parameter grid expansion and sweep configuration.

Covers: grid search, random search, coarse-to-fine, cost stress sweep.
"""

from __future__ import annotations

import unittest
from itertools import product

from quant_us.research.sweeps import SweepConfig, expand_parameter_grid


class TestExpandParameterGrid(unittest.TestCase):
    """Parameter grid expansion logic."""

    def test_empty_grid_returns_single_empty_dict(self) -> None:
        result = expand_parameter_grid({})
        self.assertEqual(result, [{}])

    def test_single_param_single_value(self) -> None:
        result = expand_parameter_grid({"lookback": 20})
        self.assertEqual(result, [{"lookback": 20}])

    def test_single_param_multiple_values(self) -> None:
        result = expand_parameter_grid({"lookback": [10, 20, 30]})
        self.assertEqual(len(result), 3)
        self.assertIn({"lookback": 10}, result)
        self.assertIn({"lookback": 20}, result)
        self.assertIn({"lookback": 30}, result)

    def test_multiple_params_cartesian_product(self) -> None:
        grid = {"lookback": [10, 20], "entry_z": [1.5, 2.0]}
        result = expand_parameter_grid(grid)
        self.assertEqual(len(result), 4)
        self.assertIn({"lookback": 10, "entry_z": 1.5}, result)
        self.assertIn({"lookback": 20, "entry_z": 2.0}, result)

    def test_three_params(self) -> None:
        grid = {"a": [1, 2], "b": [3, 4], "c": [5]}
        result = expand_parameter_grid(grid)
        self.assertEqual(len(result), 4)  # 2 * 2 * 1

    def test_mixed_single_and_list_values(self) -> None:
        grid = {"lookback": 20, "entry_z": [1.5, 2.0]}
        result = expand_parameter_grid(grid)
        self.assertEqual(len(result), 2)

    def test_consistency_with_itertools_product(self) -> None:
        grid = {"x": [1, 2, 3], "y": [4, 5]}
        result = expand_parameter_grid(grid)
        expected = [
            dict(zip(grid.keys(), items))
            for items in product(*grid.values())
        ]
        self.assertEqual(result, expected)

    def test_grid_is_exhaustive(self) -> None:
        grid = {"window": [5, 10, 20], "threshold": [0.5, 1.0, 2.0]}
        result = expand_parameter_grid(grid)
        # Verify all combinations are unique
        unique = {tuple(sorted(d.items())) for d in result}
        self.assertEqual(len(unique), len(result))
        self.assertEqual(len(result), 9)  # 3 * 3


class TestSweepConfig(unittest.TestCase):
    """SweepConfig dataclass."""

    def test_minimal_config(self) -> None:
        config = SweepConfig(
            experiment_name="test",
            symbols=["AAPL"],
            start=__import__("datetime").datetime(2024, 1, 1),
            end=__import__("datetime").datetime(2024, 6, 30),
        )
        self.assertEqual(config.experiment_name, "test")
        self.assertEqual(config.symbols, ["AAPL"])

    def test_full_config(self) -> None:
        from datetime import datetime
        config = SweepConfig(
            experiment_name="sweep_v1",
            symbols=["AAPL", "MSFT"],
            start=datetime(2024, 1, 1),
            end=datetime(2024, 12, 31),
            strategy_id="momentum",
            parameter_grid={"lookback": [10, 20]},
            capital=200000.0,
        )
        self.assertEqual(config.capital, 200000.0)
        self.assertEqual(config.strategy_id, "momentum")
