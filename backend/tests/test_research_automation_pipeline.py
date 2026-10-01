"""Tests for ResearchAutomationPipeline.

Covers: full pipeline run, ranking, and manual-only PAPER_ELIGIBLE promotion.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from quant_us.research.automation.promotion_gate import ResearchPromotionGate
from quant_us.research.automation.pipeline import ResearchAutomationPipeline
from quant_us.research.automation.report_gen import generate_v2
from quant_us.research.evidence_registry import (
    inspect_candidate_evidence,
    inspect_evidence_registry,
    rebuild_evidence_registry,
)
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


def _fake_stage_metrics_manager_run(self, experiment_id: str) -> dict:
    """Mock run() with sidecar-specific metrics for robustness aggregation tests."""
    import json

    manifest = self.load(experiment_id)
    if manifest is None:
        raise ValueError(f"Experiment {experiment_id} not found")

    family = str(manifest.strategy_family or "")
    fake_metrics = {
        "sharpe_ratio": 1.2,
        "total_return_pct": 0.12,
        "max_drawdown_pct": 0.12,
        "trade_count": 25,
        "turnover": 0.2,
        "param_count": 4,
    }
    if family.startswith("walk_forward_"):
        fake_metrics.update(
            {
                "sharpe_ratio": 1.0,
                "total_return_pct": 0.08,
                "max_drawdown_pct": 0.10,
                "trade_count": 18,
            }
        )
    elif family.startswith("cost_stress_"):
        if manifest.cost_model == "high":
            fake_metrics.update(
                {
                    "sharpe_ratio": 0.7,
                    "total_return_pct": 0.04,
                    "max_drawdown_pct": 0.18,
                    "trade_count": 18,
                }
            )
        else:
            fake_metrics.update(
                {
                    "sharpe_ratio": 1.3,
                    "total_return_pct": 0.11,
                    "max_drawdown_pct": 0.09,
                    "trade_count": 18,
                }
            )
    elif family.startswith("regime_split_"):
        fake_metrics.update(
            {
                "sharpe_ratio": 0.9,
                "total_return_pct": 0.06,
                "max_drawdown_pct": 0.16,
                "trade_count": 12,
            }
        )

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

    def _write_unified_backtest_fixture(
        self,
        *,
        candidate_id: str,
        experiment_id: str,
        reconciliation_passed: bool = False,
    ) -> None:
        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)

        backtest_dir = Path(self.tmp.name) / "research" / "backtests" / candidate_id
        backtest_dir.mkdir(parents=True, exist_ok=True)

        experiment_dir = (
            Path(self.tmp.name) / "research" / "experiments" / experiment_id
        )
        experiment_dir.mkdir(parents=True, exist_ok=True)

        snapshot_failed = {
            "timestamp_utc": "2026-05-09T12:01:00+00:00",
            "ledger_cash": 99_000.0,
            "ledger_equity": 99_500.0,
            "snapshot_cash": 99_020.0,
            "snapshot_equity": 99_450.0,
            "diff": {"cash": -20.0, "equity": 50.0},
            "max_abs_diff": 50.0,
            "max_pct_diff": 0.05,
            "passed": False,
        }
        snapshot_passed = {
            "timestamp_utc": "2026-05-09T12:02:00+00:00",
            "ledger_cash": 99_500.0,
            "ledger_equity": 100_000.0,
            "snapshot_cash": 99_500.0,
            "snapshot_equity": 100_000.0,
            "diff": {"cash": 0.0, "equity": 0.0},
            "max_abs_diff": 0.0,
            "max_pct_diff": 0.0,
            "passed": True,
        }
        reconciliation_summary = {
            "snapshot_count": 2,
            "tolerance_pct": 0.01,
            "absolute_tolerance": 1e-6,
            "max_abs_diff": 50.0 if not reconciliation_passed else 0.0,
            "max_pct_diff": 0.05 if not reconciliation_passed else 0.0,
            "passed": reconciliation_passed,
            "message": "snapshot mismatch" if not reconciliation_passed else "clean",
        }
        corporate_actions_digest = {
            "total_dividends": 10.0,
            "total_borrow_fees": 0.0,
            "total_corporate_adjustments": 10.0,
            "adjustment_count": 1,
            "split_event_count": 0,
        }

        candidate_data = {
            "candidate_id": candidate_id,
            "experiment_id": experiment_id,
            "strategy_id": "momentum",
            "promotion_status": "RESEARCH_ONLY",
            "backtest_manifest_path": f"research/backtests/{candidate_id}/run_manifest.json",
            "metrics": {},
        }
        (candidate_dir / "candidate.json").write_text(
            json.dumps(candidate_data),
            encoding="utf-8",
        )

        (experiment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "experiment_id": experiment_id,
                    "strategy_id": "momentum",
                    "status": "COMPLETED",
                    "created_at": "2026-05-09T12:00:00+00:00",
                    "data_version": "qs-yfinance-AAPL-1d-report",
                }
            ),
            encoding="utf-8",
        )

        (backtest_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "manifest_schema_version": "backtest_run_v2",
                    "engine": "event_driven",
                    "canonical_for_promotion": True,
                    "run_id": f"run_{candidate_id}",
                    "data_version": "qs-yfinance-AAPL-1d-report",
                    "strategy_version": "momentum@1.0.0",
                    "commit_hash": "abc1234",
                    "reconciliation": reconciliation_summary,
                    "corporate_actions": corporate_actions_digest,
                    "evidence": {
                        "reconciliation": {
                            "summary": reconciliation_summary,
                            "snapshots": [snapshot_failed, snapshot_passed],
                            "adjustment_cross_check": {
                                "timestamp_utc": "2026-05-09T12:03:00+00:00",
                                "replay_final_equity": 99_500.0,
                                "reconstructed_final_equity": 99_500.0,
                                "equity_diff": 0.0,
                                "passed": reconciliation_passed,
                            },
                        },
                        "corporate_actions": {
                            "summary": corporate_actions_digest,
                            "digest": corporate_actions_digest,
                            "adjustments": [
                                {
                                    "timestamp_utc": "2026-05-09T12:00:30+00:00",
                                    "symbol": "AAPL",
                                    "adjustment_type": "dividend",
                                    "amount": 10.0,
                                    "quantity_multiplier": 1.0,
                                    "avg_price_multiplier": 1.0,
                                    "description": "quarterly dividend",
                                    "has_position_impact": False,
                                }
                            ],
                        },
                        "equity": {
                            "consistent": reconciliation_passed,
                            "consistent_at_final_snapshot": reconciliation_passed,
                            "consistency_msg": "clean" if reconciliation_passed else "snapshot mismatch",
                        },
                        "orders": {
                            "count": 1,
                            "status_counts": {"filled": 1},
                            "oms_order_count": 1,
                            "all_orders_created_by_oms": True,
                            "all_orders_have_risk_check_id": True,
                        },
                        "fills": {
                            "count": 1,
                            "filled_order_count": 1,
                            "all_fills_match_orders": True,
                        },
                        "completeness": {
                            "missing_required_fields": [],
                            "ledger_evidence_complete": reconciliation_passed,
                            "data_manifest_bound": False,
                            "promotion_evidence_complete": reconciliation_passed,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

    def _write_strategy_manifest_and_approved_review(
        self,
        *,
        candidate_id: str,
        manifest_id: str,
        review_id: str,
    ) -> None:
        manifest_dir = Path(self.tmp.name) / "research" / "manifests" / manifest_id
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "strategy_candidate_id": manifest_id,
                    "source_candidate_id": candidate_id,
                    "source_experiment_id": "exp_ready_review",
                    "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                    "created_at": "2026-05-09T12:10:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        review_dir = Path(self.tmp.name) / "research" / "paper_reviews" / review_id
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "review.json").write_text(
            json.dumps(
                {
                    "paper_review_id": review_id,
                    "strategy_manifest_id": manifest_id,
                    "status": "APPROVED_FOR_PAPER_ONLY",
                    "reviewer": "risk_committee",
                    "created_at": "2026-05-09T12:20:00+00:00",
                }
            ),
            encoding="utf-8",
        )

    def _write_data_manifest(
        self,
        *,
        data_version: str,
        filename: str | None = None,
        quality_score: float = 98.0,
        coverage_pct: float = 99.0,
        checksum: str = "manifestchecksum",
        fingerprint: str = "manifestchecksum",
    ) -> dict[str, object]:
        manifest_payload: dict[str, object] = {
            "data_version": data_version,
            "source": "yfinance",
            "symbol": "AAPL",
            "interval": "1d",
            "asset_class": "equity",
            "timezone": "UTC",
            "adjustment": "split_dividend_adjusted",
            "adjustment_policy": "split_dividend_adjusted",
            "corporate_action_adjustment": "split_dividend_adjusted",
            "start": "2024-01-01T00:00:00+00:00",
            "end": "2024-02-01T00:00:00+00:00",
            "row_count": 100,
            "expected_rows": 100,
            "coverage_pct": coverage_pct,
            "fingerprint": fingerprint,
            "checksum": checksum,
            "quality_score": quality_score,
            "created_at": "2026-05-09T11:55:00+00:00",
            "fields": ["timestamp", "open", "high", "low", "close", "volume"],
            "issues": [],
            "cleaning": {
                "duplicate_timestamps_removed": 0,
                "invalid_ohlc_removed": 0,
                "non_positive_prices_removed": 0,
                "missing_bars": 0,
            },
            "raw_path": "data/raw/aapl.csv",
            "cleaned_path": "data/clean/aapl.parquet",
            "git_commit": "abc1234",
            "universe_id": "us_equity_core",
            "universe_source": "governed",
            "survivorship_bias_risk": "clean",
        }
        manifests_dir = Path(self.tmp.name) / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        target = manifests_dir / f"{filename or data_version}.json"
        target.write_text(json.dumps(manifest_payload), encoding="utf-8")
        return manifest_payload

    def _write_ready_promotion_gate_fixture(
        self,
        *,
        candidate_id: str,
        experiment_id: str,
        data_version: str = "qs-yfinance-AAPL-1d-gate",
        candidate_backtest_manifest_path: str | None = None,
        include_embedded_data_manifest: bool = True,
        inline_backtest_manifest: dict | None = None,
        data_manifest_overrides: dict[str, object] | None = None,
    ) -> None:
        from quant_us.backtest.ledger_pnl import (
            compute_ledger_reconciliation_artifact_hash,
        )

        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        experiment_dir = (
            Path(self.tmp.name) / "research" / "experiments" / experiment_id
        )
        experiment_dir.mkdir(parents=True, exist_ok=True)
        scorecard_dir = Path(self.tmp.name) / "research" / "scorecards"
        scorecard_dir.mkdir(parents=True, exist_ok=True)
        backtest_dir = Path(self.tmp.name) / "research" / "backtests" / candidate_id
        backtest_dir.mkdir(parents=True, exist_ok=True)
        strategy_manifest_dir = (
            Path(self.tmp.name) / "research" / "manifests" / f"sman_{candidate_id}"
        )
        strategy_manifest_dir.mkdir(parents=True, exist_ok=True)
        walk_forward_dir = (
            Path(self.tmp.name) / "research" / "walk_forward" / candidate_id
        )
        walk_forward_dir.mkdir(parents=True, exist_ok=True)
        cost_stress_dir = (
            Path(self.tmp.name) / "research" / "cost_stress" / candidate_id
        )
        cost_stress_dir.mkdir(parents=True, exist_ok=True)

        manifest_payload = self._write_data_manifest(data_version=data_version)
        if data_manifest_overrides:
            manifest_payload.update(data_manifest_overrides)
            (Path(self.tmp.name) / "manifests" / f"{data_version}.json").write_text(
                json.dumps(manifest_payload),
                encoding="utf-8",
            )

        reconciliation_summary = {
            "snapshot_count": 1,
            "tolerance_pct": 0.01,
            "absolute_tolerance": 1e-6,
            "max_abs_diff": 0.0,
            "max_pct_diff": 0.0,
            "passed": True,
            "message": "clean",
        }
        ledger_artifact = {
            "generated_at": "2026-05-09T12:05:30+00:00",
            "as_of_utc": "2026-05-09T12:05:30+00:00",
            "hashes": {
                "ledger_hash": "ledgerhash",
                "fills_hash": "fillshash",
                "orders_hash": "ordershash",
                "portfolio_snapshots_hash": "snapshash",
            },
            "orders": {"total_orders": 12},
            "fills": {"effective_fill_count": 12},
            "pnl": {
                "source": "ledger_fills",
                "final_equity": 100_500.0,
                "net_pnl": 500.0,
            },
            "integrity": {"passed": True},
            "reconciliation": {"summary": reconciliation_summary},
        }
        ledger_artifact["artifact_hash"] = compute_ledger_reconciliation_artifact_hash(
            ledger_artifact
        )
        ledger_artifact_path = backtest_dir / "ledger_reconciliation_artifact.json"
        ledger_artifact_path.write_text(json.dumps(ledger_artifact), encoding="utf-8")

        candidate_payload = {
            "candidate_id": candidate_id,
            "experiment_id": experiment_id,
            "strategy_id": "momentum",
            "promotion_status": "RESEARCH_ONLY",
            "data_version": data_version,
            "symbols": ["AAPL"],
            "backtest_manifest_path": (
                candidate_backtest_manifest_path
                if candidate_backtest_manifest_path is not None
                else f"research/backtests/{candidate_id}/run_manifest.json"
            ),
            "walk_forward_result_path": f"research/walk_forward/{candidate_id}/result.json",
            "cost_stress_result_path": f"research/cost_stress/{candidate_id}/result.json",
            "metrics": {
                "walk_forward_pass_rate": 0.9,
                "trade_count": 12,
                "cost_sensitivity": 0.1,
                "max_drawdown_pct": 0.12,
                "sharpe_ratio": 1.55,
                "gross_sharpe_ratio": 1.78,
                "total_return_pct": 0.24,
                "gross_total_return_pct": 0.28,
                "trial_count": 6,
                "lookahead_guard": "passed_next_bar_execution",
                "daily_returns": [
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
                ],
                "trial_sharpes": [0.82, 0.91, 1.02, 0.88, 0.95, 1.05],
                "pbo_trials": [
                    {
                        "split_id": "s1",
                        "config_id": "a",
                        "train_sharpe": 1.30,
                        "test_sharpe": 1.10,
                    },
                    {
                        "split_id": "s1",
                        "config_id": "b",
                        "train_sharpe": 1.10,
                        "test_sharpe": 0.70,
                    },
                    {
                        "split_id": "s1",
                        "config_id": "c",
                        "train_sharpe": 0.90,
                        "test_sharpe": 0.40,
                    },
                    {
                        "split_id": "s2",
                        "config_id": "a",
                        "train_sharpe": 1.25,
                        "test_sharpe": 1.00,
                    },
                    {
                        "split_id": "s2",
                        "config_id": "b",
                        "train_sharpe": 1.00,
                        "test_sharpe": 0.60,
                    },
                    {
                        "split_id": "s2",
                        "config_id": "c",
                        "train_sharpe": 0.80,
                        "test_sharpe": 0.20,
                    },
                ],
                "monte_carlo_survival_rate": 0.92,
                "alpha_decay_half_life_days": 8.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.2,
                "stress_survival_rate": 0.9,
                "estimated_capacity_usd": 1_000_000.0,
                "fragility_score": 0.12,
                "turnover": 0.35,
                "annual_turnover_pct": 120.0,
                "expected_holding_period": "5d",
                "avg_holding_period": 5.0,
                "avg_exposure": 0.72,
                "max_gross_exposure_pct": 100.0,
                "max_single_symbol_exposure_pct": 100.0,
                "style_exposure": {
                    "observations": 60,
                    "betas": {"MKT": 1.0, "SMB": 0.1},
                    "benchmark_columns": ["MKT", "SMB"],
                    "r_squared": 0.82,
                },
                "failure_conditions": ["manual_review_if_oos_sharpe_below_zero"],
            },
        }
        if inline_backtest_manifest is not None:
            candidate_payload["backtest_manifest"] = inline_backtest_manifest
        (candidate_dir / "candidate.json").write_text(
            json.dumps(candidate_payload),
            encoding="utf-8",
        )

        (experiment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "experiment_id": experiment_id,
                    "strategy_id": "momentum",
                    "status": "COMPLETED",
                    "created_at": "2026-05-09T12:00:00+00:00",
                    "data_version": data_version,
                    "symbols": ["AAPL"],
                    "asset_class": "equity",
                    "start_date": "2024-01-01T00:00:00+00:00",
                    "end_date": "2024-02-01T00:00:00+00:00",
                    "timeframe": "1d",
                    "cost_model": "fixed_bps",
                    "slippage_model": "fixed_bps",
                    "delisting_policy": "manual_review_required",
                    "failure_conditions": ["manual_review_if_oos_sharpe_below_zero"],
                    "param_grid": {
                        "lookback": [10, 20, 40],
                        "threshold": [0.1, 0.2],
                    },
                }
            ),
            encoding="utf-8",
        )
        (scorecard_dir / f"{candidate_id}.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "status": "ok",
                    "capacity_usd": 1_000_000.0,
                    "fragility_score": 0.12,
                    "avg_holding_period": 5.0,
                    "turnover": 0.35,
                    "sector_exposures": {"technology": 1.0},
                    "style_exposure": {
                        "observations": 60,
                        "betas": {"MKT": 1.0, "SMB": 0.1},
                        "benchmark_columns": ["MKT", "SMB"],
                    },
                }
            ),
            encoding="utf-8",
        )
        (strategy_manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "strategy_candidate_id": f"sman_{candidate_id}",
                    "source_candidate_id": candidate_id,
                    "source_experiment_id": experiment_id,
                    "promotion_status": "DRAFT",
                    "params_frozen": True,
                    "data_version": data_version,
                    "sample_window": {
                        "start": "2024-01-01T00:00:00+00:00",
                        "end": "2024-02-01T00:00:00+00:00",
                        "timeframe": "1d",
                    },
                    "purge_embargo": {
                        "purged": True,
                        "embargo_bars": 2,
                    },
                    "trial_id": candidate_id,
                    "trial_count": 6,
                    "pbo": 0.12,
                    "dsr": 0.8,
                    "cpcv": {
                        "method": "cpcv",
                        "purged": True,
                        "embargoed": True,
                        "embargo_steps": 2,
                        "fold_count": 4,
                        "path_count": 6,
                        "pass_rate": 0.9,
                    },
                    "cost_model": {"name": "fixed_bps", "commission_rate": 0.0001},
                    "slippage_model": {"name": "fixed_bps", "slippage_bps": 1.0},
                    "cost_stress": {
                        "status": "completed",
                        "stress_survival_rate": 0.9,
                        "cost_sensitivity": 0.1,
                        "level_count": 3,
                    },
                    "style_exposure": {
                        "observations": 60,
                        "betas": {"MKT": 1.0, "SMB": 0.1},
                        "benchmark_columns": ["MKT", "SMB"],
                    },
                    "capacity": {
                        "estimated_capacity_usd": 1_000_000.0,
                        "fragility_score": 0.12,
                    },
                    "turnover": {"annual_turnover_pct": 120.0, "trade_count": 12},
                    "holding_period": {
                        "expected": "5d",
                        "avg_holding_period": 5.0,
                    },
                    "exposure_limits": {
                        "avg_exposure": 0.72,
                        "max_gross_exposure_pct": 100.0,
                        "max_single_symbol_exposure_pct": 100.0,
                    },
                    "failure_conditions": ["manual_review_if_oos_sharpe_below_zero"],
                    "delisting_conditions": {
                        "policy": "manual_review_required",
                        "survivorship_bias_risk": "clean",
                        "universe_id": "us_equity_core",
                        "universe_source": "governed",
                    },
                    "created_at": "2026-05-09T12:01:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        (walk_forward_dir / "result.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "schema_version": "research_walk_forward_result_v2",
                    "status": "completed",
                    "validation_method": "cpcv",
                    "lookahead_guard": "passed_next_bar_execution",
                    "purged": True,
                    "embargo_bars": 2,
                    "n_splits": 4,
                    "test_splits": 2,
                    "combination_count": 6,
                    "walk_forward_pass_rate": 0.9,
                    "folds": [
                        {"fold": 1, "oos_sharpe": 1.20, "passed": True},
                        {"fold": 2, "oos_sharpe": 1.05, "passed": True},
                        {"fold": 3, "oos_sharpe": 0.95, "passed": True},
                        {"fold": 4, "oos_sharpe": 1.00, "passed": True},
                    ],
                    "pbo_trials": list(candidate_payload["metrics"]["pbo_trials"]),
                }
            ),
            encoding="utf-8",
        )
        (cost_stress_dir / "result.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "status": "completed",
                    "cost_sensitivity": 0.1,
                    "stress_survival_rate": 0.9,
                    "estimated_capacity_usd": 1_000_000.0,
                    "fragility_score": 0.12,
                    "levels": [
                        {
                            "cost_multiplier": 1.0,
                            "total_return_pct": 0.24,
                            "sharpe_ratio": 1.55,
                        },
                        {
                            "cost_multiplier": 2.0,
                            "total_return_pct": 0.21,
                            "sharpe_ratio": 1.37,
                        },
                        {
                            "cost_multiplier": 5.0,
                            "total_return_pct": 0.16,
                            "sharpe_ratio": 1.13,
                        },
                    ],
                    "scenarios": [{"name": "high_cost", "passed": True}],
                }
            ),
            encoding="utf-8",
        )

        embedded_manifest = dict(manifest_payload) if include_embedded_data_manifest else None
        backtest_manifest = {
            "manifest_schema_version": "backtest_run_v2",
            "engine": "event_driven",
            "canonical_for_promotion": True,
            "run_id": f"run_{candidate_id}",
            "data_version": data_version,
            "strategy_version": "momentum@1.0.0",
            "commit_hash": "abc1234",
            "ledger_artifact_hash": ledger_artifact["artifact_hash"],
            "ledger_artifact_path": str(
                ledger_artifact_path.relative_to(Path(self.tmp.name))
            ),
            "ledger_hash": "ledgerhash",
            "fills_hash": "fillshash",
            "reconciliation": reconciliation_summary,
            "corporate_actions": {
                "total_dividends": 0.0,
                "total_borrow_fees": 0.0,
                "total_corporate_adjustments": 0.0,
                "adjustment_count": 0,
                "split_event_count": 0,
            },
            "execution": {"annual_turnover_pct": 120.0},
            "exposure": {
                "avg_gross_exposure_pct": 72.0,
                "max_gross_exposure_pct": 100.0,
            },
            "cost_model": "fixed_bps",
            "commission_rate": 0.0001,
            "slippage_model": "fixed_bps",
            "slippage_bps": 1.0,
            "trade_count": 12,
            "evidence": {
                "equity": {"consistent": True},
                "orders": {
                    "count": 12,
                    "all_orders_have_risk_check_id": True,
                },
                "fills": {
                    "count": 12,
                    "all_fills_match_orders": True,
                },
                "completeness": {
                    "promotion_evidence_complete": True,
                },
                "pnl": {
                    "source": "ledger_fills",
                    "final_equity": 100_500.0,
                    "net_pnl": 500.0,
                },
                "reconciliation": {
                    "summary": reconciliation_summary,
                    "snapshots": [
                        {
                            "timestamp_utc": "2026-05-09T12:05:00+00:00",
                            "diff": {"cash": 0.0, "equity": 0.0},
                            "max_abs_diff": 0.0,
                            "max_pct_diff": 0.0,
                            "passed": True,
                        }
                    ],
                },
                "corporate_actions": {
                    "digest": {
                        "total_dividends": 0.0,
                        "total_borrow_fees": 0.0,
                        "total_corporate_adjustments": 0.0,
                        "adjustment_count": 0,
                        "split_event_count": 0,
                    }
                },
                "ledger_artifact": ledger_artifact,
            },
        }
        if embedded_manifest is not None:
            backtest_manifest["data_manifest"] = embedded_manifest
        (backtest_dir / "run_manifest.json").write_text(
            json.dumps(backtest_manifest),
            encoding="utf-8",
        )

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

    def test_pipeline_preserves_timeframe_across_required_stages(self) -> None:
        config = {
            "experiment_name": "timeframe_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "timeframe": "5m",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)

        mgr = ExperimentManager(data_root=self.tmp.name)
        for eid in result["experiment_ids"]:
            manifest = mgr.load(eid)
            self.assertIsNotNone(manifest)
            self.assertEqual(manifest.timeframe, "5m")

        for cid in result["candidate_ids"]:
            candidate_path = (
                Path(self.tmp.name)
                / "research"
                / "candidates"
                / cid
                / "candidate.json"
            )
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(candidate["timeframe"], "5m")

    def test_pipeline_merges_required_stage_metrics_into_base_candidates(self) -> None:
        config = {
            "experiment_name": "robustness_merge_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "bar_size": "15m",
        }
        with patch.object(ExperimentManager, "run", _fake_stage_metrics_manager_run):
            result = self.pipeline.run(config)

        self.assertEqual(result["status"], "completed")
        base_candidate_metrics: dict[str, object] | None = None
        for cid in result["candidate_ids"]:
            candidate_path = (
                Path(self.tmp.name)
                / "research"
                / "candidates"
                / cid
                / "candidate.json"
            )
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            experiment = ExperimentManager(data_root=self.tmp.name).load(
                candidate["experiment_id"]
            )
            self.assertIsNotNone(experiment)
            if not ResearchAutomationPipeline._is_stage_experiment(
                experiment.strategy_family
            ):
                base_candidate_metrics = candidate["metrics"]
                break

        self.assertIsNotNone(base_candidate_metrics)
        assert base_candidate_metrics is not None
        self.assertIn("walk_forward_pass_rate", base_candidate_metrics)
        self.assertIn("wf_fold_results", base_candidate_metrics)
        self.assertIn("stress_survival_rate", base_candidate_metrics)
        self.assertIn("cost_stress_levels", base_candidate_metrics)
        self.assertIn("regime_sharpes", base_candidate_metrics)
        self.assertGreaterEqual(base_candidate_metrics["walk_forward_pass_rate"], 0.5)
        self.assertEqual(
            result["required_stages"]["walk_forward"]["passed"],
            True,
        )

    def test_pipeline_enriches_candidate_with_validation_capacity_and_turnover_evidence(self) -> None:
        candidate_id = "cand_enriched"
        experiment_id = "exp_enriched"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )

        self.pipeline._enrich_candidate_automation_evidence(
            candidate_id,
            experiment_id=experiment_id,
        )

        candidate_path = (
            Path(self.tmp.name)
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        metrics = candidate["metrics"]

        self.assertEqual(metrics["validation_status"], "complete")
        self.assertEqual(metrics["cpcv_evidence"]["method"], "cpcv")
        self.assertEqual(metrics["cpcv_evidence"]["path_count"], 2)
        self.assertIn("dsr", metrics["dsr_evidence"])
        self.assertIn("pbo", metrics["pbo_evidence"])
        self.assertEqual(
            metrics["capacity_evidence"]["estimated_capacity_usd"],
            1_000_000.0,
        )
        self.assertEqual(
            metrics["turnover_evidence"]["annual_turnover_pct"],
            120.0,
        )
        self.assertEqual(
            metrics["style_exposure_evidence"]["betas"]["MKT"],
            1.0,
        )

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

    def test_step_promote_requires_explicit_manual_approval_after_gate(self) -> None:
        """READY_FOR_PAPER_REVIEW alone cannot write PAPER_ELIGIBLE."""
        cand_id = "cand_manual_test"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": cand_id,
                    "experiment_id": "exp_ready_manual",
                    "strategy_id": "momentum",
                    "promotion_status": "RESEARCH_ONLY",
                    "metrics": {"sharpe_ratio": 1.5},
                }
            ),
            encoding="utf-8",
        )

        with (
            patch.object(
                self.pipeline,
                "_evaluate_promotion_gate",
                return_value={"decision": "READY_FOR_PAPER_REVIEW", "reasons": []},
            ),
            patch.object(self.pipeline, "_has_approved_paper_review", return_value=False),
        ):
            with self.assertRaisesRegex(ValueError, "manual_approval=True"):
                self.pipeline.step_promote(cand_id)

            candidate = self.pipeline.step_promote(cand_id, manual_approval=True)
        self.assertEqual(candidate.promotion_status, "PAPER_ELIGIBLE")

    def test_step_promote_accepts_approved_paper_review(self) -> None:
        """An approved paper review can satisfy the human approval requirement."""
        cand_id = "cand_review_path"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": cand_id,
                    "experiment_id": "exp_ready_review",
                    "strategy_id": "momentum",
                    "promotion_status": "RESEARCH_ONLY",
                    "metrics": {"sharpe_ratio": 1.5},
                }
            ),
            encoding="utf-8",
        )
        self._write_strategy_manifest_and_approved_review(
            candidate_id=cand_id,
            manifest_id="sman_ready_review",
            review_id="prev_ready_review",
        )

        with patch.object(
            self.pipeline,
            "_evaluate_promotion_gate",
            return_value={"decision": "READY_FOR_PAPER_REVIEW", "reasons": []},
        ):
            candidate = self.pipeline.step_promote(cand_id)
        self.assertEqual(candidate.promotion_status, "PAPER_ELIGIBLE")

    def test_step_promote_rejects_manual_approval_when_gate_not_ready(self) -> None:
        """Explicit manual approval cannot bypass the canonical promotion gate."""
        cand_id = "cand_gate_blocked"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": cand_id,
                    "experiment_id": "exp_gate_blocked",
                    "strategy_id": "momentum",
                    "promotion_status": "RESEARCH_ONLY",
                    "metrics": {"sharpe_ratio": 1.5},
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "READY_FOR_PAPER_REVIEW"):
            self.pipeline.step_promote(cand_id, manual_approval=True)

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
            "ranked_candidates", "overfit_reports", "promotion_gate_results",
            "required_stages", "paper_review_ready", "dossier_paths",
            "report_paths", "promoted", "status",
        ]
        for key in expected_keys:
            self.assertIn(key, result)

    def test_pipeline_does_not_auto_mark_paper_eligible(self) -> None:
        """Automation may evaluate paper review readiness but must not set PAPER_ELIGIBLE."""
        config = {
            "experiment_name": "manual_gate_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        self.assertEqual(result["status"], "completed")
        for cid in result["candidate_ids"]:
            cand_path = Path(self.tmp.name) / "research" / "candidates" / cid / "candidate.json"
            data = json.loads(cand_path.read_text(encoding="utf-8"))
            self.assertNotEqual(data["promotion_status"], "PAPER_ELIGIBLE")
            self.assertNotEqual(data["promotion_status"], "LIVE")
        self.assertEqual(result["paper_review_ready"], [])

    def test_evidence_registry_builds_candidate_chain(self) -> None:
        candidate_id = "cand_chain"
        experiment_id = "exp_chain"
        data_version = "qs-yfinance-AAPL-1d-chain"

        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "experiment_id": experiment_id,
                    "strategy_id": "momentum",
                    "data_version": data_version,
                    "promotion_status": "RESEARCH_ONLY",
                    "backtest_manifest_path": "research/backtests/cand_chain/run_manifest.json",
                    "created_at": "2026-05-09T12:00:00+00:00",
                    "metrics": {"sharpe_ratio": 1.2},
                }
            ),
            encoding="utf-8",
        )

        manifest_dir = Path(self.tmp.name) / "research" / "manifests" / "sman_chain"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "strategy_candidate_id": "sman_chain",
                    "source_candidate_id": candidate_id,
                    "source_experiment_id": experiment_id,
                    "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                    "created_at": "2026-05-09T12:10:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        paper_review_dir = Path(self.tmp.name) / "research" / "paper_reviews" / "prev_chain"
        paper_review_dir.mkdir(parents=True, exist_ok=True)
        (paper_review_dir / "review.json").write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_chain",
                    "strategy_manifest_id": "sman_chain",
                    "status": "PENDING_HUMAN_REVIEW",
                    "created_at": "2026-05-09T12:20:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        backtest_dir = Path(self.tmp.name) / "research" / "backtests" / candidate_id
        backtest_dir.mkdir(parents=True, exist_ok=True)
        (backtest_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": "run_chain",
                    "engine": "event_driven",
                    "canonical_for_promotion": True,
                    "data_version": data_version,
                    "created_at": "2026-05-09T12:05:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        manifests_dir = Path(self.tmp.name) / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        (manifests_dir / f"{data_version}.json").write_text(
            json.dumps(
                {
                    "data_version": data_version,
                    "source": "yfinance",
                    "symbol": "AAPL",
                    "interval": "1d",
                    "quality_score": 95.0,
                    "created_at": "2026-05-09T11:55:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        pipeline_dir = Path(self.tmp.name) / "research" / "pipeline_results"
        pipeline_dir.mkdir(parents=True, exist_ok=True)
        (pipeline_dir / "pipe_chain.json").write_text(
            json.dumps(
                {
                    "pipeline_id": "pipe_chain",
                    "created_at": "2026-05-09T12:15:00+00:00",
                    "status": "completed",
                    "paper_review_ready": [candidate_id],
                    "promotion_gate_results": {
                        candidate_id: {"decision": "READY_FOR_PAPER_REVIEW", "reasons": []}
                    },
                }
            ),
            encoding="utf-8",
        )

        reports_dir = Path(self.tmp.name) / "daily_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "daily_report_2026-05-09.json").write_text(
            json.dumps(
                {
                    "report_date": "2026-05-09",
                    "generated_at": "2026-05-09T20:00:00+00:00",
                    "reconciliation_status": "clean",
                    "orders_submitted": 3,
                    "kill_switch_triggered": False,
                }
            ),
            encoding="utf-8",
        )

        registry = rebuild_evidence_registry(self.tmp.name)
        chain = inspect_candidate_evidence(candidate_id, self.tmp.name)

        self.assertEqual(registry["counts"]["candidate_count"], 1)
        self.assertEqual(chain.status, "complete")
        self.assertEqual(chain.data_manifest.status, "present")
        self.assertEqual(chain.backtest_manifest.status, "present")
        self.assertEqual(chain.promotion_result.status, "present")
        self.assertEqual(chain.strategy_manifest.status, "present")
        self.assertEqual(chain.paper_review.status, "present")
        self.assertEqual(chain.daily_report.status, "present")
        self.assertEqual(chain.backtest_manifest.content_type, "application/json")
        self.assertTrue(chain.backtest_manifest.sha256)
        self.assertGreater(chain.backtest_manifest.size_bytes, 0)
        self.assertGreater(chain.backtest_manifest.mtime_ns, 0)
        self.assertEqual(chain.paper_review.content_type, "application/json")
        self.assertTrue(chain.paper_review.sha256)
        self.assertGreater(chain.paper_review.size_bytes, 0)
        self.assertGreater(chain.paper_review.mtime_ns, 0)

    def test_evidence_registry_marks_recoverable_backtest_link_stale(self) -> None:
        candidate_id = "cand_stale"

        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "experiment_id": "exp_stale",
                    "strategy_id": "momentum",
                    "data_version": "qs-yfinance-AAPL-1d-stale",
                    "promotion_status": "RESEARCH_ONLY",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        backtest_dir = Path(self.tmp.name) / "research" / "backtests" / candidate_id
        backtest_dir.mkdir(parents=True, exist_ok=True)
        (backtest_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": "run_stale",
                    "engine": "event_driven",
                    "canonical_for_promotion": True,
                    "data_version": "qs-yfinance-AAPL-1d-stale",
                    "created_at": "2026-05-09T12:05:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        chain = inspect_candidate_evidence(candidate_id, self.tmp.name, use_saved=False)
        registry = inspect_evidence_registry(self.tmp.name, use_saved=False)

        self.assertEqual(registry["chains"][candidate_id]["backtest_manifest"]["status"], "stale")
        self.assertEqual(chain.backtest_manifest.status, "stale")
        self.assertIn("backtest_manifest_link_missing_but_recoverable", chain.notes)

    def test_candidate_evidence_rebuilds_when_saved_registry_content_changed(self) -> None:
        candidate_id = "cand_changed"
        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = candidate_dir / "candidate.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "experiment_id": "exp_before",
                    "strategy_id": "momentum",
                    "data_version": "qs-yfinance-AAPL-1d-changed",
                    "promotion_status": "RESEARCH_ONLY",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        rebuild_evidence_registry(self.tmp.name)

        candidate_path.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "experiment_id": "exp_after",
                    "strategy_id": "momentum",
                    "data_version": "qs-yfinance-AAPL-1d-changed",
                    "promotion_status": "RESEARCH_ONLY",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        registry = inspect_evidence_registry(
            self.tmp.name,
            use_saved=True,
            rebuild_if_missing=False,
        )
        chain = inspect_candidate_evidence(
            candidate_id,
            self.tmp.name,
            use_saved=True,
            rebuild_if_missing=False,
        )

        self.assertEqual(registry["registry_status"], "changed")
        self.assertTrue(any(note.startswith("content_changed:") for note in registry["registry_notes"]))
        self.assertEqual(chain.experiment_id, "exp_after")

    def test_promotion_gate_surfaces_reconciliation_and_corporate_actions(self) -> None:
        candidate_id = "cand_report_gate"
        experiment_id = "exp_report_gate"
        self._write_unified_backtest_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            reconciliation_passed=False,
        )

        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        gate = ResearchPromotionGate(data_root=self.tmp.name)
        result = gate.evaluate(candidate_id)

        self.assertIn("reconciliation", result.evidence)
        self.assertFalse(result.evidence["reconciliation"]["summary"]["passed"])
        self.assertEqual(result.evidence["reconciliation"]["summary"]["max_abs_diff"], 50.0)
        self.assertEqual(result.evidence["reconciliation"]["summary"]["max_pct_diff"], 0.05)
        self.assertEqual(result.evidence["reconciliation_passed"], False)
        self.assertEqual(result.evidence["reconciliation_failed_snapshot_count"], 1)
        self.assertIn("count=1", result.evidence["reconciliation_failed_snapshot_summary"])
        self.assertIn("max_abs_diff=50.0000", result.evidence["reconciliation_failed_snapshot_summary"])
        self.assertIn("corporate_actions", result.evidence)
        self.assertEqual(result.evidence["corporate_actions"]["digest"]["adjustment_count"], 1)
        self.assertEqual(result.evidence["corporate_actions_digest"]["total_dividends"], 10.0)

    def test_promotion_gate_does_not_treat_string_false_reconciliation_as_passed(self) -> None:
        candidate_id = "cand_report_string_false"
        experiment_id = "exp_report_string_false"
        self._write_unified_backtest_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            reconciliation_passed=False,
        )
        manifest_path = (
            Path(self.tmp.name)
            / "research"
            / "backtests"
            / candidate_id
            / "run_manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["evidence"]["reconciliation"]["summary"]["passed"] = "False"
        manifest["evidence"]["reconciliation"]["snapshots"][0]["passed"] = "False"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertFalse(result.evidence["reconciliation_passed"])
        self.assertEqual(result.evidence["reconciliation_failed_snapshot_count"], 1)
        self.assertIn(
            "reconciliation_failed: backtest reconciliation summary.passed is false",
            result.reasons,
        )

    def test_promotion_gate_accepts_canonical_persisted_evidence(self) -> None:
        candidate_id = "cand_gate_ready"
        experiment_id = "exp_gate_ready"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "READY_FOR_PAPER_REVIEW")
        self.assertEqual(result.reasons, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.evidence["backtest_manifest_source"], "path")
        self.assertEqual(result.evidence["data_manifest_binding_state"], "bound")
        self.assertTrue(result.evidence["strategy_manifest_exists"])
        self.assertTrue(result.evidence["walk_forward_artifact_exists"])
        self.assertTrue(result.evidence["cost_stress_artifact_exists"])
        self.assertTrue(result.evidence["promotion_result_exists"])
        self.assertTrue(Path(result.evidence["promotion_result_path"]).exists())

    def test_strategy_manifest_manager_finalizes_only_after_canonical_gate(self) -> None:
        candidate_id = "cand_strategy_manifest_ready"
        experiment_id = "exp_strategy_manifest_ready"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )

        from quant_us.research.strategy_manifest import StrategyManifestManager

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            manifest = StrategyManifestManager(
                data_root=self.tmp.name
            ).create_from_candidate(candidate_id)

        self.assertEqual(manifest.promotion_status, "READY_FOR_PORTFOLIO_SIM")
        self.assertEqual(manifest.source_candidate_id, candidate_id)
        self.assertTrue(manifest.params_frozen)
        self.assertTrue(Path(manifest.promotion_result_path).exists())

    def test_promotion_gate_rejects_inline_only_backtest_manifest(self) -> None:
        candidate_id = "cand_inline_only"
        experiment_id = "exp_inline_only"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            candidate_backtest_manifest_path="",
            inline_backtest_manifest={
                "engine": "event_driven",
                "canonical_for_promotion": True,
            },
        )

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn(
            "missing_canonical_backtest_manifest_path: candidate must persist "
            "backtest_manifest_path=research/backtests/cand_inline_only/run_manifest.json",
            result.reasons,
        )
        self.assertIn(
            "inline_backtest_manifest_not_allowed: promotion requires a persisted canonical backtest_manifest_path",
            result.reasons,
        )

    def test_promotion_gate_rejects_missing_canonical_backtest_manifest(self) -> None:
        candidate_id = "cand_missing_backtest"
        experiment_id = "exp_missing_backtest"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        candidate_path = (
            Path(self.tmp.name)
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["backtest_manifest_path"] = ""
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn(
            "missing_canonical_backtest_manifest_path: candidate must persist "
            "backtest_manifest_path=research/backtests/cand_missing_backtest/run_manifest.json",
            result.reasons,
        )
        self.assertIn(
            "missing_backtest_manifest_evidence: READY_FOR_PAPER_REVIEW requires canonical backtest manifest evidence",
            result.reasons,
        )

    def test_promotion_gate_rejects_missing_strategy_manifest(self) -> None:
        candidate_id = "cand_missing_strategy_manifest"
        experiment_id = "exp_missing_strategy_manifest"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        manifest_dir = (
            Path(self.tmp.name)
            / "research"
            / "manifests"
            / f"sman_{candidate_id}"
        )
        (manifest_dir / "manifest.json").unlink()

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn(
            "missing_strategy_manifest: canonical strategy manifest not found for candidate",
            result.reasons,
        )

    def test_promotion_gate_rejects_missing_scorecard(self) -> None:
        candidate_id = "cand_missing_scorecard"
        experiment_id = "exp_missing_scorecard"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        (
            Path(self.tmp.name)
            / "research"
            / "scorecards"
            / f"{candidate_id}.json"
        ).unlink()

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn("missing_scorecard: robust scorecard not found", result.reasons)

    def test_promotion_gate_rejects_missing_walk_forward_artifact(self) -> None:
        candidate_id = "cand_missing_walk_forward"
        experiment_id = "exp_missing_walk_forward"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        (
            Path(self.tmp.name)
            / "research"
            / "walk_forward"
            / candidate_id
            / "result.json"
        ).unlink()

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertTrue(
            any(reason.startswith("walk_forward_artifact_path_missing:") for reason in result.reasons)
        )
        self.assertNotIn("READY_FOR_PAPER_REVIEW", result.decision)

    def test_promotion_gate_rejects_missing_cost_stress_artifact(self) -> None:
        candidate_id = "cand_missing_cost_stress"
        experiment_id = "exp_missing_cost_stress"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        (
            Path(self.tmp.name)
            / "research"
            / "cost_stress"
            / candidate_id
            / "result.json"
        ).unlink()

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertTrue(
            any(reason.startswith("cost_stress_artifact_path_missing:") for reason in result.reasons)
        )

    def test_promotion_gate_rejects_inline_walk_forward_metrics_only(self) -> None:
        candidate_id = "cand_inline_wf"
        experiment_id = "exp_inline_wf"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        candidate_path = (
            Path(self.tmp.name)
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["walk_forward_result_path"] = ""
        candidate["walk_forward_result"] = {"walk_forward_pass_rate": 1.0}
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn(
            "inline_walk_forward_artifact_not_allowed: promotion requires persisted canonical walk_forward evidence",
            result.reasons,
        )

    def test_promotion_gate_rejects_when_promotion_result_cannot_persist(self) -> None:
        candidate_id = "cand_persist_fail"
        experiment_id = "exp_persist_fail"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )

        with (
            patch(
                "quant_us.research.automation.overfit.OverfitDetector.check",
                return_value=SimpleNamespace(
                    is_overfit=False,
                    degradation_pct=0.0,
                    reasons=[],
                ),
            ),
            patch.object(
                ResearchPromotionGate,
                "_persist_promotion_result",
                return_value=None,
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn(
            "missing_persisted_promotion_result: READY_FOR_PAPER_REVIEW requires persisted gate evidence",
            result.reasons,
        )

    def test_promotion_gate_rejects_missing_canonical_data_manifest(self) -> None:
        candidate_id = "cand_missing_data_manifest"
        experiment_id = "exp_missing_data_manifest"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        (Path(self.tmp.name) / "manifests" / "qs-yfinance-AAPL-1d-gate.json").unlink()

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertTrue(
            any(reason.startswith("missing_canonical_data_manifest:") for reason in result.reasons)
        )

    def test_promotion_gate_rejects_stale_data_manifest_binding(self) -> None:
        candidate_id = "cand_stale_manifest_binding"
        experiment_id = "exp_stale_manifest_binding"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        manifest_path = (
            Path(self.tmp.name)
            / "research"
            / "backtests"
            / candidate_id
            / "run_manifest.json"
        )
        backtest_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backtest_manifest["data_manifest"]["checksum"] = "stale-checksum"
        backtest_manifest["data_manifest"]["fingerprint"] = "stale-checksum"
        manifest_path.write_text(json.dumps(backtest_manifest), encoding="utf-8")

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn(
            "stale_data_manifest_binding: embedded backtest data manifest differs from the canonical persisted data manifest",
            result.reasons,
        )
        self.assertEqual(result.evidence["data_manifest_binding_state"], "stale")

    def test_promotion_gate_rejects_conflicting_data_manifests(self) -> None:
        candidate_id = "cand_conflict_manifest"
        experiment_id = "exp_conflict_manifest"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
        )
        self._write_data_manifest(
            data_version="qs-yfinance-AAPL-1d-gate",
            filename="qs-yfinance-AAPL-1d-gate-duplicate",
            checksum="otherchecksum",
            fingerprint="otherchecksum",
        )

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn(
            "data_manifest_conflict: multiple persisted manifests found for data_version=qs-yfinance-AAPL-1d-gate",
            result.reasons,
        )
        self.assertEqual(result.evidence["data_manifest_candidate_count"], 2)

    def test_promotion_gate_rejects_low_quality_data_manifest(self) -> None:
        candidate_id = "cand_low_quality_manifest"
        experiment_id = "exp_low_quality_manifest"
        self._write_ready_promotion_gate_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            data_manifest_overrides={
                "quality_score": 70.0,
                "coverage_pct": 85.0,
            },
        )

        with patch(
            "quant_us.research.automation.overfit.OverfitDetector.check",
            return_value=SimpleNamespace(
                is_overfit=False,
                degradation_pct=0.0,
                reasons=[],
            ),
        ):
            result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertEqual(result.decision, "BLOCKED")
        self.assertIn(
            "data_manifest_invalid:coverage_below_threshold:85.00",
            result.reasons,
        )
        self.assertIn(
            "data_manifest_invalid:quality_below_threshold:70.00",
            result.reasons,
        )

    def test_generate_v2_includes_unified_backtest_evidence(self) -> None:
        candidate_id = "cand_report_text"
        experiment_id = "exp_report_text"
        self._write_unified_backtest_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            reconciliation_passed=False,
        )

        report = generate_v2(experiment_id, data_root=self.tmp.name)

        self.assertIn("## Unified Backtest Evidence", report)
        self.assertIn("Reconciliation Passed: False", report)
        self.assertIn("Max Abs Diff: 50.0000", report)
        self.assertIn("Max Pct Diff: 0.0500", report)
        self.assertIn("Failed Snapshot Summary:", report)
        self.assertIn("Corporate Actions Digest:", report)
        self.assertIn("adjustment_count=1", report)
        self.assertIn("total_dividends=10.0000", report)
        self.assertNotIn("Reconciliation Passed: True", report)
