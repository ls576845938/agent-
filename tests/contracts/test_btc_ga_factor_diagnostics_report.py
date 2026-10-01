from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.research.ga_factor_mining import (
    build_btc_ga_factor_diagnostics_report,
    write_btc_ga_factor_diagnostics_report,
)


TS = datetime(2026, 6, 27, tzinfo=timezone.utc)


def test_ga_factor_diagnostics_rejects_failed_batch_without_paper_or_live_unlock() -> None:
    payload = build_btc_ga_factor_diagnostics_report(_source_report(), generated_at_utc=TS)

    assert validate_btc_artifact_schema(payload) == []
    assert payload["status"] == "complete"
    assert payload["decision"] == "research_only_ga_factor_failure_diagnostics"
    assert payload["gate"]["current_ga_batch_decision"] == "reject_current_ga_batch"
    assert payload["gate"]["paper_or_live_unlock_allowed"] is False
    assert payload["promotion"]["paper_candidate_generated"] is False
    assert payload["promotion"]["paper_queue_status"] == "LOCKED"
    assert payload["promotion"]["live_status"] == "FROZEN"
    assert payload["safety"]["broker_calls_allowed"] is False
    assert payload["safety"]["order_endpoints_allowed"] is False
    assert payload["safety"]["strategy_skeleton_generated"] is False

    reasons = set(payload["diagnostic_summary"]["failure_reasons"])
    assert "oos_stability_pass_rate_zero" in reasons
    assert "median_validation_profit_factor_below_1" in reasons
    assert "derivatives_value_coverage_zero_after_merge" in reasons
    assert "cost_stress_no_candidate_survives_any_scenario" in reasons


def test_ga_factor_diagnostics_reports_candidate_and_fold_failure_reasons() -> None:
    payload = build_btc_ga_factor_diagnostics_report(_source_report(), generated_at_utc=TS)
    candidate = payload["candidate_diagnostics"]["candidates"][0]
    fold = payload["fold_diagnostics"]["folds"][0]

    assert candidate["expression_hash"] == "expr001"
    assert "validation_signal_inactive_or_threshold_mismatch" in candidate["failure_reasons"]
    assert "train_validation_pf_decay_gt_50pct" in candidate["failure_reasons"]
    assert fold["fold_id"] == 1
    assert fold["passed"] is False
    assert fold["cost_stress_surviving_scenarios"] == []
    assert payload["cost_diagnostics"]["base_survival_count"] == 0
    assert payload["primitive_usage"]["primitive_counts"]["momentum_24h"] == 1


def test_ga_factor_diagnostics_separates_time_overlap_failure_from_raw_field_coverage() -> None:
    source = _source_report()
    source["data_coverage"].update(
        {
            "derivatives_market_overlap_rows": 0,
            "field_non_null_counts_raw_visible": {
                "open_interest_usd": 719,
                "funding_rate": 720,
                "long_liquidation_usd": 720,
                "short_liquidation_usd": 720,
                "long_short_ratio": 719,
            },
            "field_non_null_counts_after_join": {
                "open_interest_usd": 0,
                "funding_rate": 0,
                "long_liquidation_usd": 0,
                "short_liquidation_usd": 0,
                "long_short_ratio": 0,
            },
        }
    )

    payload = build_btc_ga_factor_diagnostics_report(source, generated_at_utc=TS)

    assert payload["diagnostic_summary"]["derivative_value_coverage_status"] == "no_market_derivatives_time_overlap"
    assert "derivatives_market_time_overlap_missing" in payload["diagnostic_summary"]["failure_reasons"]
    assert (
        "refresh_or_backfill_btc_1h_ohlcv_to_overlap_sentiment_window_before_remining"
        in payload["recommended_next_actions"]
    )


def test_ga_factor_diagnostics_missing_source_blocks_report(tmp_path: Path) -> None:
    output = tmp_path / "ga_factor_diagnostics_report.json"
    payload = write_btc_ga_factor_diagnostics_report(
        source_report_path=tmp_path / "missing.json",
        output_path=output,
        generated_at_utc=TS,
    )

    assert output.exists()
    assert payload["status"] == "blocked"
    assert payload["blockers"] == ["btc_ga_factor_mining_report_missing"]
    assert payload["gate"]["paper_or_live_unlock_allowed"] is False


def test_ga_factor_diagnostics_writer_reads_source_and_writes_artifact(tmp_path: Path) -> None:
    source = tmp_path / "ga_factor_mining_report.json"
    output = tmp_path / "ga_factor_diagnostics_report.json"
    source.write_text(json.dumps(_source_report()), encoding="utf-8")

    payload = write_btc_ga_factor_diagnostics_report(
        source_report_path=source,
        output_path=output,
        generated_at_utc=TS,
    )

    assert output.exists()
    assert payload["source_report"]["path"].endswith("ga_factor_mining_report.json")
    assert payload["source_report"]["selected_candidate_count"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["decision"] == "research_only_ga_factor_failure_diagnostics"


def _source_report() -> dict[str, object]:
    return {
        "schema_version": "btc_ga_factor_mining_report_v1",
        "status": "complete",
        "decision": "research_only_expression_review",
        "run_id": "btc_ga_fixture",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "as_of_utc": TS.isoformat(),
        "artifact_hash": "a" * 64,
        "blockers": [],
        "data_coverage": {
            "decision_time": TS.isoformat(),
            "market_rows": 720,
            "derivatives_total_rows": 720,
            "derivatives_visible_rows": 720,
            "merged_rows": 716,
            "merged_rows_after_lookback": 716,
            "lookahead_policy": "fixture",
            "field_non_null_counts": {
                "open_interest_usd": 0,
                "funding_rate": 0,
                "long_liquidation_usd": 0,
                "short_liquidation_usd": 0,
                "long_short_ratio": 0,
            },
        },
        "ga_config": {
            "candidate_count": 1,
            "selected_candidate_count": 1,
            "trial_count": 64,
            "rejected_count": 3,
        },
        "walk_forward": {
            "oos_stability": {
                "fold_count": 1,
                "pass_rate": 0.0,
                "median_validation_pf": 0.25,
                "folds": [
                    {
                        "fold_id": 1,
                        "passed": False,
                        "profit_factor": 0.25,
                        "rank_ic": -0.01,
                        "max_drawdown": -0.06,
                    }
                ],
            }
        },
        "top_candidates": [
            {
                "candidate_id": "btc_ga_expr001_fold1",
                "expression_hash": "expr001",
                "fold_id": 1,
                "complexity": 2,
                "depth": 2,
                "expression": {
                    "op": "tanh",
                    "args": [{"op": "primitive", "primitive": "momentum_24h"}],
                },
                "train_metrics": {
                    "profit_factor": 2.0,
                    "total_return": 0.12,
                    "rank_ic": 0.2,
                    "max_drawdown": -0.02,
                    "turnover": 0.1,
                    "exposure": 0.3,
                },
                "validation_metrics": {
                    "profit_factor": 0.25,
                    "total_return": -0.02,
                    "rank_ic": -0.01,
                    "max_drawdown": -0.06,
                    "turnover": 0.0,
                    "exposure": 0.0,
                },
                "validation_fitness": -0.1,
                "cost_stress": {
                    "base": {"survives": False, "profit_factor": 0.25, "total_return": -0.02},
                    "fees_2x": {"survives": False, "profit_factor": 0.2, "total_return": -0.03},
                },
            }
        ],
    }
