from __future__ import annotations

import unittest
from datetime import datetime

from backend.app.services.backtests import ResearchBacktestService


class BacktestServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ResearchBacktestService()
        self.base_range = {
            "start": datetime(2024, 1, 1),
            "end": datetime(2024, 2, 15),
        }

    def test_single_backtest_is_deterministic(self) -> None:
        first = self.service.run_single({"strategy_id": "trend_macd", **self.base_range})
        second = self.service.run_single({"strategy_id": "trend_macd", **self.base_range})

        self.assertEqual(first.summary, second.summary)
        self.assertEqual(len(first.chart["candles"]), len(second.chart["candles"]))
        self.assertGreater(first.summary["trade_count"], 0)

    def test_portfolio_backtest_produces_chart_and_weights(self) -> None:
        result = self.service.run_portfolio(
            {
                **self.base_range,
                "weights": [
                    {"strategy_id": "trend_macd", "weight": 0.4},
                    {"strategy_id": "reversion_rsi", "weight": 0.2},
                    {"strategy_id": "donchian_breakout", "weight": 0.4},
                ],
            }
        )

        self.assertGreater(result.summary["trade_count"], 0)
        self.assertEqual(len(result.chart["candles"]), len(result.chart["equity"]))
        self.assertTrue(result.latest_weights)


if __name__ == "__main__":
    unittest.main()
