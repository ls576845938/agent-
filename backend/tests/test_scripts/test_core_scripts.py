"""Tests for core backtest scripts: run_backtest, run_walk_forward, run_parameter_sweep.

Each script is loaded via importlib so its main() can be tested without
polluting sys.path.  Heavy backtest / data dependencies are mocked.
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

# -- run_backtest.py --
_spec_bt = importlib.util.spec_from_file_location(
    "run_backtest_test", str(_SCRIPTS_DIR / "run_backtest.py")
)
_run_backtest = importlib.util.module_from_spec(_spec_bt)
_spec_bt.loader.exec_module(_run_backtest)

# -- run_walk_forward.py --
_spec_wf = importlib.util.spec_from_file_location(
    "run_walk_forward_test", str(_SCRIPTS_DIR / "run_walk_forward.py")
)
_run_walk_forward = importlib.util.module_from_spec(_spec_wf)
_spec_wf.loader.exec_module(_run_walk_forward)

# -- run_parameter_sweep.py --
_spec_ps = importlib.util.spec_from_file_location(
    "run_parameter_sweep_test", str(_SCRIPTS_DIR / "run_parameter_sweep.py")
)
_run_parameter_sweep = importlib.util.module_from_spec(_spec_ps)
_spec_ps.loader.exec_module(_run_parameter_sweep)


class TestRunBacktestScript(unittest.TestCase):
    """Tests for scripts/run_backtest.py"""

    def test_run_backtest_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_run_backtest)
        self.assertTrue(hasattr(_run_backtest, "main"))
        self.assertTrue(hasattr(_run_backtest, "parse_utc"))
        self.assertTrue(hasattr(_run_backtest, "synthetic_daily_bars"))

    def test_run_backtest_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _run_backtest.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_run_backtest_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_run_backtest.main))

    def test_run_backtest_minimal_args(self):
        """Minimal args runs via run_event_backtest_from_lake (mocked)."""
        mock_result = MagicMock()
        mock_result.summary = "mock summary"

        mock_config = MagicMock()

        with (
            patch.object(_run_backtest, "build_backtest_config", return_value=mock_config),
            patch.object(
                _run_backtest, "run_event_backtest_from_lake", return_value=mock_result
            ) as mock_runner,
        ):
            test_args = [
                "prog",
                "--symbol",
                "AAPL",
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-10",
                "--data-root",
                "/tmp/test_backtest",
            ]
            with patch("sys.argv", test_args):
                _run_backtest.main()

        mock_runner.assert_called_once()
        _call_args, call_kwargs = mock_runner.call_args
        self.assertEqual(call_kwargs["symbol"], "AAPL")
        self.assertEqual(call_kwargs["symbols"], ["AAPL"])
        self.assertEqual(call_kwargs["data_root"], "/tmp/test_backtest")

    def test_run_backtest_minimal_args_multi_symbol(self):
        """Comma-separated --symbols are parsed into a list."""
        mock_result = MagicMock()
        mock_result.summary = "mock summary"

        mock_config = MagicMock()

        with (
            patch.object(_run_backtest, "build_backtest_config", return_value=mock_config),
            patch.object(
                _run_backtest, "run_event_backtest_from_lake", return_value=mock_result
            ) as mock_runner,
        ):
            test_args = [
                "prog",
                "--symbols",
                "AAPL,MSFT,GOOGL",
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-10",
                "--data-root",
                "/tmp/test_backtest",
            ]
            with patch("sys.argv", test_args):
                _run_backtest.main()

        mock_runner.assert_called_once()
        _call_args, call_kwargs = mock_runner.call_args
        self.assertEqual(call_kwargs["symbols"], ["AAPL", "MSFT", "GOOGL"])

    def test_run_backtest_synthetic_path(self):
        """Without --start/--end, the synthetic path is taken (mocked)."""
        mock_config = MagicMock()
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.summary = "mock synthetic summary"
        mock_engine.run.return_value = mock_result

        with (
            patch.object(_run_backtest, "build_backtest_config", return_value=mock_config),
            patch.object(_run_backtest, "EventDrivenBacktestEngine", return_value=mock_engine),
            patch.object(_run_backtest, "build_strategy") as mock_build_strategy,
        ):
            mock_build_strategy.return_value = MagicMock()
            test_args = ["prog", "--synthetic", "--symbol", "AAPL"]
            with patch("sys.argv", test_args):
                _run_backtest.main()

        mock_engine.run.assert_called_once()
        args, _kwargs = mock_engine.run.call_args
        bars = args[0]
        self.assertGreater(len(bars), 0)
        self.assertEqual(bars[0].symbol, "AAPL")


class TestRunWalkForwardScript(unittest.TestCase):
    """Tests for scripts/run_walk_forward.py"""

    def test_run_walk_forward_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_run_walk_forward)
        self.assertTrue(hasattr(_run_walk_forward, "main"))
        self.assertTrue(hasattr(_run_walk_forward, "parse_utc"))

    def test_run_walk_forward_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _run_walk_forward.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_run_walk_forward_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_run_walk_forward.main))


class TestRunParameterSweepScript(unittest.TestCase):
    """Tests for scripts/run_parameter_sweep.py"""

    def test_run_parameter_sweep_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_run_parameter_sweep)
        self.assertTrue(hasattr(_run_parameter_sweep, "main"))
        self.assertTrue(hasattr(_run_parameter_sweep, "parse_utc"))
        self.assertTrue(hasattr(_run_parameter_sweep, "load_grid"))

    def test_run_parameter_sweep_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _run_parameter_sweep.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_run_parameter_sweep_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_run_parameter_sweep.main))


if __name__ == "__main__":
    unittest.main()
