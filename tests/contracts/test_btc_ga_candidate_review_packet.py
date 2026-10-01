from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.research.ga_factor_mining import (
    build_btc_ga_candidate_review_markdown,
    build_btc_ga_candidate_review_packet,
    write_btc_ga_candidate_review_packet,
)


TS = datetime(2026, 6, 27, tzinfo=timezone.utc)


def test_ga_candidate_review_packet_is_research_only_and_classifies_candidates() -> None:
    payload = build_btc_ga_candidate_review_packet(
        _source_report(),
        _candidate_payload(),
        source_report_path=Path("ga_factor_mining_report.json"),
        candidate_path=Path("candidate_factor_expressions.json"),
        generated_at_utc=TS,
    )

    assert validate_btc_artifact_schema(payload) == []
    assert payload["status"] == "complete"
    assert payload["decision"] == "research_only_candidate_review_packet"
    assert payload["scope"] == "research_only_candidate_review_packet"
    assert payload["review_summary"]["candidate_count"] == 2
    assert payload["review_summary"]["extended_research_shortlist_count"] == 1
    assert payload["review_summary"]["reject_count"] == 1
    assert payload["confirmatory_holdout_summary"]["enabled"] is True
    assert payload["confirmatory_holdout_summary"]["surviving_candidate_count"] == 1
    assert payload["confirmatory_holdout_summary"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["paper_candidate_generated"] is False
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["live_unlock_allowed"] is False
    assert payload["promotion"]["paper_queue_status"] == "LOCKED"
    assert payload["promotion"]["live_status"] == "FROZEN"
    assert payload["safety"]["broker_calls_allowed"] is False
    assert payload["safety"]["order_endpoints_allowed"] is False
    assert payload["safety"]["strategy_skeleton_generated"] is False

    funding_candidate = payload["candidate_reviews"][0]
    momentum_candidate = payload["candidate_reviews"][1]
    assert funding_candidate["logic_family"] == "funding_pressure"
    assert "funding" in funding_candidate["expression_human"]
    assert funding_candidate["logic_family_zh"] == "资金费率压力"
    assert "资金费率" in funding_candidate["expression_human_zh"]
    assert funding_candidate["review_verdict"] == "promising_for_extended_research"
    assert funding_candidate["review_verdict_zh"] == "可进入扩展研究短名单"
    assert "funding_dominant_logic_needs_economic_review" in funding_candidate["review_flags"]
    assert "资金费率主导" in ",".join(funding_candidate["review_flags_zh"])
    assert momentum_candidate["logic_family"] == "price_momentum_trend"
    assert momentum_candidate["logic_family_zh"] == "价格动量趋势"
    assert momentum_candidate["review_verdict"] == "reject_from_current_review"
    assert "price_only_candidate_missing_derivatives_edge" in momentum_candidate["review_flags"]
    assert "do_not_write_paper_queue_or_live_unlock_from_this_packet" in payload["recommended_next_actions"]
    assert "不要根据这个复核包写入 paper 队列" in payload["recommended_next_actions_zh"][0]


def test_ga_candidate_review_packet_blocks_missing_source_or_candidates(tmp_path: Path) -> None:
    output = tmp_path / "ga_candidate_review_packet.json"
    markdown = tmp_path / "ga_candidate_review_packet.md"

    payload = write_btc_ga_candidate_review_packet(
        source_report_path=tmp_path / "missing_report.json",
        candidate_path=tmp_path / "missing_candidates.json",
        output_path=output,
        markdown_path=markdown,
        generated_at_utc=TS,
    )

    assert output.exists()
    assert markdown.exists()
    assert payload["status"] == "blocked"
    assert "btc_ga_factor_mining_report_missing" in payload["blockers"]
    assert "btc_ga_candidate_review_no_candidates" in payload["blockers"]
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["live_unlock_allowed"] is False


def test_ga_candidate_review_writer_reads_inputs_and_writes_markdown(tmp_path: Path) -> None:
    source_path = tmp_path / "ga_factor_mining_report.json"
    candidate_path = tmp_path / "candidate_factor_expressions.json"
    output_path = tmp_path / "ga_candidate_review_packet.json"
    markdown_path = tmp_path / "ga_candidate_review_packet.md"
    source_path.write_text(json.dumps(_source_report()), encoding="utf-8")
    candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")

    payload = write_btc_ga_candidate_review_packet(
        source_report_path=source_path,
        candidate_path=candidate_path,
        output_path=output_path,
        markdown_path=markdown_path,
        generated_at_utc=TS,
    )

    assert payload["source_report"]["path"].endswith("ga_factor_mining_report.json")
    assert output_path.exists()
    assert markdown_path.exists()
    stored = json.loads(output_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert stored["decision"] == "research_only_candidate_review_packet"
    assert "# BTC GA 候选因子复核包" in markdown
    assert "可进入扩展研究短名单" in markdown
    assert "资金费率" in markdown
    assert "确认性 holdout" in markdown


def test_ga_candidate_review_markdown_summarizes_gate_state() -> None:
    payload = build_btc_ga_candidate_review_packet(_source_report(), _candidate_payload(), generated_at_utc=TS)

    markdown = build_btc_ga_candidate_review_markdown(payload)

    assert "Paper 队列写入允许：false" in markdown
    assert "Live 解锁允许：false" in markdown
    assert "候选因子表" in markdown


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
        "code_commit": "fixture",
        "blockers": [],
        "data_coverage": {
            "decision_time": TS.isoformat(),
            "market_rows": 976,
            "market_start_time": "2026-05-17T17:00:00+00:00",
            "market_end_time": "2026-06-27T08:00:00+00:00",
            "derivatives_visible_start_time": "2026-05-28T09:00:00+00:00",
            "derivatives_visible_end_time": "2026-06-27T08:00:00+00:00",
            "derivatives_market_overlap_rows": 720,
            "merged_rows_after_lookback": 720,
            "derivatives_alignment_status_after_lookback": "value_fields_present",
            "lookahead_policy": "features use event_time/available_time <= decision_time",
            "field_non_null_counts_after_lookback": {
                "open_interest_usd": 711,
                "funding_rate": 712,
                "long_liquidation_usd": 712,
                "short_liquidation_usd": 712,
                "long_short_ratio": 711,
            },
        },
        "ga_config": {
            "candidate_count": 32,
            "selected_candidate_count": 2,
            "trial_count": 4284,
            "rejected_count": 836,
        },
        "walk_forward": {
            "fold_count": 4,
            "method": "rolling_train_validation_with_embargo",
            "embargo_hours": 4,
            "oos_stability": {
                "fold_count": 4,
                "pass_rate": 1.0,
                "median_validation_pf": 1.29,
                "folds": [],
            },
        },
        "confirmatory_holdout": {
            "enabled": True,
            "status": "complete",
            "requested_hours": 72,
            "selection_rows": 648,
            "holdout_rows": 72,
            "ga_selection_used_holdout": False,
            "surviving_candidate_count": 1,
            "shortlist_for_extended_research_only": ["btc_ga_expr001_fold3"],
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _candidate_payload() -> dict[str, object]:
    return {
        "schema_version": "btc_ga_candidate_factor_expressions_v1",
        "run_id": "btc_ga_fixture",
        "scope": "research_only_expression",
        "candidate_count": 2,
        "paper_candidate_generated": False,
        "live_enabled": False,
        "candidates": [
            {
                "candidate_id": "btc_ga_expr001_fold3",
                "expression_hash": "expr001",
                "fold_id": 3,
                "complexity": 6,
                "depth": 4,
                "expression": {
                    "op": "rolling_z",
                    "window": 12,
                    "args": [
                        {
                            "op": "gate",
                            "args": [
                                {
                                    "op": "safe_ratio",
                                    "args": [
                                        {"op": "primitive", "primitive": "funding_z_24"},
                                        {"op": "primitive", "primitive": "funding_z_24"},
                                    ],
                                },
                                {"op": "primitive", "primitive": "funding_rate"},
                            ],
                        }
                    ],
                },
                "train_metrics": {
                    "profit_factor": 3.8,
                    "total_return": 0.17,
                    "rank_ic": -0.06,
                    "max_drawdown": -0.02,
                    "turnover": 0.10,
                    "exposure": 0.26,
                    "hit_rate": 0.17,
                    "observations": 134,
                    "threshold": 1.0,
                    "direction": -1,
                },
                "validation_metrics": {
                    "profit_factor": 3.2,
                    "total_return": 0.04,
                    "rank_ic": -0.12,
                    "max_drawdown": -0.02,
                    "turnover": 0.11,
                    "exposure": 0.30,
                    "hit_rate": 0.20,
                    "observations": 65,
                    "threshold": 1.0,
                    "direction": -1,
                },
                "validation_fitness": 2.1,
                "cost_stress": {
                    "base": {"survives": True, "profit_factor": 3.2, "total_return": 0.04},
                    "fees_2x": {"survives": True, "profit_factor": 2.8, "total_return": 0.03},
                    "slippage_2x": {"survives": True, "profit_factor": 2.7, "total_return": 0.03},
                    "costs_2x": {"survives": True, "profit_factor": 2.2, "total_return": 0.02},
                },
            },
            {
                "candidate_id": "btc_ga_expr002_fold1",
                "expression_hash": "expr002",
                "fold_id": 1,
                "complexity": 2,
                "depth": 2,
                "expression": {
                    "op": "tanh",
                    "args": [{"op": "primitive", "primitive": "momentum_24h"}],
                },
                "train_metrics": {
                    "profit_factor": 1.5,
                    "total_return": 0.05,
                    "rank_ic": 0.08,
                    "max_drawdown": -0.03,
                    "turnover": 0.09,
                    "exposure": 0.30,
                },
                "validation_metrics": {
                    "profit_factor": 0.8,
                    "total_return": -0.01,
                    "rank_ic": 0.01,
                    "max_drawdown": -0.06,
                    "turnover": 0.08,
                    "exposure": 0.20,
                },
                "validation_fitness": -0.2,
                "cost_stress": {
                    "base": {"survives": False, "profit_factor": 0.8, "total_return": -0.01},
                    "fees_2x": {"survives": False, "profit_factor": 0.7, "total_return": -0.02},
                },
            },
        ],
    }
