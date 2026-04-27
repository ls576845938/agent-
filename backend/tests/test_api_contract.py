from __future__ import annotations

import importlib.util
import unittest
from tempfile import TemporaryDirectory


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


if __name__ == "__main__":
    unittest.main()
