"""Tests for ResearchAutomationPipeline.

Covers: full pipeline run, ranking, promotion stops at PAPER_ELIGIBLE.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from quant_us.research.automation.pipeline import ResearchAutomationPipeline
from quant_us.research.lab.manifest import ExperimentManager


def _fake_manager_run(self, experiment_id: str) -> dict:
    """Mock ExperimentManager.run() to write fake results instead of real backtests.

    This avoids the need for real backtest infrastructure in unit tests.
    """
    import json
    from datetime import datetime

    manifest = self.load(experiment_id)
    if manifest is None:
        raise ValueError(f"Experiment {experiment_id} not found")

    fake_metrics = {
        "sharpe_ratio": 1.5,
        "cagr": 0.12,
        "max_drawdown_pct": 0.10,
        "total_return_pct": 0.15,
        "win_rate": 0.55,
        "trade_count": 50,
        "cost_sensitivity": 0.1,
        "walk_forward_pass_rate": 0.8,
        "oos_degradation": 0.1,
        "turnover": 0.2,
        "param_count": 4,
    }

    exp_dir = Path(self.data_root) / "research" / "experiments" / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    result_path = exp_dir / "run_result.json"
    result_path.write_text(json.dumps(fake_metrics, default=str), encoding="utf-8")

    manifest.status = "COMPLETED"
    manifest.run_result_path = str(result_path)
    manifest.metrics = fake_metrics
    self._save_manifest(manifest)
    return fake_metrics


class TestResearchAutomationPipeline(unittest.TestCase):
    """Pipeline orchestration tests."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.pipeline = ResearchAutomationPipeline(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pipeline_initialization(self) -> None:
        self.assertIsNotNone(self.pipeline)

    def test_run_with_minimal_config(self) -> None:
        """Pipeline run with minimal config should not crash."""
        config = {
            "experiment_name": "test_pipeline",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "data_version": "v1",
            "feature_version": "v1",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        if result["status"] == "failed":
            self.fail(f"Pipeline failed with error: {result.get('error')}")
        self.assertEqual(result["status"], "completed")
        self.assertGreater(len(result["experiment_ids"]), 0)

    def test_pipeline_creates_experiments(self) -> None:
        config = {
            "experiment_name": "test_exp",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        for eid in result["experiment_ids"]:
            mgr = ExperimentManager(data_root=self.tmp.name)
            manifest = mgr.load(eid)
            self.assertIsNotNone(manifest)

    def test_pipeline_with_param_grid(self) -> None:
        config = {
            "experiment_name": "grid_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "param_grid": {"lookback": [10, 20], "entry_z": [1.5, 2.0]},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        if result["status"] == "failed":
            self.fail(f"Pipeline failed with error: {result.get('error')}")
        # At least the base experiment + walk-forward + cost stress + regime split
        self.assertGreater(len(result["experiment_ids"]), 5)

    def test_step_evaluate_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.pipeline.step_evaluate("exp_nonexistent")

    def test_step_rank_returns_list(self) -> None:
        config = {
            "experiment_name": "rank_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            self.pipeline.run(config)
        ranked = self.pipeline.step_rank()
        self.assertIsInstance(ranked, list)

    def test_step_promote_manual_only(self) -> None:
        """Pipeline auto-promotes to PAPER_ELIGIBLE. step_promote works on RESEARCH_ONLY candidates."""
        # Create a RESEARCH_ONLY candidate manually (not via pipeline)
        import json
        cand_id = "cand_manual_test"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        candidate_data = {
            "candidate_id": cand_id,
            "experiment_id": "exp_001",
            "strategy_id": "momentum",
            "promotion_status": "RESEARCH_ONLY",
            "metrics": {"sharpe_ratio": 1.5},
        }
        (cand_dir / "candidate.json").write_text(
            json.dumps(candidate_data), encoding="utf-8"
        )
        # Now promote manually
        candidate = self.pipeline.step_promote(cand_id)
        self.assertEqual(candidate.promotion_status, "PAPER_ELIGIBLE")

    def test_cannot_promote_unknown_candidate(self) -> None:
        with self.assertRaises(ValueError):
            self.pipeline.step_promote("cand_nonexistent")

    def test_cannot_promote_past_paper_eligible(self) -> None:
        """Cannot promote a candidate that is already PAPER_ELIGIBLE."""
        import json
        cand_id = "cand_already_promoted"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        candidate_data = {
            "candidate_id": cand_id,
            "experiment_id": "exp_001",
            "strategy_id": "momentum",
            "promotion_status": "PAPER_ELIGIBLE",
            "metrics": {"sharpe_ratio": 1.5},
        }
        (cand_dir / "candidate.json").write_text(
            json.dumps(candidate_data), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            self.pipeline.step_promote(cand_id)

    def test_pipeline_result_has_all_keys(self) -> None:
        config = {
            "experiment_name": "keys_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        expected_keys = [
            "pipeline_id", "experiment_ids", "candidate_ids",
            "ranked_candidates", "overfit_reports", "dossier_paths",
            "promoted", "status",
        ]
        for key in expected_keys:
            self.assertIn(key, result)
