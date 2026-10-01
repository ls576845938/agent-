from __future__ import annotations

import json
from pathlib import Path

from quant_us.research.evidence_contracts import summarize_strategy_manifest_contract
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
                    "style_exposure": {
                        "observations": 252,
                        "alpha_period": 0.0002,
                        "alpha_annualized": 0.0504,
                        "betas": {"MKT": 1.12, "SMB": -0.18},
                        "r_squared": 0.81,
                        "benchmark_columns": ["MKT", "SMB"],
                    },
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
        json.dumps(
            {
                "recommended_holding_period": "5d",
                "validation_method": "cpcv",
                "purged": True,
                "embargo_bars": 2,
                "combination_count": 6,
                "folds": [{"oos_sharpe": 1.0, "passed": True}] * 4,
                "walk_forward_pass_rate": 0.75,
            }
        ),
        encoding="utf-8",
    )
    (cost_stress_dir / "result.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "capacity_warning": "OK",
                "fragility_score": 0.14,
                "stress_survival_rate": 0.84,
                "cost_sensitivity": 0.19,
                "levels": [
                    {"cost_multiplier": 1.0, "total_return_pct": 0.21, "sharpe_ratio": 1.3},
                    {"cost_multiplier": 2.0, "total_return_pct": 0.17, "sharpe_ratio": 1.1},
                ],
            }
        ),
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
    assert manifest.cpcv["method"] == "cpcv"
    assert manifest.cpcv["path_count"] == 6
    assert manifest.cost_model["name"] == "default"
    assert manifest.cost_model["commission_model"] == "commission_pct"
    assert manifest.slippage_model["name"] == "default"
    assert manifest.slippage_model["slippage_bps"] == 1.0
    assert manifest.cost_stress["stress_survival_rate"] == 0.84
    assert manifest.cost_stress["level_count"] == 2
    assert manifest.style_exposure["betas"]["MKT"] == 1.12
    assert manifest.capacity["estimated_capacity_usd"] == 2500000.0
    assert manifest.turnover["annual_turnover_pct"] == 190.0
    assert manifest.holding_period["expected"] == "5d"
    assert manifest.exposure_limits["max_gross_exposure_pct"] == 95.0
    assert "max_drawdown_gt_15pct" in manifest.failure_conditions
    assert manifest.delisting_conditions["policy"] == "remove_and_manual_review"
    assert manifest.delisting_conditions["survivorship_bias_risk"] == "clean"
    assert manifest.contract_missing_reasons == {}
    assert manifest.promotion_status == "READY_FOR_PORTFOLIO_SIM"

    contract = summarize_strategy_manifest_contract(manifest.__dict__)
    assert contract["contract_complete"] is True
    assert contract["field_status"]["style_exposure"]["present"] is True


def test_strategy_manifest_contract_records_missing_reasons() -> None:
    contract = summarize_strategy_manifest_contract(
        {
            "strategy_candidate_id": "sm_missing",
            "source_candidate_id": "cand_missing",
            "data_version": "qs-yfinance-test",
            "sample_window": {"start": "2024-01-01", "end": "2024-12-31"},
            "purge_embargo": {"purge_bars": 3, "embargo_bars": 1},
            "trial_id": "cand_missing",
            "trial_count": 6,
            "pbo": 0.11,
            "dsr": 0.42,
            "cpcv": {"missing_reason": "validation_method_not_cpcv:purged_kfold"},
            "cost_model": {"name": "default"},
            "slippage_model": {"name": "default"},
            "cost_stress": {"stress_survival_rate": 0.8},
            "capacity": {"estimated_capacity_usd": 1_000_000.0},
            "turnover": {"annual_turnover_pct": 120.0},
            "holding_period": {"expected": "5d"},
            "exposure_limits": {"max_gross_exposure_pct": 95.0},
            "failure_conditions": ["drawdown_limit_breach"],
            "delisting_conditions": {"policy": "manual_review_required"},
            "style_exposure": {
                "missing_reason": "style_exposure_benchmark_regression_missing"
            },
            "contract_missing_reasons": {
                "cpcv": "validation_method_not_cpcv:purged_kfold",
                "style_exposure": "style_exposure_benchmark_regression_missing",
            },
        }
    )

    assert contract["contract_complete"] is False
    assert contract["contract_documented"] is True
    assert contract["missing_fields"] == ["cpcv", "style_exposure"]
    assert (
        contract["missing_field_reasons"]["style_exposure"]
        == "style_exposure_benchmark_regression_missing"
    )
