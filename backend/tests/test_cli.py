"""Tests for quant_us/cli.py — unified CLI entry point.

Covers:
  - Each subcommand --help works
  - Ingest subcommand with mocked pipeline
  - Backtest subcommand with mocked runner
"""

from __future__ import annotations

import argparse
import io
import unittest
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
        self.assertIn("manifest", help_text)
        self.assertIn("report", help_text)

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

    @patch("quant_us.live.paper_runtime.PaperRuntime")
    @patch("quant_us.strategies.factory.build_strategy")
    def test_paper_run_passes_broker_to_runtime_config(
        self,
        mock_build_strategy: MagicMock,
        mock_runtime_cls: MagicMock,
    ) -> None:
        from quant_us.cli import _cmd_paper_run

        mock_build_strategy.return_value = MagicMock()
        runtime = mock_runtime_cls.return_value
        runtime.metrics_log = []
        runtime.broker.get_account.return_value = MagicMock(
            equity=100_000.0,
            cash=100_000.0,
            positions={},
        )
        runtime.kill_switch.triggered = False
        args = argparse.Namespace(
            strategy="trend_momentum",
            broker="alpaca",
            submit_orders=True,
            initial_cash=100_000.0,
            commission_rate=0.0001,
            slippage_bps=1.0,
            poll_interval=60.0,
            data_root="data",
            max_runtime_hours=1.0,
            data_vendor="yfinance",
            bar_size="1m",
        )

        with patch.dict(
            "os.environ",
            {"APCA_API_KEY_ID": "paper_key", "APCA_API_SECRET_KEY": "paper_secret"},
            clear=True,
        ):
            _cmd_paper_run(["SPY"], args)

        config = mock_runtime_cls.call_args.kwargs["config"]
        self.assertEqual(config.paper_broker, "alpaca")
        self.assertTrue(config.submit_orders)

    @patch("quant_us.live.paper_runtime.PaperRuntime")
    @patch("quant_us.strategies.factory.build_strategy")
    def test_paper_start_enable_orders_maps_to_submit_orders(
        self,
        mock_build_strategy: MagicMock,
        mock_runtime_cls: MagicMock,
    ) -> None:
        from quant_us.cli import _start_paper_production_loop

        mock_build_strategy.return_value = MagicMock()
        runtime = mock_runtime_cls.return_value
        runtime.metrics_log = []
        runtime.broker.get_account.return_value = MagicMock(
            equity=100_000.0,
            cash=100_000.0,
            positions={},
        )
        runtime.kill_switch.triggered = False
        args = argparse.Namespace(
            strategy="trend_momentum",
            enable_paper_orders=True,
            initial_cash=100_000.0,
            commission_rate=0.0001,
            slippage_bps=1.0,
            data_vendor="yfinance",
            bar_size="1d",
        )

        _start_paper_production_loop(["SPY"], args)

        config = mock_runtime_cls.call_args.kwargs["config"]
        self.assertTrue(config.submit_orders)
        self.assertEqual(config.paper_broker, "alpaca")


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

    def test_readiness_prints_paper_review_status(self) -> None:
        with TemporaryDirectory() as tmp:
            review_dir = Path(tmp) / "research" / "paper_reviews" / "prev_001"
            review_dir.mkdir(parents=True)
            (review_dir / "review.json").write_text(
                """{
                  "paper_review_id": "prev_001",
                  "strategy_manifest_id": "sman_001",
                  "status": "PENDING_HUMAN_REVIEW",
                  "created_at": "2026-05-08T12:00:00+00:00"
                }""",
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                main(["readiness", "--data-root", tmp])

            text = out.getvalue()
            self.assertIn("scope:       report only, no execution", text)
            self.assertIn("validation_state_state: MISSING", text)
            self.assertIn("latest_daily_report_state: MISSING", text)
            self.assertIn("paper_review_status: PENDING_HUMAN_REVIEW", text)
            self.assertIn("paper_review_entry_allowed: YES", text)
            self.assertIn("manual_review_pending: YES", text)
            self.assertIn("evidence:     paper_review=", text)


class CliManifestReportTests(unittest.TestCase):
    """Traceability commands for manifests and reports."""

    def test_manifest_inspect_backtest_run_id(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest_dir = Path(tmp) / "manifests"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "run_abc123.json").write_text(
                """{
                  "run_id": "abc123",
                  "data_version": "data_v1",
                  "strategy_version": "strat_v1",
                  "commit_hash": "deadbee",
                  "start_time": "2026-05-01T00:00:00+00:00",
                  "end_time": "2026-05-01T00:01:00+00:00",
                  "config": {"initial_cash": 100000, "commission_rate": 0.0001, "slippage_bps": 1.0}
                }""",
                encoding="utf-8",
            )
            main(["manifest", "inspect", "--manifest", "abc123", "--data-root", tmp])

    def test_report_backtest_prints_state_and_report_only_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest_dir = Path(tmp) / "manifests"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "run_abc123.json").write_text(
                """{
                  "run_id": "abc123",
                  "data_version": "data_v1",
                  "strategy_version": "strat_v1",
                  "commit_hash": "deadbee",
                  "start_time": "2026-05-01T00:00:00+00:00",
                  "end_time": "2026-05-01T00:01:00+00:00",
                  "config": {"initial_cash": 100000, "commission_rate": 0.0001, "slippage_bps": 1.0}
                }""",
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                main(["report", "backtest", "--run-id", "abc123", "--data-root", tmp])

            text = out.getvalue()
            self.assertIn("evidence_state: PASS manifest_path", text)
            self.assertIn("scope:       report only, no execution", text)

    def test_report_backtest_requires_identifier(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["report", "backtest"])
        self.assertEqual(ctx.exception.code, 2)

    def test_report_evidence_registry_missing_uses_required_state_word(self) -> None:
        with TemporaryDirectory() as tmp:
            out = io.StringIO()
            with redirect_stdout(out):
                main(["report", "evidence-registry", "--data-root", tmp])

            text = out.getvalue()
            self.assertIn("Evidence Registry Report", text)
            self.assertIn("registry_state: MISSING (missing)", text)
            self.assertIn("scope:       report only, no execution", text)

    def test_report_daily_latest_uses_ledger_report(self) -> None:
        with TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "paper_ledger" / "daily_reports"
            report_dir.mkdir(parents=True)
            (report_dir / "daily_report_2026-05-08.json").write_text(
                """{
                  "report_date": "2026-05-08",
                  "generated_at": "2026-05-08T21:00:00+00:00",
                  "ending_equity": 101000.0,
                  "daily_pnl": 1000.0,
                  "orders_submitted": 2,
                  "orders_filled": 2,
                  "reconciliation_status": "clean",
                  "kill_switch_triggered": false
                }""",
                encoding="utf-8",
            )
            review_dir = Path(tmp) / "research" / "paper_reviews" / "prev_001"
            review_dir.mkdir(parents=True)
            (review_dir / "review.json").write_text(
                """{
                  "paper_review_id": "prev_001",
                  "strategy_manifest_id": "sman_001",
                  "status": "APPROVED_FOR_PAPER_ONLY",
                  "created_at": "2026-05-08T22:00:00+00:00"
                }""",
                encoding="utf-8",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                main(["report", "daily", "--latest", "--data-root", tmp])

            text = out.getvalue()
            self.assertIn("paper_review_status: APPROVED_FOR_PAPER_ONLY", text)
            self.assertIn("manual_review_pending: NO", text)
            self.assertIn("report_state: PASS daily_report", text)
            self.assertIn("readiness_state: MISSING validation_state", text)
            self.assertIn("evidence_registry_state: MISSING (missing)", text)
            self.assertIn("scope:       report only, no execution", text)
            self.assertIn("Reporting only. This does not approve or start paper/live trading.", text)
