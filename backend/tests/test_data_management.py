from __future__ import annotations

import io
import json
import urllib.error
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.services.data_management import BinanceKlineClient, DataSyncSpec, MarketDataService


class FakeBinanceClient:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> list[list[object]]:
        self.calls += 1
        return [
            [
                start_time_ms,
                "42000.0",
                "42100.0",
                "41900.0",
                "42050.0",
                "12.5",
                start_time_ms + 59_999,
                "525000.0",
                42,
                "6.0",
                "252000.0",
                "0",
            ],
            [
                start_time_ms + 60_000,
                "42050.0",
                "42200.0",
                "42000.0",
                "42150.0",
                "10.0",
                start_time_ms + 119_999,
                "421500.0",
                37,
                "5.0",
                "210750.0",
                "0",
            ],
        ]


class FakeCoinbaseClient:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 300,
    ) -> list[list[object]]:
        self.calls += 1
        start_seconds = start_time_ms // 1000
        return [
            [start_seconds, "41900.0", "42100.0", "42000.0", "42050.0", "12.5"],
            [start_seconds + 60, "42000.0", "42200.0", "42050.0", "42150.0", "10.0"],
        ]


class FakeKrakenClient:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 720,
    ) -> list[list[object]]:
        self.calls += 1
        start_seconds = start_time_ms // 1000
        return [
            [start_seconds, "42000.0", "42100.0", "41900.0", "42050.0", "42025.0", "12.5", 42],
            [start_seconds + 60, "42050.0", "42200.0", "42000.0", "42150.0", "42100.0", "10.0", 37],
        ]


