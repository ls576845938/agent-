from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from quant_us.backtest.ledger_pnl import compute_ledger_reconciliation_artifact_hash
from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore
from quant_us.research.automation.evidence_materializer import ResearchEvidenceMaterializer
from quant_us.research.automation.promotion_gate import ResearchPromotionGate
from quant_us.research.strategy_manifest import StrategyManifestManager
from quant_us.research.validation import summarize_candidate_validation


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _validation_inputs(profile: str) -> tuple[dict, dict, dict, dict]:
    experiment_data = {
        "experiment_id": "exp_validation",
        "strategy_family": "momentum",
        "symbols": ["AAPL"],
        "timeframe": "1d",
        "data_version": "qs-yfinance-AAPL-1d-validation",
        "lookahead_guard": "features[t] generate orders for next-bar execution only",
        "param_grid": {
            "lookback": [10, 20, 40],
            "threshold": [0.1, 0.2],
        },
    }

    good_returns = [
        0.012,
        0.008,
        -0.004,
        0.011,
        0.007,
        0.009,
        -0.003,
        0.010,
        0.006,
        0.005,
        0.013,
        -0.002,
        0.011,
        0.009,
        0.004,
        0.008,
        -0.001,
        0.007,
        0.010,
        0.006,
    ]
    weak_returns = [
        0.003,
        -0.002,
        0.001,
        0.002,
        -0.001,
        0.0005,
        -0.0025,
        0.001,
        0.0008,
        -0.0006,
        0.002,
        -0.001,
        0.0015,
        0.0004,
        -0.0015,
        0.0009,
        0.0012,
        -0.0007,
        0.0006,
        0.001,
    ]

    pbo_good = [
        {"split_id": "s1", "config_id": "a", "train_sharpe": 1.30, "test_sharpe": 1.10},
        {"split_id": "s1", "config_id": "b", "train_sharpe": 1.10, "test_sharpe": 0.70},
        {"split_id": "s1", "config_id": "c", "train_sharpe": 0.90, "test_sharpe": 0.40},
        {"split_id": "s2", "config_id": "a", "train_sharpe": 1.25, "test_sharpe": 1.00},
        {"split_id": "s2", "config_id": "b", "train_sharpe": 1.00, "test_sharpe": 0.60},
        {"split_id": "s2", "config_id": "c", "train_sharpe": 0.80, "test_sharpe": 0.20},
    ]
    pbo_bad = [
        {"split_id": "s1", "config_id": "a", "train_sharpe": 1.40, "test_sharpe": 0.10},
        {"split_id": "s1", "config_id": "b", "train_sharpe": 1.10, "test_sharpe": 0.90},
        {"split_id": "s1", "config_id": "c", "train_sharpe": 0.90, "test_sharpe": 0.70},
        {"split_id": "s2", "config_id": "a", "train_sharpe": 1.35, "test_sharpe": 0.05},
        {"split_id": "s2", "config_id": "b", "train_sharpe": 1.05, "test_sharpe": 0.85},
        {"split_id": "s2", "config_id": "c", "train_sharpe": 0.95, "test_sharpe": 0.65},
    ]

    if profile == "good":
        metrics = {
            "sharpe_ratio": 1.55,
            "in_sample_sharpe": 1.80,
            "out_of_sample_sharpe": 1.50,
            "max_drawdown_pct": 0.18,
            "trade_count": 42,
            "walk_forward_pass_rate": 0.75,
            "oos_degradation": 0.12,
            "cost_sensitivity": 0.18,
            "estimated_capacity_usd": 1_500_000.0,
            "capacity_warning": "OK",
            "stress_survival_rate": 0.83,
            "monte_carlo_survival_rate": 0.91,
            "alpha_decay_half_life_days": 14.0,
            "param_stability_score": 0.73,
            "param_sensitivity": 0.12,
            "single_year_concentration": 0.18,
            "single_symbol_concentration": 0.22,
            "correlation_redundancy": 0.21,
            "total_return_pct": 0.24,
            "gross_total_return_pct": 0.28,
            "gross_sharpe_ratio": 1.78,
            "daily_returns": good_returns,
            "trial_sharpes": [0.82, 0.91, 1.02, 0.88, 0.95, 1.05],
            "wf_fold_sharpes": [1.20, 1.05, 0.95, 1.00],
            "wf_fold_drawdowns": [0.08, 0.10, 0.12, 0.09],
            "pbo_trials": pbo_good,
            "style_exposure": {
                "observations": 252,
                "alpha_period": 0.0002,
                "alpha_annualized": 0.0504,
                "betas": {"MKT": 1.05, "SMB": -0.12},
                "r_squared": 0.79,
                "benchmark_columns": ["MKT", "SMB"],
            },
            "symbols": ["AAPL"],
            "timeframe": "1d",
            "data_source": "yfinance",
            "asset_class": "equity",
            "data_version": experiment_data["data_version"],
            "lookahead_guard": experiment_data["lookahead_guard"],
        }
    else:
        metrics = {
            "sharpe_ratio": 0.25,
            "in_sample_sharpe": 0.32,
            "out_of_sample_sharpe": 0.25,
            "max_drawdown_pct": 0.16,
            "trade_count": 38,
            "walk_forward_pass_rate": 0.75,
            "oos_degradation": 0.08,
            "cost_sensitivity": 0.10,
            "estimated_capacity_usd": 1_100_000.0,
            "capacity_warning": "OK",
            "stress_survival_rate": 0.82,
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 11.0,
            "param_stability_score": 0.71,
            "param_sensitivity": 0.10,
            "single_year_concentration": 0.18,
            "single_symbol_concentration": 0.22,
            "correlation_redundancy": 0.19,
            "total_return_pct": 0.09,
            "gross_total_return_pct": 0.11,
            "gross_sharpe_ratio": 0.35,
            "daily_returns": weak_returns,
            "trial_sharpes": [0.95, 1.05, 1.20, 1.10, 1.30, 1.15],
            "wf_fold_sharpes": [0.30, 0.28, 0.22, 0.18],
            "wf_fold_drawdowns": [0.08, 0.10, 0.12, 0.09],
            "pbo_trials": pbo_bad,
            "style_exposure": {
                "observations": 252,
                "alpha_period": 0.0001,
                "alpha_annualized": 0.0252,
                "betas": {"MKT": 0.98, "SMB": -0.08},
                "r_squared": 0.74,
                "benchmark_columns": ["MKT", "SMB"],
            },
            "symbols": ["AAPL"],
            "timeframe": "1d",
            "data_source": "yfinance",
            "asset_class": "equity",
            "data_version": experiment_data["data_version"],
            "lookahead_guard": experiment_data["lookahead_guard"],
        }

    walk_forward_artifact = {
        "schema_version": "research_walk_forward_result_v2",
        "status": "completed",
        "validation_method": "cpcv",
        "purged": True,
        "purge_bars": 1,
        "embargo_bars": 2,
        "embargoed": True,
        "lookahead_guard": experiment_data["lookahead_guard"],
        "n_splits": 4,
        "test_splits": 2,
        "combination_count": 6,
        "folds": [
            {"oos_sharpe": value, "passed": True}
            for value in metrics["wf_fold_sharpes"]
        ],
        "fold_sharpes": list(metrics["wf_fold_sharpes"]),
        "fold_drawdowns": list(metrics["wf_fold_drawdowns"]),
        "walk_forward_pass_rate": metrics["walk_forward_pass_rate"],
        "pbo_trials": list(metrics["pbo_trials"]),
        "metrics": {
            "walk_forward_pass_rate": metrics["walk_forward_pass_rate"],
            "oos_degradation": metrics["oos_degradation"],
        },
    }
    cost_stress_artifact = {
        "schema_version": "research_cost_stress_result_v1",
        "status": "completed",
        "stress_survival_rate": metrics["stress_survival_rate"],
        "cost_sensitivity": metrics["cost_sensitivity"],
        "levels": [
            {"cost_multiplier": 1.0, "total_return_pct": metrics["total_return_pct"], "sharpe_ratio": metrics["sharpe_ratio"]},
            {"cost_multiplier": 2.0, "total_return_pct": metrics["total_return_pct"] - 0.03, "sharpe_ratio": metrics["sharpe_ratio"] - 0.18},
            {"cost_multiplier": 5.0, "total_return_pct": metrics["total_return_pct"] - 0.08, "sharpe_ratio": metrics["sharpe_ratio"] - 0.42},
        ],
        "metrics": {
            "stress_survival_rate": metrics["stress_survival_rate"],
            "cost_sensitivity": metrics["cost_sensitivity"],
        },
    }
    return metrics, walk_forward_artifact, cost_stress_artifact, experiment_data


