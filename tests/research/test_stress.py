"""Tests for PortfolioStressTester."""

from __future__ import annotations

import pytest

from quant_us.research.portfolio_research.stress import (
    PortfolioStressTester,
    StressResult,
)


class TestPortfolioStressTester:
    """Tests for PortfolioStressTester."""

    def _make_returns(self, n: int = 252) -> list[float]:
        """Generate simple synthetic returns."""
        import random
        random.seed(42)
        return [random.gauss(0.0005, 0.012) for _ in range(n)]

    # ------------------------------------------------------------------
    # cost_stress
    # ------------------------------------------------------------------

    def test_cost_stress_returns_dict(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_cost_stress(returns, multipliers=[2.0, 3.0])
        assert isinstance(result, dict)
        assert "2.0" in result
        assert "3.0" in result
        assert "stressed_return_pct" in result["2.0"]
        assert "cost_hit" in result["2.0"]

    def test_cost_stress_higher_multiplier_worse_return(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_cost_stress(returns, multipliers=[1.0, 10.0])
        # Higher multiplier should yield lower (more negative) return
        assert result["1.0"]["stressed_return_pct"] >= result["10.0"]["stressed_return_pct"]

    def test_cost_stress_empty_returns(self) -> None:
        tester = PortfolioStressTester()
        result = tester.test_cost_stress([], multipliers=[2.0])
        assert "2.0" in result

    def test_cost_stress_default_multipliers(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_cost_stress(returns)
        assert set(result.keys()) == {"2.0", "3.0", "5.0"}

    # ------------------------------------------------------------------
    # slippage_stress
    # ------------------------------------------------------------------

    def test_slippage_stress_returns_dict(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_slippage_stress(returns, multipliers=[2.0, 3.0])
        assert isinstance(result, dict)
        assert "2.0" in result
        assert "stressed_max_drawdown_pct" in result["2.0"]

    def test_slippage_stress_default_multipliers(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_slippage_stress(returns)
        assert set(result.keys()) == {"2.0", "3.0"}

    def test_slippage_stress_higher_mult_drawdown(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_slippage_stress(returns, multipliers=[1.0, 100.0])
        # Higher slippage should cause worse drawdown
        assert result["1.0"]["stressed_max_drawdown_pct"] >= result["100.0"]["stressed_max_drawdown_pct"]

    # ------------------------------------------------------------------
    # crash_window
    # ------------------------------------------------------------------

    def test_crash_window_returns_dict(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_crash_window(
            returns,
            crash_periods=[("mild", "1.5"), ("severe", "2.5")],
        )
        assert "mild" in result
        assert "severe" in result
        assert "survival_flag" in result["mild"]

    def test_crash_window_severe_worse_than_mild(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_crash_window(
            returns,
            crash_periods=[("mild", "1.0"), ("severe", "100.0")],
        )
        # Severe crash should have much worse return
        assert result["mild"]["stressed_return_pct"] > result["severe"]["stressed_return_pct"]

    # ------------------------------------------------------------------
    # signal_delay
    # ------------------------------------------------------------------

    def test_signal_delay_returns_dict(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_signal_delay(returns, delay_bars=[1, 2])
        assert "1" in result
        assert "2" in result
        assert "stressed_return_pct" in result["1"]

    def test_signal_delay_longer_delay_worse(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_signal_delay(returns, delay_bars=[1, 5])
        assert result["1"]["stressed_return_pct"] >= result["5"]["stressed_return_pct"]

    def test_signal_delay_ignores_non_positive(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        result = tester.test_signal_delay(returns, delay_bars=[0, -1])
        assert result == {}

    # ------------------------------------------------------------------
    # run_all
    # ------------------------------------------------------------------

    def test_run_all_returns_stress_result(self) -> None:
        tester = PortfolioStressTester()
        result = tester.run_all("portfolio_1")
        assert isinstance(result, StressResult)
        assert result.portfolio_id == "portfolio_1"
        assert 0.0 <= result.stress_survival_rate <= 1.0
        assert result.worst_case_drawdown >= 0.0
        assert result.capacity_warning in ("OK", "WARN_HIGH_TURNOVER", "WARN_CONCENTRATION")
        assert 0.0 <= result.fragility_score <= 1.0

    def test_run_all_scenarios_present(self) -> None:
        tester = PortfolioStressTester()
        result = tester.run_all("portfolio_1")
        expected_scenarios = {
            "cost_stress", "slippage_stress",
            "crash_stress", "signal_delay_stress",
        }
        assert expected_scenarios.issubset(set(result.scenarios.keys()))

    def test_run_all_includes_all_sub_scenarios(self) -> None:
        tester = PortfolioStressTester()
        result = tester.run_all("portfolio_1")
        # Each scenario bucket should have entries
        for bucket_name in ("cost_stress", "slippage_stress", "crash_stress", "signal_delay_stress"):
            assert len(result.scenarios[bucket_name]) > 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def test_compute_max_drawdown_no_negatives(self) -> None:
        tester = PortfolioStressTester()
        returns = [0.001] * 100  # always positive
        dd = tester._compute_max_drawdown(returns)
        assert dd == 0.0

    def test_compute_max_drawdown_has_drawdown(self) -> None:
        tester = PortfolioStressTester()
        # Start positive, then crash
        returns = [0.01] * 50 + [-0.2] + [-0.1] * 10
        dd = tester._compute_max_drawdown(returns)
        assert dd < 0.0

    def test_compute_max_drawdown_empty(self) -> None:
        tester = PortfolioStressTester()
        assert tester._compute_max_drawdown([]) == 0.0

    def test_estimate_base_cost_returns_positive(self) -> None:
        tester = PortfolioStressTester()
        returns = self._make_returns()
        cost = tester._estimate_base_cost(returns)
        assert cost > 0.0

    def test_estimate_base_cost_empty(self) -> None:
        tester = PortfolioStressTester()
        assert tester._estimate_base_cost([]) == 0.001
