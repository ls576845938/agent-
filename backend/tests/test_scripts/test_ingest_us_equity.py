"""Tests for US equity ingestion script and pipeline.

Mock strategy:
- yfinance.download is patched directly (yfinance >=0.2.40 is a project dependency).
- The CLI script (scripts/ingest_us_equity.py) is loaded via importlib so its
  main() and SP500_TOP can be tested without polluting sys.path.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_DATES = pd.bdate_range("2024-01-02", "2024-01-05")
FAKE_OHLCV = pd.DataFrame(
    {
        "Open": [150.0, 151.0, 152.0, 153.0],
        "High": [155.0, 156.0, 157.0, 158.0],
        "Low": [149.0, 150.0, 151.0, 152.0],
        "Close": [154.0, 155.0, 156.0, 157.0],
        "Volume": [1_000_000, 1_100_000, 1_200_000, 1_300_000],
    },
    index=pd.DatetimeIndex(FAKE_DATES, name="Date"),
)

# Load the CLI script module once so we can test its main() and SP500_TOP.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
_SCRIPT_PATH = _SCRIPTS_DIR / "ingest_us_equity.py"
_spec = importlib.util.spec_from_file_location("ingest_us_equity_test", str(_SCRIPT_PATH))
_ingest_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ingest_script)


# ---------------------------------------------------------------------------
# Pipeline-level tests
# ---------------------------------------------------------------------------


class TestIngestUSEquityPipeline(unittest.TestCase):
    """Tests for USEquityIngestionPipeline with yfinance.download mocked."""

    def setUp(self):
        self.yf_patch = patch("yfinance.download", return_value=FAKE_OHLCV)
        self.mock_download = self.yf_patch.start()

    def tearDown(self):
        self.yf_patch.stop()

    @staticmethod
    def _make_config(data_root: str, **overrides):
        """Build a USEquityIngestionConfig with safe default overrides.

        The default fields (symbols, intervals, start, end) are only set when
        *overrides* does not supply them, avoiding duplicate keyword errors.
        """
        from quant_us.data.connectors.us_equity_ingestion import (
            USEquityIngestionConfig,
        )

        defaults = dict(
            data_root=data_root,
            symbols=["AAPL"],
            intervals=["1d"],
            start="2024-01-01",
            end="2024-01-10",
        )
        defaults.update(overrides)
        return USEquityIngestionConfig(**defaults)

    @staticmethod
    def _pipeline(data_root: str, **overrides):
        """Build a pipeline whose manifest store also lives under *data_root*."""
        from quant_us.data.connectors.us_equity_ingestion import (
            USEquityIngestionPipeline,
        )
        from quant_us.data.storage.data_manifest import DataManifestStore

        config = TestIngestUSEquityPipeline._make_config(data_root, **overrides)
        pipeline = USEquityIngestionPipeline(config)
        pipeline.manifest_store = DataManifestStore(root=Path(data_root) / "manifests")
        return pipeline

    # -- test_successful_ingestion_returns_expected_structure --

    def test_successful_ingestion_returns_expected_structure(self):
        """Returns IngestionResult with symbol, interval, data_version, paths."""
        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp)
            results = pipeline.run()

            self.assertEqual(len(results), 1)
            r = results[0]
            self.assertEqual(r.symbol, "AAPL")
            self.assertEqual(r.interval, "1d")
            self.assertEqual(r.error, "")
            self.assertGreater(r.row_count, 0)
            self.assertTrue(
                r.data_version.startswith("qs-yfinance-AAPL-1d-"),
                f"data_version={r.data_version!r} does not start with expected prefix",
            )
            self.assertIn(tmp, r.path)
            self.assertIn(tmp, r.manifest_path)

    # -- test_output_parquet_files_written_correctly --

    def test_output_parquet_files_written_correctly(self):
        """Parquet files land under the Hive-style path."""
        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp)
            results = pipeline.run()

            r = results[0]
            expected_layout = "raw/vendor=yfinance/asset_class=equity/bar_size=1d/symbol=AAPL"
            self.assertIn(expected_layout, r.path)

            parquet_dir = Path(r.path)
            self.assertTrue(parquet_dir.is_dir())
            parquet_files = list(parquet_dir.glob("date=*.parquet"))
            self.assertGreater(len(parquet_files), 0)

    # -- test_yfinance_download_called_with_correct_params --

    def test_yfinance_download_called_with_correct_params(self):
        """Verify the mock was invoked with expected keyword arguments."""
        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp)
            pipeline.run()

        self.mock_download.assert_called()
        _call_args, kwargs = self.mock_download.call_args
        self.assertEqual(kwargs["tickers"], "AAPL")
        self.assertEqual(kwargs["interval"], "1d")
        self.assertFalse(kwargs["auto_adjust"])
        self.assertTrue(kwargs["prepost"])
        self.assertFalse(kwargs["progress"])
        self.assertEqual(kwargs["group_by"], "column")

    # -- test_multiple_symbols --

    def test_multiple_symbols(self):
        """Pipeline processes each symbol independently and returns per-symbol results."""
        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp, symbols=["AAPL", "MSFT"], generate_manifest=False)
            results = pipeline.run()

            self.assertEqual(len(results), 2)
            symbols_found = {r.symbol for r in results}
            self.assertEqual(symbols_found, {"AAPL", "MSFT"})
            for r in results:
                self.assertGreater(r.row_count, 0)

    # -- test_invalid_symbol_returns_error --

    def test_invalid_symbol_returns_error(self):
        """When yfinance returns an empty DataFrame, the result carries an error."""
        self.mock_download.return_value = pd.DataFrame()
        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp)
            results = pipeline.run()

            self.assertEqual(len(results), 1)
            r = results[0]
            self.assertNotEqual(r.error, "")
            self.assertEqual(r.row_count, 0)

    # -- test_manifest_generated_by_default --

    def test_manifest_generated_by_default(self):
        """With generate_manifest=True (default), a manifest JSON file is written."""
        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp, generate_manifest=True)
            results = pipeline.run()

            r = results[0]
            self.assertNotEqual(r.manifest_path, "")
            manifest_file = Path(r.manifest_path)
            self.assertTrue(manifest_file.is_file())

    # -- test_no_manifest_flag_does_not_crash --

    def test_no_manifest_flag_does_not_crash(self):
        """generate_manifest=False skips manifest write and does not crash.

        Verify that no manifest JSON file is created on disk.
        """
        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp, generate_manifest=False)
            results = pipeline.run()

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].error, "")
            # Manifest path should be empty when generate_manifest is False.
            self.assertEqual(results[0].manifest_path, "")
            # No manifest files should exist under the data root.
            manifest_files = list(Path(tmp).rglob("*.json"))
            self.assertEqual(len(manifest_files), 0, f"Unexpected manifest files: {manifest_files}")

    # -- test_data_cleaning_filters_bad_rows --

    def test_bad_ohlc_rows_are_removed(self):
        """Rows where high < low or non-positive prices get cleaned out."""
        bad_data = FAKE_OHLCV.copy()
        # Third row: high < low (invalid)
        bad_data.iloc[2, bad_data.columns.get_loc("High")] = 140.0
        # Fourth row: close <= 0
        bad_data.iloc[3, bad_data.columns.get_loc("Close")] = -1.0

        self.mock_download.return_value = bad_data

        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp)
            results = pipeline.run()

            # Only the first 2 rows should survive cleaning.
            r = results[0]
            self.assertGreater(r.row_count, 0)
            # There were 4 rows; 2 were bad; at most 2 survive.
            self.assertLessEqual(r.row_count, 2)

    # -- test_sorted_and_deduplicated --

    def test_timestamps_are_sorted_and_deduplicated(self):
        """Cleaned data has unique, sorted timestamps."""
        with TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp)
            results = pipeline.run()

            r = results[0]
            self.assertGreater(r.row_count, 0)

            # Read back the parquet data and verify ordering.
            parquet_dir = Path(r.path)
            all_frames = []
            for pf in sorted(parquet_dir.glob("date=*.parquet")):
                all_frames.append(pd.read_parquet(pf))
            df = pd.concat(all_frames, ignore_index=True)

            ts = pd.to_datetime(df["timestamp_utc"], utc=True)
            self.assertTrue(ts.is_monotonic_increasing, "Timestamps are not sorted")
            self.assertEqual(len(ts), len(ts.unique()), "Duplicate timestamps present")


# ---------------------------------------------------------------------------
# CLI-level tests
# ---------------------------------------------------------------------------


class TestIngestUSEquityCLI(unittest.TestCase):
    """Test CLI argument parsing and symbol expansion."""

    def test_sp500_top_has_expected_symbols(self):
        self.assertGreater(len(_ingest_script.SP500_TOP), 0)
        self.assertIn("AAPL", _ingest_script.SP500_TOP)
        self.assertIn("MSFT", _ingest_script.SP500_TOP)
        # SPY / QQQ are ETF proxies; verify they are present.
        self.assertIn("SPY", _ingest_script.SP500_TOP)

    def test_main_respects_no_manifest_flag(self):
        """--no-manifest builds config with generate_manifest=False."""
        test_args = [
            "prog",
            "--symbols", "AAPL",
            "--intervals", "1d",
            "--data-root", "/tmp/irrelevant",
            "--no-manifest",
        ]
        with patch("sys.argv", test_args):
            with patch.object(_ingest_script, "USEquityIngestionPipeline") as MockPipe:
                instance = MockPipe.return_value
                instance.run.return_value = []

                _ingest_script.main()

        config = MockPipe.call_args[0][0]
        self.assertFalse(config.generate_manifest)

    def test_main_all_flag_expands_to_sp500_top(self):
        """--all flag passes SP500_TOP as symbols to the pipeline config."""
        test_args = [
            "prog",
            "--all",
            "--intervals", "1d",
            "--data-root", "/tmp/irrelevant",
            "--no-manifest",
        ]
        with patch("sys.argv", test_args):
            with patch.object(_ingest_script, "USEquityIngestionPipeline") as MockPipe:
                instance = MockPipe.return_value
                instance.run.return_value = []

                _ingest_script.main()

        config = MockPipe.call_args[0][0]
        self.assertEqual(config.symbols, _ingest_script.SP500_TOP)

    def test_main_default_symbols(self):
        """Without --all or --symbols, the default comma-separated list is used."""
        test_args = [
            "prog",
            "--intervals", "1d",
            "--data-root", "/tmp/irrelevant",
            "--no-manifest",
        ]
        with patch("sys.argv", test_args):
            with patch.object(_ingest_script, "USEquityIngestionPipeline") as MockPipe:
                instance = MockPipe.return_value
                instance.run.return_value = []

                _ingest_script.main()

        config = MockPipe.call_args[0][0]
        # The default in the argument parser is "AAPL,MSFT,GOOGL".
        self.assertEqual(config.symbols, ["AAPL", "MSFT", "GOOGL"])


if __name__ == "__main__":
    unittest.main()
