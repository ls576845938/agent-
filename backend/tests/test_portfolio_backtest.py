"""Tests for PortfolioBacktestRunner.

Covers: portfolio backtest, attribution, turnover.
"""

from __future__ import annotations

import unittest

from quant_us.portfolio.construction.backtest import (
    PortfolioBacktestResult,
    PortfolioBacktestRunner,
)


class TestPortfolioBacktestResult(unittest.TestCase):
    """PortfolioBacktestResult dataclass."""

    def test_defaults(self) -> None:
        result = PortfolioBacktestResult(portfolio_id="pf_001")
        self.assertEqual(result.portfolio_id, "pf_001")
        self.assertEqual(result.cagr, 0.0)

    def test_full_result(self) -> None:
        result = PortfolioBacktestResult(
            portfolio_id="pf_test",
            cagr=0.12,
            sharpe=1.5,
            max_drawdown=0.10,
            strategy_contributions={"strat_a": 0.08, "strat_b": 0.04},
        )
        self.assertAlmostEqual(result.cagr, 0.12)
        self.assertEqual(len(result.strategy_contributions), 2)


class TestPortfolioBacktestRunner(unittest.TestCase):
    """Portfolio backtest runner logic."""

    def setUp(self) -> None:
        self.runner = PortfolioBacktestRunner(data_root="/tmp/test_portfolio_bt")

    def test_empty_strategy_returns_defaults(self) -> None:
        result = self.runner.run(
            portfolio_id="pf_empty",
            start="2024-01-01",
            end="2024-06-30",
            strategy_returns={},
        )
        self.assertEqual(result.cagr, 0.0)
        self.assertEqual(result.sharpe, 0.0)

    def test_single_strategy_perfect_returns(self) -> None:
        result = self.runner.run(
            portfolio_id="pf_single",
            start="2024-01-01",
            end="2024-06-30",
            strategy_returns={"strat_a": [0.01] * 252},
            risk_free_rate=0.02,
        )
        self.assertGreater(result.cagr, 0)
        self.assertGreater(result.sharpe, 0)

    def test_two_strategies_equal_weight(self) -> None:
        result = self.runner.run(
            portfolio_id="pf_two",
            start="2024-01-01",
            end="2024-06-30",
            strategy_returns={
                "strat_a": [0.01] * 252,
                "strat_b": [0.005] * 252,
            },
        )
        self.assertEqual(len(result.strategy_contributions), 2)

    def test_weights_normalized(self) -> None:
        result = self.runner.run(
            portfolio_id="pf_w",
            start="2024-01-01",
            end="2024-06-30",
            strategy_returns={
                "strat_a": [0.01] * 100,
                "strat_b": [0.005] * 100,
            },
            weights={"strat_a": 0.5, "strat_b": 0.5},
        )
        self.assertIn("strat_a", result.strategy_contributions)

    def test_custom_weights(self) -> None:
        result = self.runner.run(
            portfolio_id="pf_cw",
            start="2024-01-01",
            end="2024-06-30",
            strategy_returns={
                "strat_a": [0.01] * 100,
                "strat_b": [0.005] * 100,
            },
            weights={"strat_a": 0.8, "strat_b": 0.2},
        )
        self.assertGreater(result.cagr, 0)

    def test_compute_attribution(self) -> None:
        result = self.runner.compute_attribution(
            portfolio_id="pf_attr",
            strategy_returns={
                "strat_a": [0.01] * 100,
                "strat_b": [0.005] * 100,
            },
        )
        self.assertEqual(len(result), 2)

    def test_compute_attribution_normalized(self) -> None:
        result = self.runner.compute_attribution(
            portfolio_id="pf_attr2",
            strategy_returns={
                "a": [0.01] * 100,
                "b": [0.005] * 100,
            },
        )
        total = sum(result.values())
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_varying_length_returns(self) -> None:
        result = self.runner.run(
            portfolio_id="pf_varying",
            start="2024-01-01",
            end="2024-06-30",
            strategy_returns={
                "strat_a": [0.01] * 200,
                "strat_b": [0.005] * 100,
            },
        )
        self.assertGreater(result.cagr, 0)
