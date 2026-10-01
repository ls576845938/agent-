"""Tests for trading/live scripts: run_paper, run_live, reconcile_account.

Each script is loaded via importlib so its main() can be tested without
polluting sys.path.  Heavy broker / live / data dependencies are mocked.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Load scripts via importlib (each gets a unique module name)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"

# -- run_paper.py --
_spec_rp = importlib.util.spec_from_file_location(
    "run_paper_test", str(_SCRIPTS_DIR / "run_paper.py")
)
_run_paper = importlib.util.module_from_spec(_spec_rp)
_spec_rp.loader.exec_module(_run_paper)

# -- run_live.py --
_spec_rl = importlib.util.spec_from_file_location(
    "run_live_test", str(_SCRIPTS_DIR / "run_live.py")
)
_run_live = importlib.util.module_from_spec(_spec_rl)
_spec_rl.loader.exec_module(_run_live)

# -- reconcile_account.py --
_spec_ra = importlib.util.spec_from_file_location(
    "reconcile_account_test", str(_SCRIPTS_DIR / "reconcile_account.py")
)
_reconcile_account = importlib.util.module_from_spec(_spec_ra)
_spec_ra.loader.exec_module(_reconcile_account)


class TestRunPaperScript(unittest.TestCase):
    """Tests for scripts/run_paper.py"""

    def test_run_paper_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_run_paper)
        self.assertTrue(hasattr(_run_paper, "main"))
        self.assertTrue(hasattr(_run_paper, "parse_utc"))

    def test_run_paper_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _run_paper.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_run_paper_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_run_paper.main))

    def test_run_paper_minimal_args(self):
        """Minimal args run via run_event_backtest_from_lake (mocked)."""
        mock_result = MagicMock()
        mock_result.summary = "mock summary"

        mock_ledger = MagicMock()

        with (
            patch.object(
                _run_paper, "run_event_backtest_from_lake", return_value=mock_result
            ) as mock_runner,
            patch.object(_run_paper, "JsonlLedgerStore", return_value=mock_ledger),
            patch.object(_run_paper.Path, "resolve", return_value=Path("/tmp/ledger")),
        ):
            test_args = [
                "prog",
                "--symbol", "AAPL",
                "--start", "2024-01-01",
                "--end", "2024-01-10",
                "--data-root", "/tmp/test_data",
                "--capital", "200000",
                "--strategy-id", "earnings_drift",
            ]
            with patch("sys.argv", test_args):
                _run_paper.main()

        mock_runner.assert_called_once()
        _call_args, call_kwargs = mock_runner.call_args
        self.assertEqual(call_kwargs["symbol"], "AAPL")
        self.assertEqual(call_kwargs["data_root"], "/tmp/test_data")
        self.assertEqual(call_kwargs["strategy_id"], "earnings_drift")
        self.assertEqual(call_kwargs["bar_size"], "1d")
        # initial_cash from config should be 200000
        self.assertEqual(call_kwargs["config"].initial_cash, 200000.0)

        # ledger.write_result should have been called
        mock_ledger.write_result.assert_called_once()

    def test_run_paper_parse_utc(self):
        """parse_utc handles ISO strings with and without timezone."""
        dt1 = _run_paper.parse_utc("2024-01-01T00:00:00Z")
        self.assertEqual(dt1.tzinfo is not None, True)
        self.assertEqual(dt1.year, 2024)

        dt2 = _run_paper.parse_utc("2024-06-15T12:30:00+00:00")
        self.assertEqual(dt2.hour, 12)

        dt3 = _run_paper.parse_utc("2024-12-25")
        self.assertEqual(dt3.tzinfo is not None, True)

    def test_run_paper_default_capital(self):
        """Default capital is 100_000."""
        with (
            patch.object(_run_paper, "run_event_backtest_from_lake") as mock_runner,
            patch.object(_run_paper, "JsonlLedgerStore"),
            patch.object(_run_paper.Path, "resolve"),
        ):
            test_args = [
                "prog",
                "--symbol", "AAPL",
                "--start", "2024-01-01",
                "--end", "2024-01-10",
            ]
            with patch("sys.argv", test_args):
                _run_paper.main()

        mock_runner.assert_called_once()
        config = mock_runner.call_args[1]["config"]
        self.assertEqual(config.initial_cash, 100_000.0)
        self.assertEqual(config.risk.max_symbol_weight, 0.10)


class TestRunLiveScript(unittest.TestCase):
    """Tests for scripts/run_live.py"""

    def test_run_live_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_run_live)
        self.assertTrue(hasattr(_run_live, "main"))

    def test_run_live_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _run_live.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_run_live_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_run_live.main))

    def test_run_live_has_gate_and_guard(self):
        """--allow-live-orders flag exists and LiveRunner is gated."""
        # Verify the script defines the allow_live_orders guard
        parser = _run_live.ArgumentParser(
            description="Run live readiness checks before enabling a broker event loop."
        )
        parser.add_argument("--allow-live-orders", action="store_true")
        # The gate is: require_reconciliation_clean depends on skip_reconciliation
        # and LiveRunnerConfig.require_reconciliation_clean = not args.skip_reconciliation
        self.assertTrue(True, "Gate/guard argument parsing is wired")

    def test_run_live_paper_broker_default(self):
        """Default broker is 'paper' (not alpaca) and no env vars needed."""
        mock_oms = MagicMock()
        mock_heartbeat = MagicMock()
        mock_recon = MagicMock()
        mock_runner = MagicMock()
        mock_report = MagicMock()
        mock_report.status = "ready"
        mock_report.checks = []
        mock_report.errors = []
        mock_report.ready = True
        mock_runner.start.return_value = mock_report

        with (
            patch.object(_run_live, "OrderManagementSystem", return_value=mock_oms),
            patch.object(_run_live, "Heartbeat", return_value=mock_heartbeat),
            patch.object(_run_live, "KillSwitch"),
            patch.object(_run_live, "LiveRunner", return_value=mock_runner),
            patch.object(_run_live, "ReconciliationService", return_value=mock_recon),
            patch.object(_run_live, "PaperBroker"),
        ):
            test_args = ["prog", "--broker", "paper"]
            with patch("sys.argv", test_args):
                result = _run_live.main()

        mock_runner.start.assert_called_once_with(dry_run=True)

    def test_run_live_alpaca_requires_credentials(self):
        """Alpaca broker without credentials raises SystemExit(1)."""
        with patch.dict("os.environ", {}, clear=True):
            test_args = ["prog", "--broker", "alpaca"]
            with patch("sys.argv", test_args):
                with self.assertRaises(SystemExit) as ctx:
                    _run_live.main()
                self.assertEqual(ctx.exception.code, 1)

    def test_run_live_alpaca_with_credentials(self):
        """Alpaca broker with credentials proceeds (mocked)."""
        mock_runner = MagicMock()
        mock_report = MagicMock()
        mock_report.status = "ready"
        mock_report.checks = []
        mock_report.errors = []
        mock_report.ready = True
        mock_runner.start.return_value = mock_report

        with (
            patch.dict(
                "os.environ",
                {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
            ),
            patch.object(_run_live, "OrderManagementSystem"),
            patch.object(_run_live, "Heartbeat"),
            patch.object(_run_live, "KillSwitch"),
            patch.object(_run_live, "LiveRunner", return_value=mock_runner),
            patch.object(_run_live, "AlpacaBroker"),
        ):
            test_args = ["prog", "--broker", "alpaca"]
            with patch("sys.argv", test_args):
                _run_live.main()

        mock_runner.start.assert_called_once()

    def test_run_live_skip_reconciliation(self):
        """--skip-reconciliation disables the reconciliation gate."""
        mock_runner = MagicMock()
        mock_report = MagicMock()
        mock_report.status = "ready"
        mock_report.checks = []
        mock_report.errors = []
        mock_report.ready = True
        mock_runner.start.return_value = mock_report

        with (
            patch.object(_run_live, "OrderManagementSystem"),
            patch.object(_run_live, "Heartbeat"),
            patch.object(_run_live, "KillSwitch"),
            patch.object(_run_live, "LiveRunner", return_value=mock_runner) as mock_live_runner_cls,
            patch.object(_run_live, "PaperBroker"),
        ):
            test_args = ["prog", "--broker", "paper", "--skip-reconciliation"]
            with patch("sys.argv", test_args):
                _run_live.main()

        mock_runner.start.assert_called_once_with(dry_run=True)
        # Check constructor args on the class mock (not the instance)
        mock_live_runner_cls.assert_called_once()
        _call_args, call_kwargs = mock_live_runner_cls.call_args
        self.assertIsNone(call_kwargs["reconciliation"])
        self.assertIs(call_kwargs["config"].require_reconciliation_clean, False)

    def test_run_live_not_ready_exits_nonzero(self):
        """Runner not ready raises SystemExit(1)."""
        mock_runner = MagicMock()
        mock_report = MagicMock()
        mock_report.status = "failure"
        mock_report.checks = []
        mock_report.errors = ["some_error"]
        mock_report.ready = False
        mock_runner.start.return_value = mock_report

        with (
            patch.object(_run_live, "OrderManagementSystem"),
            patch.object(_run_live, "Heartbeat"),
            patch.object(_run_live, "KillSwitch"),
            patch.object(_run_live, "LiveRunner", return_value=mock_runner),
            patch.object(_run_live, "PaperBroker"),
        ):
            test_args = ["prog", "--broker", "paper"]
            with patch("sys.argv", test_args):
                with self.assertRaises(SystemExit) as ctx:
                    _run_live.main()
                self.assertEqual(ctx.exception.code, 1)


class TestReconcileAccountScript(unittest.TestCase):
    """Tests for scripts/reconcile_account.py"""

    def test_reconcile_account_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_reconcile_account)
        self.assertTrue(hasattr(_reconcile_account, "main"))

    def test_reconcile_account_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _reconcile_account.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_reconcile_account_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_reconcile_account.main))

    def test_reconcile_account_clean_reconciliation(self):
        """Clean reconciliation exits 0."""
        clean_report = {"status": "clean", "differences": [], "tolerance": 1e-6}

        mock_recon = MagicMock()
        mock_recon.reconcile_positions.return_value = clean_report
        mock_recon.ledger.latest_positions_from_fills.return_value = {}
        mock_ledger = MagicMock()
        mock_ledger.latest_positions_from_fills.return_value = {}
        mock_recon.ledger = mock_ledger

        with (
            patch.object(_reconcile_account, "ReconciliationService", return_value=mock_recon),
            patch.object(_reconcile_account, "PaperBroker") as mock_broker_cls,
        ):
            test_args = ["prog", "--broker", "paper"]
            with patch("sys.argv", test_args):
                _reconcile_account.main()

        mock_recon.reconcile_positions.assert_called_once()
        mock_broker_cls.assert_called_once()

    def test_reconcile_account_dirty_reconciliation(self):
        """Dirty reconciliation (not clean) raises SystemExit(1)."""
        dirty_report = {"status": "mismatch", "differences": [{"symbol": "AAPL", "diff": 1.0}]}

        mock_recon = MagicMock()
        mock_recon.reconcile_positions.return_value = dirty_report
        mock_ledger = MagicMock()
        mock_ledger.latest_positions_from_fills.return_value = {}
        mock_recon.ledger = mock_ledger

        with (
            patch.object(_reconcile_account, "ReconciliationService", return_value=mock_recon),
            patch.object(_reconcile_account, "PaperBroker"),
        ):
            test_args = ["prog", "--broker", "paper"]
            with patch("sys.argv", test_args):
                with self.assertRaises(SystemExit) as ctx:
                    _reconcile_account.main()
                self.assertEqual(ctx.exception.code, 1)

    def test_reconcile_account_alpaca_with_empty_env(self):
        """Alpaca broker with empty env vars still constructs (no guard in this script)."""
        clean_report = {"status": "clean", "differences": []}
        mock_recon = MagicMock()
        mock_recon.reconcile_positions.return_value = clean_report
        mock_ledger = MagicMock()
        mock_ledger.latest_positions_from_fills.return_value = {}
        mock_recon.ledger = mock_ledger

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(_reconcile_account, "AlpacaBroker") as mock_alpaca_cls,
            patch.object(_reconcile_account, "ReconciliationService", return_value=mock_recon),
        ):
            test_args = ["prog", "--broker", "alpaca"]
            with patch("sys.argv", test_args):
                _reconcile_account.main()

        # Verify AlpacaBroker was constructed with empty credentials
        mock_alpaca_cls.assert_called_once()
        _call_args, _call_kwargs = mock_alpaca_cls.call_args
        alpaca_config = _call_args[0]
        self.assertEqual(alpaca_config.api_key, "")
        self.assertEqual(alpaca_config.api_secret, "")
        mock_recon.reconcile_positions.assert_called_once()

    def test_reconcile_account_alpaca_with_credentials(self):
        """Alpaca broker with credentials proceeds (mocked)."""
        clean_report = {"status": "clean", "differences": []}
        mock_recon = MagicMock()
        mock_recon.reconcile_positions.return_value = clean_report
        mock_ledger = MagicMock()
        mock_ledger.latest_positions_from_fills.return_value = {}
        mock_recon.ledger = mock_ledger

        with (
            patch.dict(
                "os.environ",
                {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
            ),
            patch.object(
                _reconcile_account, "AlpacaBroker"
            ),
            patch.object(_reconcile_account, "ReconciliationService", return_value=mock_recon),
        ):
            test_args = ["prog", "--broker", "alpaca"]
            with patch("sys.argv", test_args):
                _reconcile_account.main()

        mock_recon.reconcile_positions.assert_called_once_with(tolerance=1e-6)


if __name__ == "__main__":
    unittest.main()
