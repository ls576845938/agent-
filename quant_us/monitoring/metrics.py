"""Prometheus-style monitoring metrics collector.

Provides MetricsCollector with typed gauges and counters for operational
visibility. Outputs Prometheus text format for /metrics endpoints.

Usage:
    collector = MetricsCollector()
    collector.equity = 105000.0
    collector.broker_connected = 1
    collector.daily_orders_total += 1  # counter

    print(collector.to_prometheus_text())
    print(collector.snapshot())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsCollector:
    """Aggregate runtime metrics for monitoring and alerting.

    Gauges represent point-in-time values; counters are monotonically
    increasing (use += to bump).  Use snapshot() for a dict view or
    to_prometheus_text() for /metrics endpoint output.
    """

    # --- Gauges -----------------------------------------------------------

    equity: float = 0.0
    """Current portfolio equity in USD (gauge)."""

    cash: float = 0.0
    """Current cash balance in USD (gauge)."""

    positions_count: int = 0
    """Number of currently open positions (gauge)."""

    pending_orders: int = 0
    """Number of orders that have been submitted but not yet filled (gauge)."""

    daily_pnl: float = 0.0
    """Today's realised + unrealised PnL in USD (gauge, resets daily)."""

    max_drawdown_pct: float = 0.0
    """Maximum drawdown as a fraction of peak equity (gauge)."""

    broker_connected: int = 0
    """Broker connection liveness (1=connected, 0=disconnected)."""

    data_latency_seconds: float = 0.0
    """Age of the most recent data bar in seconds (gauge)."""

    reconciliation_status: int = 0
    """Ledger-vs-broker reconciliation status (0=clean, 1=breaks)."""

    kill_switch_triggered: int = 0
    """Global kill-switch state (0=normal, 1=triggered)."""

    # --- Counters ---------------------------------------------------------

    daily_orders_total: float = 0.0
    """Cumulative orders submitted today (counter, resets daily)."""

    daily_fills_total: float = 0.0
    """Cumulative fills received today (counter, resets daily)."""

    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return all current metric values as a flat dictionary."""
        return {
            "equity": self.equity,
            "cash": self.cash,
            "positions_count": self.positions_count,
            "pending_orders": self.pending_orders,
            "daily_orders_total": self.daily_orders_total,
            "daily_fills_total": self.daily_fills_total,
            "daily_pnl": self.daily_pnl,
            "max_drawdown_pct": self.max_drawdown_pct,
            "broker_connected": self.broker_connected,
            "data_latency_seconds": self.data_latency_seconds,
            "reconciliation_status": self.reconciliation_status,
            "kill_switch_triggered": self.kill_switch_triggered,
        }

    def to_prometheus_text(self) -> str:
        """Render all metrics in Prometheus text exposition format (v0.0.4).

        Every metric is prefixed with ``quantstation_``.  Gauges and
        counters are emitted with a TYPE and HELP comment.
        """
        lines: list[str] = []

        # Helper to append a metric block
        def _emit(name: str, typ: str, help_text: str, value: float | int) -> None:
            lines.append(f"# HELP quantstation_{name} {help_text}")
            lines.append(f"# TYPE quantstation_{name} {typ}")
            lines.append(f"quantstation_{name} {value}")
            lines.append("")

        _emit("up", "gauge", "Service liveness (always 1 if endpoint responds)", 1)
        _emit("equity", "gauge", "Current portfolio equity in USD", self.equity)
        _emit("cash", "gauge", "Current cash balance in USD", self.cash)
        _emit("positions_count", "gauge", "Number of open positions", self.positions_count)
        _emit("pending_orders", "gauge", "Number of pending orders", self.pending_orders)
        _emit("daily_orders_total", "counter", "Total orders submitted today", self.daily_orders_total)
        _emit("daily_fills_total", "counter", "Total fills received today", self.daily_fills_total)
        _emit("daily_pnl", "gauge", "Today's PnL in USD", self.daily_pnl)
        _emit("max_drawdown_pct", "gauge", "Maximum drawdown as a fraction", self.max_drawdown_pct)
        _emit("broker_connected", "gauge", "Broker connection status (1=connected)", self.broker_connected)
        _emit("data_latency_seconds", "gauge", "Data latency in seconds", self.data_latency_seconds)
        _emit("reconciliation_status", "gauge", "Reconciliation status (0=clean, 1=breaks)", self.reconciliation_status)
        _emit("kill_switch_triggered", "gauge", "Kill switch state (1=triggered)", self.kill_switch_triggered)

        return "\n".join(lines)


# Convenience alias used by the rest of the system
MetricsRegistry = MetricsCollector
