from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.services.backtests import ResearchBacktestService
from backend.app.services.research_gate import ResearchPromotionGateService
from quant_us.research.experiments import ExperimentRegistry


class ResearchPromotionGateTests(unittest.TestCase):
    def test_core_gate_returns_decision_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            service = ResearchPromotionGateService(
                research_service=ResearchBacktestService(),
                manifest_root=Path(directory) / "manifests",
                experiment_root=Path(directory) / "experiments",
            )
            result = service.evaluate(
                {
                    "mode": "portfolio",
                    "source": "fixture",
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "start": datetime(2024, 1, 1),
                    "end": datetime(2024, 2, 15),
                    "weights": [
                        {"strategy_id": "trend_macd", "weight": 0.5},
                        {"strategy_id": "reversion_rsi", "weight": 0.25},
                        {"strategy_id": "donchian_breakout", "weight": 0.25},
                    ],
                    "include_deep_checks": False,
                    "persist_manifest": True,
                    "register_experiment": True,
                    "experiment_name": "btc_portfolio_gate",
                }
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["selected_priority"], "研究准入与实验晋级门")
            self.assertIn(result["decision"], {"pass", "warn", "fail"})
            self.assertGreaterEqual(len(result["gates"]), 4)
            self.assertTrue(Path(result["manifest_path"]).exists())
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["manifest_id"], result["manifest_id"])
            self.assertIn("data_version", manifest)
            self.assertTrue(result["strategy_version"].startswith("strategy_"))
            self.assertEqual(result["experiment_record"]["experiment_name"], "btc_portfolio_gate")
            self.assertTrue(Path(result["experiment_record"]["registry_path"]).exists())
            records = ExperimentRegistry(Path(directory) / "experiments").load_records("btc_portfolio_gate")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["spec"]["promotion_manifest_id"], result["manifest_id"])
            self.assertEqual(records[0]["spec"]["strategy_version"], result["strategy_version"])


if __name__ == "__main__":
    unittest.main()