def _write_candidate_fixture(
    data_root: Path,
    *,
    candidate_id: str,
    profile: str,
    include_strategy_manifest: bool,
    source: str = "yfinance",
    symbol: str = "AAPL",
    asset_class: str = "equity",
    data_version: str | None = None,
) -> str:
    metrics, walk_forward_artifact, cost_stress_artifact, experiment_data = _validation_inputs(profile)
    experiment_id = experiment_data["experiment_id"]
    data_version = data_version or (
        experiment_data["data_version"]
        if source == "yfinance" and symbol == "AAPL" and asset_class == "equity"
        else f"qs-{source}-{symbol}-1d-validation"
    )
    experiment_data = {
        **experiment_data,
        "symbols": [symbol],
        "data_version": data_version,
        "source": source,
        "data_source": source,
        "asset_class": asset_class,
    }
    metrics = {
        **metrics,
        "symbols": [symbol],
        "data_source": source,
        "asset_class": asset_class,
        "data_version": data_version,
    }

    data_manifest = DataManifest(
        data_version=data_version,
        source=source,
        symbol=symbol,
        interval="1d",
        asset_class=asset_class,
        timezone="UTC",
        start="2024-01-01T00:00:00+00:00",
        end="2024-02-01T00:00:00+00:00",
        row_count=22,
        expected_rows=22,
        coverage_pct=100.0,
        fingerprint="validation-fingerprint",
        checksum="validation-fingerprint",
        quality_score=95.0,
        universe_id="validation-universe",
        universe_source="unit-test",
        survivorship_bias_risk="clean",
    )
    DataManifestStore(data_root / "manifests").write(data_manifest)

    experiment_path = data_root / "research" / "experiments" / experiment_id / "manifest.json"
    _write_json(experiment_path, experiment_data)

    scorecard_path = data_root / "research" / "scorecards" / f"{candidate_id}.json"
    _write_json(
        scorecard_path,
        {
            "candidate_id": candidate_id,
            "sharpe": metrics["sharpe_ratio"],
            "cagr": metrics["total_return_pct"],
            "walk_forward_pass_rate": metrics["walk_forward_pass_rate"],
            "cost_sensitivity": metrics["cost_sensitivity"],
            "robustness_score": 0.8,
            "trade_count": metrics["trade_count"],
            "turnover": 0.21,
            "avg_holding_period": 5.0,
            "avg_exposure": 0.68,
            "style_exposure": metrics["style_exposure"],
        },
    )

    walk_forward_path = data_root / "research" / "walk_forward" / candidate_id / "result.json"
    cost_stress_path = data_root / "research" / "cost_stress" / candidate_id / "result.json"
    _write_json(walk_forward_path, walk_forward_artifact)
    _write_json(cost_stress_path, cost_stress_artifact)

    reconciliation_summary = {
        "snapshot_count": 2,
        "tolerance_pct": 0.0,
        "absolute_tolerance": 0.0,
        "max_abs_diff": 0.0,
        "max_pct_diff": 0.0,
        "passed": True,
    }
    ledger_artifact = {
        "generated_at": "2024-02-02T00:00:00+00:00",
        "as_of_utc": "2024-02-02T00:00:00+00:00",
        "hashes": {
            "fills_hash": "fills-hash-1",
            "ledger_hash": "ledger-hash-1",
            "orders_hash": "orders-hash-1",
            "portfolio_snapshots_hash": "snapshots-hash-1",
        },
        "orders": {"total_orders": 12},
        "fills": {"effective_fill_count": 12},
        "pnl": {
            "source": "ledger_fills",
            "final_equity": 125000.0,
            "net_pnl": 25000.0,
        },
        "reconciliation": {"summary": reconciliation_summary},
        "integrity": {"passed": True},
    }
    ledger_artifact["artifact_hash"] = compute_ledger_reconciliation_artifact_hash(
        ledger_artifact
    )
    ledger_artifact_path = (
        data_root / "research" / "backtests" / candidate_id / "ledger_artifact.json"
    )
    _write_json(ledger_artifact_path, ledger_artifact)

    backtest_manifest = {
        "candidate_id": candidate_id,
        "experiment_id": experiment_id,
        "strategy_id": "trend_momentum",
        "engine": "event_driven",
        "canonical_for_promotion": True,
        "data_version": data_version,
        "data_manifest_exists": True,
        "missing_data_manifest": False,
        "ledger_artifact_path": str(ledger_artifact_path),
        "ledger_artifact_hash": ledger_artifact["artifact_hash"],
        "ledger_hash": ledger_artifact["hashes"]["ledger_hash"],
        "fills_hash": ledger_artifact["hashes"]["fills_hash"],
        "orders_hash": ledger_artifact["hashes"]["orders_hash"],
        "portfolio_snapshots_hash": ledger_artifact["hashes"]["portfolio_snapshots_hash"],
        "data_manifest": asdict(data_manifest),
        "reconciliation": reconciliation_summary,
        "corporate_actions": {"adjustment_count": 0},
        "ledger_artifact": ledger_artifact,
        "evidence": {
            "orders": {
                "count": 12,
                "all_orders_have_risk_check_id": True,
                "orders_hash": ledger_artifact["hashes"]["orders_hash"],
            },
            "fills": {
                "count": 12,
                "all_fills_match_orders": True,
                "fills_hash": ledger_artifact["hashes"]["fills_hash"],
            },
            "equity": {"consistent": True},
            "completeness": {"promotion_evidence_complete": True},
            "pnl": {
                "source": "ledger_fills",
                "final_equity": 125000.0,
                "net_pnl": 25000.0,
            },
            "reconciliation": {
                "summary": reconciliation_summary,
                "snapshots": [
                    {
                        "timestamp_utc": "2024-02-02T00:00:00+00:00",
                        "passed": True,
                        "diff": {"cash": 0.0, "equity": 0.0},
                        "max_abs_diff": 0.0,
                        "max_pct_diff": 0.0,
                    }
                ],
            },
            "corporate_actions": {"digest": {"adjustment_count": 0}},
            "ledger_artifact": ledger_artifact,
            "ledger_artifact_path": str(ledger_artifact_path),
            "data_scope": {"promotion_scope_ok": True, "scope_rejections": []},
        },
    }
    backtest_manifest_path = (
        data_root / "research" / "backtests" / candidate_id / "run_manifest.json"
    )
    _write_json(backtest_manifest_path, backtest_manifest)

    metrics = {
        **metrics,
        "backtest_manifest_path": str(backtest_manifest_path),
        "scorecard_path": str(scorecard_path),
        "walk_forward_result_path": str(walk_forward_path),
        "cost_stress_result_path": str(cost_stress_path),
    }
    candidate_path = data_root / "research" / "candidates" / candidate_id / "candidate.json"
    _write_json(
        candidate_path,
        {
            "candidate_id": candidate_id,
            "experiment_id": experiment_id,
            "strategy_id": "trend_momentum",
            "symbols": [symbol],
            "timeframe": "1d",
            "data_source": source,
            "asset_class": asset_class,
            "data_version": data_version,
            "backtest_manifest_path": str(backtest_manifest_path),
            "scorecard_path": str(scorecard_path),
            "walk_forward_result_path": str(walk_forward_path),
            "cost_stress_result_path": str(cost_stress_path),
            "promotion_status": "RESEARCH_ONLY",
            "metrics": metrics,
        },
    )

    if include_strategy_manifest:
        _write_json(
            data_root / "research" / "manifests" / f"sman_{candidate_id}" / "manifest.json",
            {
                "strategy_candidate_id": f"sman_{candidate_id}",
                "source_candidate_id": candidate_id,
                "promotion_status": "DRAFT",
                "data_version": data_version,
                "sample_window": {
                    "start": "2024-01-01T00:00:00+00:00",
                    "end": "2024-02-01T00:00:00+00:00",
                    "timeframe": "1d",
                },
                "purge_embargo": {
                    "method": "cpcv",
                    "purged": True,
                    "embargoed": True,
                    "embargo_steps": 2,
                    "fold_count": 4,
                    "path_count": 6,
                },
                "trial_id": candidate_id,
                "trial_count": 6,
                "pbo": 0.0 if profile == "good" else 1.0,
                "dsr": 0.62 if profile == "good" else 0.02,
                "cpcv": {
                    "method": "cpcv",
                    "purged": True,
                    "embargoed": True,
                    "embargo_steps": 2,
                    "fold_count": 4,
                    "path_count": 6,
                    "pass_rate": metrics["walk_forward_pass_rate"],
                },
                "cost_model": {"name": "default", "commission_rate": 0.0001},
                "slippage_model": {"name": "default", "slippage_bps": 1.0},
                "cost_stress": {
                    "stress_survival_rate": metrics["stress_survival_rate"],
                    "cost_sensitivity": metrics["cost_sensitivity"],
                    "level_count": 3,
                },
                "style_exposure": metrics["style_exposure"],
                "capacity": {
                    "estimated_capacity_usd": 1_500_000.0,
                    "fragility_score": 0.14,
                },
                "turnover": {
                    "turnover": 0.21,
                    "annual_turnover_pct": 140.0,
                    "trade_count": metrics["trade_count"],
                },
                "holding_period": {"expected": "5d", "avg_holding_period": 5.0},
                "exposure_limits": {"max_gross_exposure_pct": 95.0},
                "failure_conditions": ["oos_decay_gt_30pct"],
                "delisting_conditions": {
                    "policy": "manual_review_required",
                    "survivorship_bias_risk": "clean",
                },
            },
        )

    return candidate_id


