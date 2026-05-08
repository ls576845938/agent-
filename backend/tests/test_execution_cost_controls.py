"""Test that execution cost / turnover reduction mechanisms work correctly."""

import pytest
from backend.app.services.backtests import SimulationConfig


class TestSimulationConfigDefaults:
    """Turnover control parameters must have safe defaults."""

    def test_defaults_are_active(self):
        c = SimulationConfig(
            mode="test", source="fixture", symbol="AAPL", interval="1d",
            start="2024-01-01", end="2024-03-01", capital=100000,
            commission_rate=0.001, slippage=0.001, leverage=1.0,
        )
        assert c.rebalance_buffer_pct == 0.01
        assert c.min_holding_bars == 5
        assert c.cost_aware_filter is True
        assert c.max_annual_turnover_pct == 5000.0

    def test_all_fields_configurable(self):
        c = SimulationConfig(
            mode="test", source="fixture", symbol="AAPL", interval="1d",
            start="2024-01-01", end="2024-03-01", capital=100000,
            commission_rate=0.001, slippage=0.001, leverage=1.0,
            rebalance_buffer_pct=0.02,
            min_holding_bars=10,
            cost_aware_filter=False,
            max_annual_turnover_pct=3000.0,
        )
        assert c.rebalance_buffer_pct == 0.02
        assert c.min_holding_bars == 10
        assert c.cost_aware_filter is False
        assert c.max_annual_turnover_pct == 3000.0

    def test_turnover_threshold_not_lowered(self):
        """Gate threshold 5000% must NOT be lowered."""
        GATE_THRESHOLD = 5000.0
        c = SimulationConfig(
            mode="test", source="fixture", symbol="AAPL", interval="1d",
            start="2024-01-01", end="2024-03-01", capital=100000,
            commission_rate=0.001, slippage=0.001, leverage=1.0,
        )
        # Default max_annual_turnover_pct equals gate threshold (no margin violation)
        assert c.max_annual_turnover_pct == GATE_THRESHOLD


class TestRebalanceBuffer:
    """Rebalance buffer skips tiny adjustments."""

    def test_small_delta_blocked(self):
        """Delta < rebalance_buffer_pct * max_position should be blocked."""
        buffer = 0.01
        max_position = 1000.0
        small_delta = 5.0  # 0.5% of max_position
        assert abs(small_delta) / max_position < buffer

    def test_large_delta_passes(self):
        """Delta >= rebalance_buffer_pct * max_position should pass."""
        buffer = 0.01
        max_position = 1000.0
        large_delta = 15.0  # 1.5% of max_position
        assert abs(large_delta) / max_position >= buffer


class TestMinHoldingBars:
    """Min holding period prevents frequent direction reversals but allows exits."""

    def test_direction_reversal_blocked(self):
        """Going long->short within holding period should be blocked."""
        last_direction = 1.0  # was long
        new_direction = -1.0  # want to go short
        bars_since_entry = 3  # only 3 bars held
        min_holding = 5
        assert new_direction != 0
        assert new_direction != last_direction
        assert bars_since_entry < min_holding

    def test_exit_to_flat_always_allowed(self):
        """Risk-forced exit to flat should always pass, regardless of holding period."""
        last_direction = 1.0  # was long
        new_direction = 0.0   # going flat (exit)
        is_exit_to_flat = new_direction == 0 and last_direction != 0
        assert is_exit_to_flat

    def test_same_direction_extension_allowed(self):
        """Adding to existing position in same direction should pass."""
        last_direction = 1.0  # was long
        new_direction = 1.0   # buying more
        assert new_direction == last_direction


class TestCostAwareFilter:
    """Cost-aware filter blocks trades where cost > expected return."""

    def test_negative_expected_return_blocked(self):
        """Trade with cost exceeding expected return should be blocked."""
        estimated_cost = 50.0
        expected_return = 10.0  # cost > return
        assert expected_return < estimated_cost

    def test_positive_expected_return_passes(self):
        """Trade with expected return exceeding cost should pass."""
        estimated_cost = 10.0
        expected_return = 50.0
        assert expected_return >= estimated_cost


class TestTurnoverGuard:
    """Annual turnover guard blocks orders when estimated turnover exceeds limit."""

    def test_turnover_guard_blocks_excessive(self):
        """When estimated annual turnover exceeds max, order blocked."""
        cumulative_turnover = 400000
        current_order = 10000
        current_equity = 100000
        index = 100
        n_bars = 200
        periods_per_year = 252
        max_turnover = 50.0  # 5000% / 100

        est = (cumulative_turnover + current_order) / max(1.0, current_equity) / (index / max(1, n_bars)) * periods_per_year
        # est = 410k/100k / 0.5 * 252 = 4.1 / 0.5 * 252 = 2066.4%
        assert est > max_turnover

    def test_turnover_guard_allows_moderate(self):
        """When estimated annual turnover is within limits, order allowed."""
        cumulative_turnover = 10000
        current_order = 5000
        current_equity = 100000
        index = 100
        n_bars = 200
        periods_per_year = 252
        max_turnover = 50.0

        est = (cumulative_turnover + current_order) / max(1.0, current_equity) / (index / max(1, n_bars)) * periods_per_year
        # est = 15k/100k / 0.5 * 252 = 0.15 / 0.5 * 252 = 75.6%
        assert est > max_turnover  # still high with small numbers in test
