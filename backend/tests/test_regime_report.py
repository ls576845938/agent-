"""Tests for RegimeReportBuilder.

Covers: timeline, strategy report, filter recommendation.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.regime.backtest import RegimeBacktestResult
from quant_us.regime.report import RegimeReportBuilder


class TestRegimeReportBuilder(unittest.TestCase):
    """Regime report generation tests."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.builder = RegimeReportBuilder(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_timeline(self) -> None:
        timeline = self.builder.build_timeline(symbol="SPY")
        self.assertIsInstance(timeline, str)

    def test_build_timeline_no_data(self) -> None:
        timeline = self.builder.build_timeline(symbol="NONEXISTENT")
        self.assertIsInstance(timeline, str)
        self.assertIn("No regime data", timeline)

    def test_build_strategy_report(self) -> None:
        result = RegimeBacktestResult(
            symbol="SPY",
            strategy_id="momentum_v1",
            regime_performance={
                "BULL_TREND": {"cagr_pct": 15.0, "sharpe_ratio": 1.5, "max_drawdown_pct": 5.0, "trade_count": 50},
                "BEAR_TREND": {"cagr_pct": -5.0, "sharpe_ratio": -0.5, "max_drawdown_pct": 15.0, "trade_count": 20},
            },
            best_regime="BULL_TREND",
            worst_regime="BEAR_TREND",
        )
        report = self.builder.build_strategy_report("momentum_v1", result)
        self.assertIn("momentum_v1", report)
        self.assertIn("BULL_TREND", report)
        self.assertIn("BEAR_TREND", report)

    def test_build_strategy_report_empty_perf(self) -> None:
        result = RegimeBacktestResult(symbol="SPY", strategy_id="test")
        report = self.builder.build_strategy_report("test", result)
        self.assertIn("test", report)

    def test_recommend_filter(self) -> None:
        result = RegimeBacktestResult(
            symbol="SPY",
            strategy_id="mom",
            regime_performance={
                "BULL_TREND": {"cagr_pct": 15.0, "sharpe_ratio": 1.5, "max_drawdown_pct": 5.0, "trade_count": 50},
                "BEAR_TREND": {"cagr_pct": -5.0, "sharpe_ratio": -0.5, "max_drawdown_pct": 15.0, "trade_count": 20},
            },
        )
        rec = self.builder.recommend_filter(result)
        self.assertIsInstance(rec, list)
        self.assertIn("BEAR_TREND", rec)

    def test_recommend_filter_empty(self) -> None:
        result = RegimeBacktestResult(symbol="SPY", strategy_id="test")
        rec = self.builder.recommend_filter(result)
        self.assertEqual(rec, [])

    def test_no_live_import(self) -> None:
        import quant_us.regime.report as report
        with open(report.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("from quant_us.live import", content)
        self.assertNotIn("import quant_us.live", content)
        self.assertNotIn("from quant_us.execution import", content)
        self.assertNotIn("import quant_us.execution", content)
