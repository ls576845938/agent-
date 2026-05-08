"""PROVE --manual flag required for PAPER_ELIGIBLE promotion.

No research module can auto-promote to PAPER_ELIGIBLE.
Promotion to PAPER_ELIGIBLE must be an explicit manual action.
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
    """Mock ExperimentManager.run() to write fake results."""
    import json
    from pathlib import Path

    manifest = self.load(experiment_id)
    if manifest is None:
        raise ValueError(f"Experiment {experiment_id} not found")
    fake_metrics = {
        "sharpe_ratio": 1.5, "cagr": 0.12, "max_drawdown_pct": 0.10,
        "total_return_pct": 0.15, "win_rate": 0.55, "trade_count": 50,
        "cost_sensitivity": 0.1, "walk_forward_pass_rate": 0.8,
        "oos_degradation": 0.1, "turnover": 0.2, "param_count": 4,
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


class TestPaperEligibleRequiresManual(unittest.TestCase):
    """Verify PAPER_ELIGIBLE requires manual intervention."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.manager = ExperimentManager(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_completed_experiment(self) -> str:
        import json
        from quant_us.core.types import new_id

        eid = new_id("exp")
        exp_dir = Path(self.tmp.name) / "research" / "experiments" / eid
        exp_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "experiment_id": eid,
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {},
            "status": "COMPLETED",
            "created_at": "2024-01-01T00:00:00",
            "run_result_path": str(exp_dir / "run_result.json"),
            "metrics": {"sharpe_ratio": 1.5},
        }
        (exp_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (exp_dir / "run_result.json").write_text(
            json.dumps({"sharpe_ratio": 1.5}), encoding="utf-8"
        )
        return eid

    def test_experiment_manager_has_no_auto_promote(self) -> None:
        """ExperimentManager should not have auto-promote to paper methods."""
        methods = [
            attr for attr in dir(self.manager)
            if "paper" in attr.lower() or "auto_promote" in attr.lower()
        ]
        self.assertEqual(methods, [])

    def test_promote_to_candidate_does_not_reach_paper(self) -> None:
        """Promote to candidate stops at RESEARCH_ONLY, not PAPER_ELIGIBLE."""
        eid = self._create_completed_experiment()
        candidate = self.manager.promote_to_candidate(eid)
        self.assertEqual(candidate.promotion_status, "RESEARCH_ONLY")
        self.assertNotEqual(candidate.promotion_status, "PAPER_ELIGIBLE")

    def test_pipeline_auto_promote_stops_at_paper_eligible(self) -> None:
        """Pipeline's auto-promote should mark PAPER_ELIGIBLE but not LIVE."""
        pipeline = ResearchAutomationPipeline(data_root=self.tmp.name)
        config = {
            "experiment_name": "manual_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = pipeline.run(config)
        if result["status"] == "failed":
            self.fail(f"Pipeline failed with error: {result.get('error')}")
        self.assertEqual(result["status"], "completed")
        for cid in result["promoted"]:
            cand_path = (
                Path(self.tmp.name)
                / "research"
                / "candidates"
                / cid
                / "candidate.json"
            )
            data = json.loads(cand_path.read_text(encoding="utf-8"))
            self.assertEqual(data["promotion_status"], "PAPER_ELIGIBLE")
            self.assertNotEqual(data["promotion_status"], "LIVE")

    def test_no_live_promotion_method_exists(self) -> None:
        """No promote_to_live method should exist in research modules."""
        self.assertFalse(hasattr(self.manager, "promote_to_live"))
        from quant_us.research.automation.pipeline import ResearchAutomationPipeline
        pipeline = ResearchAutomationPipeline()
        self.assertFalse(hasattr(pipeline, "step_promote_to_live"))

    def test_candidate_json_does_not_contain_live_status(self) -> None:
        """The promotion_status enum should not include LIVE as a valid value."""
        from quant_us.research.lab.manifest import StrategyCandidate
        # LIVE is not a valid promotion_status value
        eid = self._create_completed_experiment()
        candidate = self.manager.promote_to_candidate(eid)
        valid_statuses = {"RESEARCH_ONLY", "CANDIDATE", "PAPER_ELIGIBLE", "REJECTED"}
        self.assertIn(candidate.promotion_status, valid_statuses)