def test_validation_summary_computes_cpcv_dsr_pbo_and_cost_drag() -> None:
    metrics, walk_forward_artifact, cost_stress_artifact, experiment_data = _validation_inputs(
        "good"
    )

    summary = summarize_candidate_validation(
        candidate_id="cand_summary",
        metrics=metrics,
        walk_forward_artifact=walk_forward_artifact,
        cost_stress_artifact=cost_stress_artifact,
        experiment_data=experiment_data,
    )

    assert summary["status"] == "complete"
    assert summary["cv_summary"]["method"] == "cpcv"
    assert summary["cv_summary"]["purged"] is True
    assert summary["cv_summary"]["purge_recorded"] is True
    assert summary["cv_summary"]["embargoed"] is True
    assert summary["cv_summary"]["embargo_recorded"] is True
    assert summary["lookahead_controls"]["recorded"] is True
    assert summary["lookahead_controls"]["passed"] is True
    assert summary["trial_counting"]["param_grid_trial_count"] == 6
    assert summary["trial_counting"]["effective_trial_count"] >= 6
    assert summary["deflated_sharpe_ratio"]["dsr"] is not None
    assert summary["deflated_sharpe_ratio"]["dsr"] > 0.10
    assert summary["pbo"]["pbo"] == 0.0
    assert summary["multiple_testing"]["passed"] is True
    assert summary["promotion_gate_contract"]["status"] == "passed"
    assert summary["promotion_gate_contract"]["checks"]["cpcv_available"] is True
    assert summary["promotion_gate_contract"]["checks"]["purge_embargo_recorded"] is True
    assert summary["promotion_gate_contract"]["checks"]["lookahead_guard_recorded"] is True
    assert summary["promotion_gate_contract"]["checks"]["multi_path_validation"] is True
    assert summary["net_return_distribution"]["count"] == 20
    assert summary["cost_before_after"]["mode"] == "gross_vs_net_plus_stress"
    assert summary["cost_before_after"]["cost_drag_return"] == 0.04


