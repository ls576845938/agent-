from __future__ import annotations

import json
from pathlib import Path

from quant_us.research.strategy_manifest import StrategyManifestManager


def test_strategy_manifest_creation_populates_research_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    candidate_id = "cand_contract"
    experiment_id = "exp_contract"
    data_version = "qs-yfinance-SPY-1d-contract"

    candidate_dir = tmp_path / "research" / "candidates" / candidate_id
    experiment_dir = tmp_path / "research" / "experiments" / experiment_id
    backtest_dir = tmp_path / "research" / "backtests" / candidate_id
    scorecard_dir = tmp_path / "research" / "scorecards"
    walk_forward_dir = tmp_path / "research" / "walk_forward" / candidate_id
    cost_stress_dir = tmp_path / "research" / "cost_stress" / candidate_id
    manifests_dir = tmp_path / "manifests"

    candidate_dir.mkdir(parents=True, exist_ok=True)
    experiment_dir.mkdir(parents=True, exist_ok=True)
    backtest_dir.mkdir(parents=True, exist_ok=True)
    scorecard_dir.mkdir(parents=True, exist_ok=True)
    walk_forward_dir.mkdir(parents=True, exist_ok=True)
    cost_stress_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    (candidate_dir / "candidate.json").write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "experiment_id": experiment_id,
                "data_version": data_version,
                "backtest_manifest_path": f"research/backtests/{candidate_id}/run_manifest.json",
                "walk_forward_result_path": f"research/walk_forward/{candidate_id}/result.json",
                "cost_stress_result_path": f"research/cost_stress/{candidate_id}/result.json",
                "metrics": {
                    "trial_id": "trial_017",
                    "trial_count": 12,
                    "pbo": 0.08,
                    "dsr": 0.91,
                    "estimated_capacity_usd": 2500000.0,
                    "capacity_warning": "OK",
                    "turnover": 0.23,
                    "annual_turnover_pct": 185.0,
                    "avg_holding_period": 6.5,
                    "avg_exposure": 0.74,
                    "max_single_symbol_exposure_pct": 18.0,
                    "failure_conditions": ["oos_decay_gt_30pct"],
                },
                "invalidation_conditions": ["max_drawdown_gt_15pct"],
                "delisting_policy": "remove_and_manual_review",
            }
        ),
        encoding="utf-8",
    )
    (experiment_dir / "manifest.json").write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "strategy_family": "momentum",
                "symbols": ["SPY", "QQQ"],
                "timeframe": "1d",
                "start_date": "2023-01-01",
                "end_date": "2024-12-31",
                "train_period": "2023-01-01/2024-06-30",
                "test_period": "2024-07-01/2024-12-31",
                "data_version": data_version,
                "cost_model": "default",
                "slippage_model": "default",
                "params": {
                    "purge_bars": 5,
                    "embargo_bars": 2,
                },
                "param_grid": {
                    "lookback": [10, 20, 40],
                    "threshold": [0.1, 0.2, 0.3, 0.4],
                },
            }
        ),
        encoding="utf-8",
    )
    (backtest_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "data_version": data_version,
                "cost_model": "default",
                "commission_model": "commission_pct",
                "commission_rate": 0.0001,
                "slippage_model": "bps_1",
                "slippage_bps": 1.0,
                "execution": {"annual_turnover_pct": 190.0},
                "exposure": {"max_gross_exposure_pct": 95.0},
            }
        ),
        encoding="utf-8",
    )
    (scorecard_dir / f"{candidate_id}.json").write_text(
        json.dumps(
            {
                "turnover": 0.22,
                "avg_holding_period": 6.0,
                "avg_exposure": 0.71,
                "trade_count": 48,
                "sector_exposures": {"Tech": 0.62, "ETF": 0.38},
            }
        ),
        encoding="utf-8",
    )
    (walk_forward_dir / "result.json").write_text(
        json.dumps({"recommended_holding_period": "5d"}),
        encoding="utf-8",
    )
    (cost_stress_dir / "result.json").write_text(
        json.dumps({"capacity_warning": "OK", "fragility_score": 0.14}),
        encoding="utf-8",
    )
    (manifests_dir / f"{data_version}.json").write_text(
        json.dumps(
            {
                "data_version": data_version,
                "start": "2023-01-01",
                "end": "2024-12-31",
                "survivorship_bias_risk": "clean",
                "universe_id": "us-large-cap-v1",
                "universe_source": "curated",
            }
        ),
        encoding="utf-8",
    )

    class StubGate:
        def __init__(self, data_root: str) -> None:
            self.data_root = data_root

        def evaluate(self, candidate_id: str) -> object:
            return type(
                "GateResult",
                (),
                {
                    "decision": "READY_FOR_PAPER_REVIEW",
                    "reasons": [],
                    "warnings": [],
                    "evidence": {"promotion_result_path": "research/promotion/result.json"},
                },
            )()

    monkeypatch.setattr(
        "quant_us.research.automation.promotion_gate.ResearchPromotionGate",
        StubGate,
    )

    manifest = StrategyManifestManager(data_root=str(tmp_path)).create_from_candidate(
        candidate_id
    )

    assert manifest.data_version == data_version
    assert manifest.sample_window["start"] == "2023-01-01"
    assert manifest.sample_window["end"] == "2024-12-31"
    assert manifest.purge_embargo == {"purge_bars": 5, "embargo_bars": 2}
    assert manifest.trial_id == "trial_017"
    assert manifest.trial_count == 12
    assert manifest.pbo == 0.08
    assert manifest.dsr == 0.91
    assert manifest.cost_model["name"] == "default"
    assert manifest.cost_model["commission_model"] == "commission_pct"
    assert manifest.slippage_model["name"] == "default"
    assert manifest.slippage_model["slippage_bps"] == 1.0
    assert manifest.capacity["estimated_capacity_usd"] == 2500000.0
    assert manifest.turnover["annual_turnover_pct"] == 190.0
    assert manifest.holding_period["expected"] == "5d"
    assert manifest.exposure_limits["max_gross_exposure_pct"] == 95.0
    assert "max_drawdown_gt_15pct" in manifest.failure_conditions
    assert manifest.delisting_conditions["policy"] == "remove_and_manual_review"
    assert manifest.delisting_conditions["survivorship_bias_risk"] == "clean"
    assert manifest.promotion_status == "READY_FOR_PORTFOLIO_SIM"
