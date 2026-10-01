from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.strategy_attribution import (
    build_btc_multi_strategy_attribution,
    render_btc_multi_strategy_attribution_markdown,
)
from scripts.build_btc_multi_strategy_attribution import build_btc_multi_strategy_attribution_file


TS = datetime(2026, 6, 29, 8, 0, tzinfo=timezone.utc)


def test_btc_multi_strategy_attribution_separates_strategy_buckets() -> None:
    payload = build_btc_multi_strategy_attribution(
        generated_at_utc=TS,
        sources=_sources(),
        source_paths=_source_paths(),
        report_paths={"json": "artifacts/btc_multi_strategy_attribution/latest/report.json"},
    )

    assert payload["status"] == "complete"
    assert payload["scope"] == "btc_read_only_multi_strategy_attribution"
    assert validate_btc_artifact_schema(payload) == []
    assert set(payload["strategy_buckets"]) == {
        "trend_forward_observation",
        "intraday_event_ledger",
        "ga_factor_research",
    }
    trend = payload["strategy_buckets"]["trend_forward_observation"]
    intraday = payload["strategy_buckets"]["intraday_event_ledger"]
    ga = payload["strategy_buckets"]["ga_factor_research"]

    assert trend["metrics"]["observation_days"] == 5
    assert trend["gate"]["paper_candidate_allowed"] is False
    assert intraday["metrics"]["profit_factor"] == 2.647434
    assert intraday["metrics"]["trade_ledger_rows"] == 78
    assert intraday["gate"]["source_gate_passed"] is True
    assert intraday["gate"]["paper_queue_write_allowed"] is False
    assert ga["metrics"]["trial_count"] == 4279
    assert ga["gate"]["source_gate_status"] == "reject_current_ga_batch"
    assert ga["gate"]["live_allowed"] is False

    controls = payload["contamination_controls"]
    assert controls["shared_ledger_allowed"] is False
    assert controls["cross_strategy_pnl_reuse_allowed"] is False
    assert controls["cross_strategy_gate_inheritance_allowed"] is False
    assert controls["violations"] == []
    assert controls["per_bucket_ledger_scope"] == {
        "trend_forward_observation": "forward_observation_ledger_only",
        "intraday_event_ledger": "intraday_trade_ledger_only",
        "ga_factor_research": "no_trade_ledger_expression_candidate_only",
    }
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["live_unlock_allowed"] is False
    assert payload["guardrails"] == {
        "live_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }

    markdown = render_btc_multi_strategy_attribution_markdown(payload)
    assert "BTC 多策略归因只读报告" in markdown
    assert "不写 paper 队列" in markdown
    assert "不解锁 live" in markdown
    assert "submit_order" not in markdown


def test_btc_multi_strategy_attribution_blocks_missing_core_source() -> None:
    sources = _sources()
    sources["ga_factor_diagnostics"] = None
    payload = build_btc_multi_strategy_attribution(
        generated_at_utc=TS,
        sources=sources,
        source_paths=_source_paths(),
    )

    assert payload["status"] == "blocked"
    assert "btc_multi_strategy_attribution_source_missing:ga_factor_diagnostics" in payload["blockers"]
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["live_unlock_allowed"] is False


def test_btc_multi_strategy_attribution_blocks_unsafe_source_flag() -> None:
    sources = _sources()
    sources["ga_factor_diagnostics"] = {
        **sources["ga_factor_diagnostics"],
        "safety": {
            **sources["ga_factor_diagnostics"]["safety"],
            "real_orders_created": True,
        },
    }
    payload = build_btc_multi_strategy_attribution(
        generated_at_utc=TS,
        sources=sources,
        source_paths=_source_paths(),
    )

    assert payload["status"] == "blocked"
    assert any("real_orders_created=true" in blocker for blocker in payload["blockers"])
    assert payload["guardrails"]["real_order_submitted"] is False


def test_btc_multi_strategy_attribution_file_builder_writes_read_only_artifact(tmp_path: Path) -> None:
    _write_fixture_tree(tmp_path)
    payload = build_btc_multi_strategy_attribution_file(repo_root=tmp_path)

    assert payload["status"] == "complete"
    assert (
        tmp_path
        / "artifacts/btc_multi_strategy_attribution/latest/btc_multi_strategy_attribution_report.json"
    ).exists()
    assert (
        tmp_path
        / "artifacts/btc_multi_strategy_attribution/latest/btc_multi_strategy_attribution_summary_cn.md"
    ).exists()
    assert payload["strategy_buckets"]["intraday_event_ledger"]["metrics"]["trade_ledger_rows"] == 2
    assert payload["gate"]["paper_candidate_created"] is False


def _sources() -> dict[str, dict[str, object] | None]:
    return {
        "current_status": {"status": "paper_observing", "live_status": "frozen"},
        "trend_forward_observation": {
            "status": "PASS",
            "generated_at": "2026-06-29T03:13:39Z",
            "data": {
                "sample_start": "2021-06-30T00:00:00Z",
                "sample_end": "2026-06-29T00:00:00Z",
                "daily_rows": 1826,
                "public_rest_only": True,
            },
            "forward_observation": {"observation_days": 5},
            "guardrails": {
                "simulated_only": True,
                "forward_observation_is_not_alpha_validation": True,
                "live_order_allowed": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
                "real_order_submitted": False,
            },
        },
        "intraday_canonical_backtest": {
            "strategy_id": "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1",
            "gate_decision": {
                "status": "candidate_passed_internal_gate",
                "passed": True,
                "fail_reasons": [],
            },
            "metrics": {
                "profit_factor": 2.647434,
                "event_profit_factor": 1.4397,
                "total_return_pct": 3.7663,
                "max_drawdown": -1.7496,
                "walk_forward_pass_rate": 0.833333,
                "regime_pass_rate": 0.8,
                "trade_count": 78,
                "fill_count": 156,
            },
        },
        "intraday_fold_audit": {
            "fold_contract": {"status": "pass"},
            "regime_contract": {"status": "pass"},
        },
        "intraday_trade_ledger_summary": {"status": "present", "row_count": 78, "sha256": "a" * 64},
        "intraday_trade_attribution_summary": {"status": "present", "row_count": 78, "sha256": "b" * 64},
        "ga_factor_diagnostics": {
            "status": "complete",
            "decision": "research_only_ga_factor_failure_diagnostics",
            "diagnostic_summary": {
                "source_decision": "research_only_expression_review",
                "selected_candidate_count": 6,
                "trial_count": 4279,
                "rejected_count": 841,
                "oos_pass_rate": 0.5,
                "median_validation_profit_factor": 0.860734,
                "failure_reasons": ["median_validation_profit_factor_below_1"],
            },
            "gate": {
                "current_ga_batch_decision": "reject_current_ga_batch",
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            },
            "promotion": {
                "paper_queue_status": "LOCKED",
                "live_status": "FROZEN",
            },
            "safety": {
                "broker_calls_allowed": False,
                "order_endpoints_allowed": False,
                "paper_queue_write_allowed": False,
                "private_endpoints_allowed": False,
                "real_orders_created": False,
                "research_only": True,
                "strategy_skeleton_generated": False,
            },
        },
        "ga_candidate_review": {"status": "complete"},
        "timesfm_vs_trend_baseline": {
            "status": "COMPLETE_RESEARCH_ONLY_DIAGNOSTIC",
            "input": {"decision_count": 24},
            "comparison": {
                "metrics": [
                    {
                        "model_id": "timesfm_zero_shot_h24",
                        "evaluation": {"profit_factor": 0.0, "total_return": -0.047063},
                    },
                    {
                        "model_id": "btc_trend_baseline_momentum_24h_z24",
                        "evaluation": {"profit_factor": 2.66925, "total_return": 0.012103},
                    },
                ]
            },
            "gate": {"paper_candidate_allowed": False, "live_allowed": False},
        },
        "compression_expansion_attribution": {
            "status": "archived",
            "strategy_id": "btc_compression_expansion_breakout_v1",
            "gate_status": "candidate_gate_failed",
            "allowed_next_action": "archive_only",
            "paper_review_pending_allowed": False,
            "promotion_ready": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "candidate_metrics": {"event_pf": 1.0241},
            "blockers": ["btc_compression_expansion_archived"],
        },
    }


def _source_paths() -> dict[str, str]:
    return {
        "trend_forward_observation": "artifacts/btc_trend_v0/latest/daily.json",
        "intraday_canonical_backtest": "artifacts/btc_intraday_event_ledger/run/canonical_backtest_report.json",
        "intraday_fold_audit": "artifacts/btc_intraday_event_ledger/run/fold_regime_contract_audit.json",
        "intraday_trade_ledger_summary": "artifacts/btc_intraday_event_ledger/run/trade_ledger.csv",
        "intraday_trade_attribution_summary": "artifacts/btc_intraday_event_ledger/run/trade_attribution.csv",
        "ga_factor_diagnostics": "artifacts/btc_ga_factor_mining/latest/ga_factor_diagnostics_report.json",
        "ga_candidate_review": "artifacts/btc_ga_factor_mining/latest/ga_candidate_review_packet.json",
        "timesfm_vs_trend_baseline": "artifacts/shared_forecasting/timesfm/latest.json",
        "compression_expansion_attribution": "artifacts/btc_candidate_attribution/latest/attribution_report.json",
    }


def _write_fixture_tree(root: Path) -> None:
    sources = _sources()
    paths = {
        "current_status": "artifacts/btc_current_status/latest/btc_current_status_report.json",
        "trend_forward_observation": (
            "artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json"
        ),
        "ga_factor_diagnostics": "artifacts/btc_ga_factor_mining/latest/ga_factor_diagnostics_report.json",
        "ga_candidate_review": "artifacts/btc_ga_factor_mining/latest/ga_candidate_review_packet.json",
        "timesfm_vs_trend_baseline": (
            "artifacts/shared_forecasting/timesfm/btc_vs_trend_baseline_latest/"
            "btc_timesfm_vs_trend_baseline_oos_report.json"
        ),
        "compression_expansion_attribution": (
            "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json"
        ),
        "intraday_canonical_backtest": (
            "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger/"
            "canonical_backtest_report.json"
        ),
        "intraday_fold_audit": (
            "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger/"
            "fold_regime_contract_audit.json"
        ),
    }
    for name, relpath in paths.items():
        _write_json(root / relpath, sources[name] or {})

    run_dir = (
        root
        / "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger"
    )
    _write_csv(run_dir / "trade_ledger.csv")
    _write_csv(run_dir / "trade_attribution.csv")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["trade_id", "net_pnl"])
        writer.writeheader()
        writer.writerow({"trade_id": "t1", "net_pnl": "1.0"})
        writer.writerow({"trade_id": "t2", "net_pnl": "-0.5"})
