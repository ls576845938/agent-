"""Tests for quant_us/monitoring/metrics.py — MetricsCollector.

Covers:
  - All gauges and counters have correct initial values
  - Setting values works for gauges and counters
  - snapshot() returns correct dict format
  - to_prometheus_text() produces valid Prometheus exposition format
  - /metrics endpoint returns 200
"""

from __future__ import annotations

import unittest
from typing import Any

from quant_us.monitoring.metrics import MetricsCollector


class MetricsCollectorInitTests(unittest.TestCase):
    """All fields should start at their zero / default values."""

    def test_all_gauges_start_at_zero(self) -> None:
        c = MetricsCollector()
        self.assertEqual(c.equity, 0.0)
        self.assertEqual(c.cash, 0.0)
        self.assertEqual(c.positions_count, 0)
        self.assertEqual(c.pending_orders, 0)
        self.assertEqual(c.daily_pnl, 0.0)
        self.assertEqual(c.max_drawdown_pct, 0.0)
        self.assertEqual(c.broker_connected, 0)
        self.assertEqual(c.data_latency_seconds, 0.0)
        self.assertEqual(c.reconciliation_status, 0)
        self.assertEqual(c.kill_switch_triggered, 0)

    def test_all_counters_start_at_zero(self) -> None:
        c = MetricsCollector()
        self.assertEqual(c.daily_orders_total, 0.0)
        self.assertEqual(c.daily_fills_total, 0.0)


class MetricsCollectorGaugeTests(unittest.TestCase):
    """Setting gauge values should be reflected in snapshot."""

    def test_equity_gauge(self) -> None:
        c = MetricsCollector()
        c.equity = 105000.50
        snap = c.snapshot()
        self.assertEqual(snap["equity"], 105000.50)

    def test_cash_gauge(self) -> None:
        c = MetricsCollector()
        c.cash = 50000.0
        self.assertEqual(c.snapshot()["cash"], 50000.0)

    def test_positions_count_gauge(self) -> None:
        c = MetricsCollector()
        c.positions_count = 5
        self.assertEqual(c.snapshot()["positions_count"], 5)

    def test_pending_orders_gauge(self) -> None:
        c = MetricsCollector()
        c.pending_orders = 3
        self.assertEqual(c.snapshot()["pending_orders"], 3)

    def test_daily_pnl_gauge(self) -> None:
        c = MetricsCollector()
        c.daily_pnl = 1234.56
        self.assertEqual(c.snapshot()["daily_pnl"], 1234.56)

    def test_max_drawdown_pct_gauge(self) -> None:
        c = MetricsCollector()
        c.max_drawdown_pct = 0.05
        self.assertEqual(c.snapshot()["max_drawdown_pct"], 0.05)

    def test_broker_connected_gauge(self) -> None:
        c = MetricsCollector()
        c.broker_connected = 1
        self.assertEqual(c.snapshot()["broker_connected"], 1)

    def test_data_latency_seconds_gauge(self) -> None:
        c = MetricsCollector()
        c.data_latency_seconds = 12.5
        self.assertEqual(c.snapshot()["data_latency_seconds"], 12.5)

    def test_reconciliation_status_gauge(self) -> None:
        c = MetricsCollector()
        c.reconciliation_status = 1
        self.assertEqual(c.snapshot()["reconciliation_status"], 1)

    def test_kill_switch_triggered_gauge(self) -> None:
        c = MetricsCollector()
        c.kill_switch_triggered = 1
        self.assertEqual(c.snapshot()["kill_switch_triggered"], 1)


class MetricsCollectorCounterTests(unittest.TestCase):
    """Counters should be incremented with += ."""

    def test_daily_orders_counter(self) -> None:
        c = MetricsCollector()
        c.daily_orders_total += 1
        c.daily_orders_total += 3
        self.assertEqual(c.daily_orders_total, 4.0)

    def test_daily_fills_counter(self) -> None:
        c = MetricsCollector()
        c.daily_fills_total += 2
        c.daily_fills_total += 5
        self.assertEqual(c.daily_fills_total, 7.0)


class MetricsCollectorSnapshotTests(unittest.TestCase):
    """snapshot() must return a flat dict with all 12 metrics."""

    def test_snapshot_returns_all_keys(self) -> None:
        c = MetricsCollector()
        snap = c.snapshot()
        expected_keys = {
            "equity", "cash", "positions_count", "pending_orders",
            "daily_orders_total", "daily_fills_total",
            "daily_pnl", "max_drawdown_pct",
            "broker_connected", "data_latency_seconds",
            "reconciliation_status", "kill_switch_triggered",
        }
        self.assertEqual(set(snap.keys()), expected_keys)

    def test_snapshot_returns_correct_types(self) -> None:
        c = MetricsCollector()
        c.equity = 100000.0
        c.positions_count = 10
        c.broker_connected = 1
        c.daily_orders_total = 5.0
        snap = c.snapshot()
        self.assertIsInstance(snap["equity"], float)
        self.assertIsInstance(snap["positions_count"], int)
        self.assertIsInstance(snap["broker_connected"], int)
        self.assertIsInstance(snap["daily_orders_total"], float)


class MetricsCollectorPrometheusTextTests(unittest.TestCase):
    """to_prometheus_text() must produce valid Prometheus format."""

    def test_includes_up_metric(self) -> None:
        text = MetricsCollector().to_prometheus_text()
        self.assertIn("quantstation_up 1", text)

    def test_includes_all_metrics(self) -> None:
        text = MetricsCollector().to_prometheus_text()
        for name in [
            "equity", "cash", "positions_count", "pending_orders",
            "daily_orders_total", "daily_fills_total",
            "daily_pnl", "max_drawdown_pct",
            "broker_connected", "data_latency_seconds",
            "reconciliation_status", "kill_switch_triggered",
        ]:
            self.assertIn(f"quantstation_{name}", text)

    def test_has_help_and_type_lines(self) -> None:
        text = MetricsCollector().to_prometheus_text()
        self.assertIn("# HELP", text)
        self.assertIn("# TYPE", text)

    def test_reflects_current_values(self) -> None:
        c = MetricsCollector()
        c.equity = 99999.99
        c.positions_count = 7
        c.daily_orders_total = 42.0
        text = c.to_prometheus_text()
        self.assertIn("quantstation_equity 99999.99", text)
        self.assertIn("quantstation_positions_count 7", text)
        self.assertIn("quantstation_daily_orders_total 42.0", text)


class MetricsEndpointTests(unittest.TestCase):
    """The /metrics endpoint must return HTTP 200 with Prometheus text."""

    def test_metrics_endpoint_returns_200(self) -> None:
        """Send GET /metrics to the test client and assert 200."""
        import importlib.util

        if not importlib.util.find_spec("httpx"):
            self.skipTest("fastapi TestClient dependency httpx not available")
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError):
            self.skipTest("fastapi.testclient not available")

        from backend.app.api.app_factory import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers.get("content-type", ""))
        self.assertIn("quantstation_up", response.text)
