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
            "rebalance_buffer_pct": 0.0,
            "min_holding_bars": 0,
            "cost_aware_filter": False,
        }

    def test_single_backtest_is_deterministic(self) -> None:
        first = self.service.run_single({"strategy_id": "trend_macd", **self.base_range})
        second = self.service.run_single({"strategy_id": "trend_macd", **self.base_range})

        self.assertEqual(first.summary, second.summary)
        self.assertEqual(len(first.chart["candles"]), len(second.chart["candles"]))
        self.assertGreater(first.summary["trade_count"], 0)
        self.assertIn("report_sections", first.diagnostics)
        self.assertIn("drawdown_periods", first.diagnostics)
        self.assertIn("monthly_returns", first.diagnostics)
        self.assertIn("execution", first.diagnostics)
        self.assertEqual(first.diagnostics["report_sections"][0]["priority"], 1)

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
        self.assertEqual(len(result.chart["turnover"]), len(result.chart["equity"]))
        self.assertTrue(result.latest_weights)
        self.assertGreaterEqual(result.diagnostics["execution"]["orders"], 1)

    def test_strategy_optimization_returns_ranked_oos_candidates(self) -> None:
        result = self.service.optimize_strategy(
            {
                "strategy_id": "trend_macd",
                **self.base_range,
                "max_candidates": 1,
            }
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["framework"][0]["status"], "selected")
        self.assertEqual(result["framework"][0]["priority"], 1)
        self.assertLessEqual(len(result["candidates"]), 1)
        self.assertIsNotNone(result["best"])
        self.assertIn("validation", result["best"])
        self.assertGreater(result["split"]["train_rows"], 0)
        self.assertGreater(result["split"]["validation_rows"], 0)

    def test_cost_stress_returns_survival_scenarios(self) -> None:
        result = self.service.run_cost_stress(
            {
                "strategy_id": "trend_macd",
                **self.base_range,
                "max_scenarios": 2,
            }
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["selected_priority"], "交易成本压力测试")
        self.assertEqual(len(result["scenarios"]), 2)
        self.assertIsNotNone(result["baseline"])
        self.assertIn("survives", result["scenarios"][0])
        self.assertIn("recommendations", result)

    def test_walk_forward_returns_oos_windows_and_regimes(self) -> None:
        result = self.service.run_walk_forward(
            {
                "strategy_id": "trend_macd",
                **self.base_range,
                "windows": 2,
                "max_candidates": 1,
            }
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["selected_priority"], "Walk-forward 与市场状态切片")
        self.assertGreaterEqual(len(result["windows"]), 1)
        self.assertIn("validation", result["windows"][0])
        self.assertIn("stability", result)
        self.assertIn("pass_rate_pct", result["stability"])
        self.assertGreaterEqual(len(result["regimes"]), 1)
        self.assertIn("recommendations", result)

    def test_portfolio_optimization_returns_weight_and_risk_budget(self) -> None:
        result = self.service.optimize_portfolio(
            {
                **self.base_range,
                "weights": [
                    {"strategy_id": "trend_macd", "weight": 0.5},
                    {"strategy_id": "reversion_rsi", "weight": 0.25},
                    {"strategy_id": "donchian_breakout", "weight": 0.25},
                ],
                "max_single_weight": 0.6,
                "correlation_penalty": 0.75,
            }
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["selected_priority"], "组合层相关性与资金分配")
        self.assertAlmostEqual(sum(result["optimized_weights"].values()), 1.0, places=4)
        self.assertIn("optimized_summary", result)
        self.assertIn("risk_contributions", result["risk_budget"])
        self.assertGreaterEqual(len(result["strategy_allocations"]), 1)
        self.assertIn("recommendations", result)


if __name__ == "__main__":
    unittest.main()
