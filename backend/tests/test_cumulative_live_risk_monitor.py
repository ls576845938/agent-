"""Tests for G6 CumulativeLiveRiskMonitor.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_us.live.g6_risk_monitor import (
    CumulativeLiveRiskMonitor,
    CumulativeRiskState,
)


class TestCumulativeLiveRiskMonitor:
    """Comprehensive tests for CumulativeLiveRiskMonitor safety invariants."""

    def test_initial_state_is_pass(self, tmp_path: Path) -> None:
        """Fresh risk state with no activity evaluates to PASS."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        state = monitor.evaluate(
            episode_id="ep_1",
            max_cumulative_notional=300.0,
            max_cumulative_loss=10.0,
        )
        assert state.status == "PASS"
        assert state.episode_id == "ep_1"

    def test_notional_exceeded_blocked(self, tmp_path: Path) -> None:
        """Cumulative notional over limit → BLOCK_NEW_ORDER."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        # Record an order that exceeds notional
        monitor.record_order("ep_1", notional=500.0)
        state = monitor.evaluate(
            episode_id="ep_1",
            max_cumulative_notional=300.0,
        )
        assert state.status == "BLOCK_NEW_ORDER"

    def test_cumulative_loss_exceeded_terminate(self, tmp_path: Path) -> None:
        """Cumulative loss over limit → TERMINATE_EPISODE."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.update_pnl("ep_1", realized_pnl=-20.0)
        state = monitor.evaluate(
            episode_id="ep_1",
            max_cumulative_loss=10.0,
        )
        assert state.status == "TERMINATE_EPISODE"

    def test_open_position_exceeded_blocked(self, tmp_path: Path) -> None:
        """Too many open positions → BLOCK_NEW_ORDER."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.update_position_count("ep_1", count=3)
        state = monitor.evaluate(
            episode_id="ep_1",
            max_open_positions=1,
        )
        assert state.status == "BLOCK_NEW_ORDER"

    def test_daily_order_count_exceeded_blocked(self, tmp_path: Path) -> None:
        """Daily order count over limit → BLOCK_NEW_ORDER."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.update_daily_order_count("ep_1")
        monitor.update_daily_order_count("ep_1")
        state = monitor.evaluate(
            episode_id="ep_1",
            max_orders_per_day=1,
        )
        assert state.status == "BLOCK_NEW_ORDER"

    def test_total_order_count_exceeded_blocked(self, tmp_path: Path) -> None:
        """Total order count over limit → BLOCK_NEW_ORDER."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        for _ in range(6):
            monitor.record_order("ep_1", notional=10.0)
        state = monitor.evaluate(
            episode_id="ep_1",
            max_total_orders=5,
        )
        assert state.status == "BLOCK_NEW_ORDER"

    def test_recon_fail_blocked(self, tmp_path: Path) -> None:
        """Recon failure → BLOCK_NEW_ORDER."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.record_recon_fail("ep_1")
        state = monitor.evaluate(episode_id="ep_1")
        assert state.status == "BLOCK_NEW_ORDER"

    def test_broker_error_blocked(self, tmp_path: Path) -> None:
        """Broker error → BLOCK_NEW_ORDER."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.record_broker_error("ep_1")
        state = monitor.evaluate(episode_id="ep_1")
        assert state.status == "BLOCK_NEW_ORDER"

    def test_incident_warns(self, tmp_path: Path) -> None:
        """Incidents only cause WARN, not block or terminate."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.record_incident("ep_1")
        state = monitor.evaluate(episode_id="ep_1")
        assert state.status == "WARN"

    def test_all_pass_returns_pass(self, tmp_path: Path) -> None:
        """All within limits → PASS."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.record_order("ep_1", notional=50.0)
        monitor.update_pnl("ep_1", realized_pnl=2.0)
        monitor.update_position_count("ep_1", count=1)
        state = monitor.evaluate(
            episode_id="ep_1",
            max_cumulative_notional=300.0,
            max_cumulative_loss=10.0,
            max_open_positions=1,
            max_total_orders=5,
        )
        assert state.status == "PASS"

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Risk monitor has no submit_order capability."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        assert not hasattr(monitor, "submit_order")
        assert not hasattr(monitor, "_broker")
        assert not hasattr(monitor, "broker")

    def test_state_persists_across_load(self, tmp_path: Path) -> None:
        """Risk state survives across separate monitor instances."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.record_order("ep_1", notional=100.0)
        monitor.record_order("ep_1", notional=50.0)

        # New instance loads same data
        monitor2 = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        state = monitor2.load("ep_1")
        assert state is not None
        assert state.cumulative_notional == 150.0
        assert state.total_order_count == 2

    def test_incident_count_adds_up(self, tmp_path: Path) -> None:
        """Multiple incidents increment the counter."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.record_incident("ep_1")
        monitor.record_incident("ep_1")
        monitor.record_incident("ep_1")
        state = monitor.load("ep_1")
        assert state is not None
        assert state.incident_count == 3

    def test_record_order_tracks_symbol_concentration(self, tmp_path: Path) -> None:
        """Orders for a symbol show up in concentration tracking."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.record_order("ep_1", notional=100.0, symbol="SPY")
        monitor.record_order("ep_1", notional=50.0, symbol="QQQ")
        state = monitor.load("ep_1")
        assert state is not None
        assert state.symbol_concentration.get("SPY") == 100.0
        assert state.symbol_concentration.get("QQQ") == 50.0

    def test_update_pnl_tracks_drawdown(self, tmp_path: Path) -> None:
        """Drawdown is tracked as negative PnL accumulates."""
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.update_pnl("ep_1", realized_pnl=-5.0)
        monitor.update_pnl("ep_1", unrealized_pnl=-3.0)
        state = monitor.load("ep_1")
        assert state is not None
        assert state.cumulative_realized_pnl == -5.0
        assert state.cumulative_unrealized_pnl == -3.0
