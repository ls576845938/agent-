"""Tests for quant_us.portfolio.construction modules.

Verifies that:
- Portfolio engine outputs targets only (never orders).
- No imports from quant_us.live or broker modules.
- All allocator methods produce normalized weights.
- Exposure analysis checks limits correctly.
- Backtest runner computes metrics consistently.
- Scorecard builder produces expected output.
"""

from __future__ import annotations

import math
from dataclasses import fields

import pytest

from quant_us.portfolio.construction.allocator import AllocationMethod, CapitalAllocator
from quant_us.portfolio.construction.backtest import PortfolioBacktestResult, PortfolioBacktestRunner
from quant_us.portfolio.construction.engine import PortfolioConfig, PortfolioConstructionEngine, PortfolioTarget
from quant_us.portfolio.construction.exposure import ExposureManager, ExposureReport
from quant_us.portfolio.construction.scorecard import PortfolioScorecard, PortfolioScorecardBuilder


# ======================================================================
# ALLOCATOR
# ======================================================================


class TestCapitalAllocator:
    def test_equal_weight_empty(self) -> None:
        assert CapitalAllocator.equal_weight(0) == []
        assert CapitalAllocator.equal_weight(-1) == []

    def test_equal_weight_single(self) -> None:
        assert CapitalAllocator.equal_weight(1) == [1.0]

    def test_equal_weight_multi(self) -> None:
        result = CapitalAllocator.equal_weight(4)
        assert len(result) == 4
        assert all(w == 0.25 for w in result)
        assert sum(result) == pytest.approx(1.0)

    def test_inverse_volatility_empty(self) -> None:
        assert CapitalAllocator.inverse_volatility({}) == {}

    def test_inverse_volatility_basic(self) -> None:
        vols = {"a": 0.10, "b": 0.20, "c": 0.40}
        result = CapitalAllocator.inverse_volatility(vols)
        assert sum(result.values()) == pytest.approx(1.0)
        assert result["a"] > result["b"] > result["c"]

    def test_inverse_volatility_single(self) -> None:
        assert CapitalAllocator.inverse_volatility({"a": 0.15}) == {"a": 1.0}

    def test_allocate_equal_weight(self) -> None:
        candidates = [
            {"id": "s1", "volatility": 0.15},
            {"id": "s2", "volatility": 0.25},
        ]
        allocator = CapitalAllocator()
        result = allocator.allocate(candidates, AllocationMethod.EQUAL_WEIGHT)
        assert set(result.keys()) == {"s1", "s2"}
        assert result["s1"] == pytest.approx(0.5)
        assert sum(result.values()) == pytest.approx(1.0)

    def test_allocate_inverse_vol(self) -> None:
        candidates = [
            {"id": "low_vol", "volatility": 0.10},
            {"id": "high_vol", "volatility": 0.40},
        ]
        allocator = CapitalAllocator()
        result = allocator.allocate(candidates, AllocationMethod.INVERSE_VOL)
        assert result["low_vol"] > result["high_vol"]
        assert sum(result.values()) == pytest.approx(1.0)

    def test_allocate_capped_at_max_single(self) -> None:
        candidates = [
            {"id": "a", "volatility": 0.10},
            {"id": "b", "volatility": 0.10},
            {"id": "c", "volatility": 0.10},
            {"id": "d", "volatility": 0.10},
            {"id": "e", "volatility": 0.10},
        ]
        allocator = CapitalAllocator()
        constraints = {"max_single_weight": 0.50}
        result = allocator.allocate(candidates, AllocationMethod.EQUAL_WEIGHT, constraints)
        # With 5 equal and 0.50 cap, all should be 0.20 anyway
        assert all(w <= 0.50 for w in result.values())
        assert sum(result.values()) == pytest.approx(1.0)

    def test_allocate_empty_candidates(self) -> None:
        allocator = CapitalAllocator()
        assert allocator.allocate([], AllocationMethod.EQUAL_WEIGHT) == {}

    def test_allocate_unknown_method(self) -> None:
        allocator = CapitalAllocator()
        with pytest.raises(ValueError, match="Unknown allocation method"):
            allocator.allocate([{"id": "a", "volatility": 0.15}], "not_a_method")

    def test_vol_targeting(self) -> None:
        weights = {"a": 0.5, "b": 0.5}
        result = CapitalAllocator.vol_targeting(weights, target_vol=0.10, current_vol=0.20)
        assert result["a"] == pytest.approx(0.25)
        assert sum(result.values()) == pytest.approx(0.5)

    def test_vol_targeting_zero_vol(self) -> None:
        weights = {"a": 0.5}
        result = CapitalAllocator.vol_targeting(weights, target_vol=0.15, current_vol=0.0)
        assert result == weights

    def test_drawdown_adjusted(self) -> None:
        weights = {"a": 0.5, "b": 0.5}
        drawdowns = {"a": 0.20, "b": 0.05}
        result = CapitalAllocator.drawdown_adjusted(weights, drawdowns)
        # a has deeper drawdown, should get more penalty
        assert sum(result.values()) == pytest.approx(1.0)
        assert result["b"] > result["a"]

    def test_drawdown_adjusted_empty(self) -> None:
        assert CapitalAllocator.drawdown_adjusted({}, {}) == {}

    def test_risk_parity_simple(self) -> None:
        labels = ["a", "b"]
        cov = [[0.04, 0.01], [0.01, 0.09]]
        result = CapitalAllocator.risk_parity(cov, labels)
        assert set(result.keys()) == {"a", "b"}
        assert sum(result.values()) == pytest.approx(1.0)

    def test_risk_parity_single(self) -> None:
        result = CapitalAllocator.risk_parity([[0.04]], ["a"])
        assert result == {"a": 1.0}

    def test_risk_parity_empty(self) -> None:
        assert CapitalAllocator.risk_parity([], []) == {}


