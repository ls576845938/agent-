from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill


FASTAPI_AVAILABLE = bool(importlib.util.find_spec("fastapi"))


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is not installed in the current environment")
class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.api.app_factory import create_app

        self.client = TestClient(create_app())

    def test_health_endpoint(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")

    def test_metrics_endpoint(self) -> None:
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("quantstation_up 1", response.text)

    def test_single_backtest_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/single",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIn("summary", payload)

    def test_strategy_optimization_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/optimize",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "max_candidates": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["framework"][0]["status"], "selected")
        self.assertLessEqual(len(payload["candidates"]), 1)
        self.assertIsNotNone(payload["best"])

    def test_cost_stress_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/cost-stress",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "max_scenarios": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "交易成本压力测试")
        self.assertEqual(len(payload["scenarios"]), 1)
        self.assertIsNotNone(payload["baseline"])

    def test_walk_forward_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/walk-forward",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "windows": 2,
                "max_candidates": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "Walk-forward 与市场状态切片")
        self.assertGreaterEqual(len(payload["windows"]), 1)
        self.assertIn("pass_rate_pct", payload["stability"])

    def test_portfolio_optimization_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/portfolio-optimize",
            json={
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "weights": [
                    {"strategy_id": "trend_macd", "weight": 0.5},
                    {"strategy_id": "reversion_rsi", "weight": 0.25},
                    {"strategy_id": "donchian_breakout", "weight": 0.25},
                ],
                "max_single_weight": 0.6,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "组合层相关性与资金分配")
        self.assertIn("optimized_weights", payload)
        self.assertIn("risk_budget", payload)

    def test_data_database_endpoint_initializes_sqlite(self) -> None:
        with TemporaryDirectory() as directory:
            response = self.client.get(
                "/api/data/database",
                params={"db_path": f"{directory}/market.sqlite"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["initialized"])
        self.assertIn("market.sqlite", payload["db_path"])

    def test_data_quality_endpoint_returns_versioned_gate(self) -> None:
        response = self.client.post(
            "/api/data/quality",
            json={
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-10T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "数据质量与特征版本治理")
        self.assertTrue(payload["is_usable"])
        self.assertIn("data_version", payload)

    def test_us_event_backtest_endpoint_uses_local_data_lake(self) -> None:
        with TemporaryDirectory() as directory:
            timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
            price = 100.0
            rows = []
            while len(rows) < 80:
                if timestamp.weekday() < 5:
                    price *= 1.004
                    rows.append(
                        {
                            "timestamp": timestamp,
                            "symbol": "AAPL",
                            "open": price * 0.99,
                            "high": price * 1.01,
                            "low": price * 0.98,
                            "close": price,
                            "volume": 10_000_000,
                        }
                    )
                timestamp += timedelta(days=1)
            service = DataLakeService(DataLakeConfig(data_root=Path(directory)))
            cleaned = BarCleaner().clean(pd.DataFrame(rows), symbol="AAPL", source="unit").frame
            service.cleaned_store.write_bars(cleaned, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="AAPL")
            msft_rows = [{**row, "symbol": "MSFT", "close": row["close"] * 1.01} for row in rows]
            cleaned_msft = BarCleaner().clean(pd.DataFrame(msft_rows), symbol="MSFT", source="unit").frame
            service.cleaned_store.write_bars(cleaned_msft, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="MSFT")

            response = self.client.post(
                "/api/us/backtests/event",
                json={
                    "symbol": "AAPL",
                    "symbols": ["AAPL", "MSFT"],
                    "bar_size": "1d",
                    "strategy_params": {"lookback_bars": 5, "entry_threshold": 0.01},
                    "default_strategy_weight": 0.12,
                    "cash_reserve_weight": 0.10,
                    "min_trade_notional": 50.0,
                    "min_weight_change": 0.001,
                    "start": "2024-01-01T00:00:00Z",
                    "end": "2024-06-30T00:00:00Z",
                    "data_root": directory,
                    "auto_sync": False,
                    "corporate_actions": [
                        {"symbol": "AAPL", "action_type": "split", "ex_date": "2024-03-01", "ratio": 2.0}
                    ],
                    "earnings_events": [
                        {"symbol": "AAPL", "event_date": "2024-04-01", "source": "unit"}
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertGreater(payload["fill_count"], 0)
        self.assertEqual(payload["diagnostics"]["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(payload["diagnostics"]["strategy_params"]["lookback_bars"], 5)
        self.assertEqual(payload["diagnostics"]["backtest_parameters"]["cash_reserve_weight"], 0.10)
        self.assertEqual(payload["diagnostics"]["data_filters"]["corporate_action_count"], 1)
        self.assertGreater(payload["diagnostics"]["data_filters"]["earnings_blackout_removed_rows"], 0)

    def test_us_reconcile_endpoint_checks_local_ledger(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = JsonlLedgerStore(directory)
            ledger.append_fill(
                Fill(
                    order_id="order_1",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    quantity=1.0,
                    price=100.0,
                    commission=0.0,
                    filled_at=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
                )
            )
            response = self.client.post(
                "/api/us/reconcile",
                json={"ledger_dir": directory},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "clean")
        self.assertEqual(payload["break_count"], 0)


if __name__ == "__main__":
    unittest.main()
