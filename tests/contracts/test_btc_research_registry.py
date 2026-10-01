from __future__ import annotations

from pathlib import Path

from scripts.build_btc_research_registry import (
    build_btc_research_registry,
    write_btc_research_registry_outputs,
)


def test_btc_research_registry_tracks_ga_and_timesfm_as_research_only() -> None:
    registry = build_btc_research_registry(generated_at="2026-06-29T00:00:00Z")
    btc = registry["btc"]

    ga = btc["ga_factor_mining_status"]
    assert btc["latest_ga_factor_mining_report"] == "artifacts/btc_ga_factor_mining/latest/ga_factor_mining_report.json"
    assert btc["latest_ga_candidate_review_packet"] == (
        "artifacts/btc_ga_factor_mining/latest/ga_candidate_review_packet.json"
    )
    assert ga["status"] == "complete"
    assert ga["decision"] == "research_only_expression_review"
    assert ga["review_decision"] == "research_only_candidate_review_packet"
    assert ga["paper_candidate_generated"] is False
    assert ga["paper_queue_write_allowed"] is False
    assert ga["paper_or_live_unlock_allowed"] is False
    assert ga["live_unlock_allowed"] is False
    assert ga["allowed_next_action"] == "extended_research_only"

    timesfm = btc["timesfm_research_status"]
    assert btc["latest_timesfm_shared_readiness"] == (
        "artifacts/shared_forecasting/timesfm/latest/timesfm_shared_infra_readiness_report.json"
    )
    assert btc["latest_btc_timesfm_smoke"] == (
        "artifacts/shared_forecasting/timesfm/btc_1h_smoke_latest/btc_timesfm_1h_smoke_forecast_report.json"
    )
    assert btc["latest_btc_timesfm_vs_trend_baseline"] == (
        "artifacts/shared_forecasting/timesfm/btc_vs_trend_baseline_latest/"
        "btc_timesfm_vs_trend_baseline_oos_report.json"
    )
    assert timesfm["status"] == "COMPLETE_RESEARCH_ONLY_DIAGNOSTIC"
    assert timesfm["readiness_status"] == "READY_FOR_P1_RESEARCH_SMOKE"
    assert timesfm["smoke_status"] == "PASS_RESEARCH_ONLY_SMOKE"
    assert timesfm["comparison_status"] == "COMPLETE_RESEARCH_ONLY_DIAGNOSTIC"
    assert timesfm["paper_candidate_allowed"] is False
    assert timesfm["paper_queue_write_allowed"] is False
    assert timesfm["paper_or_live_unlock_allowed"] is False
    assert timesfm["live_unlock_allowed"] is False
    assert timesfm["allowed_next_action"] == "research_only_risk_auxiliary_review"


def test_btc_research_registry_tracks_strategy_first_research_lines() -> None:
    registry = build_btc_research_registry(generated_at="2026-06-29T00:00:00Z")
    btc = registry["btc"]

    assert btc["latest_multi_strategy_attribution"] == (
        "artifacts/btc_multi_strategy_attribution/latest/btc_multi_strategy_attribution_report.json"
    )
    priority = btc["strategy_first_priority"]
    assert priority["primary_focus"] == "strategy_mining_and_validation"
    assert priority["real_order_priority"] == "frozen_until_cost_adjusted_oos_strategy_edge_is_verified"
    assert priority["paper_queue_write_allowed"] is False
    assert priority["live_unlock_allowed"] is False
    assert priority["private_or_order_endpoint_allowed"] is False

    multi = btc["multi_strategy_attribution_status"]
    assert multi["status"] == "complete"
    assert multi["paper_candidate_allowed"] is False
    assert multi["paper_queue_write_allowed"] is False
    assert multi["live_unlock_allowed"] is False
    assert multi["unsafe_blockers"] == []
    assert multi["gate"]["paper_queue_write_allowed"] is False
    assert multi["gate"]["paper_candidate_created"] is False
    assert multi["gate"]["live_unlock_allowed"] is False
    assert multi["guardrails"]["private_endpoint_used"] is False
    assert multi["guardrails"]["order_endpoint_used"] is False
    assert multi["guardrails"]["real_order_submitted"] is False
    assert multi["guardrails"]["oms_access_allowed"] is False
    assert multi["guardrails"]["broker_access_allowed"] is False

    lines = {item["line_id"]: item for item in multi["registered_research_lines"]}
    assert {
        "trend_forward_observation",
        "intraday_event_ledger",
        "ga_factor_research",
        "timesfm_auxiliary_forecast",
    }.issubset(lines)
    for item in lines.values():
        assert item["paper_candidate_allowed"] is False
        assert item["paper_queue_write_allowed"] is False
        assert item["live_allowed"] is False


def test_btc_research_registry_writes_latest_and_summary(tmp_path: Path) -> None:
    registry = build_btc_research_registry(generated_at="2026-06-29T00:00:00Z")
    written = write_btc_research_registry_outputs(
        registry,
        output=tmp_path / "artifacts/btc_research_registry/research_registry.json",
        latest_output=tmp_path / "artifacts/btc_research_registry/latest/research_registry.json",
        summary_cn=tmp_path / "artifacts/btc_research_registry/latest/btc_research_registry_summary_cn.md",
    )

    assert Path(written["registry"]).exists()
    assert Path(written["latest_registry"]).exists()
    summary = Path(written["summary_cn"]).read_text(encoding="utf-8")
    assert "BTC 研究注册表摘要" in summary
    assert "strategy_mining_and_validation" in summary
    assert "不写 paper 队列" in summary
