from __future__ import annotations

import json

from quant_us.research.automation.ranking import CandidateRankingEngine


def test_candidate_ranking_penalizes_poor_candidate_quality(monkeypatch, tmp_path) -> None:
    candidate_id = "cand_quality"
    candidate_dir = tmp_path / "research" / "candidates" / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "candidate.json").write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "metrics": {
                    "turnover": 0.2,
                },
                "candidate_quality": {
                    "quality_score": 0.35,
                    "eligible": False,
                    "warnings": ["turnover_pressure", "capacity_pressure"],
                    "rejection_reasons": ["turnover_too_high"],
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeScorecard:
        sharpe = 1.0
        cagr = 0.12
        max_drawdown = 0.10
        walk_forward_pass_rate = 0.7
        oos_degradation = 0.15
        cost_sensitivity = 0.1
        overfit_risk = "LOW"

    monkeypatch.setattr(
        "quant_us.research.lab.scorecard.ResearchScorecardBuilder.build",
        lambda self, cid: FakeScorecard(),
    )

    breakdown = CandidateRankingEngine(data_root=str(tmp_path)).score_breakdown(candidate_id)

    assert breakdown["candidate_quality_overlay"] < 0.0
