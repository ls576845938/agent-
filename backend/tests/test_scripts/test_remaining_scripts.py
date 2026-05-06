"""Tests for remaining scripts: build_universe, compare_experiments, ingest_daily,
ingest_intraday, run_research_experiment.

Each script is loaded via importlib so its main() can be tested without
polluting sys.path.  Heavy dependencies are mocked.
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

# -- build_universe.py --
_spec_bu = importlib.util.spec_from_file_location(
    "build_universe_test", str(_SCRIPTS_DIR / "build_universe.py")
)
_build_universe = importlib.util.module_from_spec(_spec_bu)
_spec_bu.loader.exec_module(_build_universe)

# -- compare_experiments.py --
_spec_ce = importlib.util.spec_from_file_location(
    "compare_experiments_test", str(_SCRIPTS_DIR / "compare_experiments.py")
)
_compare_experiments = importlib.util.module_from_spec(_spec_ce)
_spec_ce.loader.exec_module(_compare_experiments)

# -- ingest_daily.py --
_spec_id = importlib.util.spec_from_file_location(
    "ingest_daily_test", str(_SCRIPTS_DIR / "ingest_daily.py")
)
_ingest_daily = importlib.util.module_from_spec(_spec_id)
_spec_id.loader.exec_module(_ingest_daily)

# -- ingest_intraday.py --
_spec_ii = importlib.util.spec_from_file_location(
    "ingest_intraday_test", str(_SCRIPTS_DIR / "ingest_intraday.py")
)
_ingest_intraday = importlib.util.module_from_spec(_spec_ii)
_spec_ii.loader.exec_module(_ingest_intraday)

# -- run_research_experiment.py --
_spec_rre = importlib.util.spec_from_file_location(
    "run_research_experiment_test", str(_SCRIPTS_DIR / "run_research_experiment.py")
)
_run_research_experiment = importlib.util.module_from_spec(_spec_rre)
_spec_rre.loader.exec_module(_run_research_experiment)


class TestBuildUniverseScript(unittest.TestCase):
    """Tests for scripts/build_universe.py"""

    def test_build_universe_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_build_universe)
        self.assertTrue(hasattr(_build_universe, "main"))
        self.assertTrue(hasattr(_build_universe, "parse_utc"))

    def test_build_universe_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _build_universe.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_build_universe_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_build_universe.main))

    def test_build_universe_calls_builder(self):
        """Mock DataLakeService and UniverseBuilder; verify builder is called."""
        import pandas as pd

        mock_data = MagicMock()
        mock_data.read_cleaned_bars.return_value = pd.DataFrame(
            {"symbol": ["AAPL"], "close": [150.0], "volume": [10_000_000]}
        )

        mock_builder = MagicMock()
        mock_builder.from_daily_bars.return_value = ["AAPL", "MSFT"]

        with (
            patch.object(_build_universe, "DataLakeService", return_value=mock_data),
            patch.object(_build_universe, "UniverseBuilder", return_value=mock_builder),
        ):
            test_args = [
                "prog",
                "--symbols",
                "AAPL,MSFT",
                "--start",
                "2024-01-01T00:00:00Z",
                "--end",
                "2024-12-31T00:00:00Z",
                "--data-root",
                "/tmp/test_universe",
            ]
            with patch("sys.argv", test_args):
                _build_universe.main()

        mock_builder.from_daily_bars.assert_called_once()


class TestCompareExperimentsScript(unittest.TestCase):
    """Tests for scripts/compare_experiments.py"""

    def test_compare_experiments_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_compare_experiments)
        self.assertTrue(hasattr(_compare_experiments, "main"))

    def test_compare_experiments_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _compare_experiments.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_compare_experiments_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_compare_experiments.main))

    def test_compare_experiments_calls_compare(self):
        """Mock ExperimentRegistry and verify compare() is called."""
        mock_registry = MagicMock()
        mock_registry.compare.return_value = [
            {"run_id": "abc", "sharpe_ratio": 1.5}
        ]

        with patch.object(
            _compare_experiments, "ExperimentRegistry", return_value=mock_registry
        ):
            test_args = ["prog", "--data-root", "/tmp/test_exp"]
            with patch("sys.argv", test_args):
                _compare_experiments.main()

        mock_registry.compare.assert_called_once()


class TestIngestDailyScript(unittest.TestCase):
    """Tests for scripts/ingest_daily.py"""

    def test_ingest_daily_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_ingest_daily)
        self.assertTrue(hasattr(_ingest_daily, "main"))
        self.assertTrue(hasattr(_ingest_daily, "parse_utc"))

    def test_ingest_daily_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _ingest_daily.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_ingest_daily_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_ingest_daily.main))

    def test_ingest_daily_calls_sync_bars(self):
        """Mock DataLakeService and verify sync_bars is called."""
        mock_result = MagicMock()
        mock_result.status = "completed"

        mock_service = MagicMock()
        mock_service.sync_bars.return_value = mock_result

        with patch.object(
            _ingest_daily, "DataLakeService", return_value=mock_service
        ):
            test_args = [
                "prog",
                "--symbol",
                "AAPL",
                "--start",
                "2024-01-01T00:00:00Z",
                "--end",
                "2024-12-31T00:00:00Z",
                "--data-root",
                "/tmp/test_ingest",
            ]
            with patch("sys.argv", test_args):
                _ingest_daily.main()

        mock_service.sync_bars.assert_called_once()


class TestIngestIntradayScript(unittest.TestCase):
    """Tests for scripts/ingest_intraday.py"""

    def test_ingest_intraday_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_ingest_intraday)
        self.assertTrue(hasattr(_ingest_intraday, "main"))
        self.assertTrue(hasattr(_ingest_intraday, "parse_utc"))

    def test_ingest_intraday_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _ingest_intraday.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_ingest_intraday_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_ingest_intraday.main))

    def test_ingest_intraday_calls_sync_bars(self):
        """Mock DataLakeService and verify sync_bars is called with 1m bar_size."""
        mock_result = MagicMock()
        mock_result.status = "completed"

        mock_service = MagicMock()
        mock_service.sync_bars.return_value = mock_result

        with patch.object(
            _ingest_intraday, "DataLakeService", return_value=mock_service
        ):
            test_args = [
                "prog",
                "--symbol",
                "AAPL",
                "--start",
                "2024-01-01T00:00:00Z",
                "--end",
                "2024-01-02T00:00:00Z",
                "--bar-size",
                "1m",
                "--data-root",
                "/tmp/test_ingest_intra",
            ]
            with patch("sys.argv", test_args):
                _ingest_intraday.main()

        mock_service.sync_bars.assert_called_once()
        _call_args, call_kwargs = mock_service.sync_bars.call_args
        self.assertEqual(call_kwargs["bar_size"], "1m")


class TestRunResearchExperimentScript(unittest.TestCase):
    """Tests for scripts/run_research_experiment.py"""

    def test_run_research_experiment_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_run_research_experiment)
        self.assertTrue(hasattr(_run_research_experiment, "main"))
        self.assertTrue(hasattr(_run_research_experiment, "parse_utc"))

    def test_run_research_experiment_help(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _run_research_experiment.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_run_research_experiment_main_function(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_run_research_experiment.main))

    def test_run_research_experiment_full_flow(self):
        """Mock all heavy deps and verify the full pipeline completes."""
        mock_config = MagicMock()
        mock_result = MagicMock()
        mock_result.run_id = "test-run-123"
        mock_result.summary = {"sharpe_ratio": 1.5, "total_return": 0.12}

        mock_persisted = MagicMock()
        mock_persisted.summary_path = "/tmp/summary.json"
        mock_persisted.metadata_path = "/tmp/metadata.json"
        mock_persisted.orders_path = "/tmp/orders.parquet"
        mock_persisted.fills_path = "/tmp/fills.parquet"
        mock_persisted.snapshots_path = "/tmp/snapshots.parquet"

        mock_store = MagicMock()
        mock_store.write.return_value = mock_persisted

        mock_registry = MagicMock()
        mock_registry.create_record.return_value = MagicMock()
        mock_registry.register.return_value = Path("/tmp/manifest.json")

        with (
            patch.object(
                _run_research_experiment,
                "build_backtest_config",
                return_value=mock_config,
            ),
            patch.object(
                _run_research_experiment,
                "run_event_backtest_from_lake",
                return_value=mock_result,
            ),
            patch.object(
                _run_research_experiment,
                "BacktestResultStore",
                return_value=mock_store,
            ),
            patch.object(
                _run_research_experiment,
                "ExperimentRegistry",
                return_value=mock_registry,
            ),
        ):
            test_args = [
                "prog",
                "--experiment-name",
                "test_exp",
                "--symbols",
                "AAPL,MSFT",
                "--start",
                "2024-01-01T00:00:00Z",
                "--end",
                "2024-12-31T00:00:00Z",
                "--data-root",
                "/tmp/test_research",
            ]
            with patch("sys.argv", test_args):
                _run_research_experiment.main()

        mock_store.write.assert_called_once_with(mock_result)
        mock_registry.create_record.assert_called_once()
        mock_registry.register.assert_called_once()


if __name__ == "__main__":
    unittest.main()