def test_materializer_persists_cpcv_purge_embargo_and_lookahead_metadata(tmp_path: Path) -> None:
    candidate_id = "cand_materializer_stats"
    experiment_id = "exp_materializer_stats"
    _write_json(
        tmp_path / "research" / "experiments" / experiment_id / "manifest.json",
        {
            "experiment_id": experiment_id,
            "validation_method": "cpcv",
            "lookahead_guard": "features[t] generate next-bar orders only",
            "params": {"lookback": 20},
        },
    )
    pbo_trials = [
        {"split_id": "s1", "config_id": "a", "train_sharpe": 1.2, "test_sharpe": 1.0},
        {"split_id": "s1", "config_id": "b", "train_sharpe": 0.8, "test_sharpe": 0.4},
    ]
    _write_json(
        tmp_path / "research" / "candidates" / candidate_id / "candidate.json",
        {
            "candidate_id": candidate_id,
            "experiment_id": experiment_id,
            "metrics": {
                "walk_forward_pass_rate": 1.0,
                "validation_method": "cpcv",
                "purged": True,
                "purge_bars": 1,
                "embargoed": True,
                "embargo_bars": 2,
                "n_splits": 3,
                "test_splits": 2,
                "combination_count": 3,
                "wf_fold_sharpes": [1.0, 0.9, 0.8],
                "pbo_trials": pbo_trials,
                "lookahead_guard": "features[t] generate next-bar orders only",
            },
        },
    )

    result = ResearchEvidenceMaterializer(data_root=str(tmp_path)).materialize_candidate(
        candidate_id,
        create_strategy_manifest=False,
        run_promotion_gate=False,
    )
    payload = json.loads(Path(result.walk_forward_result_path).read_text(encoding="utf-8"))

    assert payload["validation_method"] == "cpcv"
    assert payload["purged"] is True
    assert payload["purge_bars"] == 1
    assert payload["embargoed"] is True
    assert payload["embargo_bars"] == 2
    assert payload["lookahead_guard"] == "features[t] generate next-bar orders only"
    assert payload["pbo_trials"] == pbo_trials


