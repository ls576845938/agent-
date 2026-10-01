"""Tests for ResearchDossierBuilder.

Covers: dossier generation, recommendations.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.automation.dossier import ResearchDossierBuilder


class TestResearchDossierBuilder(unittest.TestCase):
    """Dossier generation tests."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.builder = ResearchDossierBuilder(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_candidate(self, cid: str, status: str = "RESEARCH_ONLY", metrics: dict | None = None) -> None:
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cid
        cand_dir.mkdir(parents=True, exist_ok=True)
        if metrics is None:
            metrics = {
                "sharpe_ratio": 1.5,
                "cagr": 0.12,
                "max_drawdown_pct": 0.10,
                "win_rate": 0.55,
                "trade_count": 50,
                "cost_sensitivity": 0.1,
                "walk_forward_pass_rate": 0.8,
                "oos_degradation": 0.1,
            }
        data = {
            "candidate_id": cid,
            "experiment_id": "exp_001",
            "strategy_id": "momentum",
            "promotion_status": status,
            "params_hash": "abc123",
            "metrics": metrics,
        }
        (cand_dir / "candidate.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def test_build_missing_candidate_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.builder.build("cand_nonexistent")

    def test_build_returns_markdown(self) -> None:
        self._write_candidate("cand_001")
        md = self.builder.build("cand_001")
        self.assertIsInstance(md, str)
        self.assertGreater(len(md), 100)

    def test_dossier_contains_sections(self) -> None:
        self._write_candidate("cand_002")
        md = self.builder.build("cand_002")
        required_sections = [
            "Research Dossier",
            "Strategy Description",
            "Parameters",
            "Backtest Results",
            "Risk Assessment",
            "Recommendation",
        ]
        for section in required_sections:
            self.assertIn(section, md)

    def test_dossier_contains_metrics(self) -> None:
        self._write_candidate("cand_003")
        md = self.builder.build("cand_003")
        self.assertIn("Sharpe", md)
        self.assertIn("CAGR", md)
        self.assertIn("Max Drawdown", md)

    def test_recommend_paper_eligible(self) -> None:
        self._write_candidate("cand_good")
        rec = self.builder.recommend("cand_good")
        self.assertIn(rec, ["PAPER_ELIGIBLE", "PORTFOLIO_CANDIDATE", "RESEARCH_MORE"])

    def test_recommend_reject_for_overfit(self) -> None:
        self._write_candidate("cand_bad", metrics={
            "sharpe_ratio": 0.0,
            "cagr": 0.0,
        })
        rec = self.builder.recommend("cand_bad")
        self.assertEqual(rec, "REJECT")

    def test_recommend_research_more_low_sharpe(self) -> None:
        self._write_candidate("cand_low_sharpe", metrics={
            "sharpe_ratio": 0.2,
            "max_drawdown_pct": 0.10,
        })
        rec = self.builder.recommend("cand_low_sharpe")
        self.assertEqual(rec, "RESEARCH_MORE")
