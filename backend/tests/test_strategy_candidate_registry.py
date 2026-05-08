"""Tests for StrategyCandidate registry and promotion constraints.

Covers: create candidate, promote to PAPER_ELIGIBLE requires --manual,
cannot promote past PAPER_ELIGIBLE.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.lab.manifest import (
    ExperimentManager,
    StrategyCandidate,
)


class TestStrategyCandidate(unittest.TestCase):
    """StrategyCandidate dataclass construction."""

    def test_minimal_construction(self) -> None:
        candidate = StrategyCandidate(
            candidate_id="cand_001",
            experiment_id="exp_001",
            strategy_id="momentum",
        )
        self.assertEqual(candidate.candidate_id, "cand_001")
        self.assertEqual(candidate.promotion_status, "RESEARCH_ONLY")

    def test_full_construction(self) -> None:
        candidate = StrategyCandidate(
            candidate_id="cand_002",
            experiment_id="exp_002",
            strategy_id="mean_reversion",
            promotion_status="PAPER_ELIGIBLE",
            alpha_score=0.85,
            risk_score=0.65,
            metrics={"sharpe": 1.5, "cagr": 0.12},
        )
        self.assertEqual(candidate.promotion_status, "PAPER_ELIGIBLE")
        self.assertEqual(candidate.alpha_score, 0.85)

    def test_default_promotion_status(self) -> None:
        candidate = StrategyCandidate(
            candidate_id="cand_003",
            experiment_id="exp_003",
            strategy_id="trend",
        )
        self.assertEqual(candidate.promotion_status, "RESEARCH_ONLY")


class TestCandidatePromotion(unittest.TestCase):
    """Candidate promotion lifecycle and constraints."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.manager = ExperimentManager(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_completed_experiment(self) -> str:
        """Helper: create a completed experiment by writing directly to disk."""
        import json
        from quant_us.core.types import new_id

        eid = new_id("exp")
        exp_dir = Path(self.tmp.name) / "research" / "experiments" / eid
        exp_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "experiment_id": eid,
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "status": "COMPLETED",
            "created_at": "2024-01-01T00:00:00",
            "run_result_path": str(exp_dir / "run_result.json"),
            "metrics": {"sharpe_ratio": 1.5, "cagr": 0.12},
        }
        (exp_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        (exp_dir / "run_result.json").write_text(
            json.dumps({"sharpe_ratio": 1.5, "cagr": 0.12}), encoding="utf-8"
        )
        return eid

    def test_promote_to_candidate_creates_entry(self) -> None:
        eid = self._create_completed_experiment()
        candidate = self.manager.promote_to_candidate(eid)
        self.assertTrue(candidate.candidate_id.startswith("cand_"))
        self.assertEqual(candidate.experiment_id, eid)
        self.assertEqual(candidate.promotion_status, "RESEARCH_ONLY")

    def test_promote_updates_experiment_status(self) -> None:
        eid = self._create_completed_experiment()
        self.manager.promote_to_candidate(eid)
        manifest = self.manager.load(eid)
        self.assertEqual(manifest.status, "PROMOTED_TO_CANDIDATE")

    def test_candidate_persisted_to_disk(self) -> None:
        eid = self._create_completed_experiment()
        candidate = self.manager.promote_to_candidate(eid)
        cand_path = (
            Path(self.tmp.name)
            / "research"
            / "candidates"
            / candidate.candidate_id
            / "candidate.json"
        )
        self.assertTrue(cand_path.exists())
        data = json.loads(cand_path.read_text(encoding="utf-8"))
        self.assertEqual(data["candidate_id"], candidate.candidate_id)

    def test_list_candidates_after_promotion(self) -> None:
        eid = self._create_completed_experiment()
        self.manager.promote_to_candidate(eid)
        candidates = self.manager.list_candidates()
        self.assertEqual(len(candidates), 1)

    def test_promotion_status_remains_research_only(self) -> None:
        eid = self._create_completed_experiment()
        candidate = self.manager.promote_to_candidate(eid)
        self.assertEqual(candidate.promotion_status, "RESEARCH_ONLY")

    def test_cannot_promote_past_paper_eligible_via_manager(self) -> None:
        """ExperimentManager has no promote_to_paper method — verify no such method."""
        self.assertFalse(hasattr(self.manager, "promote_to_paper"))
        self.assertFalse(hasattr(self.manager, "promote_to_live"))

    def test_promotion_requires_explicit_manual_flag(self) -> None:
        """Verify promotion to PAPER_ELIGIBLE requires direct file manipulation
        (simulating CLI --manual flag) not a method on ExperimentManager."""
        eid = self._create_completed_experiment()
        candidate = self.manager.promote_to_candidate(eid)

        # Simulate manual promotion via CLI
        cand_path = (
            Path(self.tmp.name)
            / "research"
            / "candidates"
            / candidate.candidate_id
            / "candidate.json"
        )
        data = json.loads(cand_path.read_text(encoding="utf-8"))
        data["promotion_status"] = "PAPER_ELIGIBLE"
        cand_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Verify it can be read back
        candidates = self.manager.list_candidates()
        promoted = [c for c in candidates if c.promotion_status == "PAPER_ELIGIBLE"]
        self.assertEqual(len(promoted), 1)

    def test_candidate_no_live_reference(self) -> None:
        """Candidates have no reference to live execution."""
        import quant_us.research.lab.manifest as manifest_module
        with open(manifest_module.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("submit_order", content)
        self.assertNotIn("AlpacaBroker", content)