def test_promotion_gate_blocks_high_pbo_and_low_dsr(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_bad_validation",
        profile="bad",
        include_strategy_manifest=True,
    )

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert any(reason.startswith("deflated_sharpe_too_low:") for reason in result.reasons)
    assert any(reason.startswith("pbo_too_high:") for reason in result.reasons)
    assert result.evidence["validation_stats"]["pbo"]["pbo"] == 1.0
    assert result.evidence["validation_stats"]["deflated_sharpe_ratio"]["dsr"] < 0.10


def test_promotion_gate_blocks_missing_cpcv_dsr_pbo_and_validation_controls(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_missing_stat_evidence",
        profile="good",
        include_strategy_manifest=True,
    )
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    walk_forward_path = tmp_path / "research" / "walk_forward" / candidate_id / "result.json"

    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_payload["metrics"]["return_observation_count"] = 1
    candidate_payload["metrics"].pop("pbo_trials", None)
    candidate_payload["metrics"].pop("lookahead_guard", None)
    _write_json(candidate_path, candidate_payload)

    experiment_path = tmp_path / "research" / "experiments" / "exp_validation" / "manifest.json"
    experiment_payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    experiment_payload.pop("lookahead_guard", None)
    _write_json(experiment_path, experiment_payload)

    walk_forward_payload = json.loads(walk_forward_path.read_text(encoding="utf-8"))
    walk_forward_payload.update(
        {
            "validation_method": "walk_forward",
            "pbo_trials": [],
        }
    )
    for key in ("purged", "purge_bars", "embargoed", "embargo_bars", "lookahead_guard"):
        walk_forward_payload.pop(key, None)
    _write_json(walk_forward_path, walk_forward_payload)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert any(reason.startswith("missing_deflated_sharpe_ratio:") for reason in result.reasons)
    assert any(reason.startswith("missing_pbo_evidence:") for reason in result.reasons)
    assert "missing_cpcv_evidence: promotion requires CPCV metadata with at least 2 persisted validation paths" in result.reasons
    assert "validation_purge_embargo_missing: promotion requires recorded purge and embargo parameters for out-of-sample validation" in result.reasons
    assert "lookahead_guard_missing: promotion requires recorded no-lookahead feature/label timing controls" in result.reasons
    contract = result.evidence["validation_promotion_contract"]
    assert contract["checks"]["cpcv_available"] is False
    assert contract["checks"]["purge_embargo_recorded"] is False
    assert contract["checks"]["lookahead_guard_recorded"] is False


def test_fake_fixture_can_pass_statistics_but_is_still_blocked_by_data_gate(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_fixture_stats_pass_gate_blocked",
        profile="good",
        include_strategy_manifest=True,
        source="fixture",
        symbol="AAPL",
        asset_class="equity",
        data_version="qs-fixture-AAPL-1d-validation",
    )

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert result.evidence["validation_contract_status"] == "passed"
    assert result.evidence["validation_promotion_contract"]["checks"]["cpcv_available"] is True
    assert any("fixture_data_not_allowed" in reason for reason in result.reasons)


def test_crypto_sqlite_candidate_can_reach_paper_review_with_full_evidence(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_btc_sqlite_ready",
        profile="good",
        include_strategy_manifest=True,
        source="sqlite",
        symbol="BTCUSD",
        asset_class="crypto",
        data_version="qs-sqlite-BTCUSD-1d-validation",
    )

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "READY_FOR_PAPER_REVIEW"
    assert result.evidence["asset_class"] == "crypto"
    assert result.evidence["data_source"] == "sqlite"
    assert result.evidence["data_manifest_validation"]["ok"] is True
    assert result.evidence["engine"] == "event_driven"
    assert result.evidence["ledger_artifact_ok"] is True
    assert result.evidence["orders_have_risk_check_id"] is True


def test_crypto_fixture_candidate_is_blocked_from_promotion(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_btc_fixture_blocked",
        profile="good",
        include_strategy_manifest=True,
        source="fixture",
        symbol="BTCUSD",
        asset_class="crypto",
        data_version="qs-fixture-BTCUSD-1d-validation",
    )

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert result.evidence["fixture_used"] is True
    assert any("fixture_data_not_allowed" in reason for reason in result.reasons)


