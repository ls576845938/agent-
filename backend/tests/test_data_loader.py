from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.core.exceptions import DataNotAvailableError
from backend.app.services.data_management import KlineRecord, MarketDataRepository
from backend.app.services.market_data import inspect_market_data_quality, load_market_frame


class DataLoaderTests(unittest.TestCase):
    def test_fixture_loader_returns_normalized_frame(self) -> None:
        frame = load_market_frame(
            source="fixture",
            symbol="BTCUSDT",
            interval="1h",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 10),
        )

        self.assertGreater(len(frame), 100)
        self.assertListEqual(list(frame.columns), ["open", "high", "low", "close", "volume"])
        self.assertTrue(frame.index.is_monotonic_increasing)
        self.assertTrue((frame["high"] >= frame["low"]).all())

    def test_yfinance_parquet_loader_returns_normalized_frame(self) -> None:
        frame = load_market_frame(
            source="yfinance",
            symbol="SPY",
            interval="1d",
            start=datetime(2024, 1, 2),
            end=datetime(2024, 3, 29),
        )

        self.assertGreater(len(frame), 0)
        self.assertListEqual(list(frame.columns), ["open", "high", "low", "close", "volume"])
        self.assertTrue(frame.index.is_monotonic_increasing)

    def test_sqlite_loader_raises_explicit_error_when_missing(self) -> None:
        with self.assertRaises(DataNotAvailableError):
            load_market_frame(
                source="sqlite",
                symbol="BTCUSDT",
                interval="1h",
                start=datetime(2024, 1, 1),
                end=datetime(2024, 1, 10),
                db_path="D:/Trading/比特币聚合多策略模型codex/does-not-exist.db",
            )

    def test_sqlite_loader_reads_managed_market_kline_table(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = f"{directory}/market.sqlite"
            repository = MarketDataRepository(db_path=db_path)
            repository.upsert_klines(
                [
                    KlineRecord(
                        exchange="binance_spot",
                        symbol="BTCUSDT",
                        interval="1m",
                        open_time_ms=1_704_067_200_000,
                        open_time="2024-01-01T00:00:00+00:00",
                        close_time_ms=1_704_067_259_999,
                        close_time="2024-01-01T00:00:59.999000+00:00",
                        open=42000.0,
                        high=42100.0,
                        low=41900.0,
                        close=42050.0,
                        volume=12.5,
                        quote_volume=525000.0,
                        trade_count=42,
                        taker_buy_base_volume=6.0,
                        taker_buy_quote_volume=252000.0,
                    )
                ]
            )

            frame = load_market_frame(
                source="sqlite",
                symbol="BTCUSDT",
                interval="1m",
                start=datetime(2024, 1, 1, 0, 0),
                end=datetime(2024, 1, 1, 0, 1),
                db_path=db_path,
            )

        self.assertEqual(len(frame), 1)
        self.assertEqual(float(frame.iloc[0]["close"]), 42050.0)

    def test_fixture_quality_report_has_stable_version(self) -> None:
        result = inspect_market_data_quality(
            source="fixture",
            symbol="BTCUSDT",
            interval="1h",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 10),
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["selected_priority"], "数据质量与特征版本治理")
        self.assertTrue(result["is_usable"])
        self.assertEqual(result["missing_bars"], 0)
        self.assertIn("qs-fixture-BTCUSDT-1h", result["data_version"])
        self.assertEqual(len(result["fingerprint"]), 64)

    def test_auto_loader_does_not_silently_fallback_to_fixture_when_disabled(self) -> None:
        fake_settings = SimpleNamespace(
            resolved_data_db_path=None,
            allow_fixture_fallback=False,
        )
        with patch("backend.app.services.market_data.settings", fake_settings):
            with self.assertRaises(DataNotAvailableError):
                load_market_frame(
                    source="auto",
                    symbol="SPY",
                    interval="1d",
                    start=datetime(2024, 1, 1),
                    end=datetime(2024, 1, 10),
                )

    def test_auto_loader_allows_fixture_only_when_explicitly_enabled(self) -> None:
        fake_settings = SimpleNamespace(
            resolved_data_db_path=None,
            allow_fixture_fallback=True,
        )
        with patch("backend.app.services.market_data.settings", fake_settings):
            frame = load_market_frame(
                source="auto",
                symbol="SPY",
                interval="1d",
                start=datetime(2024, 1, 1),
                end=datetime(2024, 1, 10),
            )

        self.assertGreater(len(frame), 0)

    def test_explicit_yfinance_loader_never_falls_back_to_fixture(self) -> None:
        fake_settings = SimpleNamespace(
            resolved_data_db_path=None,
            allow_fixture_fallback=True,
        )
        with (
            patch("backend.app.services.market_data.settings", fake_settings),
            patch("quant_us.data.storage.parquet_store.ParquetBarStore.read_bars",
                  side_effect=RuntimeError("parquet unavailable")),
        ):
            with self.assertRaises(DataNotAvailableError):
                load_market_frame(
                    source="yfinance",
                    symbol="NO_SUCH_SYMBOL",
                    interval="1d",
                    start=datetime(2024, 1, 1),
                    end=datetime(2024, 1, 10),
                )

    def test_sqlite_quality_report_detects_missing_bars(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = f"{directory}/market.sqlite"
            repository = MarketDataRepository(db_path=db_path)
            repository.upsert_klines(
                [
                    KlineRecord(
                        exchange="binance_spot",
                        symbol="BTCUSDT",
                        interval="1m",
                        open_time_ms=1_704_067_200_000,
                        open_time="2024-01-01T00:00:00+00:00",
                        close_time_ms=1_704_067_259_999,
                        close_time="2024-01-01T00:00:59.999000+00:00",
                        open=42000.0,
                        high=42100.0,
                        low=41900.0,
                        close=42050.0,
                        volume=12.5,
                        quote_volume=525000.0,
                        trade_count=42,
                        taker_buy_base_volume=6.0,
                        taker_buy_quote_volume=252000.0,
                    ),
                    KlineRecord(
                        exchange="binance_spot",
                        symbol="BTCUSDT",
                        interval="1m",
                        open_time_ms=1_704_067_320_000,
                        open_time="2024-01-01T00:02:00+00:00",
                        close_time_ms=1_704_067_379_999,
                        close_time="2024-01-01T00:02:59.999000+00:00",
                        open=42100.0,
                        high=42200.0,
                        low=42000.0,
                        close=42150.0,
                        volume=10.0,
                        quote_volume=421500.0,
                        trade_count=37,
                        taker_buy_base_volume=5.0,
                        taker_buy_quote_volume=210750.0,
                    ),
                ]
            )

            result = inspect_market_data_quality(
                source="sqlite",
                symbol="BTCUSDT",
                interval="1m",
                start=datetime(2024, 1, 1, 0, 0),
                end=datetime(2024, 1, 1, 0, 2),
                db_path=db_path,
            )

        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["expected_rows"], 3)
        self.assertEqual(result["missing_bars"], 1)
        self.assertFalse(result["is_usable"])
        self.assertTrue(any(issue["code"] == "missing_bars" for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
