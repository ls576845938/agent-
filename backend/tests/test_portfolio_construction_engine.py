"""Tests for PortfolioConstructionEngine.

Covers: construct from candidates, equal weight, inverse vol, risk parity.
"""

from __future__ import annotations

import unittest
from datetime import date
from tempfile import TemporaryDirectory

from quant_us.portfolio.construction.engine import (
    PortfolioConfig,
    PortfolioConstructionEngine,
    PortfolioTarget,
)
from quant_us.portfolio.construction.allocator import AllocationMethod


class TestPortfolioConfig(unittest.TestCase):
    """PortfolioConfig dataclass."""

    def test_default_config(self) -> None:
        config = PortfolioConfig(portfolio_id="pf_001")
        self.assertEqual(config.portfolio_id, "pf_001")
        self.assertEqual(config.capital, 100000.0)
        self.assertEqual(config.max_single_weight, 0.25)
        self.assertEqual(config.rebalance_frequency, "monthly")

    def test_custom_config(self) -> None:
        config = PortfolioConfig(
            portfolio_id="pf_002",
            capital=500000.0,
            max_single_weight=0.15,
            max_gross_exposure=0.8,
        )
        self.assertEqual(config.capital, 500000.0)
        self.assertEqual(config.max_single_weight, 0.15)


class TestPortfolioConstructionEngine(unittest.TestCase):
    """Portfolio construction engine tests."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.engine = PortfolioConstructionEngine(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_scorecard(self, sid: str, vol: float = 0.15, ret: float = 0.10) -> dict:
        return {
            "id": sid,
            "volatility": vol,
            "expected_return": ret,
        }

    def test_construct_empty_candidates(self) -> None:
        config = PortfolioConfig(portfolio_id="pf_empty")
        target = self.engine.construct(config, [])
        self.assertEqual(target.portfolio_id, "pf_empty")
        self.assertEqual(target.strategy_weights, {})

    def test_construct_single_candidate(self) -> None:
        config = PortfolioConfig(portfolio_id="pf_single")
        candidates = [self._make_scorecard("strat_a")]
        target = self.engine.construct(config, candidates)
        self.assertEqual(target.portfolio_id, "pf_single")
        self.assertIn("strat_a", target.strategy_weights)
        self.assertAlmostEqual(target.strategy_weights["strat_a"], 1.0)

    def test_construct_equal_weight_fallback(self) -> None:
        config = PortfolioConfig(portfolio_id="pf_equal")
        candidates = [
            self._make_scorecard("strat_a", vol=0.20),
            self._make_scorecard("strat_b", vol=0.20),
        ]
        target = self.engine.construct(config, candidates)
        self.assertEqual(len(target.strategy_weights), 2)
        self.assertAlmostEqual(target.strategy_weights["strat_a"], 0.5, places=4)
        self.assertAlmostEqual(target.strategy_weights["strat_b"], 0.5, places=4)

    def test_construct_inverse_vol(self) -> None:
        config = PortfolioConfig(portfolio_id="pf_inv_vol", max_single_weight=0.9)
        candidates = [
            self._make_scorecard("low_vol", vol=0.10),
            self._make_scorecard("high_vol", vol=0.30),
        ]
        target = self.engine.construct(config, candidates)
        # Low vol should get higher weight
        self.assertGreater(
            target.strategy_weights["low_vol"],
            target.strategy_weights["high_vol"],
        )

    def test_construct_with_capital(self) -> None:
        config = PortfolioConfig(portfolio_id="pf_cap", capital=200000.0)
        candidates = [self._make_scorecard("strat_a")]
        target = self.engine.construct(config, candidates)
        self.assertEqual(target.total_capital, 200000.0)

    def test_construct_with_holdings(self) -> None:
        config = PortfolioConfig(portfolio_id="pf_hold", capital=100000.0)
        candidates = [{
            "id": "strat_a",
            "volatility": 0.15,
            "expected_return": 0.10,
            "holdings": {"AAPL": 0.5, "MSFT": 0.5},
        }]
        target = self.engine.construct(config, candidates)
        self.assertIn("AAPL", target.symbol_exposures)
        self.assertIn("MSFT", target.symbol_exposures)

    def test_rebalance_simple(self) -> None:
        target = self.engine.rebalance(
            portfolio_id="pf_rebal",
            current_weights={"strat_a": 0.6, "strat_b": 0.4},
        )
        self.assertEqual(target.portfolio_id, "pf_rebal")
        self.assertIn("strat_a", target.strategy_weights)

    def test_rebalance_empty_weights(self) -> None:
        target = self.engine.rebalance(
            portfolio_id="pf_empty",
            current_weights={},
        )
        self.assertEqual(target.strategy_weights, {})

    def test_save_and_load_target(self) -> None:
        config = PortfolioConfig(portfolio_id="pf_saveload")
        candidates = [self._make_scorecard("strat_a")]
        target = self.engine.construct(config, candidates)
        saved_path = self.engine.save_target(target)
        loaded = self.engine.load_target("pf_saveload", path=saved_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.portfolio_id, "pf_saveload")