def test_crypto_yfinance_candidate_is_blocked_until_sqlite_evidence_exists(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_btc_yfinance_blocked",
        profile="good",
        include_strategy_manifest=True,
        source="yfinance",
        symbol="BTCUSDT",
        asset_class="crypto",
        data_version="qs-yfinance-BTCUSDT-1d-validation",
    )

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert result.evidence["asset_class"] == "crypto"
    assert any(reason.startswith("crypto_requires_sqlite_data_source:") for reason in result.reasons)


def test_btc_new_strategy_family_cannot_bypass_walk_forward_or_cost_gate(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_btc_new_family_missing_gates",
        profile="good",
        include_strategy_manifest=True,
        source="sqlite",
        symbol="BTCUSD",
        asset_class="crypto",
        data_version="qs-sqlite-BTCUSD-1d-new-family",
    )
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    experiment_path = tmp_path / "research" / "experiments" / "exp_validation" / "manifest.json"
    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    experiment_payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    candidate_payload["strategy_family"] = "btc_breakout_vnext"
    candidate_payload["metrics"]["strategy_family"] = "btc_breakout_vnext"
    experiment_payload["strategy_family"] = "btc_breakout_vnext"
    _write_json(candidate_path, candidate_payload)
    _write_json(experiment_path, experiment_payload)

    (tmp_path / "research" / "walk_forward" / candidate_id / "result.json").unlink()
    (tmp_path / "research" / "cost_stress" / candidate_id / "result.json").unlink()

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert result.evidence["asset_class"] == "crypto"
    assert result.evidence["data_source"] == "sqlite"
    assert result.evidence["walk_forward_artifact_exists"] is False
    assert result.evidence["cost_stress_artifact_exists"] is False
    assert any(reason.startswith("walk_forward_artifact_path_missing:") for reason in result.reasons)
    assert any(reason.startswith("cost_stress_artifact_path_missing:") for reason in result.reasons)
    assert result.evidence["validation_contract_status"] == "blocked"


def test_crypto_trade_count_zero_fails_promotion(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_btc_zero_trades",
        profile="good",
        include_strategy_manifest=True,
        source="sqlite",
        symbol="BTCUSD",
        asset_class="crypto",
        data_version="qs-sqlite-BTCUSD-1d-zero-trades",
    )
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["metrics"]["trade_count"] = 0
    _write_json(candidate_path, payload)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert "trade_count_zero: paper-review candidates must have at least one completed trade" in result.reasons


def test_promotion_gate_fail_closed_when_dsr_evidence_missing(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_missing_dsr_evidence",
        profile="good",
        include_strategy_manifest=True,
    )
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    cost_stress_path = tmp_path / "research" / "cost_stress" / candidate_id / "result.json"
    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    for key in (
        "daily_returns",
        "net_returns",
        "return_series",
        "net_return_series",
        "returns",
        "return_observation_count",
        "n_observations",
        "n_periods",
        "bar_count",
        "sample_count",
    ):
        candidate_payload["metrics"].pop(key, None)
    _write_json(candidate_path, candidate_payload)

    cost_stress_payload = json.loads(cost_stress_path.read_text(encoding="utf-8"))
    cost_stress_payload["levels"] = []
    _write_json(cost_stress_path, cost_stress_payload)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert result.evidence["validation_stats"]["available_components"]["deflated_sharpe_ratio"] is False
    assert "missing_deflated_sharpe_ratio: promotion requires DSR evidence after trial counting" in result.reasons


def test_promotion_gate_fail_closed_when_pbo_path_trials_missing(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_missing_pbo_trials",
        profile="good",
        include_strategy_manifest=True,
    )
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    walk_forward_path = tmp_path / "research" / "walk_forward" / candidate_id / "result.json"
    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_payload["metrics"].pop("pbo_trials", None)
    _write_json(candidate_path, candidate_payload)

    walk_forward_payload = json.loads(walk_forward_path.read_text(encoding="utf-8"))
    walk_forward_payload["pbo_trials"] = []
    _write_json(walk_forward_path, walk_forward_payload)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert result.evidence["validation_stats"]["available_components"]["pbo"] is False
    assert "missing_pbo_evidence: promotion requires CPCV/PBO path statistics, not a single best-path summary" in result.reasons


def test_promotion_gate_fail_closed_when_trial_counting_missing(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_missing_trial_counting",
        profile="good",
        include_strategy_manifest=True,
    )
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    experiment_path = tmp_path / "research" / "experiments" / "exp_validation" / "manifest.json"
    walk_forward_path = tmp_path / "research" / "walk_forward" / candidate_id / "result.json"
    cost_stress_path = tmp_path / "research" / "cost_stress" / candidate_id / "result.json"

    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_payload["metrics"].pop("trial_count", None)
    candidate_payload["metrics"].pop("trial_sharpes", None)
    candidate_payload["metrics"].pop("candidate_trial_sharpes", None)
    candidate_payload["metrics"].pop("wf_fold_sharpes", None)
    candidate_payload["metrics"].pop("pbo_trials", None)
    candidate_payload["metrics"].pop("cost_stress_levels", None)
    _write_json(candidate_path, candidate_payload)

    experiment_payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    experiment_payload["param_grid"] = {}
    _write_json(experiment_path, experiment_payload)

    walk_forward_payload = json.loads(walk_forward_path.read_text(encoding="utf-8"))
    walk_forward_payload["pbo_trials"] = []
    walk_forward_payload["fold_sharpes"] = []
    walk_forward_payload["folds"] = []
    _write_json(walk_forward_path, walk_forward_payload)

    cost_stress_payload = json.loads(cost_stress_path.read_text(encoding="utf-8"))
    cost_stress_payload["levels"] = []
    _write_json(cost_stress_path, cost_stress_payload)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert result.evidence["validation_effective_trial_count"] == 0
    assert result.evidence["validation_independent_trial_count"] == 0
    assert "insufficient_effective_trials: promotion requires at least 2 effective and independent trials" in result.reasons