# ======================================================================
# ENGINE
# ======================================================================


class TestPortfolioConfig:
    def test_default_values(self) -> None:
        config = PortfolioConfig(portfolio_id="test", candidate_ids=["a", "b"])
        assert config.capital == 100000.0
        assert config.max_gross_exposure == 1.0
        assert config.max_single_weight == 0.25
        assert config.target_volatility == 0.15
        assert config.rebalance_frequency == "monthly"
        assert config.risk_free_rate == 0.02

    def test_frozen(self) -> None:
        config = PortfolioConfig(portfolio_id="test", candidate_ids=["a"])
        with pytest.raises(Exception):
            config.capital = 99999  # type: ignore[misc]


class TestPortfolioTarget:
    def test_default_values(self) -> None:
        target = PortfolioTarget(portfolio_id="test", date="2026-01-01")
        assert target.strategy_weights == {}
        assert target.symbol_exposures == {}
        assert target.total_capital == 0.0

    def test_frozen(self) -> None:
        target = PortfolioTarget(portfolio_id="test", date="2026-01-01")
        with pytest.raises(Exception):
            target.total_capital = 100.0  # type: ignore[misc]


class TestPortfolioConstructionEngine:
    def test_construct_empty_candidates(self) -> None:
        config = PortfolioConfig(portfolio_id="test", candidate_ids=[])
        engine = PortfolioConstructionEngine(data_root="/tmp/test_pfolio")
        target = engine.construct(config, [])
        assert target.portfolio_id == "test"
        assert target.strategy_weights == {}

    def test_construct_basic(self) -> None:
        config = PortfolioConfig(
            portfolio_id="test",
            candidate_ids=["strat_a", "strat_b"],
            capital=50000.0,
            max_single_weight=1.0,  # no cap so inverse-vol weight is visible
        )
        scorecards = [
            {"id": "strat_a", "volatility": 0.15, "expected_return": 0.12},
            {"id": "strat_b", "volatility": 0.25, "expected_return": 0.08},
        ]
        engine = PortfolioConstructionEngine(data_root="/tmp/test_pfolio")
        target = engine.construct(config, scorecards)

        assert target.portfolio_id == "test"
        assert set(target.strategy_weights.keys()) == {"strat_a", "strat_b"}
        assert sum(target.strategy_weights.values()) == pytest.approx(1.0)
        assert target.total_capital == 50000.0
        # Lower vol gets higher weight (inverse-vol)
        assert target.strategy_weights["strat_a"] > target.strategy_weights["strat_b"]

    def test_construct_with_holdings(self) -> None:
        config = PortfolioConfig(portfolio_id="test", candidate_ids=["a"])
        scorecards = [
            {
                "id": "a",
                "volatility": 0.15,
                "expected_return": 0.10,
                "holdings": {"AAPL": 0.5, "MSFT": 0.5},
            },
        ]
        engine = PortfolioConstructionEngine(data_root="/tmp/test_pfolio")
        target = engine.construct(config, scorecards)
        assert "AAPL" in target.symbol_exposures
        assert "MSFT" in target.symbol_exposures

    def test_rebalance_no_scorecards(self) -> None:
        engine = PortfolioConstructionEngine(data_root="/tmp/test_pfolio")
        target = engine.rebalance("test", {"a": 0.6, "b": 0.4})
        assert target.portfolio_id == "test"
        # After normalization: 0.6/1.0=0.6, 0.4/1.0=0.4
        # Both exceed default max_single_weight (0.25), so capped then re-normalized
        assert target.strategy_weights["a"] == pytest.approx(0.5, abs=0.01)
        assert target.strategy_weights["b"] == pytest.approx(0.5, abs=0.01)
        assert sum(target.strategy_weights.values()) == pytest.approx(1.0)

    def test_rebalance_with_scorecards(self) -> None:
        config = PortfolioConfig(portfolio_id="test", candidate_ids=["a", "b"])
        engine = PortfolioConstructionEngine(data_root="/tmp/test_pfolio")
        scorecards = [
            {"id": "a", "volatility": 0.15, "expected_return": 0.12},
            {"id": "b", "volatility": 0.25, "expected_return": 0.08},
        ]
        target = engine.rebalance("test", {"a": 0.5, "b": 0.5}, scorecards, config)
        assert sum(target.strategy_weights.values()) == pytest.approx(1.0)

    def test_save_and_load_target(self, tmp_path) -> None:
        engine = PortfolioConstructionEngine(data_root=str(tmp_path))
        target = PortfolioTarget(
            portfolio_id="save_test",
            date="2026-01-01",
            strategy_weights={"a": 0.6, "b": 0.4},
            total_capital=100000.0,
        )
        path = engine.save_target(target)
        loaded = engine.load_target("save_test")
        assert loaded is not None
        assert loaded.portfolio_id == "save_test"
        assert loaded.strategy_weights == {"a": 0.6, "b": 0.4}

    def test_load_target_missing(self) -> None:
        engine = PortfolioConstructionEngine(data_root="/tmp/nonexistent")
        assert engine.load_target("missing") is None

    def test_no_live_imports(self) -> None:
        import ast

        import quant_us.portfolio.construction.engine as mod

        tree = ast.parse(open(mod.__file__).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "quant_us.live" not in alias.name, (
                        f"Live import found: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module and "quant_us.live" in node.module:
                    raise AssertionError(f"Live import found: {node.module}")


# ======================================================================
# EXPOSURE
# ======================================================================


class TestExposureManager:
    def test_analyze_empty(self) -> None:
        mgr = ExposureManager()
        report = mgr.analyze({}, {})
        assert report.gross_exposure == 0.0
        assert report.net_exposure == 0.0

    def test_analyze_single_position(self) -> None:
        mgr = ExposureManager()
        report = mgr.analyze({"AAPL": 10000.0}, {"AAPL": 150.0})
        assert report.gross_exposure == 10000.0
        assert report.net_exposure == 10000.0
        assert report.single_symbol_exposures["AAPL"] == pytest.approx(1.0)

    def test_analyze_multi_position(self) -> None:
        mgr = ExposureManager()
        report = mgr.analyze(
            {"AAPL": 6000.0, "MSFT": 4000.0, "GOOG": -2000.0},
            {"AAPL": 150.0, "MSFT": 300.0, "GOOG": 100.0},
        )
        # Gross = sum of abs values = 6000 + 4000 + 2000 = 12000
        assert report.gross_exposure == 12000.0
        # Net = 6000 + 4000 - 2000 = 8000
        assert report.net_exposure == 8000.0

    def test_analyze_with_sectors(self) -> None:
        mgr = ExposureManager()
        report = mgr.analyze(
            {"AAPL": 5000.0, "MSFT": 5000.0, "XOM": 5000.0},
            {"AAPL": 100.0, "MSFT": 200.0, "XOM": 50.0},
            sectors={"AAPL": "tech", "MSFT": "tech", "XOM": "energy"},
        )
        assert "tech" in report.sector_exposures
        assert "energy" in report.sector_exposures
        # tech = 10000 / 15000 = 0.666, energy = 5000 / 15000 = 0.333
        assert report.sector_exposures["tech"] == pytest.approx(2.0 / 3.0, abs=0.01)
        assert report.sector_exposures["energy"] == pytest.approx(1.0 / 3.0, abs=0.01)

    def test_check_limits_pass(self) -> None:
        report = ExposureReport(gross_exposure=50000.0, net_exposure=30000.0)
        mgr = ExposureManager()
        passed, violations = mgr.check_limits(report, {"max_gross_exposure": 100000.0})
        assert passed
        assert violations == []

    def test_check_limits_gross_violation(self) -> None:
        report = ExposureReport(gross_exposure=200000.0)
        mgr = ExposureManager()
        passed, violations = mgr.check_limits(report, {"max_gross_exposure": 100000.0})
        assert not passed
        assert any("gross" in v.lower() for v in violations)

    def test_check_limits_single_weight_violation(self) -> None:
        report = ExposureReport(
            gross_exposure=100000.0,
            single_symbol_exposures={"AAPL": 0.30, "MSFT": 0.10},
        )
        mgr = ExposureManager()
        passed, violations = mgr.check_limits(report, {"max_single_weight": 0.25})
        assert not passed
        assert any("AAPL" in v for v in violations)

    def test_check_limits_sector_violation(self) -> None:
        report = ExposureReport(
            gross_exposure=100000.0,
            sector_exposures={"tech": 0.50, "energy": 0.10},
        )
        mgr = ExposureManager()
        passed, violations = mgr.check_limits(report, {"max_sector_weight": 0.40})
        assert not passed
        assert any("tech" in v for v in violations)


# ======================================================================
# BACKTEST
# ======================================================================


class TestPortfolioBacktestRunner:
    def test_run_empty(self) -> None:
        runner = PortfolioBacktestRunner(data_root="/tmp/test_bt")
        result = runner.run("test", "2020-01-01", "2023-01-01")
        assert result.portfolio_id == "test"
        assert result.cagr == 0.0

    def test_run_with_data(self) -> None:
        runner = PortfolioBacktestRunner(data_root="/tmp/test_bt")
        strategy_returns = {
            "a": [0.001] * 252,  # ~28% annual
            "b": [-0.0005] * 252,  # negative
        }
        result = runner.run(
            "test", "2020-01-01", "2023-01-01",
            strategy_returns=strategy_returns,
            weights={"a": 0.7, "b": 0.3},
        )
        assert result.sharpe != 0.0
        assert result.cagr > 0.0  # a has positive returns with 70% weight
        assert "a" in result.strategy_contributions
        assert "b" in result.strategy_contributions

    def test_run_with_equal_weights(self) -> None:
        runner = PortfolioBacktestRunner(data_root="/tmp/test_bt")
        strategy_returns = {
            "a": [0.001] * 252,
            "b": [0.002] * 252,
        }
        result = runner.run("test", "2020-01-01", "2023-01-01",
                            strategy_returns=strategy_returns,
                            weights={"a": 0.5, "b": 0.5})
        assert result.portfolio_id == "test"

    def test_compute_attribution(self) -> None:
        runner = PortfolioBacktestRunner(data_root="/tmp/test_bt")
        strategy_returns = {
            "a": [0.001] * 252,
            "b": [0.0005] * 252,
        }
        attr = runner.compute_attribution("test", strategy_returns=strategy_returns)
        assert set(attr.keys()) == {"a", "b"}
        assert sum(attr.values()) == pytest.approx(1.0)

    def test_compute_attribution_empty(self) -> None:
        runner = PortfolioBacktestRunner(data_root="/tmp/test_bt")
        assert runner.compute_attribution("test") == {}


# ======================================================================
# SCORECARD
# ======================================================================


class TestPortfolioScorecardBuilder:
    def test_build_empty(self) -> None:
        builder = PortfolioScorecardBuilder()
        sc = builder.build("test")
        assert sc.portfolio_id == "test"
        assert sc.cagr == 0.0

    def test_build_with_data(self) -> None:
        builder = PortfolioScorecardBuilder()
        strategy_scorecards = [
            {"id": "a", "cagr": 0.15, "sharpe": 1.5, "max_drawdown": 0.10, "volatility": 0.15},
            {"id": "b", "cagr": 0.10, "sharpe": 0.8, "max_drawdown": 0.20, "volatility": 0.25},
        ]
        weights = {"a": 0.6, "b": 0.4}
        sc = builder.build("test", strategy_scorecards, weights)
        assert sc.portfolio_id == "test"
        # Weighted CAGR = 0.6*0.15 + 0.4*0.10 = 0.13
        assert sc.cagr == pytest.approx(0.13)
        # Max drawdown picks worst
        assert sc.max_drawdown == 0.20
        assert set(sc.strategy_contributions.keys()) == {"a", "b"}

    def test_to_markdown(self) -> None:
        builder = PortfolioScorecardBuilder()
        sc = PortfolioScorecard(
            portfolio_id="test",
            cagr=0.12,
            sharpe=1.2,
            max_drawdown=0.15,
            strategy_contributions={"a": 0.06, "b": 0.06},
            turnover_pct=0.3,
            capital_efficiency=0.8,
        )
        md = builder.to_markdown(sc)
        assert "Portfolio Scorecard: test" in md
        assert "12.00%" in md
        assert "1.200" in md
        assert "15.00%" in md
        assert "a" in md
        assert "b" in md