class FakeHttpResponse:
    def __init__(self, payload: object) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class DataManagementTests(unittest.TestCase):
    def _write_btc_data_status_report(self, root: Path) -> None:
        report = root / "artifacts/btc_data_status/latest/btc_data_status_report.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                {
                    "schema_version": "btc_data_status_report_v1",
                    "symbol": "BTCUSDT",
                    "generated_at": "2026-05-22T20:37:23.618519+00:00",
                    "coverage": {
                        "intervals_available": ["5m", "1h"],
                        "bar_count_by_interval": {"5m": 248257, "1h": 20689},
                        "sample_start": "2024-01-01T00:00:00+00:00",
                        "sample_end": "2026-05-12T00:00:00+00:00",
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_binance_client_falls_back_when_primary_endpoint_is_restricted(self) -> None:
        restricted_error = urllib.error.HTTPError(
            url="https://api.binance.com/api/v3/klines",
            code=451,
            msg="restricted",
            hdrs=None,
            fp=io.BytesIO(b'{"msg":"restricted location"}'),
        )
        success_payload = [
            [
                1_704_067_200_000,
                "42000.0",
                "42100.0",
                "41900.0",
                "42050.0",
                "12.5",
                1_704_067_259_999,
                "525000.0",
                42,
                "6.0",
                "252000.0",
                "0",
            ]
        ]
        client = BinanceKlineClient(
            base_url="https://api.binance.com",
            fallback_base_urls=["https://api.binance.us"],
            timeout_seconds=1,
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=[restricted_error, FakeHttpResponse(success_payload)],
        ) as urlopen:
            rows = client.fetch_klines(
                symbol="BTCUSDT",
                interval="1m",
                start_time_ms=1_704_067_200_000,
                end_time_ms=1_704_067_259_999,
            )

        requested_urls = [call.args[0].full_url for call in urlopen.call_args_list]
        self.assertEqual(rows, success_payload)
        self.assertEqual(len(requested_urls), 2)
        self.assertTrue(requested_urls[0].startswith("https://api.binance.com"))
        self.assertTrue(requested_urls[1].startswith("https://api.binance.us"))

    def test_sync_binance_klines_upserts_rows_and_records_run(self) -> None:
        with TemporaryDirectory() as directory:
            service = MarketDataService(client=FakeBinanceClient())
            result = service.sync_binance_klines(
                DataSyncSpec(
                    symbol="BTCUSDT",
                    interval="1m",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc),
                    db_path=f"{directory}/market.sqlite",
                    closed_only=False,
                )
            )
            coverage = service.coverage(db_path=f"{directory}/market.sqlite")
            aliased_coverage = service.coverage(
                db_path=f"{directory}/market.sqlite",
                exchange="binance",
                symbol="BTCUSDT",
            )
            rows = service.preview_klines(
                db_path=f"{directory}/market.sqlite",
                symbol="BTCUSDT",
                interval="1m",
                limit=10,
            )
            runs = service.list_sync_runs(db_path=f"{directory}/market.sqlite")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows_written, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(coverage[0]["rows"], 2)
        self.assertEqual(aliased_coverage[0]["exchange"], "binance_spot")
        self.assertEqual(aliased_coverage[0]["rows"], 2)
        self.assertEqual(runs[0]["status"], "completed")

    def test_sync_coinbase_klines_upserts_us_spot_rows(self) -> None:
        with TemporaryDirectory() as directory:
            service = MarketDataService(client=FakeBinanceClient(), coinbase_client=FakeCoinbaseClient())
            result = service.sync_binance_klines(
                DataSyncSpec(
                    exchange="coinbase_spot",
                    symbol="BTCUSD",
                    interval="1m",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
                    db_path=f"{directory}/market.sqlite",
                    closed_only=False,
                )
            )
            coverage = service.coverage(
                db_path=f"{directory}/market.sqlite",
                exchange="coinbase_spot",
                symbol="BTCUSD",
            )
            rows = service.preview_klines(
                db_path=f"{directory}/market.sqlite",
                exchange="coinbase_spot",
                symbol="BTCUSD",
                interval="1m",
                limit=10,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows_written, 2)
        self.assertEqual(coverage[0]["exchange"], "coinbase_spot")
        self.assertEqual(coverage[0]["rows"], 2)
        self.assertEqual(rows[-1]["open"], 42000.0)
        self.assertEqual(rows[-1]["quote_volume"], 42050.0 * 12.5)

    def test_sync_kraken_klines_upserts_us_spot_rows(self) -> None:
        with TemporaryDirectory() as directory:
            service = MarketDataService(
                client=FakeBinanceClient(),
                coinbase_client=FakeCoinbaseClient(),
                kraken_client=FakeKrakenClient(),
            )
            result = service.sync_binance_klines(
                DataSyncSpec(
                    exchange="kraken_spot",
                    symbol="BTCUSD",
                    interval="1m",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
                    db_path=f"{directory}/market.sqlite",
                    closed_only=False,
                )
            )
            coverage = service.coverage(
                db_path=f"{directory}/market.sqlite",
                exchange="kraken_spot",
                symbol="BTCUSD",
            )
            rows = service.preview_klines(
                db_path=f"{directory}/market.sqlite",
                exchange="kraken_spot",
                symbol="BTCUSD",
                interval="1m",
                limit=10,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows_written, 2)
        self.assertEqual(coverage[0]["exchange"], "kraken_spot")
        self.assertEqual(coverage[0]["rows"], 2)
        self.assertEqual(rows[-1]["trade_count"], 42)
        self.assertEqual(rows[-1]["quote_volume"], 42050.0 * 12.5)

    def test_btc_perpetual_artifact_coverage_fills_empty_sqlite_status(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_btc_data_status_report(root)
            service = MarketDataService(client=FakeBinanceClient(), repo_root=root)

            coverage = service.coverage(
                db_path=str(root / "market.sqlite"),
                exchange="binance_usdm",
                symbol="BTCUSDT",
            )
            database = service.database_status(db_path=str(root / "market.sqlite"))

        self.assertEqual([row["interval"] for row in coverage], ["5m", "1h"])
        self.assertEqual(coverage[0]["exchange"], "binance_usdm")
        self.assertEqual(coverage[0]["rows"], 248257)
        self.assertEqual(coverage[0]["start"], "2024-01-01T00:00:00+00:00")
        self.assertEqual(database["coverage"][1]["interval"], "1h")

    def test_btc_perpetual_artifact_coverage_does_not_pollute_spot_exchange(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_btc_data_status_report(root)
            service = MarketDataService(client=FakeBinanceClient(), repo_root=root)

            coverage = service.coverage(
                db_path=str(root / "market.sqlite"),
                exchange="binance_spot",
                symbol="BTCUSDT",
            )

        self.assertEqual(coverage, [])


if __name__ == "__main__":
    unittest.main()
