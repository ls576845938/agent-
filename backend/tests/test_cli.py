"""Tests for quant_us/cli.py — unified CLI entry point.

Covers:
  - Each subcommand --help works
  - Ingest subcommand with mocked pipeline
  - Backtest subcommand with mocked runner
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from quant_us.cli import build_parser, main


class CliHelpTests(unittest.TestCase):
    """Each subcommand must display --help without error."""

    def test_root_help(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("ingest", help_text)
        self.assertIn("backtest", help_text)
        self.assertIn("paper", help_text)
        self.assertIn("reconcile", help_text)
        self.assertIn("readiness", help_text)

    def test_ingest_help(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        ingest_parser = sub.choices["ingest"]
        help_text = ingest_parser.format_help()
        self.assertIn("--source", help_text)
        self.assertIn("--bar-size", help_text)
        self.assertIn("--start", help_text)
        self.assertIn("--end", help_text)

    def test_backtest_help(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        bt_parser = sub.choices["backtest"]
        help_text = bt_parser.format_help()
        self.assertIn("--strategy", help_text)
        self.assertIn("--start", help_text)
        self.assertIn("--end", help_text)
        self.assertIn("--initial-cash", help_text)

    def test_paper_help(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        pp_parser = sub.choices["paper"]
        help_text = pp_parser.format_help()
        self.assertIn("--strategy", help_text)
        self.assertIn("--broker", help_text)

    def test_reconcile_help(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        rc_parser = sub.choices["reconcile"]
        help_text = rc_parser.format_help()
        self.assertIn("--broker", help_text)


class CliIngestTests(unittest.TestCase):
    """Ingest subcommand with mocked pipeline."""

    @patch("quant_us.data.connectors.us_equity_ingestion.USEquityIngestionPipeline")
    def test_ingest_calls_pipeline(self, mock_pipeline_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_pipeline_cls.return_value = mock_instance
        mock_instance.run.return_value = []

        main(["ingest", "--symbols", "SPY,QQQ", "--source", "yfinance", "--start", "2024-01-01", "--end", "2024-01-05"])

        mock_pipeline_cls.assert_called_once()
        call_config = mock_pipeline_cls.call_args[0][0]
        self.assertEqual(call_config.source, "yfinance")
        self.assertEqual(call_config.symbols, ["SPY", "QQQ"])
        self.assertEqual(call_config.start, "2024-01-01")
        self.assertEqual(call_config.end, "2024-01-05")
        mock_instance.run.assert_called_once()

    @patch("quant_us.data.connectors.us_equity_ingestion.USEquityIngestionPipeline")
    def test_ingest_with_default_symbols(self, mock_pipeline_cls: MagicMock) -> None:
        """When no --symbols given, should use V1_SYMBOLS."""
        mock_instance = MagicMock()
        mock_pipeline_cls.return_value = mock_instance
        mock_instance.run.return_value = []

        from config.v1_universe import V1_SYMBOLS

        main(["ingest", "--start", "2024-01-01", "--end", "2024-01-05"])

        call_config = mock_pipeline_cls.call_args[0][0]
        self.assertEqual(len(call_config.symbols), len(V1_SYMBOLS))
        self.assertIn("SPY", call_config.symbols)


class CliBacktestTests(unittest.TestCase):
    """Backtest subcommand with mocked runner."""

    @patch("quant_us.backtest.unified_runner.UnifiedBacktestRunner")
    @patch("quant_us.cli._load_backtest_data")
    @patch("quant_us.strategies.factory.build_strategy")
    def test_backtest_calls_runner(
        self,
        mock_build_strategy: MagicMock,
        mock_load_data: MagicMock,
        mock_runner_cls: MagicMock,
    ) -> None:
        import pandas as pd

        mock_strategy = MagicMock()
        mock_strategy.version = "0.1.0"
        mock_build_strategy.return_value = mock_strategy

        mock_frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC"),
            "symbol": ["SPY"] * 10,
            "open": [450.0] * 10,
            "high": [452.0] * 10,
            "low": [449.0] * 10,
            "close": [451.0] * 10,
            "volume": [1_000_000] * 10,
        })
        mock_load_data.return_value = mock_frame

        mock_instance = MagicMock()
        mock_runner_cls.return_value = mock_instance
        mock_result = MagicMock()
        mock_result.run_id = "test-run"
        mock_result.summary = {
            "total_return_pct": 1.5,
            "sharpe_ratio": 0.8,
            "max_drawdown_pct": -2.0,
            "trade_count": 10,
        }
        mock_result.equity_consistent = True
        mock_result.is_trustworthy = True
        mock_instance.run.return_value = mock_result

        main([
            "backtest",
            "--strategy", "etf_rotation",
            "--symbols", "SPY,QQQ",
            "--start", "2024-01-01",
            "--end", "2024-01-10",
            "--initial-cash", "50000",
        ])

        mock_build_strategy.assert_called_once_with("etf_rotation", {})
        mock_load_data.assert_called_once()
        mock_instance.run.assert_called_once()

    def test_backtest_requires_strategy(self) -> None:
        """--strategy is required for backtest subcommand."""
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["backtest", "--start", "2024-01-01"])

    def test_backtest_help_includes_strategy(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        bt_parser = sub.choices["backtest"]
        help_text = bt_parser.format_help()
        self.assertIn("--strategy", help_text)


class CliPaperTests(unittest.TestCase):
    """Paper subcommand."""

    def test_paper_help_includes_broker(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        pp_parser = sub.choices["paper"]
        help_text = pp_parser.format_help()
        self.assertIn("--broker", help_text)
        self.assertIn("--strategy", help_text)

    def test_paper_strategy_defaults(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        pp_parser = sub.choices["paper"]
        args = pp_parser.parse_args(["--broker", "simulated"])
        self.assertEqual(args.strategy, "etf_rotation")


class CliReconcileTests(unittest.TestCase):
    """Reconcile subcommand."""

    def test_reconcile_help(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        rc_parser = sub.choices["reconcile"]
        help_text = rc_parser.format_help()
        self.assertIn("--broker", help_text)


class CliReadinessTests(unittest.TestCase):
    """Readiness subcommand."""

    def test_readiness_help_has_validation_state(self) -> None:
        parser = build_parser()
        sub = parser._subparsers._group_actions[0]
        rd_parser = sub.choices["readiness"]
        help_text = rd_parser.format_help()
        self.assertIn("--validation-state", help_text)

    def test_readiness_runs_without_error(self) -> None:
        """'quant-us readiness' should execute without exception."""
        from quant_us.cli import main

        main(["readiness"])
