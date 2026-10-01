"""Tests for quant_us.data.pipeline: DataLakeService, DataLakeConfig, DataLakeSyncResult.

These tests verify the data pipeline orchestration layer using mocked data sources
and temporary directories for file I/O.  No real network calls or filesystem side
effects outside of TemporaryDirectory.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pandas as pd

from quant_us.data.cleaners.bar_cleaner import BarCleaner, CleaningResult
from quant_us.data.cleaners.data_validator import DataQualityReport
from quant_us.data.pipeline import DataLakeConfig, DataLakeService, DataLakeSyncResult
from quant_us.data.storage.data_manifest import DataManifestStore, validate_manifest_for_promotion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_bars(
    count: int = 10,
    symbol: str = "AAPL",
    start: datetime | None = None,
) -> pd.DataFrame:
    """Return a DataFrame with valid OHLCV columns consumable by BarCleaner."""
    start = start or datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)  # Tuesday, trading day
    timestamps = [start + timedelta(days=i) for i in range(count)]
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1_000_000,
            "symbol": symbol,
        }
    )


def _mock_connector(frame: pd.DataFrame | None = None, vendor: str = "yfinance") -> MagicMock:
    """Build a mocked MarketDataConnector that returns *frame*."""
    connector = MagicMock()
    connector.vendor = vendor
    connector.fetch_bars.return_value = frame if frame is not None else pd.DataFrame()
    return connector


# ---------------------------------------------------------------------------
# DataLakeConfig
# ---------------------------------------------------------------------------

class TestDataLakeConfig(unittest.TestCase):
    """Config construction / default values."""

    def test_default_values(self) -> None:
        config = DataLakeConfig()
        self.assertEqual(config.data_root, Path("data"))
        self.assertEqual(config.raw_subdir, "raw")
        self.assertEqual(config.cleaned_subdir, "cleaned")

    def test_derived_properties(self) -> None:
        config = DataLakeConfig()
        self.assertEqual(config.raw_root, Path("data") / "raw")
        self.assertEqual(config.cleaned_root, Path("data") / "cleaned")

    def test_custom_values(self) -> None:
        config = DataLakeConfig(
            data_root=Path("/tmp/my_data"),
            raw_subdir="incoming",
            cleaned_subdir="processed",
        )
        self.assertEqual(config.raw_root, Path("/tmp/my_data/incoming"))
        self.assertEqual(config.cleaned_root, Path("/tmp/my_data/processed"))


# ---------------------------------------------------------------------------
# DataLakeService
# ---------------------------------------------------------------------------

class TestDataLakeService(unittest.TestCase):
    """Pipeline orchestration tests with mocked connector and real cleaners."""

    # -- empty source -------------------------------------------------------

    def test_empty_source_returns_completed_with_zero_rows(self) -> None:
        """Empty DataFrame from connector must not crash and yield 0 rows."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(pd.DataFrame())

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="AAPL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 10, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows_received, 0)
        self.assertEqual(result.rows_cleaned, 0)
        self.assertEqual(result.raw_files, [])
        self.assertEqual(result.cleaned_files, [])

    # -- ingest step --------------------------------------------------------

    def test_ingest_calls_data_source_with_correct_args(self) -> None:
        """sync_bars must delegate to connector.fetch_bars with the right args."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                mock = _mock_connector(_synthetic_bars(5))
                cls.return_value = mock

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                service.sync_bars(
                    symbol="MSFT",
                    start=datetime(2024, 2, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 2, 10, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        mock.fetch_bars.assert_called_once()
        _, kwargs = mock.fetch_bars.call_args
        self.assertEqual(kwargs["symbol"], "MSFT")
        self.assertEqual(kwargs["bar_size"], "1d")
        self.assertEqual(kwargs["start"], datetime(2024, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(kwargs["end"], datetime(2024, 2, 10, tzinfo=timezone.utc))

    def test_ingest_connector_vendor_recorded_in_result(self) -> None:
        """The vendor name from the connector propagates to the result."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(3), vendor="yfinance")

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="AAPL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 5, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        self.assertEqual(result.vendor, "yfinance")

    # -- clean step ---------------------------------------------------------

    def test_clean_step_produces_quality_report(self) -> None:
        """After clean + validate, the result has a populated DataQualityReport."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(10))

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="AAPL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 15, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        self.assertIsInstance(result.quality, DataQualityReport)
        self.assertEqual(result.quality.row_count, 10)
        self.assertEqual(result.quality.non_positive_prices, 0)
        self.assertEqual(result.quality.invalid_ohlc, 0)

    def test_cleaner_receives_custom_injectable(self) -> None:
        """A custom cleaner passed to the constructor must be used by sync_bars."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(3))

                mock_cleaner = MagicMock(spec=BarCleaner)
                cleaned = CleaningResult(
                    frame=pd.DataFrame(
                        {
                            "timestamp_utc": pd.date_range(
                                "2024-01-01", periods=3, freq="D", tz="UTC"
                            ),
                            "symbol": "AAPL",
                            "open": 100.0,
                            "high": 101.0,
                            "low": 99.0,
                            "close": 100.5,
                            "volume": 1_000_000,
                            "timestamp_et": pd.NaT,
                            "session": "regular",
                            "is_regular_session": True,
                            "is_pre_market": False,
                            "is_after_hours": False,
                            "source": "yfinance",
                            "adjusted_flag": False,
                            "vwap": pd.NA,
                            "trade_count": pd.NA,
                        }
                    ),
                    dropped_rows=0,
                    duplicate_rows=0,
                )
                mock_cleaner.clean.return_value = cleaned

                service = DataLakeService(
                    config=DataLakeConfig(data_root=Path(tmpdir)),
                    cleaner=mock_cleaner,
                )
                service.sync_bars(
                    symbol="AAPL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 5, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        mock_cleaner.clean.assert_called_once()

    # -- manifest result structure -------------------------------------------

    def test_manifest_result_fields(self) -> None:
        """DataLakeSyncResult must carry all manifest metadata."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(5))

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="IBM",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 10, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        self.assertIsInstance(result, DataLakeSyncResult)
        self.assertTrue(result.run_id.startswith("sync_"))
        self.assertIn(result.status, {"completed", "failed"})
        self.assertEqual(result.vendor, "yfinance")
        self.assertEqual(result.asset_class, "equity")
        self.assertEqual(result.symbol, "IBM")
        self.assertEqual(result.bar_size, "1d")
        self.assertIsInstance(result.start, datetime)
        self.assertIsInstance(result.end, datetime)
        self.assertIsInstance(result.rows_received, int)
        self.assertIsInstance(result.rows_cleaned, int)
        self.assertIsInstance(result.raw_files, list)
        self.assertIsInstance(result.cleaned_files, list)
        self.assertIsInstance(result.quality, DataQualityReport)
        self.assertIsInstance(result.created_at, datetime)
        self.assertIsInstance(result.completed_at, (datetime, type(None)))
        self.assertIsNone(result.error)

    def test_sync_writes_promotion_manifest_and_data_version(self) -> None:
        """Successful sync must materialize cleaned data and a usable data manifest."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(5))

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="AAPL",
                    start=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 8, tzinfo=timezone.utc),
                    bar_size="1d",
                )

            self.assertEqual(result.status, "completed")
            self.assertTrue(result.data_version.startswith("qs-yfinance-AAPL-1d-"))
            self.assertTrue(result.data_manifest_path)
            self.assertTrue(Path(result.data_manifest_path).is_file())
            manifest = DataManifestStore(Path(tmpdir) / "manifests").read(result.data_version)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            validation = validate_manifest_for_promotion(manifest)
            self.assertTrue(validation.ok, validation.reasons)
            loaded = service.read_cleaned_bars(
                symbol="AAPL",
                start=datetime(2024, 1, 2, tzinfo=timezone.utc),
                end=datetime(2024, 1, 8, tzinfo=timezone.utc),
                bar_size="1d",
            )
            self.assertIn("data_version", loaded.columns)
            self.assertEqual(set(loaded["data_version"]), {result.data_version})

    # -- full flow -----------------------------------------------------------

    def test_pipeline_full_flow_writes_parquet_files(self) -> None:
        """Full sync writes parquet to both raw and cleaned stores."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(8))

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="GOOGL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 10, tzinfo=timezone.utc),
                    bar_size="1d",
                )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.rows_received, 8)
            self.assertGreater(result.rows_cleaned, 0)
            self.assertGreater(len(result.raw_files), 0)
            self.assertGreater(len(result.cleaned_files), 0)

            # Verify actual parquet files exist on disk
            for path_str in result.raw_files:
                self.assertTrue(Path(path_str).exists(), f"Raw file missing: {path_str}")
            for path_str in result.cleaned_files:
                self.assertTrue(Path(path_str).exists(), f"Cleaned file missing: {path_str}")

    def test_pipeline_full_flow_can_read_back(self) -> None:
        """Data written by sync_bars must be readable via read_cleaned_bars."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(8))

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                service.sync_bars(
                    symbol="GOOGL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 10, tzinfo=timezone.utc),
                    bar_size="1d",
                )

                loaded = service.read_cleaned_bars(
                    symbol="GOOGL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 10, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        self.assertIsInstance(loaded, pd.DataFrame)
        self.assertFalse(loaded.empty)
        self.assertIn("timestamp_utc", loaded.columns)
        self.assertIn("open", loaded.columns)
        self.assertIn("close", loaded.columns)

    # -- error handling -----------------------------------------------------

    def test_error_in_ingest_returns_failed_result(self) -> None:
        """When the connector raises, status must be 'failed' and error populated."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                mock = MagicMock()
                mock.vendor = "yfinance"
                mock.fetch_bars.side_effect = RuntimeError("Connection refused")
                cls.return_value = mock

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="AAPL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 10, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error)
        self.assertIn("Connection refused", result.error)
        self.assertEqual(result.rows_received, 0)
        self.assertEqual(result.rows_cleaned, 0)
        self.assertEqual(result.raw_files, [])
        self.assertEqual(result.cleaned_files, [])

    def test_error_from_cleaner_recorded_gracefully(self) -> None:
        """A crash during cleaning must produce a failed result, not propagate."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                mock = MagicMock()
                mock.vendor = "yfinance"
                mock.fetch_bars.return_value = _synthetic_bars(5)
                cls.return_value = mock

                failing_cleaner = MagicMock(spec=BarCleaner)
                failing_cleaner.clean.side_effect = ValueError("Bad adjustment")

                service = DataLakeService(
                    config=DataLakeConfig(data_root=Path(tmpdir)),
                    cleaner=failing_cleaner,
                )
                result = service.sync_bars(
                    symbol="AAPL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 10, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error)
        self.assertIn("Bad adjustment", result.error)

    # -- edge cases ---------------------------------------------------------

    def test_symbol_is_uppercased_in_result(self) -> None:
        """Symbol must be upper-cased in the result regardless of input case."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(3, symbol="aapl"))

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="aapl",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 5, tzinfo=timezone.utc),
                    bar_size="1d",
                )

        self.assertEqual(result.symbol, "AAPL")

    def test_timezone_normalization(self) -> None:
        """Timestamps passed in any timezone are normalized to UTC."""
        with TemporaryDirectory() as tmpdir:
            with patch("quant_us.data.pipeline.YFinanceDataConnector") as cls:
                cls.return_value = _mock_connector(_synthetic_bars(3))

                service = DataLakeService(DataLakeConfig(data_root=Path(tmpdir)))
                result = service.sync_bars(
                    symbol="AAPL",
                    start=datetime(2024, 1, 1),  # naive
                    end=datetime(2024, 1, 5),  # naive
                    bar_size="1d",
                )

        # The service calls ensure_utc on both, so they should be UTC-aware
        self.assertIsNotNone(result.start.tzinfo)
        self.assertIsNotNone(result.end.tzinfo)
        self.assertEqual(str(result.start.tzinfo), "UTC")
        self.assertEqual(str(result.end.tzinfo), "UTC")


if __name__ == "__main__":
    unittest.main()