def test_crypto_missing_event_driven_ledger_evidence_blocks_paper_candidate(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_btc_missing_ledger",
        profile="good",
        include_strategy_manifest=True,
        source="sqlite",
        symbol="BTCUSD",
        asset_class="crypto",
        data_version="qs-sqlite-BTCUSD-1d-missing-ledger",
    )
    manifest_path = tmp_path / "research" / "backtests" / candidate_id / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["engine"] = "vectorized"
    manifest["evidence"].pop("ledger_artifact", None)
    manifest.pop("ledger_artifact", None)
    _write_json(manifest_path, manifest)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert "event_driven_required: promotion requires event_driven backtest evidence" in result.reasons
    assert any("ledger_reconciliation_artifact" in reason for reason in result.reasons)


def test_crypto_sqlite_candidate_without_data_quality_manifest_is_blocked(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_btc_missing_data_manifest",
        profile="good",
        include_strategy_manifest=True,
        source="sqlite",
        symbol="BTCUSD",
        asset_class="crypto",
        data_version="qs-sqlite-BTCUSD-1d-missing-data-manifest",
    )
    (tmp_path / "manifests" / "qs-sqlite-BTCUSD-1d-missing-data-manifest.json").unlink()

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert any(reason.startswith("missing_canonical_data_manifest:") for reason in result.reasons)


def test_promotion_gate_blocks_single_path_high_sharpe_candidate(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_single_path",
        profile="good",
        include_strategy_manifest=True,
    )

    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    walk_forward_path = tmp_path / "research" / "walk_forward" / candidate_id / "result.json"

    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    metrics = dict(candidate_payload["metrics"])
    metrics.update(
        {
            "sharpe_ratio": 3.4,
            "trial_sharpes": [3.4],
            "wf_fold_sharpes": [3.4],
            "wf_fold_drawdowns": [0.04],
            "walk_forward_pass_rate": 1.0,
        }
    )
    metrics.pop("pbo_trials", None)
    candidate_payload["metrics"] = metrics
    _write_json(candidate_path, candidate_payload)

    walk_forward_payload = json.loads(walk_forward_path.read_text(encoding="utf-8"))
    walk_forward_payload.update(
        {
            "validation_method": "walk_forward",
            "purged": False,
            "embargo_bars": 0,
            "n_splits": 1,
            "test_splits": 1,
            "combination_count": 1,
            "folds": [{"oos_sharpe": 3.4, "passed": True}],
            "fold_sharpes": [3.4],
            "fold_drawdowns": [0.04],
            "walk_forward_pass_rate": 1.0,
            "pbo_trials": [],
        }
    )
    _write_json(walk_forward_path, walk_forward_payload)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert "single_path_validation_not_allowed: candidate cannot promote on a single validation path even with high Sharpe" in result.reasons
    assert any(reason.startswith("missing_pbo_evidence:") for reason in result.reasons)
    assert result.evidence["validation_contract_status"] == "blocked"
    contract = result.evidence["validation_promotion_contract"]
    assert contract["checks"]["multi_path_validation"] is False
    assert contract["checks"]["pbo_available"] is False
    blocker_details = {
        item["code"]: item
        for item in result.evidence["machine_readable_blocker_details"]
    }
    assert blocker_details["single_path_validation_not_allowed"]["observed"]["validation_paths"] == 1
    assert blocker_details["single_path_validation_not_allowed"]["required"]["min_validation_paths"] == 2
    assert "research walk-forward" in blocker_details["single_path_validation_not_allowed"]["cli_next_command"]
    assert "materialize_candidate" in blocker_details["missing_pbo_evidence"]["materialization"]["command"]


def test_promotion_gate_fail_closed_on_missing_manifest_key_stats(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_missing_style_contract",
        profile="good",
        include_strategy_manifest=True,
    )
    manifest_path = (
        tmp_path / "research" / "manifests" / f"sman_{candidate_id}" / "manifest.json"
    )
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["style_exposure"] = {
        "missing_reason": "style_exposure_benchmark_regression_missing"
    }
    manifest_payload["contract_missing_reasons"] = {
        "style_exposure": "style_exposure_benchmark_regression_missing"
    }
    _write_json(manifest_path, manifest_payload)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert result.decision == "BLOCKED"
    assert any(
        reason == f"strategy_manifest_contract_incomplete:sman_{candidate_id}:style_exposure"
        for reason in result.reasons
    )
    assert result.evidence["strategy_manifest_contract_complete"] is False


