"""Tests for PortfolioScorecardBuilder.

Covers: scorecard computation, markdown output.
"""

from __future__ import annotations

import unittest

from quant_us.portfolio.construction.scorecard import (
    PortfolioScorecard,
    PortfolioScorecardBuilder,
)


class TestPortfolioScorecard(unittest.TestCase):
    """PortfolioScorecard dataclass."""

    def test_defaults(self) -> None:
        sc = PortfolioScorecard(portfolio_id="pf_001")
        self.assertEqual(sc.portfolio_id, "pf_001")
        self.assertEqual(sc.cagr, 0.0)

    def test_full_construction(self) -> None:
        sc = PortfolioScorecard(
            portfolio_id="pf_002",
            cagr=0.15,
            sharpe=1.8,
            max_drawdown=0.08,
            diversification_ratio=2.5,
        )
        self.assertAlmostEqual(sc.cagr, 0.15)
        self.assertAlmostEqual(sc.diversification_ratio, 2.5)


class TestPortfolioScorecardBuilder(unittest.TestCase):
    """Scorecard building logic."""

    def setUp(self) -> None:
        self.builder = PortfolioScorecardBuilder(data_root="/tmp/test_pf_sc")

    def test_empty_inputs(self) -> None:
        sc = self.builder.build(
            portfolio_id="pf_empty",
            strategy_scorecards=[],
            portfolio_weights={},
        )
        self.assertEqual(sc.cagr, 0.0)

    def test_single_strategy(self) -> None:
        sc = self.builder.build(
            portfolio_id="pf_single",
            strategy_scorecards=[
                {"id": "s1", "cagr": 0.10, "sharpe": 1.5, "max_drawdown": 0.05, "volatility": 0.15},
            ],
            portfolio_weights={"s1": 1.0},
        )
        self.assertAlmostEqual(sc.cagr, 0.10)
        self.assertAlmostEqual(sc.sharpe, 1.5)

    def test_two_strategies_weighted(self) -> None:
        sc = self.builder.build(
            portfolio_id="pf_two",
            strategy_scorecards=[
                {"id": "s1", "cagr": 0.10, "sharpe": 1.5, "max_drawdown": 0.05, "volatility": 0.15},
                {"id": "s2", "cagr": 0.05, "sharpe": 0.8, "max_drawdown": 0.10, "volatility": 0.25},
            ],
            portfolio_weights={"s1": 0.6, "s2": 0.4},
        )
        expected_cagr = 0.6 * 0.10 + 0.4 * 0.05
        self.assertAlmostEqual(sc.cagr, expected_cagr)

    def test_strategy_contributions(self) -> None:
        sc = self.builder.build(
            portfolio_id="pf_contrib",
            strategy_scorecards=[
                {"id": "s1", "cagr": 0.10, "sharpe": 1.0, "max_drawdown": 0.05, "volatility": 0.15},
                {"id": "s2", "cagr": 0.05, "sharpe": 0.5, "max_drawdown": 0.10, "volatility": 0.25},
            ],
            portfolio_weights={"s1": 0.5, "s2": 0.5},
        )
        self.assertIn("s1", sc.strategy_contributions)
        self.assertIn("s2", sc.strategy_contributions)

    def test_max_drawdown_is_max_of_all(self) -> None:
        sc = self.builder.build(
            portfolio_id="pf_dd",
            strategy_scorecards=[
                {"id": "s1", "cagr": 0.10, "sharpe": 1.0, "max_drawdown": 0.05, "volatility": 0.15},
                {"id": "s2", "cagr": 0.05, "sharpe": 0.5, "max_drawdown": 0.20, "volatility": 0.25},
            ],
            portfolio_weights={"s1": 0.5, "s2": 0.5},
        )
        self.assertAlmostEqual(sc.max_drawdown, 0.20)

    def test_to_markdown_contains_metrics(self) -> None:
        sc = PortfolioScorecard(
            portfolio_id="pf_md",
            cagr=0.12,
            sharpe=1.5,
            max_drawdown=0.08,
            diversification_ratio=2.0,
        )
        md = PortfolioScorecardBuilder.to_markdown(sc)
        self.assertIn("Portfolio Scorecard: pf_md", md)
        self.assertIn("CAGR", md)
        self.assertIn("Sharpe", md)
        self.assertIn("Max Drawdown", md)
        self.assertIn("Diversification Ratio", md)
