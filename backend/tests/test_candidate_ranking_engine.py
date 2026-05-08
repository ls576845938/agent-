"""Tests for CandidateRankingEngine.

Covers: ranking logic, score breakdowns.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.automation.ranking import CandidateRankingEngine


class TestCandidateRankingEngine(unittest.TestCase):
    """Ranking engine tests."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.engine = CandidateRankingEngine(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_candidate(self, cid: str, metrics: dict | None = None) -> None:
        if metrics is None:
            metrics = {
                "sharpe_ratio": 1.5,
                "cagr": 0.12,
                "max_drawdown_pct": 0.10,
                "turnover": 0.2,
                "trade_count": 50,
                "walk_forward_pass_rate": 0.8,
                "oos_degradation": 0.1,
                "cost_sensitivity": 0.1,
                "param_count": 4,
            }
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cid
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps({"candidate_id": cid, "metrics": metrics}, indent=2),
            encoding="utf-8",
        )

    def test_rank_empty_list(self) -> None:
        result = self.engine.rank([])
        self.assertEqual(result, [])

    def test_rank_single_candidate(self) -> None:
        self._write_candidate("cand_001")
        result = self.engine.rank(["cand_001"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "cand_001")

    def test_rank_better_candidate_first(self) -> None:
        # Better candidate has higher Sharpe and lower drawdown
        self._write_candidate("cand_good", {
            "sharpe_ratio": 2.5,
            "cagr": 0.20,
            "max_drawdown_pct": 0.05,
            "turnover": 0.1,
            "trade_count": 100,
            "walk_forward_pass_rate": 0.9,
            "oos_degradation": 0.05,
            "cost_sensitivity": 0.05,
            "param_count": 3,
        })
        self._write_candidate("cand_bad", {
            "sharpe_ratio": 0.3,
            "cagr": 0.02,
            "max_drawdown_pct": 0.40,
            "turnover": 0.8,
            "trade_count": 5,
            "walk_forward_pass_rate": 0.2,
            "oos_degradation": 0.6,
            "cost_sensitivity": 0.5,
            "param_count": 15,
        })
        result = self.engine.rank(["cand_good", "cand_bad"])
        self.assertEqual(result[0][0], "cand_good")
        self.assertEqual(result[1][0], "cand_bad")

    def test_score_breakdown_contains_all_keys(self) -> None:
        self._write_candidate("cand_001")
        breakdown = self.engine.score_breakdown("cand_001")
        expected_keys = [
            "performance", "risk", "stability", "cost_robustness",
            "regime_robustness", "simplicity_bonus", "turnover_penalty",
            "overfit_penalty",
        ]
        for key in expected_keys:
            self.assertIn(key, breakdown)

    def test_score_breakdown_missing_candidate_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.engine.score_breakdown("cand_nonexistent")

    def test_rank_skips_missing_candidates(self) -> None:
        self._write_candidate("cand_001")
        result = self.engine.rank(["cand_001", "cand_nonexistent"])
        self.assertEqual(len(result), 1)

    def test_high_sharpe_scores_higher_performance(self) -> None:
        self._write_candidate("high", {
            "sharpe_ratio": 3.0,
            "cagr": 0.30,
            "max_drawdown_pct": 0.05,
        })
        self._write_candidate("low", {
            "sharpe_ratio": 0.5,
            "cagr": 0.05,
            "max_drawdown_pct": 0.05,
        })
        high_breakdown = self.engine.score_breakdown("high")
        low_breakdown = self.engine.score_breakdown("low")
        self.assertGreater(
            high_breakdown["performance"],
            low_breakdown["performance"],
        )

    def test_risk_score_decreases_with_drawdown(self) -> None:
        self._write_candidate("low_dd", {
            "sharpe_ratio": 1.0,
            "max_drawdown_pct": 0.05,
        })
        self._write_candidate("high_dd", {
            "sharpe_ratio": 1.0,
            "max_drawdown_pct": 0.40,
        })
        low_dd = self.engine.score_breakdown("low_dd")
        high_dd = self.engine.score_breakdown("high_dd")
        self.assertGreater(low_dd["risk"], high_dd["risk"])
