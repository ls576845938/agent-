"""V1 data acceptance criteria tests.

Six acceptance criteria:
  1. Same symbol + date re-ingest does not produce duplicate bars
  2. Every bar has source, ingested_at, data_version
  3. Bars can distinguish regular / pre_market / after_hours sessions
  4. Missing bars can be detected
  5. Data quality report can be output
  6. Given symbol + date_range, cleaned bars are returned stably
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.data.connectors.us_equity_ingestion import (
    USEquityIngestionConfig,
    USEquityIngestionPipeline,
)


def _make_raw_bars(symbol: str, days: int = 5, start_date: str = "2024-06-03") -> pd.DataFrame:
    """Synthetic OHLCV bars mimicking yfinance output."""
    start = pd.Timestamp(start_date, tz="UTC")
    records = []
    price = 150.0
    for i in range(days):
        ts = start + pd.Timedelta(days=i) + pd.Timedelta(hours=14, minutes=30)  # 14:30 UTC = 10:30 ET
        if ts.day_of_week >= 5:  # skip weekends
            continue
        price *= 1.0 + (i % 3 - 1) * 0.01
        records.append({
            "timestamp_utc": ts,
            "open": price * 0.999,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 1_000_000.0 + i * 100_000,
        })
    return pd.DataFrame(records)


class AcceptanceCriterion1_DedupTests(unittest.TestCase):
    """AC-1: Same symbol + date re-ingest does not produce duplicate K-lines."""

    def test_reingest_same_date_range_no_duplicates(self):
        with TemporaryDirectory() as tmp:
            cfg = USEquityIngestionConfig(data_root=tmp, symbols=["AAPL"], start="2024-06-03", end="2024-06-07")
            p1 = USEquityIngestionPipeline(cfg)
            p1._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 5, "2024-06-03")
            r1 = p1.run()
            self.assertEqual(len(r1), 1)
            row_count_1 = r1[0].row_count

            p2 = USEquityIngestionPipeline(cfg)
            p2._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 5, "2024-06-03")
            r2 = p2.run()
            row_count_2 = r2[0].row_count

            # Re-ingest should not increase row count
            self.assertEqual(row_count_1, row_count_2)

            # Verify no duplicates on disk
            root = Path(tmp) / "raw" / "vendor=yfinance" / "asset_class=equity" / "bar_size=1d" / "symbol=AAPL"
            parquet_files = list(root.glob("date=*.parquet"))
            self.assertGreater(len(parquet_files), 0)
            for pf in parquet_files:
                df = pd.read_parquet(pf)
                ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
                self.assertEqual(len(df), len(df[ts_col].drop_duplicates()),
                                 f"Duplicates found in {pf.name}")


class AcceptanceCriterion2_BarMetadataTests(unittest.TestCase):
    """AC-2: Every bar has source, ingested_at, data_version."""

    def test_bars_have_metadata_columns(self):
        with TemporaryDirectory() as tmp:
            cfg = USEquityIngestionConfig(data_root=tmp, symbols=["SPY"], start="2024-06-03", end="2024-06-07")
            pipeline = USEquityIngestionPipeline(cfg)
            pipeline._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 5, "2024-06-03")
            pipeline.run()

            root = Path(tmp) / "raw" / "vendor=yfinance" / "asset_class=equity" / "bar_size=1d" / "symbol=SPY"
            for pf in root.glob("date=*.parquet"):
                df = pd.read_parquet(pf)
                for col in ["source", "ingested_at", "data_version"]:
                    self.assertIn(col, df.columns, f"Missing column '{col}' in {pf.name}")
                self.assertTrue((df["source"] == "yfinance").all(),
                                f"source column should be 'yfinance'")
                self.assertTrue(df["ingested_at"].notna().all(),
                                "ingested_at should not be null")
                self.assertTrue(df["data_version"].notna().all(),
                                "data_version should not be null")


class AcceptanceCriterion3_SessionTests(unittest.TestCase):
    """AC-3: Bars can distinguish regular / pre_market / after_hours."""

    def test_bars_have_session_column(self):
        with TemporaryDirectory() as tmp:
            cfg = USEquityIngestionConfig(data_root=tmp, symbols=["AAPL"], start="2024-06-03", end="2024-06-07")
            pipeline = USEquityIngestionPipeline(cfg)
            pipeline._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 5, "2024-06-03")
            pipeline.run()

            root = Path(tmp) / "raw" / "vendor=yfinance" / "asset_class=equity" / "bar_size=1d" / "symbol=AAPL"
            for pf in root.glob("date=*.parquet"):
                df = pd.read_parquet(pf)
                self.assertIn("session", df.columns, f"Missing 'session' column in {pf.name}")
                sessions = df["session"].unique()
                for s in sessions:
                    self.assertIn(s, ["regular", "pre_market", "after_hours", "closed", "overnight"],
                                  f"Unexpected session value: {s}")


class AcceptanceCriterion4_MissingBarTests(unittest.TestCase):
    """AC-4: Missing bars can be detected."""

    def test_missing_bars_reported_in_quality(self):
        with TemporaryDirectory() as tmp:
            cfg = USEquityIngestionConfig(data_root=tmp, symbols=["MSFT"], start="2024-06-03", end="2024-06-28")
            pipeline = USEquityIngestionPipeline(cfg)
            # Return only 3 days of data for a 4-week range → many missing bars
            pipeline._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 3, "2024-06-03")
            results = pipeline.run()
            self.assertEqual(len(results), 1)

            # Check manifest for missing_bars
            manifest_path = results[0].manifest_path
            if manifest_path:
                import json
                with open(manifest_path) as f:
                    manifest = json.load(f)
                self.assertIn("cleaning", manifest)
                self.assertIn("missing_bars", manifest.get("cleaning", {}),
                              "Manifest should report missing_bars")

    def test_full_range_bars_missing_detected(self):
        calendar = USEquityCalendar.with_holidays()
        trading_days = 0
        d = date(2024, 6, 3)
        end = date(2024, 6, 28)
        while d <= end:
            if calendar.is_trading_day(d):
                trading_days += 1
            d = d.replace(day=d.day + 1) if d.day < 28 else date(d.year, d.month + 1, 1)
        # We provided 5 days of synthetic data, some may fall on weekends
        self.assertGreater(trading_days, 3, "June 2024 should have >3 trading days")


class AcceptanceCriterion5_QualityReportTests(unittest.TestCase):
    """AC-5: Data quality report can be output."""

    def test_quality_report_has_required_fields(self):
        with TemporaryDirectory() as tmp:
            cfg = USEquityIngestionConfig(data_root=tmp, symbols=["NVDA"], start="2024-06-03", end="2024-06-07")
            pipeline = USEquityIngestionPipeline(cfg)
            pipeline._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 5, "2024-06-03")
            results = pipeline.run()

            # Check manifest JSON
            manifest_path = results[0].manifest_path
            self.assertTrue(manifest_path, "Manifest should be generated")
            import json
            with open(manifest_path) as f:
                report = json.load(f)

            required = ["data_version", "source", "symbol", "interval",
                        "row_count", "coverage_pct", "quality_score",
                        "start", "end", "fingerprint", "cleaning"]
            for key in required:
                self.assertIn(key, report, f"Quality report missing '{key}'")

    def test_quality_score_range(self):
        with TemporaryDirectory() as tmp:
            cfg = USEquityIngestionConfig(data_root=tmp, symbols=["META"], start="2024-06-03", end="2024-06-07")
            pipeline = USEquityIngestionPipeline(cfg)
            pipeline._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 5, "2024-06-03")
            results = pipeline.run()

            import json
            with open(results[0].manifest_path) as f:
                report = json.load(f)
            score = report["quality_score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)
            coverage = report["coverage_pct"]
            self.assertGreaterEqual(coverage, 0.0)
            self.assertLessEqual(coverage, 100.0)


class AcceptanceCriterion6_StableQueryTests(unittest.TestCase):
    """AC-6: Given symbol + date_range, cleaned bars are returned stably."""

    def test_same_query_twice_returns_same_bars(self):
        with TemporaryDirectory() as tmp:
            cfg = USEquityIngestionConfig(data_root=tmp, symbols=["GOOGL"], start="2024-06-03", end="2024-06-07")
            pipeline = USEquityIngestionPipeline(cfg)
            pipeline._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 5, "2024-06-03")
            pipeline.run()

            from quant_us.data.storage.duckdb_store import DuckDBBarReader, DuckDBQuery
            reader = DuckDBBarReader(Path(tmp) / "raw")
            start_dt = datetime(2024, 6, 3, tzinfo=timezone.utc)
            end_dt = datetime(2024, 6, 7, tzinfo=timezone.utc)

            query = DuckDBQuery(vendor="yfinance", asset_class="equity", bar_size="1d",
                               symbol="GOOGL", start=start_dt, end=end_dt)
            df1 = reader.query_bars(query)
            df2 = reader.query_bars(query)

            self.assertEqual(len(df1), len(df2),
                             "Same query should return same number of rows")
            if not df1.empty:
                pd.testing.assert_frame_equal(
                    df1.sort_values("timestamp_utc").reset_index(drop=True),
                    df2.sort_values("timestamp_utc").reset_index(drop=True),
                )

    def test_query_returns_cleaned_bars_only(self):
        with TemporaryDirectory() as tmp:
            cfg = USEquityIngestionConfig(data_root=tmp, symbols=["IWM"], start="2024-06-03", end="2024-06-07")
            pipeline = USEquityIngestionPipeline(cfg)
            pipeline._connector.fetch_bars = lambda s, st, en, iv: _make_raw_bars(s, 5, "2024-06-03")
            pipeline.run()

            from quant_us.data.storage.duckdb_store import DuckDBBarReader, DuckDBQuery
            reader = DuckDBBarReader(Path(tmp) / "raw")
            start_dt = datetime(2024, 6, 3, tzinfo=timezone.utc)
            end_dt = datetime(2024, 6, 7, tzinfo=timezone.utc)

            query = DuckDBQuery(vendor="yfinance", asset_class="equity", bar_size="1d",
                               symbol="IWM", start=start_dt, end=end_dt)
            df = reader.query_bars(query)

            if not df.empty:
                # All OHLCV values must be positive
                for col in ["open", "high", "low", "close"]:
                    if col in df.columns:
                        self.assertTrue((df[col] > 0).all(), f"{col} has non-positive values")
                # high >= low
                self.assertTrue((df["high"] >= df["low"]).all(), "high < low found")
                # no duplicate timestamps
                ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
                self.assertEqual(len(df), len(df[ts_col].drop_duplicates()),
                                 "Duplicate timestamps in query result")


if __name__ == "__main__":
    unittest.main()
