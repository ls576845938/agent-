"""Tests for ResearchScorecard and ResearchScorecardBuilder.

Covers: compute all metrics, rank candidates, markdown output.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.lab.scorecard import (
    ResearchScorecard,
    ResearchScorecardBuilder,
)


class TestResearchScorecard(unittest.TestCase):
    """ResearchScorecard dataclass construction."""

    def test_default_values(self) -> None:
        sc = ResearchScorecard(candidate_id="cand_001")
        self.assertEqual(sc.candidate_id, "cand_001")
        self.assertEqual(sc.cagr, 0.0)
        self.assertEqual(sc.sharpe, 0.0)
        self.assertEqual(sc.overfit_risk, "UNKNOWN")

    def test_full_construction(self) -> None:
        sc = ResearchScorecard(
            candidate_id="cand_002",
            cagr=0.15,
            sharpe=1.8,
            sortino=2.1,
            max_drawdown=0.12,
            win_rate=0.55,
            trade_count=100,
            overfit_risk="LOW",
        )
        self.assertAlmostEqual(sc.cagr, 0.15)
        self.assertEqual(sc.overfit_risk, "LOW")
        self.assertEqual(sc.trade_count, 100)


class TestResearchScorecardBuilder(unittest.TestCase):
    """Scorecard building and ranking."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.builder = ResearchScorecardBuilder(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_candidate(self, cid: str, metrics: dict | None = None) -> None:
        if metrics is None:
            metrics = {"sharpe_ratio": 1.5, "cagr": 0.12, "max_drawdown_pct": 0.10}
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cid
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps({"candidate_id": cid, "metrics": metrics}, indent=2),
            encoding="utf-8",
        )

    def test_build_missing_candidate_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.builder.build("cand_nonexistent")

    def test_build_returns_scorecard(self) -> None:
        self._write_candidate("cand_001")
        sc = self.builder.build("cand_001")
        self.assertIsInstance(sc, ResearchScorecard)
        self.assertEqual(sc.candidate_id, "cand_001")

    def test_build_with_custom_metrics(self) -> None:
        self._write_candidate("cand_002", {
            "sharpe_ratio": 2.0,
            "total_return_pct": 0.25,
            "max_drawdown_pct": 0.08,
            "win_rate": 0.60,
            "trade_count": 50,
        })
        sc = self.builder.build("cand_002")
        self.assertAlmostEqual(sc.cagr, 0.25)
        self.assertAlmostEqual(sc.sharpe, 2.0)
        self.assertAlmostEqual(sc.max_drawdown, 0.08)

    def test_build_handles_zero_drawdown(self) -> None:
        self._write_candidate("cand_003", {
            "sharpe_ratio": 0.5,
            "max_drawdown_pct": 0.0,
        })
        sc = self.builder.build("cand_003")
        self.assertEqual(sc.max_drawdown, 0.0)

    def test_rank_candidates_empty_list(self) -> None:
        result = self.builder.rank_candidates([])
        self.assertEqual(result, [])

    def test_rank_candidates_single(self) -> None:
        self._write_candidate("cand_001", {
            "sharpe_ratio": 1.5,
            "max_drawdown_pct": 0.10,
        })
        result = self.builder.rank_candidates(["cand_001"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "cand_001")

    def test_rank_candidates_ordered_by_robustness(self) -> None:
        self._write_candidate("cand_better", {
            "sharpe_ratio": 2.0,
            "max_drawdown_pct": 0.05,
        })
        self._write_candidate("cand_worse", {
            "sharpe_ratio": 0.5,
            "max_drawdown_pct": 0.30,
        })
        result = self.builder.rank_candidates(["cand_better", "cand_worse"])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "cand_better")

    def test_rank_skips_missing_candidates(self) -> None:
        self._write_candidate("cand_001")
        result = self.builder.rank_candidates(["cand_001", "cand_nonexistent"])
        self.assertEqual(len(result), 1)

    def test_to_markdown_contains_all_metrics(self) -> None:
        sc = ResearchScorecard(
            candidate_id="cand_001",
            cagr=0.15,
            sharpe=1.8,
            sortino=2.1,
            calmar=1.5,
            max_drawdown=0.12,
            win_rate=0.55,
            profit_factor=1.8,
            trade_count=100,
            overfit_risk="LOW",
        )
        md = self.builder.to_markdown(sc)
        self.assertIn("Research Scorecard: cand_001", md)
        self.assertIn("CAGR", md)
        self.assertIn("Sharpe", md)
        self.assertIn("Max Drawdown", md)
        self.assertIn("Overfit Risk", md)
        self.assertIn("LOW", md)