def test_strategy_manifest_captures_validation_evidence(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_manifest_validation",
        profile="good",
        include_strategy_manifest=False,
    )

    manifest = StrategyManifestManager(data_root=str(tmp_path)).create_from_candidate(
        candidate_id
    )

    assert manifest.promotion_status == "READY_FOR_PORTFOLIO_SIM"
    assert manifest.trial_count >= 6
    assert manifest.dsr is not None and manifest.dsr > 0.10
    assert manifest.pbo == 0.0
    assert manifest.purge_embargo["method"] == "cpcv"
    assert manifest.purge_embargo["purged"] is True
    assert manifest.purge_embargo["embargoed"] is True
    assert manifest.evidence["promotion_gate"]["decision"] == "READY_FOR_PAPER_REVIEW"
    assert manifest.evidence["promotion_gate"]["validation_stats"]["status"] == "complete"


def test_promotion_gate_resolves_repo_relative_canonical_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    candidate_id = _write_candidate_fixture(
        data_root,
        candidate_id="cand_repo_relative",
        profile="good",
        include_strategy_manifest=True,
    )
    candidate_path = data_root / "research" / "candidates" / candidate_id / "candidate.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    for key in (
        "backtest_manifest_path",
        "scorecard_path",
        "walk_forward_result_path",
        "cost_stress_result_path",
    ):
        absolute = Path(payload[key])
        payload[key] = str(absolute.relative_to(tmp_path))
        payload["metrics"][key] = payload[key]
    candidate_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    result = ResearchPromotionGate(data_root="data").evaluate(candidate_id)

    assert result.decision == "READY_FOR_PAPER_REVIEW"
    assert not any(reason.startswith("non_canonical_walk_forward_artifact_path") for reason in result.reasons)
    assert not any(reason.startswith("non_canonical_cost_stress_artifact_path") for reason in result.reasons)
    assert result.evidence["walk_forward_artifact_resolved_path"] == (
        f"data/research/walk_forward/{candidate_id}/result.json"
    )


def test_promotion_gate_uses_missing_metric_blockers_when_validation_metrics_absent(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_missing_validation_metrics",
        profile="good",
        include_strategy_manifest=True,
    )
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    for key in (
        "monte_carlo_survival_rate",
        "param_stability_score",
        "alpha_decay_half_life_days",
        "stress_survival_rate",
    ):
        payload["metrics"].pop(key, None)
    candidate_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    cost_stress_path = tmp_path / "research" / "cost_stress" / candidate_id / "result.json"
    cost_stress = json.loads(cost_stress_path.read_text(encoding="utf-8"))
    cost_stress.pop("stress_survival_rate", None)
    cost_stress_metrics = dict(cost_stress.get("metrics", {}))
    cost_stress_metrics.pop("stress_survival_rate", None)
    cost_stress["metrics"] = cost_stress_metrics
    _write_json(cost_stress_path, cost_stress)

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

    assert "missing_monte_carlo_survival_rate: promotion requires Monte Carlo survival evidence" in result.reasons
    assert "missing_param_stability_score: promotion requires parameter stability evidence" in result.reasons
    assert "missing_stress_survival_rate: promotion requires persisted cost-stress survival evidence" in result.reasons
    assert "missing_alpha_decay_half_life_days: promotion evidence is missing alpha decay half-life metadata" in result.warnings
    assert not any(reason.startswith("monte_carlo_survival_low:") for reason in result.reasons)
    assert not any(reason.startswith("param_unstable:") for reason in result.reasons)
    assert not any(reason.startswith("stress_survival_low:") for reason in result.reasons)
    assert not any(warning.startswith("rapid_alpha_decay:") for warning in result.warnings)
    blocker_details = {
        item["code"]: item
        for item in result.evidence["machine_readable_blocker_details"]
    }
    monte_carlo = blocker_details["missing_monte_carlo_survival_rate"]
    assert monte_carlo["observed"]["trade_return_count"] == 0
    assert monte_carlo["observed"]["daily_return_count"] == 20
    assert monte_carlo["cli_next_command"]
    assert "research robustness-run" in monte_carlo["diagnostic_cli_command"]
    assert "synthetic returns" in monte_carlo["materialization"]["note"]
    param_stability = blocker_details["missing_param_stability_score"]
    assert param_stability["observed"]["param_grid_trial_count"] == 6
    assert param_stability["cli_next_command"]
    assert "research param-stability" in param_stability["diagnostic_cli_command"]
    assert "real sweep evidence" in param_stability["materialization"]["note"]


def test_blocked_strategy_manifest_persists_gate_blockers_and_next_commands(tmp_path: Path) -> None:
    candidate_id = _write_candidate_fixture(
        tmp_path,
        candidate_id="cand_manifest_blocked_summary",
        profile="bad",
        include_strategy_manifest=False,
    )

    with pytest.raises(ValueError):
        StrategyManifestManager(data_root=str(tmp_path)).create_from_candidate(candidate_id)

    manifest_paths = sorted((tmp_path / "research" / "manifests").glob("*/manifest.json"))
    assert manifest_paths
    manifest_payload = json.loads(manifest_paths[0].read_text(encoding="utf-8"))

    assert manifest_payload["promotion_status"] == "BLOCKED"
    assert manifest_payload["promotion_gate_decision"] == "BLOCKED"
    assert manifest_payload["promotion_gate_blocking_reasons"]
    assert manifest_payload["promotion_gate_blocker_details"]
    assert manifest_payload["promotion_gate_next_commands"]
    assert manifest_payload["evidence"]["promotion_gate"]["blocker_details"] == manifest_payload["promotion_gate_blocker_details"]
    assert manifest_payload["evidence"]["promotion_gate"]["next_commands"] == manifest_payload["promotion_gate_next_commands"]
