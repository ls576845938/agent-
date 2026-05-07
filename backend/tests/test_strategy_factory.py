from __future__ import annotations

import unittest

from quant_us.strategies.earnings_drift_strategy import EarningsDriftStrategy
from quant_us.strategies.factor_rank_strategy import FactorRankStrategy
from quant_us.strategies.factory import (
    available_strategies,
    build_strategy,
    strategy_parameter_names,
)
from quant_us.strategies.mean_reversion_strategy import MeanReversionStrategy
from quant_us.strategies.momentum_strategy import MomentumStrategy


class StrategyFactoryTests(unittest.TestCase):
    """Unit tests for quant_us/strategies/factory.py."""

    # ------------------------------------------------------------------
    # available_strategies
    # ------------------------------------------------------------------

    def test_available_strategies_returns_sorted_list(self) -> None:
        strategies = available_strategies()
        self.assertEqual(strategies, sorted(strategies))
        self.assertIsInstance(strategies, list)

    def test_available_strategies_contains_all_registered(self) -> None:
        strategies = available_strategies()
        self.assertIn("trend_momentum", strategies)
        self.assertIn("short_reversion", strategies)
        self.assertIn("factor_rank", strategies)
        self.assertIn("earnings_drift", strategies)

    def test_available_strategies_count(self) -> None:
        self.assertGreaterEqual(len(available_strategies()), 5)

    # ------------------------------------------------------------------
    # build_strategy — success
    # ------------------------------------------------------------------

    def test_build_trend_momentum_returns_momentum_strategy(self) -> None:
        strategy = build_strategy("trend_momentum")
        self.assertIsInstance(strategy, MomentumStrategy)
        self.assertEqual(strategy.strategy_id, "trend_momentum")

    def test_build_earnings_drift_returns_earnings_drift_strategy(self) -> None:
        strategy = build_strategy("earnings_drift")
        self.assertIsInstance(strategy, EarningsDriftStrategy)
        self.assertEqual(strategy.strategy_id, "earnings_drift")

    def test_build_short_reversion_returns_mean_reversion_strategy(self) -> None:
        strategy = build_strategy("short_reversion")
        self.assertIsInstance(strategy, MeanReversionStrategy)
        self.assertEqual(strategy.strategy_id, "short_reversion")

    def test_build_factor_rank_returns_factor_rank_strategy(self) -> None:
        strategy = build_strategy("factor_rank")
        self.assertIsInstance(strategy, FactorRankStrategy)
        self.assertEqual(strategy.strategy_id, "factor_rank")

    # ------------------------------------------------------------------
    # build_strategy — with valid parameters
    # ------------------------------------------------------------------

    def test_build_strategy_with_parameters_sets_values(self) -> None:
        strategy = build_strategy(
            "trend_momentum",
            {"lookback_bars": 7, "entry_threshold": 0.02},
        )
        self.assertEqual(strategy.lookback_bars, 7)
        self.assertEqual(strategy.entry_threshold, 0.02)
        # unset params keep defaults
        self.assertEqual(strategy.exit_threshold, 0.0)
        self.assertFalse(strategy.allow_short)

    def test_build_strategy_with_earnings_drift_params(self) -> None:
        strategy = build_strategy(
            "earnings_drift",
            {"drift_period_days": 15, "max_positions": 5, "allow_short": False},
        )
        self.assertEqual(strategy.drift_period_days, 15)
        self.assertEqual(strategy.max_positions, 5)
        self.assertFalse(strategy.allow_short)
        # unset params keep defaults
        self.assertEqual(strategy.min_price, 5.0)
        self.assertEqual(strategy.reaction_lookback_days, 2)

    def test_build_strategy_with_factor_rank_params(self) -> None:
        strategy = build_strategy(
            "factor_rank",
            {"factor_name": "quality_score", "top_n": 10, "rank_descending": False},
        )
        self.assertEqual(strategy.factor_name, "quality_score")
        self.assertEqual(strategy.top_n, 10)
        self.assertFalse(strategy.rank_descending)

    def test_build_strategy_with_short_reversion_params(self) -> None:
        strategy = build_strategy(
            "short_reversion",
            {"window": 10, "entry_zscore": 1.5, "exit_zscore": 0.5},
        )
        self.assertEqual(strategy.window, 10)
        self.assertEqual(strategy.entry_zscore, 1.5)
        self.assertEqual(strategy.exit_zscore, 0.5)

    # ------------------------------------------------------------------
    # build_strategy — errors
    # ------------------------------------------------------------------

    def test_build_strategy_unknown_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_strategy("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))

    def test_build_strategy_unknown_param_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_strategy("trend_momentum", {"not_a_param": 1})
        self.assertIn("not_a_param", str(ctx.exception))

    def test_build_strategy_multiple_unknown_params_reported(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_strategy("trend_momentum", {"foo": 1, "bar": 2})
        self.assertIn("foo", str(ctx.exception))
        self.assertIn("bar", str(ctx.exception))

    # ------------------------------------------------------------------
    # strategy_parameter_names
    # ------------------------------------------------------------------

    def test_strategy_parameter_names_trend_momentum(self) -> None:
        names = strategy_parameter_names("trend_momentum")
        expected = {"strategy_id", "lookback_bars", "entry_threshold", "exit_threshold", "allow_short"}
        self.assertEqual(names, expected)

    def test_strategy_parameter_names_earnings_drift(self) -> None:
        names = strategy_parameter_names("earnings_drift")
        expected = {"strategy_id", "drift_period_days", "min_price", "max_positions", "allow_short", "reaction_lookback_days"}
        self.assertEqual(names, expected)

    def test_strategy_parameter_names_short_reversion(self) -> None:
        names = strategy_parameter_names("short_reversion")
        expected = {"strategy_id", "window", "entry_zscore", "exit_zscore", "allow_short"}
        self.assertEqual(names, expected)

    def test_strategy_parameter_names_factor_rank(self) -> None:
        names = strategy_parameter_names("factor_rank")
        expected = {"strategy_id", "factor_name", "top_n", "bottom_n", "min_symbols", "rank_descending", "allow_short", "emit_flats"}
        self.assertEqual(names, expected)

    def test_strategy_parameter_names_unknown_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            strategy_parameter_names("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
